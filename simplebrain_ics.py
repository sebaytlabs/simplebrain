"""SimpleBrain calendar-feed parsing: .ics text in, a list of events out.
No UI, no network. Times are shown on this computer's clock.

Self-test: python3 simplebrain_ics.py
"""
import re
from datetime import date, datetime, timedelta, timezone

from dateutil.rrule import rrulestr

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9: events with a named zone are then read as local time
    ZoneInfo = None

# Outlook/Exchange feeds name zones the Windows way; these are the common ones.
WINDOWS_ZONES = {
    "Eastern Standard Time": "America/New_York", "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver", "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix", "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu", "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest", "India Standard Time": "Asia/Kolkata",
    "Tokyo Standard Time": "Asia/Tokyo", "AUS Eastern Standard Time": "Australia/Sydney",
    "UTC": "UTC",
}


def _unfold_ics(text):
    lines = []
    for raw in text.splitlines():
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_dt(value):
    value = value.rstrip("Z")
    y, mo, d = int(value[0:4]), int(value[4:6]), int(value[6:8])
    if len(value) == 8:
        return datetime(y, mo, d)
    hh, mm, ss = int(value[9:11]), int(value[11:13]), int(value[13:15])
    return datetime(y, mo, d, hh, mm, ss)


def _params(key):
    out = {}
    for p in key.split(";")[1:]:
        k, _, v = p.partition("=")
        out[k.upper()] = v.strip('"')
    return out


def _zone(name):
    if ZoneInfo is None or not name:
        return None
    try:
        return ZoneInfo(WINDOWS_ZONES.get(name, name))
    except Exception:  # unknown zone, or no tz database (Windows without tzdata)
        return None


def _parse_dt(key, value):
    """(datetime, all_day). Aware for a UTC ("Z") or named-zone time, naive for a
    date or a floating time (those already mean the viewer's own clock)."""
    p = _params(key)
    value = value.strip()
    dt = _parse_ics_dt(value)
    if len(value) == 8 or p.get("VALUE") == "DATE":
        return dt, True
    if value.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc), False
    zone = _zone(p.get("TZID"))
    return (dt.replace(tzinfo=zone) if zone else dt), False


def _local(dt, tz):
    """A naive datetime on the viewer's clock; `tz` is for tests, None means this computer's."""
    if dt.tzinfo is None:
        return dt
    return (dt.astimezone(tz) if tz else dt.astimezone()).replace(tzinfo=None)


def _until_for(rule, aware):
    """dateutil refuses an UNTIL whose awareness differs from DTSTART's; feeds mix them freely."""
    def fix(m):
        v = m.group(1)
        if aware:
            if len(v) == 8:
                v += "T235959"
            return "UNTIL=" + v.rstrip("Z") + "Z"
        return "UNTIL=" + v.rstrip("Z")
    return re.sub(r"UNTIL=([0-9T]+Z?)", fix, rule, flags=re.I)


def _exclusions(exdates, tz):
    """(datetimes, dates) the feed says to skip, on the viewer's clock."""
    times, days = set(), set()
    for key, value in exdates:
        for part in value.split(","):
            try:
                dt, all_day = _parse_dt(key, part)
            except ValueError:
                continue
            (days if all_day else times).add(dt.date() if all_day else _local(dt, tz))
    return times, days


def parse_ics(text, window_days=120, today=None, tz=None):
    """Events in the next `window_days`, as {"date", "time", "title", "source"}. Times are
    converted to the viewer's clock (`tz`, default this computer's); repeating events keep
    their own wall-clock time across daylight saving; EXDATE (skipped dates), edited single
    occurrences (RECURRENCE-ID) and cancelled events are honoured. RDATE and multi-day
    spans are not."""
    today = today or date.today()
    lo = datetime.combine(today, datetime.min.time())
    hi = lo + timedelta(days=window_days)
    blocks, block = [], None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            block = {"_ex": []}
        elif line == "END:VEVENT":
            if block and "DTSTART" in block and "SUMMARY" in block:
                blocks.append(block)
            block = None
        elif block is not None and ":" in line:
            key, _, val = line.partition(":")
            base_key = key.split(";")[0].upper()
            if base_key == "EXDATE":
                block["_ex"].append((key, val))
            else:
                block[base_key] = (key, val)

    replaced = set()  # (uid, when) of occurrences a RECURRENCE-ID event takes over (or cancels)
    for b in blocks:
        if "RECURRENCE-ID" in b and "UID" in b:
            try:
                dt, all_day = _parse_dt(*b["RECURRENCE-ID"])
            except ValueError:
                continue
            replaced.add((b["UID"][1], dt.date() if all_day else _local(dt, tz)))

    events = []
    for b in blocks:
        try:
            start, all_day = _parse_dt(*b["DTSTART"])  # one odd event must not blank the whole feed
        except ValueError:
            continue
        if b.get("STATUS", ("", ""))[1].strip().upper() == "CANCELLED":
            continue
        uid = b.get("UID", ("", None))[1]
        title = b["SUMMARY"][1]
        if "RRULE" in b:
            skip_times, skip_days = _exclusions(b["_ex"], tz)
            try:
                if re.search(r"FREQ=(SECONDLY|MINUTELY)", b["RRULE"][1], re.I):
                    raise ValueError  # expanding these from the start date takes minutes and gigabytes
                rule = rrulestr(_until_for(b["RRULE"][1], start.tzinfo is not None), dtstart=start)
                if start.tzinfo is not None:  # the window, as instants
                    after = lo.replace(tzinfo=tz) if tz else lo.astimezone()
                    before = hi.replace(tzinfo=tz) if tz else hi.astimezone()
                else:
                    after, before = lo, hi
                occurrences = [_local(o, tz) for o in rule.between(after, before, inc=True)]
            except Exception:
                one = _local(start, tz)
                occurrences = [one] if one >= lo else []
            occurrences = [o for o in occurrences
                           if o not in skip_times and o.date() not in skip_days
                           and (uid, o.date() if all_day else o) not in replaced]
        else:
            one = _local(start, tz)
            occurrences = [one] if lo <= one <= hi else []
        for occ in occurrences:
            events.append({
                "date": occ.date(),
                "time": None if all_day else occ.strftime("%H:%M"),
                "title": title,
                "source": "ics",
            })
    return events


def selftest():
    chi = ZoneInfo("America/Chicago") if ZoneInfo else None
    today = date(2026, 6, 1)

    def run(body, days=60, at=today):
        return parse_ics("BEGIN:VCALENDAR\n" + body + "END:VCALENDAR\n", days, at, chi)

    def ev(*lines):
        return "BEGIN:VEVENT\n" + "\n".join(lines) + "\nEND:VEVENT\n"

    # floating and all-day times are the viewer's own, left alone
    got = run(ev("SUMMARY:Float", "DTSTART:20260610T090000") + ev("SUMMARY:Day", "DTSTART;VALUE=DATE:20260611"))
    assert [(e["date"], e["time"]) for e in got] == [(date(2026, 6, 10), "09:00"), (date(2026, 6, 11), None)]

    # UTC and a named zone show on the viewer's clock (Chicago is UTC-5 in June)
    got = run(ev("SUMMARY:Utc", "DTSTART:20260610T140000Z") + ev("SUMMARY:Ny", "DTSTART;TZID=America/New_York:20260610T100000")
              + ev("SUMMARY:Win", "DTSTART;TZID=Eastern Standard Time:20260610T100000") + ev("SUMMARY:Odd", "DTSTART;TZID=Mars/Base:20260610T100000"))
    assert {e["title"]: e["time"] for e in got} == {"Utc": "09:00", "Ny": "09:00", "Win": "09:00", "Odd": "10:00"}
    # a late UTC time lands on the previous evening's date
    assert run(ev("SUMMARY:Late", "DTSTART:20260611T020000Z"))[0]["date"] == date(2026, 6, 10)

    # a weekly 9am New York meeting stays 9am New York across the November change: 08:00 Chicago before, 08:00 after (both UTC-1)
    weekly = ev("SUMMARY:Weekly", "DTSTART;TZID=America/New_York:20261023T090000", "RRULE:FREQ=WEEKLY;COUNT=3")
    assert [(e["date"].isoformat(), e["time"]) for e in run(weekly, 30, date(2026, 10, 20))] == \
        [("2026-10-23", "08:00"), ("2026-10-30", "08:00"), ("2026-11-06", "08:00")]
    # a UTC repeat does not follow the clocks: 14:00Z is 09:00 Chicago in summer, 08:00 in winter
    utc_weekly = ev("SUMMARY:U", "DTSTART:20261030T140000Z", "RRULE:FREQ=WEEKLY;COUNT=2")
    assert [e["time"] for e in run(utc_weekly, 30, date(2026, 10, 25))] == ["09:00", "08:00"]

    # skipped dates: several EXDATE lines, a comma list, a zoned one and a date-only one
    skipping = ev("SUMMARY:Daily", "DTSTART;TZID=America/Chicago:20260601T080000", "RRULE:FREQ=DAILY;COUNT=6",
                  "EXDATE;TZID=America/Chicago:20260602T080000", "EXDATE;TZID=America/Chicago:20260603T080000,20260604T080000",
                  "EXDATE;VALUE=DATE:20260605")
    assert [e["date"].day for e in run(skipping)] == [1, 6]
    # a floating repeat with a UTC UNTIL, and a zoned one with a date-only UNTIL, both stop where they say
    assert len(run(ev("SUMMARY:A", "DTSTART:20260601T080000", "RRULE:FREQ=DAILY;UNTIL=20260603T235959Z"))) == 3
    assert len(run(ev("SUMMARY:B", "DTSTART;TZID=America/Chicago:20260601T080000", "RRULE:FREQ=DAILY;UNTIL=20260603"))) == 3

    # one edited occurrence replaces the original rather than showing beside it; a cancelled one just disappears
    series = (ev("UID:s1", "SUMMARY:Sync", "DTSTART:20260601T150000Z", "RRULE:FREQ=DAILY;COUNT=3")
              + ev("UID:s1", "SUMMARY:Sync (moved)", "RECURRENCE-ID:20260602T150000Z", "DTSTART:20260602T180000Z")
              + ev("UID:s1", "SUMMARY:Sync", "RECURRENCE-ID:20260603T150000Z", "DTSTART:20260603T150000Z", "STATUS:CANCELLED"))
    assert [(e["date"].day, e["time"], e["title"]) for e in run(series)] == [(1, "10:00", "Sync"), (2, "13:00", "Sync (moved)")]

    # odd events are skipped, not fatal; a per-second repeat is cut short
    assert run(ev("SUMMARY:odd", "DTSTART:20261225T1900") + ev("SUMMARY:fine", "DTSTART:20260626"), 60)[0]["title"] == "fine"
    assert len(run(ev("SUMMARY:busy", "DTSTART:20200101T000000Z", "RRULE:FREQ=SECONDLY"))) <= 1
    assert parse_ics("BEGIN:VEVENT\nSUMMARY:x\nDTSTART:20260610T090000\nEND:VEVENT\n", today=today)[0]["time"] == "09:00"  # no tz given: this computer's, floating untouched
    print("ics selftest OK")


if __name__ == "__main__":
    selftest()
