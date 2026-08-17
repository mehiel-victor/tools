#!/usr/bin/env python3
"""Codex data sources shared by the GTK widget and command-line helpers.

The module deliberately keeps authentication inside Codex. It starts the local
Codex app-server and reads only the responses that Codex exposes for the
authenticated account.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

DEFAULT_TIMEOUT = 10
CONFIG_FILE = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "codex-token-window" / "config.json"


@dataclass(frozen=True)
class UsageWindow:
    name: str
    used_percent: int
    resets_at: Optional[int]
    model: Optional[str] = None

    @property
    def remaining_percent(self) -> int:
        return max(0, min(100, 100 - self.used_percent))


@dataclass(frozen=True)
class CreditBalance:
    balance: Optional[float] = None
    unlimited: bool = False
    available: bool = False


@dataclass(frozen=True)
class CostSummary:
    days: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    estimated_cost: float
    by_model: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CodexSnapshot:
    account_email: Optional[str]
    plan: Optional[str]
    windows: list[UsageWindow]
    credits: CreditBalance
    cost: Optional[CostSummary] = None
    source: str = "codex-cli"
    fetched_at: int = 0


def codex_executable() -> str:
    candidates = [
        Path("/usr/lib/chatgpt/resources/codex"),
        Path.home() / ".local" / "bin" / "codex",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    executable = shutil.which("codex")
    if executable:
        return executable
    raise FileNotFoundError("Codex executable was not found")


def configured_profiles() -> list[dict[str, str]]:
    """Return configured accounts, preserving a safe native default."""
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    profiles = data.get("profiles", []) if isinstance(data, dict) else []
    result = []
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict) or not isinstance(profile.get("name"), str):
                continue
            home = profile.get("home", "")
            result.append({"name": profile["name"], "home": os.path.expanduser(home)})
    return result or [{"name": "Conta atual", "home": ""}]


def save_profiles(profiles: list[dict[str, str]]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"profiles": profiles}, indent=2) + "\n", encoding="utf-8")


def _rpc(executable: str, home: str = "", timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    environment = os.environ.copy()
    if home:
        environment["CODEX_HOME"] = home
    process = subprocess.Popen(
        [executable, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=environment,
    )
    if process.stdin is None or process.stdout is None:
        raise OSError("Não foi possível iniciar o app-server do Codex")
    messages = (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-token-window", "version": "2.0"}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "account/read", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "account/rateLimits/read", "params": None},
    )
    try:
        process.stdin.write("\n".join(json.dumps(item) for item in messages) + "\n")
        process.stdin.flush()
        results: dict[int, dict[str, Any]] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and len(results) < 2:
            line = process.stdout.readline()
            if not line:
                break
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = response.get("id")
            if request_id in (2, 3) and isinstance(response.get("result"), dict):
                results[request_id] = response["result"]
        if 3 not in results:
            raise TimeoutError("Tempo esgotado ao consultar os limites do Codex")
        return {"account": results.get(2, {}), "limits": results[3]}
    finally:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()


def _window(name: str, value: Any, model: Optional[str] = None) -> Optional[UsageWindow]:
    if not isinstance(value, dict) or not isinstance(value.get("usedPercent"), (int, float)):
        return None
    reset = value.get("resetsAt")
    return UsageWindow(name, round(max(0, min(100, float(value["usedPercent"])))), reset if isinstance(reset, int) else None, model)


def parse_snapshot(payload: dict[str, Any]) -> CodexSnapshot:
    account = payload.get("account") or {}
    limits = payload.get("limits") or {}
    windows: list[UsageWindow] = []
    groups = limits.get("rateLimitsByLimitId") or {}
    if not isinstance(groups, dict):
        groups = {}
    if not groups and isinstance(limits.get("rateLimits"), dict):
        groups = {"codex": limits["rateLimits"]}
    for limit_id, group in groups.items():
        if not isinstance(group, dict):
            continue
        title = "Limites gerais" if limit_id == "codex" else str(group.get("limitName") or limit_id)
        primary = _window(f"{title} · sessão", group.get("primary"))
        secondary = _window(f"{title} · semanal", group.get("secondary"))
        if primary:
            windows.append(primary)
        if secondary:
            windows.append(secondary)
    for extra in limits.get("additionalRateLimits", []):
        if not isinstance(extra, dict):
            continue
        name = str(extra.get("name") or extra.get("limitName") or "Limite adicional")
        primary = _window(f"{name} · sessão", extra.get("primary"), name)
        secondary = _window(f"{name} · semanal", extra.get("secondary"), name)
        if primary:
            windows.append(primary)
        if secondary:
            windows.append(secondary)
    credit_data = limits.get("credits") or limits.get("creditBalance") or {}
    balance = credit_data.get("balance") if isinstance(credit_data, dict) else None
    return CodexSnapshot(
        account.get("email") if isinstance(account.get("email"), str) else None,
        account.get("planType") if isinstance(account.get("planType"), str) else None,
        windows,
        CreditBalance(float(balance) if isinstance(balance, (int, float)) else None, bool(credit_data.get("unlimited")) if isinstance(credit_data, dict) else False, isinstance(credit_data, dict)),
        fetched_at=int(time.time()),
    )


def scan_local_cost(home: str = "", days: int = 30) -> CostSummary:
    root = Path(home).expanduser() if home else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    start = datetime.now().astimezone() - timedelta(days=days)
    totals = {"input": 0, "output": 0, "cached": 0}
    models: dict[str, int] = {}
    paths = list((root / "sessions").glob("**/*.jsonl")) + list((root / "archived_sessions").glob("*.jsonl"))
    for path in paths:
        try:
            if datetime.fromtimestamp(path.stat().st_mtime).astimezone() < start:
                continue
            for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                item = json.loads(raw)
                payload = item.get("payload")
                if item.get("type") != "event_msg" or not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                if not isinstance(info, dict):
                    continue
                usage = info.get("last_token_usage") or info.get("total_token_usage") or {}
                totals["input"] += int(usage.get("input_tokens", 0) or 0)
                totals["output"] += int(usage.get("output_tokens", 0) or 0)
                totals["cached"] += int(usage.get("cached_input_tokens", 0) or 0)
                model = str(info.get("model") or "Codex")
                models[model] = models.get(model, 0) + int(sum(usage.get(key, 0) or 0 for key in ("input_tokens", "output_tokens")))
        except (OSError, ValueError, TypeError):
            continue
    estimated = (totals["input"] * 0.000003) + (totals["output"] * 0.000012)
    return CostSummary(days, totals["input"], totals["output"], totals["cached"], estimated, models)


def load_snapshot(home: str = "") -> CodexSnapshot:
    return parse_snapshot(_rpc(codex_executable(), home))


def notify(title: str, message: str) -> None:
    executable = shutil.which("notify-send")
    if executable:
        subprocess.run([executable, title, message], check=False, timeout=3)
