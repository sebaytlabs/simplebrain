#!/usr/bin/env python3
"""Email inside SimpleBrain, and the few messages that need you, twice a day. No Qt here (the window is
simplebrain_mailwin, the setup steps simplebrain_setup).

Any email service: your address and an app password (IMAP to read, SMTP to send; `ImapAccount`, `imap_fetch`),
with the servers and the steps known for Gmail, iCloud, Yahoo, AOL, Fastmail, Zoho and GMX, and looked up for others.
Fastmail can also use an API token over JMAP (`Account`, `fetch`). The setup is kept in the settings folder on this
computer, readable only by you, never in the vault and never synced. Both read, send, archive, delete (to Trash) and
mark read; the digest only reads.

What needs you: unread mail in the Inbox from the last two days that isn't a newsletter or a no-reply robot, people
and places you name in Home first (`mail:: riverside.example, bank.example, dad@example.com`). The newest three are the
digest; the app shows it as one card in the morning and one in the afternoon, and Today lists it.

Run: python simplebrain_mail.py   (selftest, against a fake server on this computer)
"""
import json
import os
import re
import stat
import urllib.request
from datetime import datetime, timedelta, timezone

import simplebrain_core as core

SESSION_URL = "https://api.fastmail.com/jmap/session"
MAIL = "urn:ietf:params:jmap:mail"
ROBOT = re.compile(r"no-?reply|do-?not-?reply|notifications?@|mailer-daemon|newsletter|news@|marketing|bounce", re.I)
IMPORTANT_RE = re.compile(r"^\s*mail::\s*(.+?)\s*$", re.I | re.M)
TIMES = (9, 16)  # the two digests: morning and afternoon


def token_path():
    return os.path.join(core.user_config_dir(), "mail.json")


def save_token(token, session_url=SESSION_URL):
    path = token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)  # private from the start
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"token": token.strip(), "session": session_url}, f)


def load_token():
    try:
        with open(token_path(), encoding="utf-8") as f:
            d = json.load(f)
        return (d["token"], d.get("session", SESSION_URL)) if d.get("token") else None
    except (OSError, ValueError, KeyError):
        return None


def forget_token():
    try:
        os.remove(token_path())
    except OSError:
        pass


def _call(url, token, body=None, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def important(vault=None):
    try:
        text = core.settings_text(vault or core.VAULT)
    except OSError:
        return []
    return [w.strip().lower() for line in IMPORTANT_RE.findall(text) for w in re.split(r"[,;\s]+", line) if w.strip()]


def fetch(token, session_url=SESSION_URL, since_h=48, limit=40, timeout=15):
    """Unread Inbox messages from the last `since_h` hours: [{"from", "name", "subject", "preview", "when", "list"}].
    Raises OSError / ValueError when the server can't be reached or refuses the token."""
    session = _call(session_url, token, timeout=timeout)
    api = session["apiUrl"]
    acct = session["primaryAccounts"][MAIL]
    after = (datetime.now(timezone.utc) - timedelta(hours=since_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"using": ["urn:ietf:params:jmap:core", MAIL], "methodCalls": [
        ["Mailbox/query", {"accountId": acct, "filter": {"role": "inbox"}}, "box"],
        ["Email/query", {"accountId": acct, "filter": {"operator": "AND", "conditions": [
            {"#inMailbox": None}, {"notKeyword": "$seen"}, {"after": after}]},
            "sort": [{"property": "receivedAt", "isAscending": False}], "limit": limit}, "q"],
        ["Email/get", {"accountId": acct, "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                       "properties": ["from", "subject", "preview", "receivedAt", "header:List-Unsubscribe:asURLs"]}, "g"]]}  # List-* headers only come asRaw/asURLs (RFC 8621 4.1.2); asText is refused
    # the inbox id comes from the first call: JMAP back-references only reach into ids lists, so ask in two steps
    first = _call(api, token, {"using": body["using"], "methodCalls": [body["methodCalls"][0]]}, timeout)
    box = first["methodResponses"][0][1]["ids"][0]
    body["methodCalls"] = body["methodCalls"][1:]
    body["methodCalls"][0][1]["filter"]["conditions"][0] = {"inMailbox": box}
    resp = _call(api, token, body, timeout)
    got = next(r[1] for r in resp["methodResponses"] if r[0] == "Email/get")
    out = []
    for e in got.get("list", []):
        sender = (e.get("from") or [{}])[0]
        out.append({"from": (sender.get("email") or "").lower(), "name": sender.get("name") or sender.get("email") or "?",
                    "subject": (e.get("subject") or "(no subject)").strip(), "preview": (e.get("preview") or "")[:140],
                    "when": e.get("receivedAt", ""), "list": bool(e.get("header:List-Unsubscribe:asURLs"))})
    return out


SUBMISSION = "urn:ietf:params:jmap:submission"
SUMMARY_PROPS = ["from", "to", "cc", "subject", "preview", "receivedAt", "keywords", "mailboxIds"]


def _who(addrs):
    return ", ".join((a.get("name") or a.get("email") or "") for a in (addrs or []))


def html_to_text(h):
    """Readable text from an HTML mail: line breaks kept, tags and styles gone, entities decoded."""
    import html as _html
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", h)
    h = re.sub(r"(?i)<li\b[^>]*>", "• ", h)
    h = re.sub(r"(?i)<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", lambda m: m.group(2) if m.group(1) in m.group(2)
               else f"{m.group(2)} ({m.group(1)})", h)
    t = _html.unescape(re.sub(r"<[^>]+>", "", h))
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", "\n".join(l.strip() for l in t.splitlines())).strip()


class Account:
    """The whole mailbox over JMAP: list, read, reply/send, archive, delete, mark read.
    Everything here acts on the real account; the app asks before anything it can't undo."""

    def __init__(self, token, session_url=SESSION_URL, timeout=20):
        self.token, self.timeout = token, timeout
        s = _call(session_url, token, timeout=timeout)
        self.api, self.acct = s["apiUrl"], s["primaryAccounts"][MAIL]
        self.using = ["urn:ietf:params:jmap:core", MAIL] + ([SUBMISSION] if SUBMISSION in s.get("capabilities", {}) else [])
        self._boxes = None

    def call(self, *calls):
        r = _call(self.api, self.token, {"using": self.using, "methodCalls": list(calls)}, self.timeout)
        out = {}
        for name, args, tag in r["methodResponses"]:
            if name == "error":
                raise ValueError(f"Fastmail said no: {args.get('type')} {args.get('description', '')}".strip())
            out[tag] = args
        return out

    def boxes(self):
        """{role: id} for inbox, archive, trash, sent, drafts."""
        if self._boxes is None:
            got = self.call(["Mailbox/get", {"accountId": self.acct, "properties": ["role", "name"]}, "b"])["b"]["list"]
            self._boxes = {b["role"]: b["id"] for b in got if b.get("role")}
        return self._boxes

    def inbox(self, limit=60):
        """Newest first: [{"id", "from", "email", "subject", "preview", "when", "unread"}]."""
        got = self.call(
            ["Email/query", {"accountId": self.acct, "filter": {"inMailbox": self.boxes()["inbox"]},
                             "sort": [{"property": "receivedAt", "isAscending": False}], "limit": limit}, "q"],
            ["Email/get", {"accountId": self.acct, "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                           "properties": SUMMARY_PROPS}, "g"])["g"]["list"]
        return [{"id": e["id"], "from": _who(e.get("from")), "email": ((e.get("from") or [{}])[0].get("email") or ""),
                 "subject": (e.get("subject") or "(no subject)").strip(), "preview": e.get("preview") or "",
                 "when": e.get("receivedAt", ""), "unread": "$seen" not in (e.get("keywords") or {})} for e in got]

    def message(self, eid):
        """One email in full: headers to reply with, and the body as plain text."""
        e = self.call(["Email/get", {"accountId": self.acct, "ids": [eid], "fetchTextBodyValues": True,
                                     "fetchHTMLBodyValues": True, "properties": SUMMARY_PROPS + [
                                         "replyTo", "messageId", "references", "textBody", "htmlBody", "bodyValues"]},
                       "g"])["g"]["list"][0]
        vals = e.get("bodyValues") or {}
        text = "\n".join(vals[p["partId"]]["value"] for p in e.get("textBody") or [] if p.get("partId") in vals
                         and p.get("type") == "text/plain")
        if not text.strip():
            text = html_to_text("\n".join(vals[p["partId"]]["value"] for p in e.get("htmlBody") or []
                                          if p.get("partId") in vals))
        return {**e, "text": text.strip(), "from_text": _who(e.get("from")), "to_text": _who(e.get("to")),
                "cc_text": _who(e.get("cc"))}

    def _update(self, eid, patch):
        r = self.call(["Email/set", {"accountId": self.acct, "update": {eid: patch}}, "s"])["s"]
        if eid in (r.get("notUpdated") or {}):
            raise ValueError(f"Fastmail didn't change it: {r['notUpdated'][eid].get('type')}")

    def mark_read(self, eid, read=True):
        self._update(eid, {"keywords/$seen": True if read else None})

    def move(self, eid, role):
        """Out of the inbox into Archive or Trash (Trash keeps it ~30 days on Fastmail: delete is undoable there)."""
        self._update(eid, {"mailboxIds": {self.boxes()[role]: True}, "keywords/$seen": True})

    def archive(self, eid):
        self.move(eid, "archive")

    def trash(self, eid):
        self.move(eid, "trash")

    def identities(self):
        """[{"id", "email", "name"}]; a wildcard identity (*@domain) means any address at that domain."""
        return [{"id": i["id"], "email": i["email"], "name": i.get("name") or ""}
                for i in self.call(["Identity/get", {"accountId": self.acct}, "i"])["i"]["list"]]

    def send(self, to, subject, text, identity=None, from_email=None, reply_to=None, cc=""):
        """Send a plain-text email. `reply_to` is the message() being answered (threads it). Kept in Sent."""
        ids = self.identities()
        ident = identity or ids[0]
        sender = from_email or ident["email"]
        rcpt = parse_addresses(to) + parse_addresses(cc)
        if not rcpt:
            raise ValueError("Who is it to? No email address found.")
        mail = {"mailboxIds": {self.boxes()["drafts"]: True}, "keywords": {"$draft": True, "$seen": True},
                "from": [{"name": ident["name"], "email": sender}], "to": parse_addresses(to), "subject": subject,
                "bodyValues": {"b": {"value": text}}, "textBody": [{"partId": "b", "type": "text/plain"}]}
        if cc.strip():
            mail["cc"] = parse_addresses(cc)
        if reply_to:
            mid = reply_to.get("messageId") or []
            mail["inReplyTo"] = mid
            mail["references"] = (reply_to.get("references") or []) + mid
        sent_box = self.boxes().get("sent")
        r = self.call(
            ["Email/set", {"accountId": self.acct, "create": {"m": mail}}, "c"],
            ["EmailSubmission/set", {"accountId": self.acct, "create": {"s": {
                "identityId": ident["id"], "emailId": "#m",
                "envelope": {"mailFrom": {"email": sender}, "rcptTo": [{"email": a["email"]} for a in rcpt]}}},
                "onSuccessUpdateEmail": {"#s": {"mailboxIds": {sent_box: True}, "keywords/$draft": None}}}, "x"])
        if r["c"].get("notCreated") or r["x"].get("notCreated"):
            why = (r["c"].get("notCreated") or r["x"].get("notCreated"))
            raise ValueError(f"Not sent: {json.dumps(why)[:200]}")
        if reply_to:
            self._update(reply_to["id"], {"keywords/$answered": True, "keywords/$seen": True})


def parse_addresses(s):
    """'Amy <amy@x.org>, bob@y.com' -> [{"name": "Amy", "email": "amy@x.org"}, {"name": "", "email": "bob@y.com"}]."""
    from email.utils import getaddresses
    return [{"name": n, "email": e} for n, e in getaddresses([s or ""]) if "@" in e]


def pick_identity(ids, msg):
    """Reply from the address the mail was sent to (a wildcard identity covers its whole domain); else the first."""
    for a in (msg.get("to") or []) + (msg.get("cc") or []):
        addr = (a.get("email") or "").lower()
        for i in ids:
            pat = i["email"].lower()
            if addr == pat or (pat.startswith("*@") and addr.endswith(pat[1:])):
                return i, addr
    return ids[0], ids[0]["email"]


def local_when(stamp):
    """'Sun, Nov 1, 2026 at 12:57 PM' on this computer's clock, from a JMAP UTC stamp; '' if there's none."""
    try:
        dt = datetime.fromisoformat((stamp or "").replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    return f"{dt:%a, %b} {dt.day}, {dt.year} at " + dt.strftime("%I:%M %p").lstrip("0")


def reply_text(msg):
    """The quoted original under a blank space to write in."""
    when = local_when(msg.get("receivedAt"))
    quoted = "\n".join("> " + l for l in msg.get("text", "").splitlines())
    return f"\n\nOn {when}, {msg.get('from_text', '')} wrote:\n{quoted}\n"


def needs_you(messages, vip=(), n=3):
    """The few that need a person: named people/places first, then anyone who isn't a newsletter or a robot."""
    def is_vip(m):
        return any(v in m["from"] for v in vip)
    keep = [m for m in messages if is_vip(m) or not (m["list"] or ROBOT.search(m["from"]))]
    keep.sort(key=lambda m: (not is_vip(m), [-ord(c) for c in m["when"]]))
    return keep[:n]


def digest_path():
    return os.path.join(core.user_config_dir(), "mail-digest.json")


def save_digest(items, now=None):
    os.makedirs(os.path.dirname(digest_path()), exist_ok=True)
    core.write_atomic(digest_path(), json.dumps({"when": (now or datetime.now()).isoformat(timespec="seconds"),
                                                 "items": items}))


def last_digest():
    try:
        with open(digest_path(), encoding="utf-8") as f:
            d = json.load(f)
        return datetime.fromisoformat(d["when"]), d["items"]
    except (OSError, ValueError, KeyError):
        return None, []


def due(now=None, last=None):
    """True when a digest is due: past 9am or 4pm, and none since that time today."""
    now = now or datetime.now()
    slots = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in TIMES if now.hour >= h]
    return bool(slots) and (last is None or last < slots[-1])


def lines(items):
    return [f"{m['name']}: {m['subject']}" for m in items]


# -- any email service: IMAP to read, SMTP to send, with an app password --------------------------------------
PROVIDERS = {  # what to tell people, and the servers, for the services most people have
    "gmail": {"name": "Gmail", "domains": ("gmail.com", "googlemail.com"),
              "imap": ("imap.gmail.com", 993, "ssl"), "smtp": ("smtp.gmail.com", 465, "ssl"), "saves_sent": True,
              "page": "https://myaccount.google.com/apppasswords",
              "steps": ["Google lets other programs in only with an app password, and app passwords need 2-Step "
                        "Verification. If it isn't on yet, turn it on at myaccount.google.com/security first.",
                        "Click <b>Open the app password page</b> below and sign in to Google.",
                        "Type <b>SimpleBrain</b> as the app name and click <b>Create</b>.",
                        "Copy the 16-letter password Google shows and paste it below. (You won't see it again; "
                        "you can always make another.)"]},
    "icloud": {"name": "iCloud Mail", "domains": ("icloud.com", "me.com", "mac.com"),
               "imap": ("imap.mail.me.com", 993, "ssl"), "smtp": ("smtp.mail.me.com", 587, "starttls"),
               "page": "https://account.apple.com/account/manage",
               "steps": ["Click <b>Open the app password page</b> below and sign in with your Apple Account.",
                         "Go to <b>Sign-In and Security</b> &gt; <b>App-Specific Passwords</b> and click <b>+</b>.",
                         "Name it <b>SimpleBrain</b> and click <b>Create</b>.",
                         "Copy the password (four groups of letters, like abcd-efgh-ijkl-mnop) and paste it below."]},
    "yahoo": {"name": "Yahoo Mail", "domains": ("yahoo.com", "ymail.com", "rocketmail.com", "yahoo.co.uk", "yahoo.ca"),
              "imap": ("imap.mail.yahoo.com", 993, "ssl"), "smtp": ("smtp.mail.yahoo.com", 465, "ssl"),
              "page": "https://login.yahoo.com/account/security",
              "steps": ["Click <b>Open the app password page</b> below and sign in to Yahoo.",
                        "Under <b>Account security</b>, click <b>Generate app password</b> (or <b>Generate and manage "
                        "app passwords</b>).",
                        "Name it <b>SimpleBrain</b> and click <b>Generate password</b>.",
                        "Copy the password Yahoo shows and paste it below."]},
    "aol": {"name": "AOL Mail", "domains": ("aol.com", "aim.com"),
            "imap": ("imap.aol.com", 993, "ssl"), "smtp": ("smtp.aol.com", 465, "ssl"),
            "page": "https://login.aol.com/account/security",
            "steps": ["Click <b>Open the app password page</b> below and sign in to AOL.",
                      "Under <b>Account security</b>, click <b>Generate app password</b>.",
                      "Name it <b>SimpleBrain</b> and click <b>Generate password</b>.",
                      "Copy the password AOL shows and paste it below."]},
    "fastmail": {"name": "Fastmail", "domains": ("fastmail.com", "fastmail.fm", "fastmail.us", "fastmail.to",
                                                 "fastmail.net", "messagingengine.com"),
                 "imap": ("imap.fastmail.com", 993, "ssl"), "smtp": ("smtp.fastmail.com", 465, "ssl"), "saves_sent": True,
                 "page": "https://app.fastmail.com/settings/security/apps",
                 "steps": ["Click <b>Open the app password page</b> below and sign in to Fastmail (or go to "
                           "<b>Settings</b> &gt; <b>Privacy &amp; Security</b> &gt; <b>Manage app passwords and access</b>).",
                           "Click <b>New app password</b>. Name it <b>SimpleBrain</b> and give it access to "
                           "<b>Mail (IMAP/POP/SMTP)</b>.",
                           "Click <b>Generate password</b>, copy it, and paste it below."]},
    "zoho": {"name": "Zoho Mail", "domains": ("zoho.com", "zohomail.com"),
             "imap": ("imap.zoho.com", 993, "ssl"), "smtp": ("smtp.zoho.com", 465, "ssl"),
             "page": "https://accounts.zoho.com/home#security/app_password",
             "steps": ["In Zoho Mail, make sure IMAP is on: <b>Settings</b> &gt; <b>Mail Accounts</b> &gt; <b>IMAP</b>.",
                       "Click <b>Open the app password page</b> below and sign in to Zoho.",
                       "Click <b>Generate New Password</b>, name it <b>SimpleBrain</b>, and copy the password.",
                       "Paste it below. (Without two-factor sign-in on, your normal Zoho password works too.)"]},
    "gmx": {"name": "GMX", "domains": ("gmx.com", "gmx.us", "gmx.net", "gmx.de"),
            "imap": ("imap.gmx.com", 993, "ssl"), "smtp": ("mail.gmx.com", 587, "starttls"),
            "page": "https://www.gmx.com/",
            "steps": ["Sign in to GMX and open <b>Settings</b> &gt; <b>POP3 &amp; IMAP</b>.",
                      "Tick <b>Enable access to this account via POP3 and IMAP</b> and save.",
                      "Paste your GMX password below (or an app password, if you use two-factor sign-in)."]},
    "outlook": {"name": "Outlook.com / Hotmail", "domains": ("outlook.com", "hotmail.com", "live.com", "msn.com",
                                                            "hotmail.co.uk", "outlook.co.uk"),
                "blocked": "Outlook.com and Hotmail let other programs in only through Microsoft's own sign-in page, "
                           "and SimpleBrain can't use that yet. You can still use it: in Outlook.com, go to Settings "
                           "&gt; Mail &gt; Forwarding and forward your mail to an address at one of the other services "
                           "here, then connect that one."},
    "proton": {"name": "Proton Mail", "domains": ("proton.me", "protonmail.com", "protonmail.ch", "pm.me"),
               "blocked": "Proton Mail is encrypted, so other programs reach it only through the Proton Mail Bridge app "
                          "(paid Proton plans). Install Bridge and sign in there, then pick <b>Another provider</b> "
                          "here and type the server, port, user name and password that Bridge shows."},
}
OTHER = {"name": "Another provider", "domains": (), "page": "",
         "steps": ["Ask your email provider (or look in its help pages) for its <b>IMAP</b> and <b>SMTP</b> settings. "
                   "SimpleBrain filled in its best guess below.",
                   "If your provider offers <b>app passwords</b>, make one called SimpleBrain and use it; otherwise "
                   "use your normal email password.",
                   "Paste the password below and click <b>Connect</b>; SimpleBrain tries it before saving anything."]}


def provider_for(email):
    """The provider key for an address by its domain ('gmail'), or 'other'."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return next((k for k, p in PROVIDERS.items() if domain in p["domains"]), "other")


def guess_servers(email, opener=urllib.request.urlopen):
    """IMAP/SMTP for a domain no provider covers: Thunderbird's public list of providers (only the domain is
    sent), else the usual imap./smtp. names. Returns {"imap": (host, port, tls), "smtp": (...)}."""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    found = {}
    try:
        with opener(f"https://autoconfig.thunderbird.net/v1.1/{urllib.request.quote(domain)}", timeout=8) as r:
            xml = r.read().decode("utf-8", "replace")
        for kind, tag in (("imap", "incomingServer"), ("smtp", "outgoingServer")):
            for block in re.findall(rf'<{tag} type="{kind}">(.*?)</{tag}>', xml, re.S):
                host = re.search(r"<hostname>(.*?)</hostname>", block)
                port = re.search(r"<port>(\d+)</port>", block)
                sock = re.search(r"<socketType>(.*?)</socketType>", block)
                if host and port and kind not in found:
                    found[kind] = (host.group(1).replace("%EMAILDOMAIN%", domain), int(port.group(1)),
                                   "starttls" if sock and sock.group(1).upper() == "STARTTLS" else "ssl")
    except (OSError, ValueError):
        pass
    found.setdefault("imap", (f"imap.{domain}", 993, "ssl"))
    found.setdefault("smtp", (f"smtp.{domain}", 465, "ssl"))
    return found


def imap_config(email, password, name="", provider=None, imap=None, smtp=None, user=""):
    """A saved setup for any IMAP/SMTP service. `imap`/`smtp` are (host, port, "ssl" | "starttls" | "none")."""
    p = PROVIDERS.get(provider or provider_for(email), {})
    imap, smtp = imap or p.get("imap"), smtp or p.get("smtp")
    if not (imap and smtp):
        raise ValueError("Which servers? Type the IMAP and SMTP server names.")
    return {"kind": "imap", "email": email.strip(), "name": name.strip(), "password": password.strip(),
            "user": (user or email).strip(), "imap": list(imap), "smtp": list(smtp),
            "saves_sent": bool(p.get("saves_sent"))}


def save_config(cfg):
    """A setup (imap_config, or {"token", "session"} for Fastmail's JMAP), private to this user from the start."""
    path = token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def load_config():
    """The saved setup: {"kind": "imap", ...} or {"kind": "jmap", "token", "session"}; None when there is none."""
    try:
        with open(token_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if d.get("kind") == "imap" and d.get("email") and d.get("password"):
        return d
    if d.get("token"):
        return {"kind": "jmap", "token": d["token"], "session": d.get("session", SESSION_URL)}
    return None


def describe(cfg):
    """'you@gmail.com' / 'Fastmail (token)': what the setup dialog says is connected."""
    return cfg.get("email") or "Fastmail (API token)"


def open_account(cfg):
    return ImapAccount(cfg) if cfg.get("kind") == "imap" else Account(cfg["token"], cfg.get("session", SESSION_URL))


def fetch_any(cfg, since_h=48):
    return imap_fetch(cfg, since_h) if cfg.get("kind") == "imap" else fetch(cfg["token"], cfg.get("session", SESSION_URL), since_h)


def _tls_context(host):
    import ssl
    ctx = ssl.create_default_context()
    if host in ("127.0.0.1", "localhost", "::1"):  # Proton Mail Bridge and the like: a local helper with its own certificate
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    return ctx


def _imap_login(cfg, timeout=20):
    import imaplib
    host, port, tls = cfg["imap"]
    try:
        if tls == "ssl":
            c = imaplib.IMAP4_SSL(host, int(port), ssl_context=_tls_context(host), timeout=timeout)
        else:
            c = imaplib.IMAP4(host, int(port), timeout=timeout)
            if tls == "starttls":
                c.starttls(_tls_context(host))
        c.login(cfg.get("user") or cfg["email"], cfg["password"])
        typ, dat = c.capability()  # many servers list MOVE only once you're logged in
        if typ == "OK" and dat and dat[-1]:
            c.capabilities = tuple(dat[-1].decode().upper().split())
        return c
    except imaplib.IMAP4.error as e:
        raise ValueError(f"{host} didn't accept that email and password ({_said(e)}). Check the app password.") from None


def _said(e):
    t = e.args[0] if e.args else str(e)
    return (t.decode("utf-8", "replace") if isinstance(t, bytes) else str(t))[:120]


def _q(name):
    """A mailbox name as an IMAP quoted string."""
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _internaldate(meta):
    """INTERNALDATE "08-Nov-2026 10:05:00 -0600" -> "2026-11-08T16:05:00Z" (the stamps JMAP gives), '' if missing."""
    m = re.search(rb'INTERNALDATE "\s*(\d+)-(\w{3})-(\d{4}) (\d\d):(\d\d):(\d\d) ([+-])(\d\d)(\d\d)"', meta)
    if not m:
        return ""
    d, mon, y, hh, mm, ss, sign, oh, om = m.groups()
    off = timedelta(hours=int(oh), minutes=int(om)) * (1 if sign == b"+" else -1)
    dt = datetime(int(y), MONTHS.index(mon.decode().title()) + 1, int(d), int(hh), int(mm), int(ss), tzinfo=timezone(off))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetched(data):
    """imaplib FETCH results -> [(uid, flags, when, payload bytes)]."""
    out = []
    for part in data:
        if not isinstance(part, tuple):
            continue
        meta, payload = part
        uid = re.search(rb"UID (\d+)", meta)
        flags = re.search(rb"FLAGS \(([^)]*)\)", meta)
        out.append((uid.group(1).decode() if uid else "", (flags.group(1).decode() if flags else ""),
                    _internaldate(meta), payload))
    return out


def _addrs(value):
    from email.utils import getaddresses
    return [{"name": n, "email": e} for n, e in getaddresses([str(value or "")]) if e]


def _ids(value):
    return re.findall(r"<[^<>\s]+>", str(value or ""))


def parse_list_line(line):
    """b'(\\HasNoChildren \\Trash) "/" "Deleted Items"' -> (["\\Trash", ...], "Deleted Items")."""
    if isinstance(line, tuple):  # a name sent as a literal
        meta, name = line
        flags = re.match(rb"\(([^)]*)\)", meta)
        return (flags.group(1).decode().split() if flags else []), name.decode("utf-8", "replace")
    m = re.match(rb'\(([^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (.+)$', line or b"")
    if not m:
        return [], ""
    name = m.group(2).decode("utf-8", "replace").strip()
    if name.startswith('"') and name.endswith('"'):
        name = re.sub(r'\\(.)', r"\1", name[1:-1])
    return m.group(1).decode().split(), name


NAMED = {"archive": ("Archive", "Archives", "[Gmail]/All Mail", "All Mail"), "trash": ("Trash", "Deleted Items", "Deleted Messages", "Deleted", "[Gmail]/Trash", "Bin"),
         "sent": ("Sent", "Sent Items", "Sent Messages", "Sent Mail", "[Gmail]/Sent Mail"), "drafts": ("Drafts", "[Gmail]/Drafts")}
ROLES = {"\\Archive": "archive", "\\All": "archive", "\\Trash": "trash", "\\Sent": "sent", "\\Drafts": "drafts"}


class ImapAccount:
    """The same mailbox actions as Account (Fastmail's JMAP), for any service: IMAP to read and file, SMTP to
    send. One connection, one command at a time (the mail window calls from more than one thread)."""

    def __init__(self, cfg, timeout=20):
        import threading
        self.cfg, self.timeout, self.lock = cfg, timeout, threading.Lock()
        self.c, self._boxes = _imap_login(cfg, timeout), None

    def _run(self, fn):
        import imaplib
        with self.lock:
            for attempt in (0, 1):
                try:
                    return fn(self.c)
                except imaplib.IMAP4.abort:  # the server hung up (idle too long): log in again, once
                    if attempt:
                        raise ValueError("The mail server keeps hanging up; try again in a minute.") from None
                    self.c = _imap_login(self.cfg, self.timeout)
                except imaplib.IMAP4.error as e:
                    raise ValueError(f"The mail server said no: {_said(e)}") from None

    def _inbox(self, c, readonly=False):
        typ, _ = c.select("INBOX", readonly=readonly)
        if typ != "OK":
            raise ValueError("No inbox on this account.")

    def boxes(self):
        """{role: mailbox name} for archive, trash, sent, drafts: the server's own labels, else the usual names."""
        if self._boxes is None:
            def work(c):
                typ, data = c.list()
                return [parse_list_line(l) for l in data or [] if l]
            found = {}
            listed = self._run(work)
            names = {n for _, n in listed}
            for flags, name in listed:
                for f in flags:
                    role = ROLES.get(f)
                    if role and (role not in found or f == "\\Archive"):
                        found[role] = name
            for role, guesses in NAMED.items():
                if role not in found:
                    hit = next((n for g in guesses for n in names if n.lower() == g.lower()), None)
                    if hit:
                        found[role] = hit
            self._boxes = found
        return self._boxes

    def inbox(self, limit=60):
        """Newest first: [{"id", "from", "email", "subject", "preview", "when", "unread"}]; id is the IMAP UID."""
        def work(c):
            self._inbox(c, readonly=True)
            typ, data = c.uid("SEARCH", None, "ALL")
            uids = (data[0] or b"").split()[-limit:]
            if not uids:
                return []
            typ, data = c.uid("FETCH", b",".join(uids).decode(), "(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            return _fetched(data)
        out = []
        for uid, flags, when, head in self._run(work):
            msg = _parse(head)
            who = _addrs(msg["from"])
            out.append({"id": uid, "from": _who(who), "email": (who[0]["email"] if who else ""),
                        "subject": (str(msg["subject"] or "") or "(no subject)").strip(), "preview": "",
                        "when": when, "unread": "\\Seen" not in flags})
        return sorted(out, key=lambda m: (m["when"], int(m["id"] or 0)), reverse=True)

    def message(self, eid):
        def work(c):
            self._inbox(c, readonly=True)
            typ, data = c.uid("FETCH", eid, "(UID FLAGS INTERNALDATE BODY.PEEK[])")
            got = _fetched(data)
            if not got:
                raise ValueError("That email isn't in the inbox any more.")
            return got[0]
        uid, flags, when, raw = self._run(work)
        msg = _parse(raw, headers_only=False)
        body = msg.get_body(preferencelist=("plain", "html"))
        text = ""
        if body is not None:
            try:
                text = body.get_content()
            except (LookupError, ValueError):
                text = body.get_payload(decode=True).decode("utf-8", "replace")
            if body.get_content_subtype() == "html":
                text = html_to_text(text)
        frm, to, cc = _addrs(msg["from"]), _addrs(msg["to"]), _addrs(msg["cc"])
        return {"id": uid, "from": frm, "to": to, "cc": cc, "replyTo": _addrs(msg["reply-to"]) or None,
                "subject": str(msg["subject"] or ""), "receivedAt": when, "messageId": _ids(msg["message-id"]),
                "references": _ids(msg["references"]), "text": text.strip(),
                "from_text": _who(frm), "to_text": _who(to), "cc_text": _who(cc)}

    def mark_read(self, eid, read=True):
        def work(c):
            self._inbox(c)
            c.uid("STORE", eid, "+FLAGS" if read else "-FLAGS", "(\\Seen)")
        self._run(work)

    def move(self, eid, role):
        """Out of the inbox into Archive or Trash (a folder named Archive is made if the account has none)."""
        target = self.boxes().get(role) or ("Archive" if role == "archive" else None)
        if not target:
            raise ValueError("This account has no Trash folder.")

        def work(c):
            if target not in {n for _, n in [parse_list_line(l) for l in (c.list()[1] or []) if l]}:
                c.create(_q(target))
            self._inbox(c)
            c.uid("STORE", eid, "+FLAGS", "(\\Seen)")
            caps = getattr(c, "capabilities", ())
            if "MOVE" in caps:
                typ, _ = c.uid("MOVE", eid, _q(target))
                if typ != "OK":
                    raise ValueError("Not moved: the server refused.")
            else:
                typ, _ = c.uid("COPY", eid, _q(target))
                if typ != "OK":
                    raise ValueError("Not moved: the server refused the copy.")
                c.uid("STORE", eid, "+FLAGS", "(\\Deleted)")
                c.uid("EXPUNGE", eid) if "UIDPLUS" in caps else c.expunge()  # UIDPLUS: only this one, not others marked deleted
        self._run(work)

    def archive(self, eid):
        self.move(eid, "archive")

    def trash(self, eid):
        self.move(eid, "trash")

    def identities(self):
        return [{"id": "main", "email": self.cfg["email"], "name": self.cfg.get("name") or ""}]

    def send(self, to, subject, text, identity=None, from_email=None, reply_to=None, cc=""):
        """Send a plain-text email over SMTP, keep a copy in Sent (unless the service does that itself), thread replies."""
        import smtplib
        import time
        from email.message import EmailMessage
        from email.utils import formataddr, formatdate, make_msgid
        rcpt = parse_addresses(to) + parse_addresses(cc)
        if not rcpt:
            raise ValueError("Who is it to? No email address found.")
        sender = from_email or self.cfg["email"]
        m = EmailMessage()
        m["From"] = formataddr(((identity or {}).get("name") or self.cfg.get("name") or "", sender))
        m["To"] = to
        if cc.strip():
            m["Cc"] = cc
        m["Subject"] = subject
        m["Date"] = formatdate(localtime=True)
        m["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1])
        if reply_to:
            mid = reply_to.get("messageId") or []
            if mid:
                m["In-Reply-To"] = " ".join(mid)
                m["References"] = " ".join((reply_to.get("references") or []) + mid)
        m.set_content(text)
        host, port, tls = self.cfg["smtp"]
        try:
            if tls == "ssl":
                s = smtplib.SMTP_SSL(host, int(port), timeout=self.timeout, context=_tls_context(host))
            else:
                s = smtplib.SMTP(host, int(port), timeout=self.timeout)
                if tls == "starttls":
                    s.starttls(context=_tls_context(host))
            with s:
                s.login(self.cfg.get("user") or self.cfg["email"], self.cfg["password"])
                s.send_message(m, from_addr=sender, to_addrs=[a["email"] for a in rcpt])
        except smtplib.SMTPAuthenticationError:
            raise ValueError(f"{host} didn't accept that email and password for sending.") from None
        sent = self.boxes().get("sent")

        def file_it(c):
            if sent and not self.cfg.get("saves_sent"):
                import imaplib
                c.append(_q(sent), "(\\Seen)", imaplib.Time2Internaldate(time.time()), m.as_bytes())
            if reply_to and reply_to.get("id"):
                self._inbox(c)
                c.uid("STORE", reply_to["id"], "+FLAGS", "(\\Answered \\Seen)")
        self._run(file_it)


def _parse(raw, headers_only=True):
    from email import policy
    from email.parser import BytesHeaderParser, BytesParser
    return (BytesHeaderParser if headers_only else BytesParser)(policy=policy.default).parsebytes(raw or b"")


def check_login(cfg):
    """Try a setup before saving it: log in to reading and to sending. Returns a line saying it worked."""
    import smtplib
    acct = ImapAccount(cfg, timeout=15)

    def inbox_size(c):
        acct._inbox(c, readonly=True)
        return len((c.uid("SEARCH", None, "ALL")[1][0] or b"").split())
    count = acct._run(inbox_size)
    try:
        acct.c.logout()
    except Exception:
        pass
    host, port, tls = cfg["smtp"]
    try:
        s = (smtplib.SMTP_SSL(host, int(port), timeout=15, context=_tls_context(host)) if tls == "ssl"
             else smtplib.SMTP(host, int(port), timeout=15))
        with s:
            if tls == "starttls":
                s.starttls(context=_tls_context(host))
            s.login(cfg.get("user") or cfg["email"], cfg["password"])
    except smtplib.SMTPAuthenticationError:
        raise ValueError(f"Reading works, but {host} didn't accept the password for sending.") from None
    return f"Connected: {cfg['email']} ({count} in the inbox)."


def imap_fetch(cfg, since_h=48, limit=40, timeout=15):
    """The digest's input over IMAP: unread Inbox messages from the last `since_h` hours, as `fetch` returns them."""
    after = datetime.now(timezone.utc) - timedelta(hours=since_h)
    acct = ImapAccount(cfg, timeout)
    since = f"{after.day:02d}-{MONTHS[after.month - 1]}-{after.year}"

    def work(c):
        acct._inbox(c, readonly=True)
        typ, data = c.uid("SEARCH", None, "UNSEEN", "SINCE", since)
        uids = (data[0] or b"").split()[-limit:]
        if not uids:
            return []
        typ, data = c.uid("FETCH", b",".join(uids).decode(),
                          "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT LIST-UNSUBSCRIBE)])")
        return _fetched(data)
    out = []
    try:
        got = acct._run(work)
    finally:
        try:
            acct.c.logout()
        except Exception:
            pass
    stamp = after.strftime("%Y-%m-%dT%H:%M:%SZ")
    for uid, flags, when, head in got:
        if when and when < stamp:
            continue
        msg = _parse(head)
        who = (_addrs(msg["from"]) or [{"name": "", "email": ""}])[0]
        out.append({"from": who["email"].lower(), "name": who["name"] or who["email"] or "?",
                    "subject": (str(msg["subject"] or "") or "(no subject)").strip(), "preview": "",
                    "when": when, "list": bool(msg["list-unsubscribe"])})
    return sorted(out, key=lambda m: m["when"], reverse=True)


def account_selftest():
    """Account against a fake JMAP server that keeps state: list, read, mark read, archive, trash, send, reply."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    boxes = {"I": "inbox", "A": "archive", "T": "trash", "S": "sent", "D": "drafts"}
    store = {"e1": {"id": "e1", "from": [{"name": "Amy", "email": "amy@x.org"}], "to": [{"email": "sales@me.com"}],
                    "subject": "Lunch?", "preview": "Free fri", "receivedAt": "2026-11-01T15:00:00Z", "keywords": {},
                    "mailboxIds": {"I": True}, "messageId": ["<a1@x.org>"], "references": None,
                    "textBody": [], "htmlBody": [{"partId": "1", "type": "text/html"}],
                    "bodyValues": {"1": {"value": "<p>Free <b>fri</b>?</p><p>&amp; sat</p>"}}},
             "e2": {"id": "e2", "from": [{"name": "Bob", "email": "bob@y.com"}], "to": [{"email": "me@me.com"}],
                    "subject": "Plan", "preview": "x", "receivedAt": "2026-11-01T16:00:00Z", "keywords": {"$seen": True},
                    "mailboxIds": {"I": True}, "textBody": [{"partId": "t", "type": "text/plain"}], "htmlBody": [],
                    "bodyValues": {"t": {"value": "plain body"}}}}
    subs = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"apiUrl": f"http://127.0.0.1:{srv.server_port}/api", "primaryAccounts": {MAIL: "u1"},
                        "capabilities": {MAIL: {}, SUBMISSION: {}}})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out, made = [], {}
            for name, a, tag in body["methodCalls"]:
                if name == "Mailbox/get":
                    out.append([name, {"list": [{"id": k, "role": v} for k, v in boxes.items()]}, tag])
                elif name == "Email/query":
                    box = a["filter"]["inMailbox"]
                    ids = sorted((e["id"] for e in store.values() if box in e["mailboxIds"]),
                                 key=lambda i: store[i]["receivedAt"], reverse=True)
                    out.append([name, {"ids": ids}, tag])
                elif name == "Email/get":
                    ids = out[-1][1]["ids"] if "#ids" in a else a["ids"]
                    out.append([name, {"list": [store[i] for i in ids]}, tag])
                elif name == "Email/set":
                    for i, patch in (a.get("update") or {}).items():
                        for k, v in patch.items():
                            if k.startswith("keywords/"):
                                kw = k.split("/", 1)[1]
                                (store[i]["keywords"].pop(kw, None) if v is None else store[i]["keywords"].update({kw: v}))
                            else:
                                store[i][k] = v
                    for cid, m in (a.get("create") or {}).items():
                        nid = f"n{len(store)}"
                        store[nid] = {**m, "id": nid, "receivedAt": "2026-11-01T17:00:00Z"}
                        made["#" + cid] = nid
                    out.append([name, {"updated": {}, "created": {c: {"id": made["#" + c]} for c in a.get("create") or {}}}, tag])
                elif name == "Identity/get":
                    out.append([name, {"list": [{"id": "id1", "email": "me@me.com", "name": "Me"},
                                                {"id": "id2", "email": "*@me.com", "name": "Me"}]}, tag])
                elif name == "EmailSubmission/set":
                    s = a["create"]["s"]
                    eid = made[s["emailId"]]
                    subs.append((s, eid))
                    for k, v in a["onSuccessUpdateEmail"]["#s"].items():
                        if k.startswith("keywords/"):
                            store[eid]["keywords"].pop(k.split("/", 1)[1], None)
                        else:
                            store[eid][k] = v
                    out.append([name, {"created": {"s": {"id": "sub1"}}}, tag])
            self._send({"methodResponses": out})

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        acc = Account("good", f"http://127.0.0.1:{srv.server_port}/session")
        box = acc.inbox()
        assert [m["subject"] for m in box] == ["Plan", "Lunch?"] and box[1]["unread"] and not box[0]["unread"]
        m1 = acc.message("e1")
        assert m1["text"] == "Free fri?\n& sat" and m1["from_text"] == "Amy"  # html-only mail is readable
        assert acc.message("e2")["text"] == "plain body"
        acc.mark_read("e1")
        assert "$seen" in store["e1"]["keywords"]
        acc.mark_read("e1", False)
        assert "$seen" not in store["e1"]["keywords"]
        ident, addr = pick_identity(acc.identities(), m1)
        assert ident["id"] == "id2" and addr == "sales@me.com"  # replies come from the address it was sent to
        acc.send("Amy <amy@x.org>", "Re: Lunch?", "Yes!" + reply_text(m1), ident, addr, reply_to=m1)
        s, nid = subs[-1]
        assert s["envelope"]["rcptTo"] == [{"email": "amy@x.org"}] and s["envelope"]["mailFrom"]["email"] == "sales@me.com"
        assert store[nid]["inReplyTo"] == ["<a1@x.org>"] and store[nid]["mailboxIds"] == {"S": True}
        assert "> Free fri?" in store[nid]["bodyValues"]["b"]["value"] and "$draft" not in store[nid]["keywords"]
        assert "$answered" in store["e1"]["keywords"]
        try:
            acc.send("nobody", "x", "y")
            raise AssertionError("no address must not send")
        except ValueError:
            pass
        acc.archive("e1")
        acc.trash("e2")
        assert store["e1"]["mailboxIds"] == {"A": True} and store["e2"]["mailboxIds"] == {"T": True}
        assert acc.inbox() == []
        assert parse_addresses("Amy <a@x.org>, b@y.com") == [{"name": "Amy", "email": "a@x.org"},
                                                             {"name": "", "email": "b@y.com"}]
        assert html_to_text('<a href="https://x.org/p">here</a>') == "here (https://x.org/p)"
        stamp = datetime(2026, 11, 1, 12, 57).astimezone().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert local_when(stamp) == "Sun, Nov 1, 2026 at 12:57 PM" and local_when("") == ""
    finally:
        srv.shutdown()


def imap_selftest():
    """ImapAccount, imap_fetch and check_login against fake IMAP and SMTP servers on this computer."""
    import base64 as b64
    import socketserver
    import threading
    now = datetime.now(timezone.utc)
    stamp = lambda dt: f'{dt.day:02d}-{MONTHS[dt.month - 1]}-{dt.year} {dt:%H:%M:%S} +0000'
    boxes = {"INBOX": {}, "Trash": {}, "Sent": {}}
    boxes["INBOX"][1] = {"flags": {"\\Seen"}, "date": stamp(now - timedelta(days=5)), "raw": (
        b"From: Old Friend <old@x.org>\r\nTo: me@mine.example\r\nSubject: Old one\r\nMessage-ID: <o1@x.org>\r\n\r\nhi\r\n")}
    boxes["INBOX"][2] = {"flags": set(), "date": stamp(now - timedelta(hours=2)), "raw": (
        b"From: Amy <amy@x.org>\r\nTo: me@mine.example\r\nCc: Bob <bob@y.com>\r\nSubject: Lunch?\r\n"
        b"Message-ID: <a1@x.org>\r\nMIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary=zz\r\n\r\n"
        b"--zz\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Free <b>fri</b>?</p><p>&amp; sat</p>\r\n--zz--\r\n")}
    boxes["INBOX"][3] = {"flags": set(), "date": stamp(now - timedelta(hours=1)), "raw": (
        b"From: Shop <news@shop.com>\r\nSubject: 50% off\r\nList-Unsubscribe: <mailto:u@shop.com>\r\n\r\nsale\r\n")}
    log, smtp_got = [], []

    def lit(b):
        return b"{%d}\r\n" % len(b) + b

    class IMAP(socketserver.StreamRequestHandler):
        def handle(self):
            w = self.wfile.write
            w(b"* OK fake ready\r\n")
            sel, authed = None, False
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                tag, _, rest = line.rstrip(b"\r\n").partition(b" ")
                cmd, _, args = rest.partition(b" ")
                cmd = cmd.upper()
                uid = cmd == b"UID"
                if uid:
                    cmd, _, args = args.partition(b" ")
                    cmd = cmd.upper()
                log.append((cmd.decode(), args.decode("utf-8", "replace")))
                ok = tag + b" OK done\r\n"
                if cmd == b"CAPABILITY":
                    w(b"* CAPABILITY IMAP4rev1" + (b" MOVE UIDPLUS" if authed else b"") + b"\r\n" + ok)
                elif cmd == b"LOGIN":
                    if args.split(b" ")[-1].strip(b'"') == b"app-pass":
                        authed = True
                        w(ok)
                    else:
                        w(tag + b" NO [AUTHENTICATIONFAILED] Invalid credentials\r\n")
                elif cmd == b"LIST":
                    flag = {"Trash": " \\Trash", "Sent": " \\Sent"}
                    w(b"".join(f'* LIST (\\HasNoChildren{flag.get(n, "")}) "/" "{n}"\r\n'.encode() for n in boxes) + ok)
                elif cmd == b"CREATE":
                    boxes[args.decode().strip('"')] = {}
                    w(ok)
                elif cmd in (b"SELECT", b"EXAMINE"):
                    sel = args.decode().strip('"')
                    w(b"* %d EXISTS\r\n" % len(boxes[sel]) + ok)
                elif cmd == b"SEARCH":
                    want = args.upper()
                    hits = [u for u, m in sorted(boxes[sel].items()) if b"UNSEEN" not in want or "\\Seen" not in m["flags"]]
                    w(b"* SEARCH " + b" ".join(str(u).encode() for u in hits) + b"\r\n" + ok)
                elif cmd == b"FETCH":
                    which, _, items = args.partition(b" ")
                    for u in [int(x) for x in which.split(b",")]:
                        m = boxes[sel].get(u)
                        if not m:
                            continue
                        head = m["raw"].split(b"\r\n\r\n")[0] + b"\r\n\r\n"
                        part = (b"BODY[] " + lit(m["raw"])) if b"BODY.PEEK[]" in items else (
                            b"BODY[HEADER.FIELDS (FROM SUBJECT)] " + lit(head))
                        flags = " ".join(sorted(m["flags"])).encode()
                        w(b"* %d FETCH (UID %d FLAGS (%s) INTERNALDATE \"%s\" " % (u, u, flags, m["date"].encode()) + part + b")\r\n")
                    w(ok)
                elif cmd == b"STORE":
                    u, op, flags = args.split(b" ", 2)
                    fs = set(flags.decode().strip("()").split())
                    m = boxes[sel][int(u)]
                    m["flags"] = m["flags"] | fs if op.startswith(b"+") else m["flags"] - fs
                    w(ok)
                elif cmd == b"MOVE":
                    u, to = args.split(b" ", 1)
                    boxes[to.decode().strip('"')][int(u)] = boxes[sel].pop(int(u))
                    w(ok)
                elif cmd == b"APPEND":
                    n = int(re.search(rb"\{(\d+)\}$", args).group(1))
                    w(b"+ go\r\n")
                    self.wfile.flush()
                    data = self.rfile.read(n)
                    self.rfile.readline()
                    box = re.match(rb'"([^"]+)"', args).group(1).decode()
                    boxes[box][len(boxes[box]) + 100] = {"flags": {"\\Seen"}, "date": stamp(now), "raw": data}
                    w(ok)
                elif cmd == b"LOGOUT":
                    w(b"* BYE\r\n" + ok)
                    return
                else:
                    w(tag + b" BAD unknown\r\n")

    class SMTP(socketserver.StreamRequestHandler):
        def handle(self):
            w = self.wfile.write
            w(b"220 fake smtp\r\n")
            env = {"rcpt": []}
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                up = line.upper()
                if up.startswith((b"EHLO", b"HELO")):
                    w(b"250-fake\r\n250 AUTH PLAIN\r\n")
                elif up.startswith(b"AUTH PLAIN"):
                    good = b64.b64decode(line.split()[2]).split(b"\0")[-1] == b"app-pass"
                    w(b"235 ok\r\n" if good else b"535 no\r\n")
                elif up.startswith(b"MAIL FROM"):
                    env["from"] = line.decode().strip()
                    w(b"250 ok\r\n")
                elif up.startswith(b"RCPT TO"):
                    env["rcpt"].append(line.decode().strip())
                    w(b"250 ok\r\n")
                elif up.startswith(b"DATA"):
                    w(b"354 go\r\n")
                    self.wfile.flush()
                    body = b""
                    while not body.endswith(b"\r\n.\r\n"):
                        body += self.rfile.readline()
                    smtp_got.append({**env, "data": body})
                    w(b"250 queued\r\n")
                elif up.startswith(b"QUIT"):
                    w(b"221 bye\r\n")
                    return
                else:
                    w(b"250 ok\r\n")

    servers = [socketserver.ThreadingTCPServer(("127.0.0.1", 0), h) for h in (IMAP, SMTP)]
    for s in servers:
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        cfg = imap_config("me@mine.example", "app-pass", "Me", provider="other",
                          imap=("127.0.0.1", servers[0].server_address[1], "none"),
                          smtp=("127.0.0.1", servers[1].server_address[1], "none"))
        assert check_login(cfg) == "Connected: me@mine.example (3 in the inbox)."
        try:
            check_login({**cfg, "password": "wrong"})
            raise AssertionError("a wrong password was accepted")
        except ValueError as e:
            assert "didn't accept" in str(e)
        digest = imap_fetch(cfg)  # unread and recent only; the newsletter is marked as one
        assert [m["subject"] for m in digest] == ["50% off", "Lunch?"] and digest[0]["list"] and not digest[1]["list"]
        assert digest[1]["from"] == "amy@x.org" and digest[1]["name"] == "Amy"
        assert [m["subject"] for m in needs_you(digest)] == ["Lunch?"]
        a = ImapAccount(cfg)
        box = a.inbox()
        assert [m["subject"] for m in box] == ["50% off", "Lunch?", "Old one"] and [m["unread"] for m in box] == [True, True, False]
        assert box[1]["from"] == "Amy" and box[1]["email"] == "amy@x.org" and box[1]["when"].endswith("Z")
        msg = a.message(box[1]["id"])
        assert msg["text"] == "Free fri?\n& sat" and msg["messageId"] == ["<a1@x.org>"]
        assert msg["cc"] == [{"name": "Bob", "email": "bob@y.com"}] and msg["from_text"] == "Amy"
        a.mark_read("2")
        assert "\\Seen" in boxes["INBOX"][2]["flags"]
        a.mark_read("2", False)
        assert "\\Seen" not in boxes["INBOX"][2]["flags"]
        a.send("Amy <amy@x.org>", "Re: Lunch?", "Yes!", reply_to=msg, cc="bob@y.com")
        sent = smtp_got[-1]
        assert len(sent["rcpt"]) == 2 and b"In-Reply-To: <a1@x.org>" in sent["data"] and b"From: Me <me@mine.example>" in sent["data"]
        assert boxes["INBOX"][2]["flags"] >= {"\\Answered", "\\Seen"}
        assert len(boxes["Sent"]) == 1 and b"Subject: Re: Lunch?" in next(iter(boxes["Sent"].values()))["raw"]
        a.archive("2")  # no Archive folder: one is made, and the mail moves into it
        assert 2 not in boxes["INBOX"] and 2 in boxes["Archive"] and ("CREATE", '"Archive"') in log
        a.trash("3")
        assert 3 in boxes["Trash"] and [m["subject"] for m in a.inbox()] == ["Old one"]
        log.clear()
        ImapAccount({**cfg, "saves_sent": True}).send("x@y.com", "s", "t")  # the service files sent mail itself
        assert not any(c == "APPEND" for c, _ in log) and len(boxes["Sent"]) == 1
    finally:
        for s in servers:
            s.shutdown()
            s.server_close()
    assert parse_list_line(b'(\\HasNoChildren \\Trash) "/" "Deleted Items"') == (["\\HasNoChildren", "\\Trash"], "Deleted Items")
    assert parse_list_line(b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"')[1] == "[Gmail]/All Mail"
    assert parse_list_line(b'(\\Noselect) NIL INBOX') == (["\\Noselect"], "INBOX")
    assert _internaldate(b'1 (INTERNALDATE " 8-Nov-2026 10:05:00 -0600")') == "2026-11-08T16:05:00Z"
    assert provider_for("Me@GMail.com") == "gmail" and provider_for("x@me.com") == "icloud" and provider_for("a@b.org") == "other"
    assert "blocked" in PROVIDERS[provider_for("a@hotmail.com")]
    assert imap_config("a@yahoo.com", " pw ")["imap"] == ["imap.mail.yahoo.com", 993, "ssl"]
    xml = (b'<clientConfig><emailProvider><incomingServer type="imap"><hostname>mail.%EMAILDOMAIN%</hostname>'
           b'<port>143</port><socketType>STARTTLS</socketType></incomingServer><outgoingServer type="smtp">'
           b'<hostname>out.host.example</hostname><port>587</port><socketType>STARTTLS</socketType></outgoingServer>'
           b'</emailProvider></clientConfig>')

    class X:
        def __enter__(s): return s
        def __exit__(s, *a): pass
        def read(s, *a): return xml
    asked = []
    assert guess_servers("me@small.example", lambda url, timeout=0: asked.append(url) or X()) == {
        "imap": ("mail.small.example", 143, "starttls"), "smtp": ("out.host.example", 587, "starttls")}
    assert asked == ["https://autoconfig.thunderbird.net/v1.1/small.example"]  # only the domain leaves the computer

    def offline(url, timeout=0):
        raise OSError("no network")
    assert guess_servers("me@small.example", offline) == {"imap": ("imap.small.example", 993, "ssl"),
                                                         "smtp": ("smtp.small.example", 465, "ssl")}
    import tempfile
    d = tempfile.mkdtemp()
    real_cfg = core.user_config_dir
    core.user_config_dir = lambda: d
    try:
        assert load_config() is None
        save_token("tok")  # a Fastmail token from before there was a choice still works
        assert load_config() == {"kind": "jmap", "token": "tok", "session": SESSION_URL}
        save_config(imap_config("a@gmail.com", "pw", "A"))
        c = load_config()
        assert c["kind"] == "imap" and c["imap"][0] == "imap.gmail.com" and c["saves_sent"] and describe(c) == "a@gmail.com"
        if os.name == "posix":
            assert os.stat(token_path()).st_mode & 0o777 == 0o600
    finally:
        core.user_config_dir = real_cfg
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def selftest():
    account_selftest()
    imap_selftest()
    import shutil
    import tempfile
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    d = tempfile.mkdtemp()
    real_cfg = core.user_config_dir
    core.user_config_dir = lambda: d
    now = datetime.now(timezone.utc)
    mails = [("Riverside College", "billing@riverside.example", "Your payment plan", None, 1),
             ("Shop", "news@shop.com", "50% off", "<mailto:u@shop.com>", 2),
             ("Dad", "dad@example.com", "Bond papers", None, 3),
             ("GitHub", "noreply@github.com", "CI passed", None, 4),
             ("Jordan Lee", "jordan@bank.example", "Your business account", None, 5),
             ("Amy", "amy@example.org", "Re: question", None, 6)]
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.headers["Authorization"] != "Bearer good":
                self.send_response(401)
                self.end_headers()
                return
            self._send({"apiUrl": f"http://127.0.0.1:{srv.server_port}/api", "primaryAccounts": {MAIL: "u1"}})

        def do_POST(self):
            if self.headers["Authorization"] != "Bearer good":
                self.send_response(401)
                self.end_headers()
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            calls = body["methodCalls"]
            if calls[0][0] == "Mailbox/query":
                return self._send({"methodResponses": [["Mailbox/query", {"ids": ["inbox1"]}, "box"]]})
            assert calls[0][1]["filter"]["conditions"][0] == {"inMailbox": "inbox1"}
            lst = [{"from": [{"name": n, "email": e}], "subject": s, "preview": "…",
                    "receivedAt": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "header:List-Unsubscribe:asURLs": u} for n, e, s, u, h in mails]
            self._send({"methodResponses": [["Email/query", {"ids": []}, "q"], ["Email/get", {"list": lst}, "g"]]})

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/session"
        save_token(" good ", url)
        assert load_token() == ("good", url)
        if os.name == "posix":
            assert stat.S_IMODE(os.stat(token_path()).st_mode) == 0o600  # yours alone
        msgs = fetch(*load_token())
        assert len(msgs) == 6 and msgs[1]["list"] and not msgs[0]["list"]
        top = needs_you(msgs, vip=["bank.example"])
        assert [m["name"] for m in top] == ["Jordan Lee", "Riverside College", "Dad"]  # named first, no robots
        assert all("$seen" in json.dumps(b) or b["methodCalls"][0][0] == "Mailbox/query" for b in seen)
        assert not any(c[0].endswith("/set") for b in seen for c in b["methodCalls"])  # it only ever reads
        try:
            fetch("bad", url)
            raise AssertionError("a refused token must say so")
        except OSError:
            pass
        save_digest(lines(top), now=datetime(2026, 11, 2, 9, 5))
        assert last_digest()[1][0] == "Jordan Lee: Your business account"
        assert not due(datetime(2026, 11, 2, 8, 0)) and due(datetime(2026, 11, 2, 9, 1))
        assert not due(datetime(2026, 11, 2, 12, 0), last=datetime(2026, 11, 2, 9, 5))
        assert due(datetime(2026, 11, 2, 16, 30), last=datetime(2026, 11, 2, 9, 5))
        v = os.path.join(d, "v")
        core.ensure_vault(v)
        core.write_note("Home.md", "# Home\nmail:: riverside.example, bank.example\n", v)
        assert important(v) == ["riverside.example", "bank.example"]
        forget_token()
        assert load_token() is None
    finally:
        srv.shutdown()
        core.user_config_dir = real_cfg
        shutil.rmtree(d, ignore_errors=True)
    print("mail selftest OK")


if __name__ == "__main__":
    selftest()
