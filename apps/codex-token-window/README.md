# Codex token widget

Lightweight GTK/Cairo floating widget showing the account limits reported by
the authenticated local Codex app server. It preserves the existing widget
behavior: circular remaining-usage meter, general/model limit switching,
click-through, pin, resize, theme detection, monitor bounds, and 30-second
refreshes.

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
