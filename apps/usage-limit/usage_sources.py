#!/usr/bin/env python3
"""Provider-neutral usage-limit sources."""
from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DEFAULT_TIMEOUT = 10
CONFIG_ROOT = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
)
CONFIG_FILE = CONFIG_ROOT / "usage-limit" / "config.json"
LEGACY_CONFIG_FILE = CONFIG_ROOT / "codex-token-window" / "config.json"


@dataclass(frozen=True)
class UsageLimit:
    provider: str
    name: str
    window: str
    used_percent: int
    resets_at: Optional[int] = None

    @property
    def remaining_percent(self) -> int:
        return max(0, min(100, 100 - self.used_percent))


def _percent(value: Any) -> Optional[int]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(max(0.0, min(100.0, float(value))))


def _iso_timestamp(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _codex_window(
    limits: list[UsageLimit],
    provider: str,
    name: str,
    window_name: str,
    value: Any,
) -> None:
    if not isinstance(value, dict):
        return
    used = _percent(value.get("usedPercent"))
    if used is None:
        return
    reset = value.get("resetsAt")
    limits.append(UsageLimit(provider, name, window_name, used, reset if isinstance(reset, int) else None))


def parse_codex_limits(payload: dict[str, Any]) -> list[UsageLimit]:
    groups = payload.get("rateLimitsByLimitId") or {}
    if not isinstance(groups, dict):
        groups = {}
    if not groups and isinstance(payload.get("rateLimits"), dict):
        groups = {"codex": payload["rateLimits"]}
    limits: list[UsageLimit] = []
    for limit_id, group in groups.items():
        if not isinstance(group, dict):
            continue
        title = "Codex" if limit_id == "codex" else str(group.get("limitName") or limit_id)
        _codex_window(limits, "Codex", title, "session", group.get("primary"))
        _codex_window(limits, "Codex", title, "weekly", group.get("secondary"))
    for extra in payload.get("additionalRateLimits", []):
        if not isinstance(extra, dict):
            continue
        name = str(extra.get("name") or extra.get("limitName") or "Additional")
        _codex_window(limits, "Codex", name, "session", extra.get("primary"))
        _codex_window(limits, "Codex", name, "weekly", extra.get("secondary"))
    if not limits:
        raise ValueError("Codex returned no usage-limit windows")
    return limits


def codex_executable() -> str:
    candidates = (
        Path("/usr/lib/chatgpt/resources/codex"),
        Path.home() / ".local" / "bin" / "codex",
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    executable = shutil.which("codex")
    if executable:
        return executable
    raise FileNotFoundError("Codex executable was not found")


def read_codex_limits(home: str = "") -> list[UsageLimit]:
    environment = os.environ.copy()
    if home:
        environment["CODEX_HOME"] = home
    process = subprocess.Popen(
        [codex_executable(), "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
    )
    if process.stdin is None or process.stdout is None:
        raise OSError("Could not start the Codex app server")
    messages = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "usage-limit", "version": "1.0"}},
        },
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "account/rateLimits/read",
            "params": None,
        },
    )
    try:
        process.stdin.write(("\n".join(json.dumps(message) for message in messages) + "\n").encode())
        process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            buffered = b""
            deadline = time.monotonic() + DEFAULT_TIMEOUT
            while time.monotonic() < deadline:
                events = selector.select(max(0, deadline - time.monotonic()))
                if not events:
                    break
                chunk = process.stdout.read1(65_536)
                if not chunk:
                    break
                buffered += chunk
                while b"\n" in buffered:
                    line, buffered = buffered.split(b"\n", 1)
                    try:
                        response = json.loads(line.decode())
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if response.get("id") == 2:
                        result = response.get("result")
                        if not isinstance(result, dict):
                            raise ValueError(
                                "Codex did not return usage-limit data"
                            )
                        return parse_codex_limits(result)
        raise TimeoutError("Timed out while loading Codex usage limits")
    finally:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def antigravity_executable() -> str:
    preferred = Path.home() / ".local" / "bin" / "agy"
    if preferred.is_file() and os.access(preferred, os.X_OK):
        return str(preferred)
    executable = shutil.which("agy")
    if executable is None:
        raise FileNotFoundError("Antigravity executable was not found")
    return executable


def parse_antigravity_limits(payload: dict[str, Any]) -> list[UsageLimit]:
    status = payload.get("status")
    if not isinstance(status, str) or status.casefold() != "success":
        raise ValueError("Antigravity usage command was not successful")
    command = payload.get("command")
    if not isinstance(command, dict) or command.get("name") != "usage":
        raise ValueError("Antigravity returned an unexpected command")
    data = command.get("data")
    if not isinstance(data, dict):
        raise ValueError("Antigravity returned no usage data")
    limits: list[UsageLimit] = []
    for group in data.get("groups", []):
        if not isinstance(group, dict):
            continue
        group_name = str(
            group.get("name") or group.get("display_name") or "Antigravity"
        )
        for bucket in group.get("buckets", []):
            if not isinstance(bucket, dict):
                continue
            remaining = bucket.get("remaining_fraction")
            if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
                continue
            used = round(max(0.0, min(100.0, (1.0 - float(remaining)) * 100.0)))
            limits.append(
                UsageLimit(
                    "Antigravity",
                    group_name,
                    str(bucket.get("window") or "usage"),
                    used,
                    _iso_timestamp(bucket.get("reset_time")),
                )
            )
    if not limits:
        raise ValueError("Antigravity returned no usage-limit windows")
    return limits


def read_antigravity_limits() -> list[UsageLimit]:
    command = [
        antigravity_executable(),
        "-p",
        "/usage",
        "--output-format",
        "json",
        "--print-timeout",
        "30s",
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=35,
    )
    if result.returncode != 0:
        raise RuntimeError("Antigravity usage command failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Antigravity returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Antigravity returned invalid usage data")
    return parse_antigravity_limits(payload)


def configured_profiles() -> list[dict[str, str]]:
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        profiles = data.get("profiles", []) if isinstance(data, dict) else []
        if not isinstance(profiles, list):
            continue
        result = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            name = profile.get("name")
            home = profile.get("home", "")
            if isinstance(name, str) and isinstance(home, str):
                result.append({"name": name, "home": os.path.expanduser(home)})
        if result:
            return result
    return [{"name": "Current account", "home": ""}]


def notify(title: str, message: str) -> None:
    executable = shutil.which("notify-send")
    if executable is None:
        return
    try:
        subprocess.run(
            [executable, "-a", "Usage Limit", "-i", "usage-limit", title, message],
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        pass
