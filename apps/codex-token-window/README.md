# Codex token widget

Lightweight GTK/Cairo floating widget showing the account limits reported by
the authenticated local Codex app server. It preserves the existing widget
behavior: circular remaining-usage meter, general/model limit switching,
click-through, pin, resize, theme detection, monitor bounds, and 30-second
refreshes.

The widget also provides CodexBar-style Linux features: account identity and
plan, session and weekly windows, extra model windows, credits, local 30-day
token/cost estimates, account profiles, low-quota notifications, manual
refresh, a Codex dashboard shortcut, and a context-menu cost summary. Data is
read from the local Codex app-server and session logs; credentials are never
copied.

The widget asks Codex for `account/rateLimits/read`; it does not read, copy, or
expose the ChatGPT authentication token. If Codex is unavailable, it remains
open and reports an unavailable state.

## Run from this checkout

```bash
./launch-token-widget
```

## Install an application-menu entry

The local installer derives the absolute checkout path at install time, then
places the generated desktop entry and SVG icon under
`${XDG_DATA_HOME:-~/.local/share}`. It is safe to run again; it refuses to
overwrite files that were modified outside this app.

```bash
./install.sh
```

Remove only the desktop entry and icon recorded by this install:

```bash
./uninstall.sh
```

The launcher expects Python 3, GTK 3, PyGObject, and Cairo to be available on
the system. No project-local dependencies are installed.

## Multiple accounts

Create `~/.config/codex-token-window/config.json` to switch between existing
Codex homes without moving credentials:

```json
{
  "profiles": [
    {"name": "Trabalho", "home": "~/.codex-work"},
    {"name": "Pessoal", "home": "~/.codex-personal"}
  ]
}
```

The context menu's `Alternar conta` action sets `CODEX_HOME` only for the
request being made. It does not edit or refresh either account's `auth.json`.

## Linux limitations

Features that depend on macOS WebKit, Keychain, WidgetKit, or an OpenAI web
session are not silently emulated. Use `Abrir painel do Codex` for dashboard-
only information such as code-review history and the web usage chart.
