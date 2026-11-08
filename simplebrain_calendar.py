#!/usr/bin/env python3
"""The whole calendar inside SimpleBrain, over CalDAV: every event in a date range with its place and notes, and
add / edit / delete for any of them, including events made in Fastmail or on a phone. No Qt here (the window is
simplebrain_calwin).

The calendar is the one connected in SimpleBrain (the vault's .config link, with its app password). Events typed into
Calendar.md stay as they are (simplebrain_core pushes them as sb-… copies); this module leaves those copies out so
nothing shows twice.

Repeating events: the title, place and notes change for the whole series; one date can be skipped, or the series
deleted. Changing the dates of a series stays a job for later (it rarely comes up and is easy to get wrong).

Run: python simplebrain_calendar.py   (selftest, against a fake CalDAV server on this computer)
"""
import re
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree

import simplebrain_core as core
import simplebrain_ics as ics

CALDAV = "{urn:ietf:params:xml:ns:caldav}"


def esc(s):
    """An iCalendar TEXT value: backslash, comma, semicolon and newlines escaped."""
    return re.sub(r"([\\;,])", r"\\\1", s or "").replace("\r\n", "\n").replace("\n", "\\n")


def unesc(s):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s or "")


def fold(line):
    """Lines over 75 bytes continue on the next line after one space (RFC 5545 3.1)."""
    out, b = [], line.encode()
    while len(b) > 75:
        cut = 75
        while cut and (b[cut] & 0xC0) == 0x80:  # never split a multi-byte character
            cut -= 1
        out.append(b[:cut].decode())
        b = b" " + b[cut:]
    out.append(b.decode())
    return "\r\n".join(out)


def utc(d, t):
    """A local date + HH:MM as a UTC stamp, so every calendar app shows it at the right time."""
    return datetime.combine(d, datetime.strptime(t, "%H:%M").time()).astimezone().astimezone(timezone.utc) \
        .strftime("%Y%m%dT%H%M%SZ")


def when_lines(ev):
    """DTSTART/DTEND for an event dict: all-day (end date exclusive) or timed (end defaults to an hour on)."""
    d = ev["date"]
    if not ev.get("time"):
        end = ev.get("end_date") or d
        return [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{end + timedelta(days=1):%Y%m%d}"]
    end_t = ev.get("end_time") or (datetime.strptime(ev["time"], "%H:%M") + timedelta(hours=1)).strftime("%H:%M")
    end_d = ev.get("end_date") or (d if end_t > ev["time"] else d + timedelta(days=1))
    return [f"DTSTART:{utc(d, ev['time'])}", f"DTEND:{utc(end_d, end_t)}"]


def event_ics(uid, ev):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SimpleBrain//EN", "BEGIN:VEVENT", f"UID:{uid}",
             f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", *when_lines(ev), f"SUMMARY:{esc(ev['title'])}"]
    if ev.get("location"):
        lines.append(f"LOCATION:{esc(ev['location'])}")
    if ev.get("notes"):
        lines.append(f"DESCRIPTION:{esc(ev['notes'])}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def _master_props(text):
    """{PROP: (key, value)} of the main VEVENT (the one without RECURRENCE-ID)."""
    props, cur = {}, None
    for line in ics._unfold_ics(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None and "RECURRENCE-ID" not in cur and not props:
                props = cur
            cur = None
        elif cur is not None and ":" in line:
            k, _, v = line.partition(":")
            cur[k.split(";")[0].upper()] = (k, v)
    return props


def edit_ics(text, ev):
    """The resource with the main VEVENT's title/place/notes (and, unless it repeats, its dates) replaced.
    Every other line (alarms, attendees, the series' own exceptions) is kept as it was."""
    out, in_ev, is_master, block = [], False, False, []
    repeats = "RRULE" in _master_props(text)

    def flush(block):
        keep, skip = [], {"SUMMARY", "LOCATION", "DESCRIPTION", "DTSTAMP", "SEQUENCE"}
        if not repeats:
            skip |= {"DTSTART", "DTEND", "DURATION"}
        seq = 0
        for l in block:
            name = l.split(":", 1)[0].split(";", 1)[0].upper()
            if name == "SEQUENCE":
                seq = int(re.sub(r"\D", "", l.split(":", 1)[1]) or 0)
            if name not in skip:
                keep.append(l)
        new = [f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", f"SEQUENCE:{seq + 1}",
               f"SUMMARY:{esc(ev['title'])}"]
        if not repeats:
            new += when_lines(ev)
        if ev.get("location"):
            new.append(f"LOCATION:{esc(ev['location'])}")
        if ev.get("notes"):
            new.append(f"DESCRIPTION:{esc(ev['notes'])}")
        at = next((i for i, l in enumerate(keep) if l.startswith("BEGIN:") and l != "BEGIN:VEVENT"), len(keep))
        return keep[:at] + new + keep[at:]  # before any VALARM inside the event

    for line in ics._unfold_ics(text):
        if line == "BEGIN:VEVENT":
            in_ev, block = True, []
            is_master = True
            continue
        if in_ev and line == "END:VEVENT":
            in_ev = False
            out += ["BEGIN:VEVENT"] + (flush(block) if is_master else block) + ["END:VEVENT"]
            continue
        if in_ev:
            if line.upper().startswith("RECURRENCE-ID"):
                is_master = False
            block.append(line)
        else:
            out.append(line)
    return "\r\n".join(fold(l) for l in out if l) + "\r\n"


def skip_ics(text, occ_date, occ_time):
    """Add one EXDATE to the series, in the form its DTSTART uses (date, UTC or its TZID)."""
    p = _master_props(text)
    key, val = p["DTSTART"]
    if "VALUE=DATE" in key.upper() or len(val.strip()) == 8:
        ex = f"EXDATE;VALUE=DATE:{occ_date:%Y%m%d}"
    else:
        start_t = datetime.combine(occ_date, datetime.strptime(occ_time, "%H:%M").time())
        tzid = ics._params(key).get("TZID")
        if val.strip().endswith("Z"):
            ex = f"EXDATE:{start_t.astimezone().astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"
        elif tzid and (z := ics._zone(tzid)):
            ex = f"EXDATE;TZID={tzid}:{start_t.astimezone().astimezone(z):%Y%m%dT%H%M%S}"
        else:
            ex = f"EXDATE:{start_t:%Y%m%dT%H%M%S}"
    out, done = [], False
    for line in ics._unfold_ics(text):
        out.append(line)
        if not done and line.upper().startswith("DTSTART") and "RRULE" in p:
            out.append(ex)
            done = True
    return "\r\n".join(fold(l) for l in out if l) + "\r\n"


class CalDAV:
    """One calendar collection. `url` is the link SimpleBrain stores (https://user:app-password@host/dav/…/)."""

    def __init__(self, url, timeout=15):
        self.base, self.auth = core._caldav_split(url)
        self.base = self.base.rstrip("/") + "/"
        self.root = re.match(r"https?://[^/]+", self.base).group(0)
        self.timeout = timeout

    def call(self, method, target, body=None, headers=None):
        req = urllib.request.Request(target, data=body.encode() if body else None, method=method, headers=headers or {})
        if self.auth:
            req.add_unredirected_header("Authorization", self.auth)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8", errors="replace"), r.headers.get("ETag")

    def resources(self, start, end):
        """[{"href", "etag", "ics"}] with an event between start and end (dates), SimpleBrain's own sb- copies left out."""
        stamp = lambda d: datetime.combine(d, datetime.min.time()).strftime("%Y%m%dT%H%M%SZ")
        xml, _ = self.call("REPORT", self.base, (
            '<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR">'
            f'<c:comp-filter name="VEVENT"><c:time-range start="{stamp(start - timedelta(days=1))}" '
            f'end="{stamp(end + timedelta(days=1))}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'),
            {"Depth": "1", "Content-Type": "application/xml"})
        out = []
        for r in ElementTree.fromstring(xml).iter("{DAV:}response"):
            href = r.findtext("{DAV:}href") or ""
            data = r.find(f".//{CALDAV}calendar-data")
            if data is None or not data.text or href.rsplit("/", 1)[-1].startswith("sb-"):
                continue
            out.append({"href": href, "etag": r.findtext(".//{DAV:}getetag"), "ics": data.text})
        return out

    def events(self, start, end):
        """Every occurrence from start to end: {"date", "time", "end_time", "title", "location", "notes",
        "repeats", "href", "etag", "source": "caldav"}, sorted."""
        out = []
        for res in self.resources(start, end):
            p = _master_props(res["ics"])
            dur = None
            try:
                s, _ = ics._parse_dt(*p["DTSTART"])
                if "DTEND" in p:
                    e, _ = ics._parse_dt(*p["DTEND"])
                    dur = e - s
                elif "DURATION" in p:
                    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", p["DURATION"][1])
                    dur = timedelta(days=int(m.group(1) or 0), hours=int(m.group(2) or 0), minutes=int(m.group(3) or 0))
            except (KeyError, ValueError):
                pass
            extra = {"location": unesc(p.get("LOCATION", ("", ""))[1]), "notes": unesc(p.get("DESCRIPTION", ("", ""))[1]),
                     "repeats": "RRULE" in p, "href": res["href"], "etag": res["etag"], "source": "caldav"}
            for o in ics.parse_ics(res["ics"], window_days=(end - start).days + 1, today=start):
                o = {**o, **extra, "title": unesc(o["title"])}
                if o["time"] and dur:
                    o["end_time"] = (datetime.strptime(o["time"], "%H:%M") + dur).strftime("%H:%M")
                elif not o["time"] and dur and dur.days > 1:
                    o["end_date"] = o["date"] + dur - timedelta(days=1)
                out.append(o)
        out.sort(key=lambda e: (e["date"], e["time"] or ""))
        return out

    def _url(self, href):
        return href if href.startswith("http") else self.root + href

    def create(self, ev):
        uid = f"{uuid.uuid4()}"
        self.call("PUT", f"{self.base}{uid}.ics", event_ics(uid, ev),
                  {"Content-Type": "text/calendar; charset=utf-8", "If-None-Match": "*"})
        return uid

    def _rewrite(self, ev_ref, change):
        """GET the resource fresh, change it, PUT it back only if nobody changed it in between (If-Match)."""
        text, etag = self.call("GET", self._url(ev_ref["href"]))
        h = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag or ev_ref.get("etag"):
            h["If-Match"] = etag or ev_ref["etag"]
        self.call("PUT", self._url(ev_ref["href"]), change(text), h)

    def update(self, ev_ref, ev):
        self._rewrite(ev_ref, lambda text: edit_ics(text, ev))

    def skip(self, ev_ref):
        """Leave out just this date of a repeating event."""
        self._rewrite(ev_ref, lambda text: skip_ics(text, ev_ref["date"], ev_ref.get("time") or "00:00"))

    def delete(self, ev_ref):
        try:
            self.call("DELETE", self._url(ev_ref["href"]))
        except urllib.error.HTTPError as e:
            if e.code != 404:  # already gone is what we wanted
                raise


def connected(vault=None):
    """A CalDAV for the calendar SimpleBrain is linked to, or None when it's a read-only feed or nothing."""
    url = core.get_ics_url(vault)
    if url and core._caldav_split(url)[1]:
        return CalDAV(url)
    return None


def selftest():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    store = {}  # path -> (text, etag)
    n = [0]
    store["/dav/cal/a.ics"] = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nDTSTART:20991105T150000Z\r\n"
                               "DTEND:20991105T163000Z\r\nSUMMARY:Dentist\\, Dr. Lee\r\nLOCATION:Main St\r\n"
                               "BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nACTION:DISPLAY\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", '"1"')
    store["/dav/cal/r.ics"] = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:r\r\nDTSTART;VALUE=DATE:20991102\r\n"
                               "RRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Trash day\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", '"1"')
    store["/dav/cal/sb-x.ics"] = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:sb-x\r\nDTSTART;VALUE=DATE:20991103\r\n"
                                  "SUMMARY:typed in Calendar.md\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", '"1"')

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _reply(self, code, body="", etag=None):
            data = body.encode()
            self.send_response(code)
            if etag:
                self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_REPORT(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            rs = "".join(f"<d:response><d:href>{p}</d:href><d:propstat><d:prop><d:getetag>{e}</d:getetag>"
                         f"<c:calendar-data>{t.replace('&', '&amp;').replace('<', '&lt;')}</c:calendar-data></d:prop>"
                         "</d:propstat></d:response>" for p, (t, e) in store.items())
            self._reply(207, f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">{rs}</d:multistatus>')

        def do_GET(self):
            t, e = store[self.path]
            self._reply(200, t, e)

        def do_PUT(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            if self.headers.get("If-None-Match") == "*" and self.path in store:
                return self._reply(412)
            if self.headers.get("If-Match") and store.get(self.path, (0, None))[1] != self.headers["If-Match"]:
                return self._reply(412)
            n[0] += 1
            store[self.path] = (body, f'"{n[0] + 1}"')
            self._reply(201)

        def do_DELETE(self):
            store.pop(self.path, None)
            self._reply(204)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        cal = CalDAV(f"http://u:p@127.0.0.1:{srv.server_port}/dav/cal/")
        start = date(2099, 11, 1)
        evs = cal.events(start, start + timedelta(days=30))
        titles = [e["title"] for e in evs]
        assert "typed in Calendar.md" not in titles  # SimpleBrain's own copies aren't shown twice
        assert titles.count("Trash day") == 3 and "Dentist, Dr. Lee" in titles
        dent = next(e for e in evs if e["title"].startswith("Dentist"))
        assert dent["location"] == "Main St" and not dent["repeats"]
        assert dent["end_time"] == (datetime.strptime(dent["time"], "%H:%M") + timedelta(minutes=90)).strftime("%H:%M")
        # edit one: title, place, notes and time change; its alarm stays
        cal.update(dent, {**dent, "title": "Dentist; moved", "time": "09:00", "end_time": "10:00",
                          "notes": "bring card\nand ID", "location": ""})
        t = store["/dav/cal/a.ics"][0]
        assert "SUMMARY:Dentist\\; moved" in t and "TRIGGER:-PT15M" in t and "LOCATION" not in t
        assert "DESCRIPTION:bring card\\nand ID" in t and "SEQUENCE:1" in t and t.count("DTSTART") == 1
        d2 = next(e for e in cal.events(start, start + timedelta(days=30)) if e["title"] == "Dentist; moved")
        assert d2["time"] == "09:00" and d2["end_time"] == "10:00" and d2["notes"] == "bring card\nand ID"
        # someone changed it in Fastmail between our read and our write: theirs is not overwritten
        store["/dav/cal/a.ics"] = (store["/dav/cal/a.ics"][0], '"theirs"')
        try:
            cal.call("PUT", cal._url(d2["href"]), "x", {"If-Match": d2["etag"]})
            raise AssertionError("a stale write must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 412
        # a repeating one: rename the series, skip one date
        trash = [e for e in cal.events(start, start + timedelta(days=30)) if e["title"] == "Trash day"]
        assert all(e["repeats"] for e in trash)
        cal.update(trash[0], {**trash[0], "title": "Trash + recycling"})
        mid = [e for e in cal.events(start, start + timedelta(days=30)) if e["title"] == "Trash + recycling"][1]
        cal.skip(mid)
        left = [e["date"] for e in cal.events(start, start + timedelta(days=30)) if e["title"] == "Trash + recycling"]
        assert left == [date(2099, 11, 2), date(2099, 11, 16)]
        # add, then delete
        cal.create({"date": date(2099, 11, 20), "time": None, "title": "Day off, all day", "notes": "x"})
        new = next(e for e in cal.events(start, start + timedelta(days=30)) if e["title"] == "Day off, all day")
        assert new["time"] is None and new["notes"] == "x"
        cal.create({"date": date(2099, 11, 21), "time": "23:30", "title": "Late call"})
        late = next(e for e in cal.events(start, start + timedelta(days=30)) if e["title"] == "Late call")
        assert late["end_time"] == "00:30"
        cal.delete(new)
        cal.delete(new)  # twice is fine
        assert "Day off, all day" not in [e["title"] for e in cal.events(start, start + timedelta(days=30))]
        assert fold("X" * 200).count("\r\n ") == 2 and esc("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
        assert unesc(esc("a,b;c\\d\ne")) == "a,b;c\\d\ne"
    finally:
        srv.shutdown()
    print("calendar selftest OK")


if __name__ == "__main__":
    selftest()
