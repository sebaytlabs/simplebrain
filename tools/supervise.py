#!/usr/bin/env python3
"""The supervisor: runs every selftest and the app test, then checks CHECKLIST.md, so nothing asked for quietly goes
missing. Each checklist line's `proof: file :: text` must still be in that file. Exit code 0 only when all is well.

Run: python tools/supervise.py            (everything)
     python tools/supervise.py --quick    (the checklist only, no tests)
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ("core", "calendar", "ics", "recommend", "publish", "sync", "desk", "today", "find", "habits", "update", "watch", "drop",
           "budget", "links", "day", "mail", "dataview")
PROOF = re.compile(r"^- \[([ x])\] (.+?)\s+proof:\s*(\S+)\s*::\s*(.+?)\s*$")


def check_proofs(path=os.path.join(ROOT, "CHECKLIST.md")):
    """[(item, ok, why)] for every checklist line with a proof; lines marked done must have theirs in the code."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = PROOF.match(line.strip())
            if not m:
                continue
            done, item, file, text = m.groups()
            try:
                with open(os.path.join(ROOT, file), encoding="utf-8") as g:
                    found = text in g.read()
            except OSError:
                found = False
            out.append((item, found or done == " ", "" if found else f"{file} has no '{text}'"))
    return out


def run_tests():
    env = dict(os.environ, SIMPLEBRAIN_NO_UPDATE="1", QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    results = []
    for m in MODULES:
        r = subprocess.run([sys.executable, f"simplebrain_{m}.py"], cwd=ROOT, env=env, capture_output=True, text=True,
                           timeout=900)
        results.append((f"simplebrain_{m}.py", r.returncode == 0 and "OK" in r.stdout, (r.stdout + r.stderr)[-400:]))
    r = subprocess.run([sys.executable, os.path.join("tests", "test_app.py")], cwd=ROOT, env=env, capture_output=True,
                       text=True, timeout=1800)
    results.append(("tests/test_app.py", r.returncode == 0 and "app test OK" in r.stdout, (r.stdout + r.stderr)[-800:]))
    return results


def main():
    bad = 0
    if "--quick" not in sys.argv:
        for name, ok, tail in run_tests():
            print(("  ok   " if ok else "  FAIL ") + name)
            if not ok:
                bad += 1
                print("       " + tail.replace("\n", "\n       "))
    items = check_proofs()
    for item, ok, why in items:
        if not ok:
            bad += 1
            print(f"  MISSING  {item}: {why}")
    open_ = sum(1 for line in open(os.path.join(ROOT, "CHECKLIST.md"), encoding="utf-8") if line.startswith("- [ ]"))
    print(f"checklist: {len(items)} proofs checked, {open_} left for you (marked yours)")
    print("supervise OK" if not bad else f"supervise: {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
