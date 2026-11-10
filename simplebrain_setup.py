"""Connecting your own email and your own website (Qt): pick the service, follow numbered steps with a button that
opens the right page, paste what it gives you, and SimpleBrain tries it before saving anything.
The talking is in simplebrain_mail (IMAP/SMTP, Fastmail JMAP) and simplebrain_publish (WordPress, Shopify, a folder).
"""
import html
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

import simplebrain_mail as mail
import simplebrain_publish as pub

SECURITY = [("SSL/TLS", "ssl"), ("STARTTLS", "starttls"), ("None (not safe)", "none")]


class _Back(QObject):
    done = Signal(object)


def steps_html(steps, note=""):
    items = "".join(f"<li style='margin-bottom:6px'>{s}</li>" for s in steps)
    return f"<ol style='margin-left:-20px'>{items}</ol>" + (f"<p>{note}</p>" if note else "")


class _Wizard(QDialog):
    """Two pages (choose, then steps + fields), a status line, and work done off the UI thread."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.stack = QStackedWidget()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        self.back_btn, self.next_btn = QPushButton("Back"), QPushButton("Next")
        self.next_btn.setDefault(True)
        self.back_btn.clicked.connect(lambda: self.go(0))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(cancel)
        row.addStretch(1)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self._back = _Back()
        self._back.done.connect(lambda f: f())
        self.busy = False

    def go(self, page):
        self.stack.setCurrentIndex(page)
        self.back_btn.setVisible(page > 0)
        self.status.setText("")

    def say(self, text, bad=False):
        self.status.setText(f"<span style='color:#e58a6e'>{html.escape(text)}</span>" if bad else html.escape(text))

    def bg(self, fn, then, doing):
        """fn() on a thread; then(result) on the UI thread; an error lands in the status line."""
        if self.busy:
            return
        self.busy = True
        self.next_btn.setEnabled(False)
        self.say(doing)

        def work():
            try:
                r = fn()
                self._back.done.emit(lambda: self._finish(lambda: then(r)))
            except Exception as e:  # any failure is a reason to show, never a crash
                why = str(e) or type(e).__name__
                self._back.done.emit(lambda: self._finish(lambda: self.say(why, bad=True)))
        threading.Thread(target=work, daemon=True).start()

    def _finish(self, f):
        self.busy = False
        self.next_btn.setEnabled(True)
        f()


def _page(*widgets):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        lay.addLayout(x) if isinstance(x, (QFormLayout, QHBoxLayout, QVBoxLayout)) else lay.addWidget(x)
    lay.addStretch(1)
    return w


def _label(text=""):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.RichText)
    lab.setOpenExternalLinks(True)
    return lab


class EmailSetup(_Wizard):
    """Your address -> the provider's steps for an app password -> Connect (tried before it's saved)."""

    def __init__(self, parent=None):
        super().__init__(parent, "Connect your email")
        self.saved = None
        now = mail.load_config()
        # page 1: who you are
        self.email = QLineEdit(now.get("email", "") if now else "")
        self.email.setPlaceholderText("you@example.com")
        self.name = QLineEdit(now.get("name", "") if now else "")
        self.name.setPlaceholderText("Your name, as people see it on mail you send")
        form = QFormLayout()
        form.addRow("Email address", self.email)
        form.addRow("Your name", self.name)
        intro = _label("SimpleBrain reads your inbox (twice a day it picks out the few emails that need you) and "
                       "sends the replies you write in it. It works with any email service. Your password stays on "
                       "this computer, readable only by you; it is never in your notes and never synced.")
        widgets = [intro, form]
        if now:
            self.off_btn = QPushButton("Disconnect email")
            self.off_btn.clicked.connect(self.disconnect)
            row = QHBoxLayout()
            row.addWidget(_label(f"Connected now: <b>{html.escape(mail.describe(now))}</b>"), 1)
            row.addWidget(self.off_btn)
            widgets.insert(1, row)
        self.stack.addWidget(_page(*widgets))
        # page 2: the provider's steps and the password
        self.provider = QComboBox()
        self.keys = list(mail.PROVIDERS) + ["other"]
        for k in self.keys:
            self.provider.addItem((mail.PROVIDERS.get(k) or mail.OTHER)["name"], k)
        self.provider.currentIndexChanged.connect(self.show_provider)
        self.steps = _label()
        self.open_btn = QPushButton("Open the app password page")
        self.open_btn.clicked.connect(self.open_page)
        self.imap_host, self.smtp_host = QLineEdit(), QLineEdit()
        self.imap_port, self.smtp_port = QSpinBox(), QSpinBox()
        for sp in (self.imap_port, self.smtp_port):
            sp.setRange(1, 65535)
        self.imap_tls, self.smtp_tls = QComboBox(), QComboBox()
        for box in (self.imap_tls, self.smtp_tls):
            for label, key in SECURITY:
                box.addItem(label, key)
        self.user = QLineEdit()
        self.user.setPlaceholderText("Usually your whole email address")
        self.servers = QWidget()
        sform = QFormLayout(self.servers)
        sform.setContentsMargins(0, 0, 0, 0)
        for label, host, port, tls in (("Incoming (IMAP)", self.imap_host, self.imap_port, self.imap_tls),
                                       ("Outgoing (SMTP)", self.smtp_host, self.smtp_port, self.smtp_tls)):
            r = QHBoxLayout()
            r.addWidget(host, 1)
            r.addWidget(port)
            r.addWidget(tls)
            sform.addRow(label, r)
        sform.addRow("User name", self.user)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Paste the app password here")
        self.pw_row = QWidget()
        pform = QFormLayout(self.pw_row)
        pform.setContentsMargins(0, 0, 0, 0)
        pform.addRow("Password", self.password)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Email service"))
        prow.addWidget(self.provider, 1)
        orow = QHBoxLayout()
        orow.addWidget(self.open_btn)
        orow.addStretch(1)
        self.stack.addWidget(_page(prow, self.steps, orow, self.servers, self.pw_row))
        self.next_btn.clicked.connect(self.next)
        self._guessed_for = None
        self.go(0)

    def go(self, page):
        super().go(page)
        self.next_btn.setText("Next" if page == 0 else "Connect")

    def next(self):
        if self.stack.currentIndex() == 0:
            addr = self.email.text().strip()
            if "@" not in addr or "." not in addr.rsplit("@", 1)[-1]:
                return self.say("Type your whole email address, like you@example.com.", bad=True)
            if not self.user.text().strip() or self._guessed_for != addr:
                self.user.setText(addr)
            self.go(1)
            self.provider.setCurrentIndex(self.keys.index(mail.provider_for(addr)))
            self.show_provider()
            return
        self.connect_it()

    def key(self):
        return self.provider.currentData()

    def show_provider(self, *_):
        k = self.key()
        p = mail.PROVIDERS.get(k) or mail.OTHER
        blocked = p.get("blocked")
        self.steps.setText(f"<p>{blocked}</p>" if blocked else steps_html(p["steps"]))
        self.open_btn.setVisible(bool(p.get("page")) and not blocked)
        self.servers.setVisible(k == "other")
        self.pw_row.setVisible(not blocked)
        self.next_btn.setEnabled(not blocked)
        if k == "other" and self._guessed_for != self.email.text().strip():
            self.fill_servers()

    def fill_servers(self):
        addr = self._guessed_for = self.email.text().strip()

        def show(found):
            for (host, port, tls), (h, pt, t) in ((found["imap"], (self.imap_host, self.imap_port, self.imap_tls)),
                                                   (found["smtp"], (self.smtp_host, self.smtp_port, self.smtp_tls))):
                h.setText(host)
                pt.setValue(int(port))
                t.setCurrentIndex([k for _, k in SECURITY].index(tls))
            self.say("Filled in the usual settings for this address; change them if your provider says otherwise.")
        self.bg(lambda: mail.guess_servers(addr), show, "Looking up the settings for this address…")

    def open_page(self):
        p = mail.PROVIDERS.get(self.key()) or {}
        if p.get("page"):
            QDesktopServices.openUrl(QUrl(p["page"]))

    def config(self):
        addr, k = self.email.text().strip(), self.key()
        if k == "other":
            if not (self.imap_host.text().strip() and self.smtp_host.text().strip()):
                raise ValueError("Type the incoming (IMAP) and outgoing (SMTP) server names.")
            return mail.imap_config(addr, self.password.text(), self.name.text(), "other",
                                    (self.imap_host.text().strip(), self.imap_port.value(), self.imap_tls.currentData()),
                                    (self.smtp_host.text().strip(), self.smtp_port.value(), self.smtp_tls.currentData()),
                                    self.user.text().strip())
        return mail.imap_config(addr, self.password.text(), self.name.text(), k)

    def connect_it(self):
        if not self.password.text().strip():
            return self.say("Paste the password first.", bad=True)
        try:
            cfg = self.config()
        except ValueError as e:
            return self.say(str(e), bad=True)
        if cfg["user"] != cfg["email"] or self.key() != "icloud":
            tries = [cfg]
        else:  # iCloud: some accounts sign in to reading with the name before the @
            tries = [cfg, {**cfg, "user": cfg["email"].split("@")[0]}]

        def work():
            last = None
            for c in tries:
                try:
                    return c, mail.check_login(c)
                except ValueError as e:
                    last = e
            raise last

        def done(r):
            cfg, line = r
            mail.save_config(cfg)
            self.saved = cfg
            self.result_line = line + " The digest comes at 9 and 4; the Mail button at the top opens your inbox."
            self.accept()
        self.bg(work, done, "Trying it…")

    def disconnect(self):
        mail.forget_token()
        self.saved = {}
        self.result_line = "Email disconnected; the password is deleted from this computer."
        self.accept()


class WebsiteSetup(_Wizard):
    """WordPress, Shopify, or any other site (a folder of pages): numbered steps, then Connect (tried first)."""
    KINDS = [("wordpress", "WordPress", "Your own WordPress site (self-hosted, or WordPress.com Business and up)"),
             ("shopify", "Shopify", "The pages of your Shopify store"),
             ("folder", "Any other website", "plain web pages in a folder: upload it, or let it sync to "
                                             "Netlify, GitHub Pages, Neocities or your host")]

    def __init__(self, parent=None):
        super().__init__(parent, "Your website")
        self.saved = None
        now = pub.site_config()
        intro = _label("Tick <b>Show this note on my website</b> on a note and SimpleBrain publishes it as a page, "
                       "keeps it up to date when you save, and takes it down when you untick it. Tasks and calendar "
                       "lines are left out. A list of the published notes is made for you. Where is your website?")
        self.group = QButtonGroup(self)
        widgets = [intro]
        if now:
            row = QHBoxLayout()
            row.addWidget(_label(f"Connected now: <b>{html.escape(self.describe(now))}</b>"), 1)
            off = QPushButton("Stop publishing")
            off.clicked.connect(self.turn_off)
            row.addWidget(off)
            widgets.append(row)
        for i, (k, name, desc) in enumerate(self.KINDS):
            rb = QRadioButton(f"{name}: {desc}")
            self.group.addButton(rb, i)
            widgets.append(rb)
        pick = [k for k, _, _ in self.KINDS].index(now["kind"]) if now else 0
        self.group.button(pick).setChecked(True)
        self.stack.addWidget(_page(*widgets))
        # page 2: one panel per kind
        self.panels = QStackedWidget()
        self.steps = _label()
        self.open_btn = QPushButton()
        self.open_btn.clicked.connect(self.open_page)
        cur = now or {}
        same = lambda k, f: cur.get(f, "") if cur.get("kind") == k else ""
        self.wp_url, self.wp_user, self.wp_pass = QLineEdit(same("wordpress", "url")), QLineEdit(same("wordpress", "user")), QLineEdit()
        self.wp_url.setPlaceholderText("yoursite.com")
        self.wp_pass.setEchoMode(QLineEdit.Password)
        self.wp_pass.setPlaceholderText("xxxx xxxx xxxx xxxx xxxx xxxx")
        f1 = QFormLayout()
        f1.addRow("Site address", self.wp_url)
        f1.addRow("User name", self.wp_user)
        f1.addRow("Application password", self.wp_pass)
        self.shop, self.client_id, self.secret = QLineEdit(same("shopify", "shop")), QLineEdit(same("shopify", "client_id")), QLineEdit()
        self.shop.setPlaceholderText("your-store.myshopify.com")
        self.secret.setEchoMode(QLineEdit.Password)
        f2 = QFormLayout()
        f2.addRow("Store address", self.shop)
        f2.addRow("Client ID", self.client_id)
        f2.addRow("Client secret", self.secret)
        self.folder = QLineEdit(same("folder", "folder"))
        browse = QPushButton("Choose…")
        browse.clicked.connect(self.choose_folder)
        frow = QHBoxLayout()
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)
        f3 = QFormLayout()
        f3.addRow("Folder", frow)
        for f in (f1, f2, f3):
            w = QWidget()
            f.setContentsMargins(0, 0, 0, 0)
            w.setLayout(f)
            self.panels.addWidget(w)
        orow = QHBoxLayout()
        orow.addWidget(self.open_btn)
        orow.addStretch(1)
        self.stack.addWidget(_page(self.steps, orow, self.panels))
        self.next_btn.clicked.connect(self.next)
        self.go(0)

    @staticmethod
    def describe(cfg):
        return {"wordpress": lambda: f"WordPress, {cfg['url']}", "shopify": lambda: f"Shopify, {cfg['shop']}",
                "folder": lambda: f"pages in {cfg['folder']}"}[cfg["kind"]]()

    def kind(self):
        return self.KINDS[self.group.checkedId()][0]

    def go(self, page):
        super().go(page)
        self.next_btn.setText("Next" if page == 0 else "Connect")

    STEPS = {
        "wordpress": (["Type your site's address below, then click <b>Open my WordPress profile</b> (or sign in at "
                       "yoursite.com/wp-admin and go to <b>Users</b> &gt; <b>Profile</b>).",
                       "Scroll down to <b>Application Passwords</b>, type <b>SimpleBrain</b> as the name and click "
                       "<b>Add New Application Password</b>.",
                       "Copy the password WordPress shows (the spaces are fine) and paste it below, with the user "
                       "name you sign in with."],
                      "Your site needs WordPress 5.6 or newer and an https:// address. Pages are published under your "
                      "site's address, like yoursite.com/my-note/."),
        "shopify": (["Click <b>Open the Shopify Dev Dashboard</b> and sign in with the account that owns your store.",
                     "Click <b>Create app</b> and name it <b>SimpleBrain</b>.",
                     "In the app's version, add the access scope <b>write_online_store_pages</b>, then click "
                     "<b>Release</b>.",
                     "Install the app on your store (the app's <b>Home</b> &gt; <b>Install app</b>).",
                     "Open the app's <b>Settings</b>, copy the <b>Client ID</b> and <b>Client secret</b>, and paste "
                     "them below with your store address (it ends in .myshopify.com)."],
                    "Pages appear in your store at /pages/…, and the list of notes at /pages/notes."),
        "folder": (["Click <b>Choose…</b> and pick (or make) an empty folder. SimpleBrain writes each published note "
                    "there as a web page, plus <b>index.html</b>, the list of notes.",
                    "Get the folder onto your site the way your host takes files: drag it onto Netlify Drop, push it "
                    "to GitHub Pages, upload it in your host's file manager or by FTP, or choose a folder that "
                    "already syncs to your site.",
                    "Every save updates the pages in the folder. A synced folder updates the site by itself; "
                    "otherwise upload the folder again when you want the site to catch up."],
                   "The pages are plain HTML with a little styling, so they work on any web host."),
    }

    def next(self):
        if self.stack.currentIndex() == 0:
            k = self.kind()
            steps, note = self.STEPS[k]
            self.steps.setText(steps_html(steps, note))
            self.panels.setCurrentIndex([x for x, _, _ in self.KINDS].index(k))
            self.open_btn.setText({"wordpress": "Open my WordPress profile", "shopify": "Open the Shopify Dev Dashboard"}.get(k, ""))
            self.open_btn.setVisible(k != "folder")
            return self.go(1)
        self.connect_it()

    def open_page(self):
        if self.kind() == "shopify":
            return QDesktopServices.openUrl(QUrl("https://dev.shopify.com/dashboard"))
        if not self.wp_url.text().strip():
            return self.say("Type your site's address first.", bad=True)
        QDesktopServices.openUrl(QUrl(pub.site_url(self.wp_url.text()) + "/wp-admin/profile.php#application-passwords-section"))

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder for your web pages", self.folder.text())
        if d:
            self.folder.setText(d)

    def config(self):
        k = self.kind()
        vals = {"wordpress": {"url": self.wp_url.text(), "user": self.wp_user.text(), "password": self.wp_pass.text()},
                "shopify": {"shop": self.shop.text(), "client_id": self.client_id.text(), "client_secret": self.secret.text()},
                "folder": {"folder": self.folder.text()}}[k]
        missing = [f for f, v in vals.items() if not v.strip()]
        if missing:
            raise ValueError("Fill in: " + ", ".join(m.replace("_", " ") for m in missing) + ".")
        cfg = {"kind": k, **{f: v.strip() for f, v in vals.items()}}
        if k == "wordpress":
            cfg["url"] = pub.site_url(cfg["url"])
        return cfg

    def connect_it(self):
        try:
            cfg = self.config()
        except ValueError as e:
            return self.say(str(e), bad=True)

        def done(line):
            pub.save_site_config(cfg)
            self.saved = cfg
            self.result_line = line + " Tick 'Show this note on my website' on a note to publish it."
            self.accept()
        self.bg(lambda: pub.check(cfg), done, "Trying it…")

    def turn_off(self):
        pub.save_site_config({"kind": "off"})
        self.saved = {}
        self.result_line = "Website disconnected: notes are no longer published (pages already up stay until you remove them)."
        self.accept()
