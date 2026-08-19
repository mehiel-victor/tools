# Usage Limit

Lightweight GTK/Cairo floating widget showing usage limits from Codex and
Antigravity. Codex is read through its local `account/rateLimits/read`
app-server method. Antigravity is read through the documented structured
`agy -p /usage --output-format json` command; no credentials or provider
configuration files are accessed.

The widget refreshes every five minutes, supports manual refresh, click-to-cycle
windows, pinning, click-through, resize, theme detection, position persistence,
minimize/close, low-limit notifications, and a compact `C | A` toggle for
switching the displayed provider. Provider failures are tolerated
when another provider returns limits.

## Requirements and launch

The launcher expects Python 3, GTK 3, PyGObject, and Cairo. Install and sign in
to at least one provider: Codex, or Antigravity CLI 1.1.8 or newer (the first
release with structured print output). Then run:

```bash
./launch-usage-limit
```

The guarded `install.sh` and `uninstall.sh` manage the
`io.github.mehiel.UsageLimit` desktop entry and `usage-limit` icon. The installer
migrates a previous managed Codex Token Widget entry only when its recorded
hashes still match; modified files are preserved.

## Multiple Codex accounts

Optional Codex profiles belong in
`${XDG_CONFIG_HOME:-~/.config}/usage-limit/config.json`:

```json
{
  "profiles": [
    {"name": "Trabalho", "home": "~/.codex-work"},
    {"name": "Pessoal", "home": "~/.codex-personal"}
  ]
}
```

The former `codex-token-window/config.json` remains a read-only fallback.
