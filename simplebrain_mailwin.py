"""Mail inside SimpleBrain (Qt): the inbox, the whole email, reply/forward/new, archive/delete/unread, and an email
turned into a task or an event. Network calls run off the UI thread; simplebrain_mail.Account does the talking.
"""
import html
import re
import threading
from datetime import datetime, timedelta

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

import simplebrain_core as core
import simplebrain_mail as mail


def when_text(stamp, now=None):
    """'3:42 PM' today, 'Yesterday', 'Oct 30' this year, else '10/30/2025': on this computer's clock."""
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
    except (ValueError, AttributeError):
        return ""
    now = now or datetime.now().astimezone()
    if dt.date() == now.date():
        return dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    return f"{dt:%b} {dt.day}" if dt.year == now.year else f"{dt:%m/%d/%Y}"


class _Back(QObject):
    done = Signal(object)  # a callable to run on the UI thread


def mail_note(msg, vault=None):
    """The email kept as a note, so a task or event made from it links back to the whole message."""
    title = "".join(" " if c in core.BAD_TITLE_CHARS else c for c in f"Mail - {msg.get('subject') or 'no subject'}")
    title = " ".join(title.split())[:70].rstrip(". ")
    name = title + ".md"
    if not core.os.path.exists(core.os.path.join(vault or core.VAULT, name)):
        when = mail.local_when(msg.get("receivedAt"))
        core.write_note(name, f"# {title[7:]}\nfrom:: {msg.get('from_text', '')}\nwhen:: {when}\n\n{msg.get('text', '')}\n",
                        vault)
    return title


class ComposeDialog(QDialog):
    """To, Cc, Subject, From and the text. Send runs on a thread; the dialog closes once the server took it."""

    def __init__(self, parent, account, identities, to="", cc="", subject="", body="", reply_to=None, from_pick=None):
        super().__init__(parent)
        self.account, self.reply_to, self.identities = account, reply_to, identities
        self.setWindowTitle("Reply" if reply_to else "New email")
        self.resize(760, 620)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.from_box = QComboBox()
        for i in identities:
            if not i["email"].startswith("*@"):
                self.from_box.addItem(f"{i['name']} <{i['email']}>", (i, i["email"]))
        if from_pick and self.from_box.findText(from_pick[1], Qt.MatchContains) < 0:
            self.from_box.insertItem(0, f"{from_pick[0]['name']} <{from_pick[1]}>", from_pick)
        if from_pick:
            self.from_box.setCurrentIndex(self.from_box.findText(from_pick[1], Qt.MatchContains))
        self.to, self.cc, self.subject = QLineEdit(to), QLineEdit(cc), QLineEdit(subject)
        self.to.setPlaceholderText("name@example.com, another@example.com")
        for label, w in (("From", self.from_box), ("To", self.to), ("Cc", self.cc), ("Subject", self.subject)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.body = QPlainTextEdit(body)
        lay.addWidget(self.body, 1)
        row = QHBoxLayout()
        self.status = QLabel("")
        row.addWidget(self.status, 1)
        cancel, self.send_btn = QPushButton("Cancel"), QPushButton("Send")
        cancel.clicked.connect(self.reject)
        self.send_btn.clicked.connect(self.send)
        self.send_btn.setDefault(True)
        row.addWidget(cancel)
        row.addWidget(self.send_btn)
        lay.addLayout(row)
        (self.to if not to else self.body).setFocus()
        self.body.moveCursor(QTextCursor.Start)  # write above the quoted mail
        self._back = _Back()
        self._back.done.connect(lambda f: f())

    def send(self):
        if not mail.parse_addresses(self.to.text()):
            self.status.setText("Who is it to? Type an email address.")
            return
        ident, addr = self.from_box.currentData()
        args = (self.to.text(), self.subject.text(), self.body.toPlainText(), ident, addr, self.reply_to, self.cc.text())
        self.send_btn.setEnabled(False)
        self.status.setText("Sending…")

        def work():
            try:
                self.account.send(*args)
                self._back.done.emit(self.accept)
            except (OSError, ValueError, KeyError) as e:
                why = str(e)  # `e` is cleared when the except block ends; the lambda runs later
                self._back.done.emit(lambda: (self.status.setText(f"Not sent: {html.escape(why)[:160]}"),
                                              self.send_btn.setEnabled(True)))
        threading.Thread(target=work, daemon=True).start()


class MailWindow(QDialog):
    """The inbox on the left, the email on the right, every action one click."""

    def __init__(self, app_window):
        super().__init__(app_window, Qt.Window)
        self.app = app_window
        self.setWindowTitle("Mail")
        self.resize(1250, 780)
        self.account, self.idents, self.msg, self.items = None, [], None, []
        self._back = _Back()
        self._back.done.connect(lambda f: f())
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.status = QLabel("Connecting…")
        top.addWidget(self.status, 1)
        for label, slot in (("New email", self.new_mail), ("Refresh", self.refresh)):
            b = QPushButton(label)
            b.clicked.connect(lambda *_, s=slot: s())
            top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setSpacing(2)
        self.list.currentItemChanged.connect(lambda cur, _prev: self.open_item(cur))
        split.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        self.head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.head)
        self.acts = QHBoxLayout()
        self.buttons = {}
        for label, slot in (("Reply", self.reply), ("Reply all", lambda: self.reply(True)), ("Forward", self.forward),
                            ("Archive", self.archive), ("Delete", self.delete), ("Mark unread", self.toggle_read),
                            ("Make task", self.make_task), ("Make event", self.make_event)):
            b = QPushButton(label)
            b.clicked.connect(lambda *_, s=slot: s())
            b.setEnabled(False)
            self.acts.addWidget(b)
            self.buttons[label] = b
        self.acts.addStretch(1)
        rl.addLayout(self.acts)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        rl.addWidget(self.body, 1)
        split.addWidget(right)
        split.setSizes([420, 830])
        lay.addWidget(split, 1)
        self.refresh()

    # -- background work: fn runs on a thread, then(result) on the UI thread; errors land in the status line --
    def bg(self, fn, then, doing=""):
        if doing:
            self.status.setText(doing)

        def work():
            try:
                if self.account is None:
                    cfg = mail.load_config()
                    if not cfg:
                        raise ValueError("No email connected yet: File > Email (connect yours)…")
                    self.account = mail.open_account(cfg)
                    self.idents = self.account.identities()
                r = fn()
                self._back.done.emit(lambda: then(r))
            except (OSError, ValueError, KeyError, IndexError) as e:
                why = str(e)  # `e` is cleared when the except block ends; the lambda runs later
                self._back.done.emit(lambda: self.status.setText(
                    f"<span style='color:#e58a6e'>Email: {html.escape(why)[:160]}</span>"))
        threading.Thread(target=work, daemon=True).start()

    def refresh(self):
        self.bg(lambda: self.account.inbox(), self.show_inbox, "Getting your inbox…")

    def show_inbox(self, items):
        keep = self.msg["id"] if self.msg else None
        self.items = items
        self.list.blockSignals(True)
        self.list.clear()
        for m in items:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, m)
            self._style(it, m["unread"])
            self.list.addItem(it)
            if m["id"] == keep:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        unread = sum(m["unread"] for m in items)
        self.status.setText(f"Inbox: {len(items)}" + (f", {unread} unread" if unread else "") + ".")
        if not items:
            self.show_message(None)
        elif not self.msg:
            self.body.setPlainText("Pick an email on the left to read it.")

    def _style(self, item, unread):
        """Two lines, sender and when, then the subject; unread ones get a bullet and gold text (bold or a ● from a fallback font made Qt cut
        the second line off)."""
        m = item.data(Qt.UserRole)
        subj = m["subject"] if len(m["subject"]) <= 64 else m["subject"][:63] + "…"
        item.setText(f"{'• ' if unread else ''}{m['from'][:40]}  ·  {when_text(m['when'])}\n{subj}")
        item.setForeground(QBrush(QColor("#e3b25a")) if unread else QBrush())

    def open_item(self, item):
        if not item:
            return
        m = item.data(Qt.UserRole)

        def got(msg):
            if m["unread"]:
                m["unread"] = False
                self._style(item, False)
                threading.Thread(target=lambda: self._quiet(lambda: self.account.mark_read(m["id"])), daemon=True).start()
            self.show_message(msg)
        self.bg(lambda: self.account.message(m["id"]), got, "Opening…")

    def _quiet(self, fn):
        try:
            fn()
        except (OSError, ValueError, KeyError):
            pass

    def show_message(self, msg):
        self.msg = msg
        for b in self.buttons.values():
            b.setEnabled(bool(msg))
        if not msg:
            self.head.setText("")
            self.body.setPlainText("Nothing here. Your inbox is clear." if not self.items else "")
            return
        when = mail.local_when(msg.get("receivedAt"))
        e = html.escape
        self.head.setText(f"<b style='font-size:15px'>{e(msg.get('subject') or '(no subject)')}</b><br>"
                          f"From {e(msg['from_text'])} &lt;{e(((msg.get('from') or [{}])[0]).get('email', ''))}&gt;"
                          f" · {e(when)}<br>To {e(msg['to_text'])}" + (f" · Cc {e(msg['cc_text'])}" if msg['cc_text'] else ""))
        links = re.sub(r"(https?://[^\s<>()\"']+)", r'<a href="\1">\1</a>', e(msg["text"]))
        self.body.setHtml(f"<div style='white-space:pre-wrap; font-size:14px'>{links}</div>")
        self.buttons["Mark unread"].setText("Mark unread")
        self.status.setText("")

    # -- actions --
    def _compose(self, **kw):
        d = ComposeDialog(self, self.account, self.idents, **kw)
        if d.exec():
            self.status.setText("Sent.")
            self.refresh()

    def new_mail(self):
        if self.account is None:
            return self.bg(lambda: None, lambda _: self.new_mail(), "Connecting…")
        self._compose()

    def reply(self, everyone=False):
        m = self.msg
        ident, addr = mail.pick_identity(self.idents, m)
        back = (m.get("replyTo") or m.get("from") or [])
        to = ", ".join(f"{a.get('name') or ''} <{a['email']}>".strip() for a in back)
        cc = ""
        if everyone:
            mine = {addr.lower()} | {i["email"].lower() for i in self.idents}
            others = [a for a in (m.get("to") or []) + (m.get("cc") or [])
                      if a.get("email", "").lower() not in mine and a not in back]
            cc = ", ".join(f"{a.get('name') or ''} <{a['email']}>".strip() for a in others)
        subj = m.get("subject") or ""
        self._compose(to=to, cc=cc, subject=subj if subj.lower().startswith("re:") else f"Re: {subj}",
                      body=mail.reply_text(m), reply_to=m, from_pick=(ident, addr))

    def forward(self):
        m = self.msg
        subj = m.get("subject") or ""
        when = mail.local_when(m.get("receivedAt"))
        body = (f"\n\n---------- Forwarded message ----------\nFrom: {m['from_text']}\nDate: {when}\n"
                f"Subject: {subj}\nTo: {m['to_text']}\n\n{m['text']}\n")
        self._compose(subject=f"Fwd: {subj}", body=body, from_pick=mail.pick_identity(self.idents, m))

    def _gone(self, verb):
        row = self.list.currentRow()
        self.list.takeItem(row)
        self.items = [i for i in self.items if i["id"] != self.msg["id"]]
        self.status.setText(verb)
        self.show_message(None)
        if self.list.count():
            self.list.setCurrentRow(min(row, self.list.count() - 1))

    def archive(self):
        eid = self.msg["id"]
        self.bg(lambda: self.account.archive(eid), lambda _: self._gone("Archived."), "Archiving…")

    def delete(self):
        eid = self.msg["id"]
        self.bg(lambda: self.account.trash(eid), lambda _: self._gone("Moved to Trash."),
                "Deleting…")

    def toggle_read(self):
        b = self.buttons["Mark unread"]
        unread = b.text() == "Mark unread"
        eid = self.msg["id"]
        item = self.list.currentItem()

        def done(_):
            b.setText("Mark read" if unread else "Mark unread")
            if item:
                item.data(Qt.UserRole)["unread"] = unread
                self._style(item, unread)
            self.status.setText("Marked unread." if unread else "Marked read.")
        self.bg(lambda: self.account.mark_read(eid, not unread), done)

    def make_task(self):
        due = self.app.ask_text("Task from this email", "Due date (optional): fri, tomorrow, nov 5 or MM-DD-YYYY")
        if due is None:
            return
        due = due.strip()
        if due and not (due := self.app.read_date(due, "no task was made.")):
            return
        note = mail_note(self.msg)
        who = self.msg["from_text"] or "email"
        core.add_task(f"{who}: {self.msg.get('subject') or 'email'} [[{note}]]", due or None)
        self.app.refresh_tasks()
        self.app.refresh_notes_list()
        self.status.setText(f"Task added{' for ' + core.show_date(due) if due else ''}; the email is in [[{note}]].")

    def make_event(self):
        d = self.app.ask_text("Event from this email", "Date: MM-DD-YYYY, fri, tomorrow…")
        if not d or not d.strip():
            return
        d = self.app.read_date(d.strip(), "no event was made.")
        if not d or not self.app.confirm_past_date(d):
            return
        t = (self.app.ask_text("Event time (optional)", "e.g. 14:30 or 2:30pm, blank for all-day") or "").strip()
        if t and not (t := self.app.read_time(t, "no event was made.")):
            return
        title = self.app.ask_text("Event title", "What is it?", self.msg.get("subject") or "")
        if not title or not title.strip():
            return
        note = mail_note(self.msg)
        core.add_local_event(d.isoformat(), t or None, f"{title.strip()} [[{note}]]")
        self.app.refresh_notes_list()
        self.app.refresh_calendar(sync=True)  # pushes it to a connected calendar too
        self.status.setText(f"Event on {core.show_date(d)}{' ' + t if t else ''}, also on your calendar.")
