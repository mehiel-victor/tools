#!/bin/sh
set -eu

data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
state_file=$data_home/usage-limit/install-state.json
legacy_state_file=$data_home/codex-token-window/install-state.json
export STATE_FILE=$state_file LEGACY_STATE_FILE=$legacy_state_file

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

for state_file in (Path(os.environ["STATE_FILE"]), Path(os.environ["LEGACY_STATE_FILE"])):
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"no valid install state found: {state_file}")
        continue
    files = state.get("files") if isinstance(state, dict) else None
    if not isinstance(files, dict):
        print(f"no valid install state found: {state_file}")
        continue
    safe = True
    for name, metadata in files.items():
        target = Path(name)
        expected = metadata.get("sha256") if isinstance(metadata, dict) else None
        if not target.is_file():
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if expected and actual == expected:
            target.unlink()
            print(f"removed: {target}")
        else:
            safe = False
            print(f"preserved modified file: {target}")
    if safe:
        try:
            state_file.unlink()
            state_file.parent.rmdir()
        except OSError:
            pass
PY
