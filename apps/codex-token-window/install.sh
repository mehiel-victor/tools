#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
desktop_dir=$data_home/applications
icon_dir=$data_home/icons/hicolor/scalable/apps
state_dir=$data_home/codex-token-window
state_file=$state_dir/install-state.json
export APP_DIR=$app_dir DESKTOP_DIR=$desktop_dir ICON_DIR=$icon_dir STATE_FILE=$state_file

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

app = Path(os.environ["APP_DIR"])
desktop = Path(os.environ["DESKTOP_DIR"]) / "io.github.mehiel.CodexTokenWidget.desktop"
icon = Path(os.environ["ICON_DIR"]) / "codex-token-widget.svg"
state_file = Path(os.environ["STATE_FILE"])

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def desktop_exec(path: Path) -> str:
    value = str(path)
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

template = (app / "codex-token-widget.desktop.template").read_text(encoding="utf-8")
desktop_bytes = template.replace("@EXEC@", desktop_exec(app / "launch-token-widget")).encode()
icon_bytes = (app / "codex-token-widget.svg").read_bytes()
desired = {desktop: desktop_bytes, icon: icon_bytes}

try:
    previous = json.loads(state_file.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    previous = {}
previous_files = previous.get("files", {}) if isinstance(previous, dict) else {}

for target, content in desired.items():
    if target.exists():
        current_hash = digest(target.read_bytes())
        prior_hash = previous_files.get(str(target), {}).get("sha256")
        if current_hash != prior_hash and current_hash != digest(content):
            raise SystemExit(f"error: refusing to overwrite user-modified {target}")

for target, content in desired.items():
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_bytes() != content:
        target.write_bytes(content)

state_file.parent.mkdir(parents=True, exist_ok=True)
state = {"files": {str(target): {"sha256": digest(content)} for target, content in desired.items()}}
state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
print(f"installed Codex Token Widget under {app}")
print(f"desktop entry: {desktop}")
print(f"icon: {icon}")
PY
