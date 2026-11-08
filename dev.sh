#!/usr/bin/env bash
# Dev runner: restarts the app whenever a .py file changes. Close the window to stop.
cd "$(dirname "$0")"
export SIMPLEBRAIN_DEV=1  # updates pull new code here; this loop restarts on it, so the app doesn't
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
stamp() { stat -c %Y *.py; }
while true; do
  .venv/bin/python simplebrain_app.py & pid=$!
  seen=$(stamp)
  while kill -0 $pid 2>/dev/null && [ "$(stamp)" = "$seen" ]; do sleep 0.5; done
  if kill -0 $pid 2>/dev/null; then kill $pid; wait $pid 2>/dev/null; echo "[dev] change detected, restarting"
  else wait $pid; exit; fi  # window closed by the user
done
