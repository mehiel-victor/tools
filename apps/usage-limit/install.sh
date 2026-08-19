#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
desktop_dir=$data_home/applications
icon_dir=$data_home/icons/hicolor/512x512/apps
state_dir=$data_home/usage-limit
state_file=$state_dir/install-state.json
export APP_DIR=$app_dir DESKTOP_DIR=$desktop_dir ICON_DIR=$icon_dir STATE_FILE=$state_file

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

app = Path(os.environ["APP_DIR"])
desktop = Path(os.environ["DESKTOP_DIR"]) / "io.github.mehiel.UsageLimit.desktop"
icon = Path(os.environ["ICON_DIR"]) / "usage-limit.png"
state_file = Path(os.environ["STATE_FILE"])
legacy_state_file = state_file.parent.parent / "codex-token-window" / "install-state.json"

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def desktop_exec(path: Path) -> str:
    value = str(path)
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'

def manifest_files(path: Path, current: bool):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        if current:
            raise SystemExit(f"error: refusing install with malformed manifest {path}: {exc}")
        print(f"warning: preserving legacy artifacts; malformed manifest {path}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        if current:
            raise SystemExit(f"error: refusing install with invalid manifest structure {path}")
        print(f"warning: preserving legacy artifacts; invalid manifest structure {path}")
        return None
    files = data["files"]
    for name, metadata in files.items():
        if not isinstance(name, str) or not isinstance(metadata, dict):
            message = f"invalid file metadata in manifest {path}"
            if current:
                raise SystemExit(f"error: {message}")
            print(f"warning: preserving legacy artifacts; {message}")
            return None
        checksum = metadata.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            message = f"invalid sha256 metadata in manifest {path}"
            if current:
                raise SystemExit(f"error: {message}")
            print(f"warning: preserving legacy artifacts; {message}")
            return None
    return files

template = (app / "usage-limit.desktop.template").read_text(encoding="utf-8")
desktop_bytes = template.replace("@EXEC@", desktop_exec(app / "launch-usage-limit")).replace("@ICON@", str(icon)).encode()
icon_bytes = (app / "usage-limit.png").read_bytes()
desired = {desktop: desktop_bytes, icon: icon_bytes}

previous_files = manifest_files(state_file, current=True)

legacy_files = manifest_files(legacy_state_file, current=False)
if legacy_files is None:
    legacy_files = {}

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

legacy_safe = True
for name, metadata in legacy_files.items():
    target = Path(name)
    expected = metadata.get("sha256") if isinstance(metadata, dict) else None
    if target.is_file() and expected and digest(target.read_bytes()) == expected:
        target.unlink()
        print(f"removed legacy artifact: {target}")
    elif target.exists():
        legacy_safe = False
        print(f"preserved modified legacy artifact: {target}")
if legacy_safe and legacy_files:
    try:
        legacy_state_file.unlink()
        legacy_state_file.parent.rmdir()
    except OSError:
        pass
print(f"installed Usage Limit under {app}")
print(f"desktop entry: {desktop}")
print(f"icon: {icon}")
PY
