#!/usr/bin/env python3
"""Always-on-top display of the Codex account usage limits."""

from __future__ import annotations

import fcntl
import json
import math
import shutil
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from codex_features import CodexSnapshot, configured_profiles, load_snapshot, notify, scan_local_cost

try:
    import cairo
except ImportError:
    cairo = None  # type: ignore[assignment]

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo
except (ImportError, ValueError):
    Gdk = Gio = GLib = Gtk = Pango = PangoCairo = None  # type: ignore[assignment]

POSITION_FILE = Path.home() / ".codex" / "token_widget_position.json"
LOCK_FILE = Path.home() / ".codex" / "token_widget.lock"
REFRESH_MS = 30_000
APP_SERVER_TIMEOUT_SECONDS = 10
DEFAULT_CODEX_EXECUTABLE = Path("/usr/lib/chatgpt/resources/codex")
MONTHS_PT_BR = ("jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez.")
WIDGET_SIZE = 240
WIDGET_HEIGHT = 268
CONTENT_OFFSET_Y = WIDGET_HEIGHT - WIDGET_SIZE
MIN_WIDGET_SIZE = 180
MAX_WIDGET_SIZE = 360
PASSTHROUGH_CONTROL = (86, 15)
PIN_CONTROL = (120, 15)
RESIZE_CONTROL = (154, 15)
CONTROL_RADIUS = 13


@dataclass(frozen=True)
class UsageLimit:
    name: str
    used_percent: int
    resets_at: Optional[int]

    @property
    def remaining_percent(self) -> int:
        return max(0, min(100, 100 - self.used_percent))


@dataclass(frozen=True)
class ThemeColors:
    background: str
    spark_background: str
    track: str
    primary: str
    secondary: str
    tertiary: str
    label: str
    spark_label: str
    dot_active: str
    dot_inactive: str
    control: str
    control_hover: str
    control_active: str
    control_active_hover: str
    icon: str


def theme_colors(dark_mode: bool) -> ThemeColors:
    """Return a complete, contrast-safe palette for the system appearance."""
    if dark_mode:
        return ThemeColors(
            "#121212", "#1C191E", "#2C2C2C", "#F7F9FC", "#B8C0CD", "#8E98A7", "#8FB6D0", "#B9B2C0",
            "#D8DEE8", "#4B5361", "#242424", "#333333", "#2B3C30", "#354A3B", "#AAB3C1",
        )
    return ThemeColors(
        "#F7F7F5", "#F0EFF2", "#D9DDD9", "#202124", "#4F5551", "#676D69", "#456C84", "#635E68",
        "#343936", "#AEB5B0", "#ECEEEC", "#DEE2DF", "#DDEEE1", "#D0E7D5", "#555D58",
    )


def system_prefers_dark(color_scheme: str, gtk_theme: str = "", gtk_prefers_dark: bool = False) -> bool:
    """Resolve GNOME's explicit color scheme, then fall back to GTK theme hints."""
    if color_scheme == "prefer-light":
        return False
    if color_scheme == "prefer-dark":
        return True
    return gtk_prefers_dark or "dark" in gtk_theme.lower()


def context_menu_css(dark_mode: bool) -> str:
    """Return menu colors that match the palette rendered by the widget."""
    if dark_mode:
        background, border, text, hover = "#242424", "#4B5361", "#F7F9FC", "#333333"
    else:
        background, border, text, hover = "#ECEEEC", "#AEB5B0", "#202124", "#DEE2DF"
    return f"""
        .codex-token-context-menu {{
            background-color: {background};
            border: 1px solid {border};
        }}
        .codex-token-context-menu menuitem {{
            background-color: transparent;
            color: {text};
            padding: 6px 12px;
        }}
        .codex-token-context-menu menuitem label {{
            color: {text};
        }}
        .codex-token-context-menu menuitem:hover,
        .codex-token-context-menu menuitem:active {{
            background-color: {hover};
            color: {text};
        }}
        .codex-token-context-menu menuitem:hover label,
        .codex-token-context-menu menuitem:active label {{
            color: {text};
        }}
        .codex-token-context-menu separator {{
            background-color: {border};
        }}
    """


def codex_executable() -> str:
    """Locate the Codex binary bundled with the desktop app or on PATH."""
    if DEFAULT_CODEX_EXECUTABLE.is_file():
        return str(DEFAULT_CODEX_EXECUTABLE)
    executable = shutil.which("codex")
    if executable is None:
        raise FileNotFoundError("Codex executable was not found")
    return executable


def format_reset_date(timestamp: Optional[int]) -> str:
    if timestamp is None:
        return "Renovação indisponível"
    date = datetime.fromtimestamp(timestamp).astimezone()
    return f"Renova em {date.day} de {MONTHS_PT_BR[date.month - 1]}"


def gradient_color(start: str, end: str, progress: float) -> str:
    """Interpolate two hex colors for a smooth canvas meter."""
    progress = max(0.0, min(1.0, progress))
    start_rgb = tuple(int(start[position : position + 2], 16) for position in (1, 3, 5))
    end_rgb = tuple(int(end[position : position + 2], 16) for position in (1, 3, 5))
    rgb = tuple(round(first + (second - first) * progress) for first, second in zip(start_rgb, end_rgb))
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def parse_rate_limits(payload: dict[str, Any]) -> list[UsageLimit]:
    """Turn the app-server response into the limits shown in Codex settings."""
    snapshots = payload.get("rateLimitsByLimitId") or {}
    if not isinstance(snapshots, dict):
        snapshots = {}
    if not snapshots and isinstance(payload.get("rateLimits"), dict):
        snapshots = {"codex": payload["rateLimits"]}

    limits: list[UsageLimit] = []
    for limit_id, snapshot in snapshots.items():
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("primary"), dict):
            continue
        primary = snapshot["primary"]
        used_percent = primary.get("usedPercent")
        if not isinstance(used_percent, int):
            continue
        display_name = snapshot.get("limitName") or "Limites gerais de uso"
        if limit_id == "codex":
            display_name = "Limites gerais de uso"
        resets_at = primary.get("resetsAt")
        limits.append(UsageLimit(str(display_name), max(0, min(100, used_percent)), resets_at if isinstance(resets_at, int) else None))

    limits.sort(key=lambda limit: limit.name != "Limites gerais de uso")
    if not limits:
        raise ValueError("Codex returned no usage-limit windows")
    return limits


def read_usage_limits(executable: Optional[str] = None) -> list[UsageLimit]:
    """Ask the authenticated local Codex app server for account usage limits."""
    process = subprocess.Popen(
        [executable or codex_executable(), "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    if process.stdin is None or process.stdout is None:
        raise OSError("Could not start the Codex app server")

    messages = (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-token-widget", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": None},
    )
    try:
        process.stdin.write("\n".join(json.dumps(message) for message in messages) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + APP_SERVER_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if not line:
                break
            response = json.loads(line)
            if response.get("id") == 2:
                result = response.get("result")
                if not isinstance(result, dict):
                    raise ValueError("Codex did not return usage-limit data")
                return parse_rate_limits(result)
        raise TimeoutError("Timed out while loading Codex usage limits")
    finally:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()


def _set_color(context: Any, color: str, alpha: float = 1.0) -> None:
    red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    context.set_source_rgba(red, green, blue, alpha)


def _draw_text(context: Any, text: str, center_y: float, font: str, color: str) -> None:
    layout = PangoCairo.create_layout(context)
    layout.set_font_description(Pango.FontDescription(font))
    layout.set_text(text, -1)
    width, height = layout.get_pixel_size()
    context.move_to((WIDGET_SIZE - width) / 2, center_y - height / 2)
    _set_color(context, color)
    PangoCairo.show_layout(context, layout)


def usage_level(remaining_percent: int) -> str:
    """Classify remaining capacity into a stable semantic level."""
    if remaining_percent >= 60:
        return "high"
    if remaining_percent >= 30:
        return "medium"
    return "low"


def usage_palette(remaining_percent: int) -> tuple[str, str, str]:
    """Return a seamless gradient anchored in the specified semantic color."""
    palettes = {
        "high": ("#81C995", "#5EB778", "#81C995"),
        "medium": ("#FDD663", "#EAB94A", "#FDD663"),
        "low": ("#F28B82", "#D96B64", "#F28B82"),
    }
    return palettes[usage_level(remaining_percent)]


def _draw_gradient_ring(context: Any, remaining_percent: int, colors: ThemeColors) -> None:
    center = WIDGET_SIZE / 2
    radius = 106
    line_width = 20
    context.set_antialias(cairo.ANTIALIAS_BEST)
    context.set_line_width(line_width)
    context.set_line_cap(cairo.LINE_CAP_ROUND)
    _set_color(context, colors.track)
    context.arc(center, center, radius, 0, math.tau)
    context.stroke()

    fraction = max(0.0, min(1.0, remaining_percent / 100))
    if fraction == 0:
        return

    start_color, middle_color, end_color = usage_palette(remaining_percent)
    gradient = cairo.LinearGradient(22, 22, 218, 218)
    for offset, color in ((0.0, start_color), (0.5, middle_color), (1.0, end_color)):
        red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
        gradient.add_color_stop_rgb(offset, red, green, blue)

    start = -math.pi / 2
    context.set_source(gradient)
    context.set_line_cap(cairo.LINE_CAP_ROUND)
    context.arc(center, center, radius, start, start + math.tau * fraction)
    context.stroke()


def control_at(x: float, y: float) -> Optional[str]:
    """Return the icon control under a point in base-widget coordinates."""
    controls = (
        ("passthrough", PASSTHROUGH_CONTROL),
        ("pin", PIN_CONTROL),
        ("resize", RESIZE_CONTROL),
    )
    for name, center in controls:
        if math.hypot(x - center[0], y - center[1]) <= CONTROL_RADIUS:
            return name
    return None


def clamp_widget_size(size: float) -> int:
    return max(MIN_WIDGET_SIZE, min(MAX_WIDGET_SIZE, round(size)))


def widget_height(width: float) -> int:
    """Preserve the transparent control strip above the circular meter."""
    return round(width * WIDGET_HEIGHT / WIDGET_SIZE)


def outward_resize_delta(delta_x: float, delta_y: float) -> float:
    """Project pointer movement onto the handle's center-to-outside direction."""
    circle_center = (WIDGET_SIZE / 2, CONTENT_OFFSET_Y + WIDGET_SIZE / 2)
    outward_x = RESIZE_CONTROL[0] - circle_center[0]
    outward_y = RESIZE_CONTROL[1] - circle_center[1]
    distance = math.hypot(outward_x, outward_y)
    return (delta_x * outward_x + delta_y * outward_y) / distance


def passthrough_control_region(width: int, height: int) -> tuple[int, int, int, int]:
    """Return the only input area retained while click-through is active."""
    scale = min(width / WIDGET_SIZE, height / WIDGET_HEIGHT)
    radius = (CONTROL_RADIUS + 2) * scale
    center_x = PASSTHROUGH_CONTROL[0] * scale
    center_y = PASSTHROUGH_CONTROL[1] * scale
    return (
        max(0, round(center_x - radius)),
        max(0, round(center_y - radius)),
        max(1, round(radius * 2)),
        max(1, round(radius * 2)),
    )


def clamp_window_position(
    x: int,
    y: int,
    width: int,
    height: int,
    workareas: list[tuple[int, int, int, int]],
    pointer: Optional[tuple[int, int]] = None,
) -> tuple[int, int]:
    """Keep a window fully inside the active monitor, allowing monitor-to-monitor travel."""
    valid_areas = [area for area in workareas if area[2] > 0 and area[3] > 0]
    if not valid_areas:
        return x, y

    target = None
    if pointer is not None:
        pointer_x, pointer_y = pointer
        target = next(
            (
                area
                for area in valid_areas
                if area[0] <= pointer_x < area[0] + area[2]
                and area[1] <= pointer_y < area[1] + area[3]
            ),
            None,
        )

    if target is None:
        def intersection_area(area: tuple[int, int, int, int]) -> int:
            area_x, area_y, area_width, area_height = area
            overlap_width = max(0, min(x + width, area_x + area_width) - max(x, area_x))
            overlap_height = max(0, min(y + height, area_y + area_height) - max(y, area_y))
            return overlap_width * overlap_height

        target = max(valid_areas, key=intersection_area)

    area_x, area_y, area_width, area_height = target
    max_x = area_x + max(0, area_width - width)
    max_y = area_y + max(0, area_height - height)
    return max(area_x, min(x, max_x)), max(area_y, min(y, max_y))


def _draw_icon_control(
    context: Any,
    name: str,
    center: tuple[int, int],
    active: bool,
    hovered: bool,
    colors: ThemeColors,
) -> None:
    x, y = center
    fill = colors.control_hover if hovered else colors.control
    if active:
        fill = colors.control_active_hover if hovered else colors.control_active
    _set_color(context, fill)
    context.arc(x, y, 11, 0, math.tau)
    context.fill()

    _set_color(context, "#81C995" if active else colors.icon)
    context.set_line_width(1.45)
    context.set_line_cap(cairo.LINE_CAP_ROUND)
    context.set_line_join(cairo.LINE_JOIN_ROUND)
    if name == "passthrough":
        context.move_to(x - 5, y - 6)
        context.line_to(x + 4.5, y + 1)
        context.line_to(x + 0.5, y + 1.8)
        context.line_to(x + 3, y + 6)
        context.line_to(x + 0.5, y + 7)
        context.line_to(x - 1.8, y + 2.8)
        context.line_to(x - 4.5, y + 5)
        context.close_path()
        context.move_to(x + 3.5, y - 5)
        context.line_to(x + 6.5, y - 5)
        context.line_to(x + 6.5, y - 2)
    elif name == "pin":
        context.move_to(x - 4.5, y - 5)
        context.line_to(x + 4.5, y - 5)
        context.move_to(x - 2.7, y - 4.5)
        context.line_to(x - 1.8, y)
        context.line_to(x - 4.5, y + 3)
        context.line_to(x + 4.5, y + 3)
        context.line_to(x + 1.8, y)
        context.line_to(x + 2.7, y - 4.5)
        context.move_to(x, y + 3)
        context.line_to(x, y + 7)
    else:
        context.move_to(x - 5, y + 5)
        context.line_to(x + 5, y - 5)
        context.move_to(x + 1, y - 5)
        context.line_to(x + 5, y - 5)
        context.line_to(x + 5, y - 1)
        context.move_to(x - 1, y + 5)
        context.line_to(x - 5, y + 5)
        context.line_to(x - 5, y + 1)
    context.stroke()


def _draw_controls(
    context: Any,
    pinned: bool,
    click_through: bool,
    hovered: Optional[str],
    colors: ThemeColors,
) -> None:
    _draw_icon_control(context, "passthrough", PASSTHROUGH_CONTROL, click_through, hovered == "passthrough", colors)
    _draw_icon_control(context, "pin", PIN_CONTROL, pinned, hovered == "pin", colors)
    _draw_icon_control(context, "resize", RESIZE_CONTROL, False, hovered == "resize", colors)


def draw_widget(
    context: Any,
    limits: list[UsageLimit],
    selected: int,
    error: bool = False,
    pinned: bool = True,
    hovered_control: Optional[str] = None,
    click_through: bool = False,
    dark_mode: bool = True,
    status_text: Optional[str] = None,
) -> None:
    """Render the complete circular widget on a Cairo context."""
    colors = theme_colors(dark_mode)
    context.set_antialias(cairo.ANTIALIAS_BEST)
    context.set_operator(cairo.OPERATOR_CLEAR)
    context.paint()
    context.set_operator(cairo.OPERATOR_OVER)
    context.save()
    context.translate(0, CONTENT_OFFSET_Y)

    shadow = cairo.RadialGradient(120, 124, 94, 120, 124, 119)
    shadow.add_color_stop_rgba(0, 0, 0, 0, 0)
    shadow.add_color_stop_rgba(1, 0, 0, 0, 0.26)
    context.set_source(shadow)
    context.arc(120, 124, 116, 0, math.tau)
    context.fill()

    selected_limit = limits[selected] if limits and not error else None
    is_spark = selected_limit is not None and selected_limit.name != "Limites gerais de uso"
    _set_color(context, colors.spark_background if is_spark else colors.background)
    context.arc(120, 120, 112, 0, math.tau)
    context.fill()

    if error or not limits:
        _draw_text(context, "—", 107, "Sans Bold 34", colors.primary)
        _draw_text(context, "Não foi possível atualizar", 139, "Sans 9", colors.secondary)
        _draw_text(context, "Clique para tentar novamente", 163, "Sans 8", colors.tertiary)
        context.restore()
        _draw_controls(context, pinned, click_through, hovered_control, colors)
        return

    limit = limits[selected]
    label = "GERAL" if not is_spark else limit.name.removesuffix(" · sessão").removesuffix(" · semanal").upper()
    _draw_gradient_ring(context, limit.remaining_percent, colors)
    _draw_text(context, label, 67, "Sans Bold 8", colors.spark_label if is_spark else colors.label)
    _draw_text(context, f"{limit.remaining_percent}%", 111, "Sans Bold 26", colors.primary)
    _draw_text(context, "restante", 137, "Sans 8", colors.secondary)
    _draw_text(context, status_text or format_reset_date(limit.resets_at), 163, "Sans 7", colors.tertiary)

    dot_gap = 10
    start_x = 120 - (len(limits) - 1) * dot_gap / 2
    for index in range(len(limits)):
        _set_color(context, colors.dot_active if index == selected else colors.dot_inactive)
        context.arc(start_x + index * dot_gap, 185, 2.2 if index == selected else 1.8, 0, math.tau)
        context.fill()

    context.restore()
    _draw_controls(context, pinned, click_through, hovered_control, colors)


class TokenWidget(Gtk.Window if Gtk is not None else object):
    def __init__(self, application: Any = None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        if application is not None:
            self.set_application(application)
        self._position_file = POSITION_FILE
        self._limits: list[UsageLimit] = []
        self._selected_limit = 0
        self._error = False
        self._refreshing = False
        self._press_origin: Optional[tuple[float, float]] = None
        self._press_target: Optional[str] = None
        self._resize_start_size = WIDGET_SIZE
        self._did_drag = False
        self._hovered_control: Optional[str] = None
        self._pinned = True
        self._click_through = False
        self._dark_mode = True
        self._interface_settings: Optional[Any] = None
        self._gtk_settings: Optional[Any] = None
        self._context_menu_css_provider: Optional[Any] = None
        self._visibility_check_pending = False
        self._widget_size = WIDGET_SIZE
        self._minimized = False
        self._snapshot: Optional[CodexSnapshot] = None
        self._cost = None
        self._profiles = configured_profiles()
        self._profile_index = 0

        self.set_title("Codex Token Widget")
        self.set_icon_name("codex-token-widget")
        self.set_default_size(WIDGET_SIZE, WIDGET_HEIGHT)
        self.set_size_request(MIN_WIDGET_SIZE, widget_height(MIN_WIDGET_SIZE))
        self.set_resizable(True)
        self.set_decorated(False)
        self.set_keep_above(self._pinned)
        self.set_skip_taskbar_hint(False)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self._configure_system_theme()

        self.area = Gtk.DrawingArea()
        self.area.set_size_request(MIN_WIDGET_SIZE, widget_height(MIN_WIDGET_SIZE))
        self.area.set_has_tooltip(True)
        self.area.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.area.connect("draw", self._on_draw)
        self.area.connect("button-press-event", self._on_press)
        self.area.connect("motion-notify-event", self._on_motion)
        self.area.connect("button-release-event", self._on_release)
        self.area.connect("leave-notify-event", self._on_leave)
        self.area.connect("query-tooltip", self._on_tooltip)
        self.add(self.area)
        self._context_menu = self._build_context_menu()
        self.connect("key-press-event", self._on_key)
        self.connect("map-event", self._on_map)
        self.connect("configure-event", self._on_configure)
        self.connect("size-allocate", self._on_size_allocate)
        self.connect("window-state-event", self._on_window_state)
        self._restore_position()
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_MS // 1000, self._scheduled_refresh)
        GLib.timeout_add_seconds(2, self._maintain_window_layer)

    def _render_limits(self, limits: list[UsageLimit]) -> None:
        self._limits = limits
        self._selected_limit = min(self._selected_limit, len(limits) - 1)
        self._error = False
        self.area.queue_draw()

    def _on_draw(self, _area: Any, context: Any) -> bool:
        allocation = self.area.get_allocation()
        scale = min(allocation.width / WIDGET_SIZE, allocation.height / WIDGET_HEIGHT)
        context.save()
        context.scale(scale, scale)
        draw_widget(
            context,
            self._limits,
            self._selected_limit,
            self._error,
            self._pinned,
            self._hovered_control,
            self._click_through,
            self._dark_mode,
            self._status_text(),
        )
        context.restore()
        return False

    def _status_text(self) -> Optional[str]:
        if self._snapshot is None:
            return None
        if self._snapshot.credits.unlimited:
            return "Créditos ilimitados"
        if self._snapshot.credits.available and self._snapshot.credits.balance is not None:
            return f"Créditos: {self._snapshot.credits.balance:g}"
        return None

    def _base_point(self, x: float, y: float) -> tuple[float, float]:
        allocation = self.area.get_allocation()
        scale = min(allocation.width / WIDGET_SIZE, allocation.height / WIDGET_HEIGHT)
        return x / scale, y / scale

    def _configure_system_theme(self) -> None:
        """Follow the system GTK appearance and repaint when it changes."""
        self._gtk_settings = Gtk.Settings.get_default()
        if self._gtk_settings is not None:
            self._gtk_settings.connect("notify::gtk-theme-name", self._on_system_theme_changed)
            self._gtk_settings.connect(
                "notify::gtk-application-prefer-dark-theme",
                self._on_system_theme_changed,
            )
        try:
            schema_source = Gio.SettingsSchemaSource.get_default()
            schema = schema_source.lookup("org.gnome.desktop.interface", True) if schema_source else None
            if schema is not None:
                self._interface_settings = Gio.Settings.new("org.gnome.desktop.interface")
                self._interface_settings.connect("changed::color-scheme", self._on_system_theme_changed)
                self._interface_settings.connect("changed::gtk-theme", self._on_system_theme_changed)
        except GLib.Error:
            self._interface_settings = None
        self._sync_system_theme()

    def _sync_system_theme(self) -> None:
        color_scheme = "default"
        gtk_theme = ""
        if self._interface_settings is not None:
            color_scheme = self._interface_settings.get_string("color-scheme")
            gtk_theme = self._interface_settings.get_string("gtk-theme")
        gtk_settings = self._gtk_settings
        if gtk_settings is not None:
            gtk_theme = gtk_settings.get_property("gtk-theme-name") or gtk_theme
        gtk_prefers_dark = bool(gtk_settings.get_property("gtk-application-prefer-dark-theme")) if gtk_settings else False
        self._dark_mode = system_prefers_dark(color_scheme, gtk_theme, gtk_prefers_dark)

    def _on_system_theme_changed(self, _settings: Any, _key: str) -> None:
        previous = self._dark_mode
        self._sync_system_theme()
        self._apply_context_menu_theme()
        if self._dark_mode != previous:
            self.area.queue_draw()

    def _on_press(self, _area: Any, event: Any) -> bool:
        if event.button == 3:
            self._context_menu.popup_at_pointer(event)
            return True
        if event.button != 1:
            return False
        self._press_origin = (event.x_root, event.y_root)
        self._press_target = control_at(*self._base_point(event.x, event.y))
        self._resize_start_size = self._widget_size
        self._did_drag = False
        return True

    def _build_context_menu(self) -> Any:
        menu = Gtk.Menu()
        menu.get_style_context().add_class("codex-token-context-menu")
        self._context_menu_css_provider = Gtk.CssProvider()
        menu.get_style_context().add_provider(
            self._context_menu_css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._apply_context_menu_theme()
        refresh = Gtk.MenuItem.new_with_label("Atualizar agora")
        refresh.connect("activate", lambda _item: self.refresh())
        menu.append(refresh)
        account = Gtk.MenuItem.new_with_label("Alternar conta")
        account.connect("activate", lambda _item: self._next_account())
        menu.append(account)
        costs = Gtk.MenuItem.new_with_label("Mostrar custo local")
        costs.connect("activate", lambda _item: self._show_cost())
        menu.append(costs)
        dashboard = Gtk.MenuItem.new_with_label("Abrir painel do Codex")
        dashboard.connect("activate", lambda _item: webbrowser.open("https://chatgpt.com/codex/settings/usage"))
        menu.append(dashboard)
        menu.append(Gtk.SeparatorMenuItem())
        minimize = Gtk.MenuItem.new_with_label("Minimizar")
        minimize.connect("activate", lambda _item: self._minimize())
        close = Gtk.MenuItem.new_with_label("Fechar")
        close.connect("activate", lambda _item: self.close())
        menu.append(minimize)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(close)
        menu.show_all()
        return menu

    def _apply_context_menu_theme(self) -> None:
        if self._context_menu_css_provider is None:
            return
        self._context_menu_css_provider.load_from_data(context_menu_css(self._dark_mode).encode("utf-8"))

    def _next_account(self) -> None:
        self._profile_index = (self._profile_index + 1) % len(self._profiles)
        self._limits = []
        self._error = False
        self.refresh()

    def _show_cost(self) -> None:
        if self._cost is None:
            return
        summary = self._cost
        notify(
            "Custo local do Codex",
            f"{summary.days} dias · {summary.input_tokens + summary.output_tokens:,} tokens · estimado ${summary.estimated_cost:.2f}",
        )

    def _on_motion(self, _area: Any, event: Any) -> bool:
        if self._press_origin and self._press_target == "resize":
            delta_x = event.x_root - self._press_origin[0]
            delta_y = event.y_root - self._press_origin[1]
            delta = outward_resize_delta(delta_x, delta_y)
            new_size = clamp_widget_size(self._resize_start_size + delta)
            self._did_drag = self._did_drag or new_size != self._resize_start_size
            if new_size != self._widget_size:
                self._widget_size = new_size
                self.resize(new_size, widget_height(new_size))
            return True
        if self._press_origin and self._press_target is None and not self._did_drag:
            moved = abs(event.x_root - self._press_origin[0]) > 5 or abs(event.y_root - self._press_origin[1]) > 5
            if moved:
                self._did_drag = True
                self.begin_move_drag(1, round(event.x_root), round(event.y_root), event.time)
            return True
        if self._press_origin is None:
            hovered = control_at(*self._base_point(event.x, event.y))
            if hovered != self._hovered_control:
                self._hovered_control = hovered
                self._update_cursor()
                self.area.queue_draw()
        return True

    def _on_release(self, _area: Any, event: Any) -> bool:
        if event.button != 1:
            return False
        target = self._press_target
        self._press_origin = None
        self._press_target = None
        if not self._did_drag:
            if target == "pin":
                self._pinned = not self._pinned
                self._apply_window_layer()
                self.area.queue_draw()
            elif target == "passthrough":
                self._click_through = not self._click_through
                self._apply_input_region()
                self.area.queue_draw()
            elif target == "resize":
                return True
            elif len(self._limits) > 1:
                self._selected_limit = (self._selected_limit + 1) % len(self._limits)
                self.area.queue_draw()
            elif not self._limits or self._error:
                self.refresh()
        return True

    def _on_leave(self, _area: Any, _event: Any) -> bool:
        if self._press_origin is None and self._hovered_control is not None:
            self._hovered_control = None
            self._update_cursor()
            self.area.queue_draw()
        return False

    def _on_tooltip(self, _area: Any, x: int, y: int, _keyboard_mode: bool, tooltip: Any) -> bool:
        target = control_at(*self._base_point(x, y))
        if target == "pin":
            tooltip.set_text("Desfixar da tela" if self._pinned else "Fixar na tela")
        elif target == "passthrough":
            tooltip.set_text("Desativar modo intangível" if self._click_through else "Ativar modo intangível")
        elif target == "resize":
            tooltip.set_text("Arraste para redimensionar")
        else:
            if self._snapshot is None:
                return False
            account = self._snapshot.account_email or "Conta atual"
            plan = f" · {self._snapshot.plan}" if self._snapshot.plan else ""
            cost = ""
            if self._cost is not None:
                cost = f"\nCusto local (30d): ${self._cost.estimated_cost:.2f}"
            tooltip.set_text(f"{account}{plan}{cost}\nClique para alternar limites")
        return True

    def _update_cursor(self) -> None:
        window = self.area.get_window()
        if window is None:
            return
        cursor_name = "ne-resize" if self._hovered_control == "resize" else "pointer" if self._hovered_control else "default"
        window.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), cursor_name))

    def _on_key(self, _widget: Any, event: Any) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_map(self, _widget: Any, _event: Any) -> bool:
        GLib.idle_add(self._apply_window_layer)
        GLib.idle_add(self._apply_input_region)
        self._queue_visibility_check()
        return False

    def _on_configure(self, _widget: Any, _event: Any) -> bool:
        self._queue_visibility_check()
        return False

    def _queue_visibility_check(self) -> None:
        if not self._visibility_check_pending:
            self._visibility_check_pending = True
            GLib.idle_add(self._ensure_visible)

    def _monitor_workareas(self) -> list[tuple[int, int, int, int]]:
        display = self.get_display()
        workareas = []
        for index in range(display.get_n_monitors()):
            rectangle = display.get_monitor(index).get_workarea()
            workareas.append((rectangle.x, rectangle.y, rectangle.width, rectangle.height))
        return workareas

    def _pointer_position(self) -> Optional[tuple[int, int]]:
        if self._press_origin is None:
            return None
        pointer = self.get_display().get_default_seat().get_pointer()
        if pointer is None:
            return None
        _screen, pointer_x, pointer_y = pointer.get_position()
        return pointer_x, pointer_y

    def _ensure_visible(self) -> bool:
        self._visibility_check_pending = False
        if not self.get_realized():
            return False
        x, y = self.get_position()
        width, height = self.get_size()
        safe_x, safe_y = clamp_window_position(
            x,
            y,
            width,
            height,
            self._monitor_workareas(),
            self._pointer_position(),
        )
        if (safe_x, safe_y) != (x, y):
            self.move(safe_x, safe_y)
        return False

    def _on_size_allocate(self, _widget: Any, _allocation: Any) -> None:
        if self._click_through:
            GLib.idle_add(self._apply_input_region)

    def _on_window_state(self, _widget: Any, event: Any) -> bool:
        self._minimized = bool(event.new_window_state & Gdk.WindowState.ICONIFIED)
        if not self._minimized:
            self.set_skip_taskbar_hint(False)
            GLib.idle_add(self._apply_window_layer)
        return False

    def _minimize(self) -> None:
        self.set_skip_taskbar_hint(False)
        self.iconify()

    def _apply_window_layer(self) -> bool:
        self.set_keep_above(self._pinned)
        if self._pinned:
            self.stick()
        else:
            self.unstick()
        window = self.get_window()
        if window is not None:
            window.set_keep_above(self._pinned)
        return False

    def _apply_input_region(self) -> bool:
        """Keep the controls clickable while optionally passing circle clicks through."""
        window = self.get_window()
        if window is None:
            return False
        allocation = self.get_allocation()
        if not self._click_through:
            full_region = cairo.Region(cairo.RectangleInt(0, 0, allocation.width, allocation.height))
            window.input_shape_combine_region(full_region, 0, 0)
            return False
        x, y, width, height = passthrough_control_region(allocation.width, allocation.height)
        region = cairo.Region(cairo.RectangleInt(x, y, width, height))
        window.input_shape_combine_region(region, 0, 0)
        return False

    def _maintain_window_layer(self) -> bool:
        if self._pinned and not self._minimized:
            self._apply_window_layer()
        return True

    def _restore_position(self) -> None:
        try:
            position = json.loads(self._position_file.read_text(encoding="utf-8"))
            self._widget_size = clamp_widget_size(position.get("size", WIDGET_SIZE))
            self._pinned = bool(position.get("pinned", True))
            self._click_through = bool(position.get("click_through", False))
            self._apply_window_layer()
            self.resize(self._widget_size, widget_height(self._widget_size))
            safe_x, safe_y = clamp_window_position(
                int(position["x"]),
                int(position["y"]),
                self._widget_size,
                widget_height(self._widget_size),
                self._monitor_workareas(),
            )
            self.move(safe_x, safe_y)
        except (OSError, ValueError, KeyError, TypeError):
            self.move(24, 24)

    def _save_position(self) -> None:
        try:
            self._position_file.parent.mkdir(parents=True, exist_ok=True)
            x, y = self.get_position()
            state = {
                "x": x,
                "y": y,
                "size": self._widget_size,
                "pinned": self._pinned,
                "click_through": self._click_through,
            }
            self._position_file.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass

    def refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._load_limits, daemon=True).start()

    def _load_limits(self) -> None:
        try:
            profile = self._profiles[self._profile_index]
            snapshot = load_snapshot(profile["home"])
            limits = [UsageLimit(item.name, item.used_percent, item.resets_at) for item in snapshot.windows]
            cost = scan_local_cost(profile["home"])
            GLib.idle_add(self._finish_refresh, limits, False, snapshot, cost)
        except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
            GLib.idle_add(self._finish_refresh, [], True, None, None)

    def _finish_refresh(self, limits: list[UsageLimit], error: bool, snapshot: Optional[CodexSnapshot] = None, cost: Any = None) -> bool:
        self._refreshing = False
        self._error = error
        if not error:
            self._snapshot = snapshot
            self._cost = cost
            if snapshot and any(item.remaining_percent <= 20 for item in snapshot.windows):
                notify("Limite do Codex próximo do fim", "Uma das janelas de uso está com 20% ou menos restante.")
            self._render_limits(limits)
        else:
            self.area.queue_draw()
        return False

    def _scheduled_refresh(self) -> bool:
        self.refresh()
        return True

    def close(self) -> None:
        self._ensure_visible()
        self._save_position()
        self.destroy()


def main() -> None:
    if Gtk is None or Gio is None or cairo is None:
        raise SystemExit("GTK is unavailable; install python3-gi and gir1.2-gtk-3.0.")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    instance_lock = LOCK_FILE.open("w")
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    GLib.set_prgname("codex-token-widget")
    Gdk.set_program_class("codex-token-widget")
    Gtk.Window.set_default_icon_name("codex-token-widget")
    application = Gtk.Application(
        application_id="io.github.mehiel.CodexTokenWidget",
        flags=Gio.ApplicationFlags.FLAGS_NONE,
    )

    def activate(app: Any) -> None:
        windows = app.get_windows()
        widget = windows[0] if windows else TokenWidget(app)
        widget.show_all()
        widget.present()

    application.connect("activate", activate)
    application.run(None)


if __name__ == "__main__":
    main()
