#!/bin/sh
set -eu

data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
state_file=$data_home/codex-token-window/install-state.json
export STATE_FILE=$state_file

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

state_file = Path(os.environ["STATE_FILE"])
try:
    state = json.loads(state_file.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    print("no valid install state found; nothing removed")
    raise SystemExit(0)

files = state.get("files") if isinstance(state, dict) else None
if not isinstance(files, dict):
    print("no valid install state found; nothing removed")
    raise SystemExit(0)

for name, metadata in files.items():
    target = Path(name)
    expected = metadata.get("sha256") if isinstance(metadata, dict) else None
    if not target.is_file() or not expected:
        continue
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual == expected:
        target.unlink()
        print(f"removed: {target}")
    else:
        print(f"preserved modified file: {target}")

try:
    state_file.unlink()
except FileNotFoundError:
    pass
try:
    state_file.parent.rmdir()
except OSError:
    pass
PY
