#!/usr/bin/env python3
"""Always-on-top display of provider usage limits."""

from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from usage_sources import UsageLimit, configured_profiles, notify, read_antigravity_limits, read_codex_limits

PROVIDER_ERRORS = (OSError, ValueError, TimeoutError, json.JSONDecodeError, RuntimeError, subprocess.SubprocessError)

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

POSITION_FILE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "usage-limit" / "position.json"
LEGACY_POSITION_FILE = Path.home() / ".codex" / "token_widget_position.json"
RUNTIME_ROOT = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
LOCK_FILE = Path(RUNTIME_ROOT) / "usage-limit" / "widget.lock"
REFRESH_MS = 5 * 60_000
MONTHS_PT_BR = ("jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez.")
WIDGET_SIZE = 240
WIDGET_HEIGHT = 300
CONTENT_OFFSET_Y = 28
MIN_WIDGET_SIZE = 180
MAX_WIDGET_SIZE = 360
PROVIDER_TOGGLE = (120, 284)
PASSTHROUGH_CONTROL = (80, 15)
PIN_CONTROL = (120, 15)
RESIZE_CONTROL = (160, 15)
CONTROL_RADIUS = 13

def log_debug(message: str) -> None:
    try:
        with open("/tmp/usage_limit_debug.log", "a") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat()} - {message}\n")
    except Exception:
        pass


@dataclass(frozen=True)
class ThemeColors:
    background: str
    alternate_background: str
    track: str
    primary: str
    secondary: str
    tertiary: str
    label: str
    alternate_label: str
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


def _set_color(context: Any, color: str, alpha: float = 1.0) -> None:
    red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    context.set_source_rgba(red, green, blue, alpha)


def _draw_text(
    context: Any,
    text: str,
    center_y: float,
    font: str,
    color: str,
    max_width: Optional[int] = None,
    center_x: Optional[float] = None,
) -> None:
    layout = PangoCairo.create_layout(context)
    layout.set_font_description(Pango.FontDescription(font))
    layout.set_text(text, -1)
    if max_width is not None:
        layout.set_width(max_width * Pango.SCALE)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    width, height = layout.get_pixel_size()
    context.move_to((center_x if center_x is not None else WIDGET_SIZE / 2) - width / 2, center_y - height / 2)
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
    if abs(x - PROVIDER_TOGGLE[0]) <= 24 and abs(y - PROVIDER_TOGGLE[1]) <= 11:
        return "provider"
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


def control_region(
    center: tuple[int, int],
    width: int,
    height: int,
    half_width: int = CONTROL_RADIUS + 2,
    half_height: Optional[int] = None,
) -> cairo.RectangleInt:
    """Return a scaled clickable control region."""
    scale = min(width / WIDGET_SIZE, height / WIDGET_HEIGHT)
    scaled_height = (half_height if half_height is not None else half_width) * scale
    scaled_width = half_width * scale
    center_x = center[0] * scale
    center_y = center[1] * scale
    return cairo.RectangleInt(max(0, round(center_x - scaled_width)), max(0, round(center_y - scaled_height)), max(1, round(scaled_width * 2)), max(1, round(scaled_height * 2)))


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


def _rounded_rectangle(context: Any, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
    context.close_path()


def _draw_controls(
    context: Any,
    pinned: bool,
    click_through: bool,
    hovered: Optional[str],
    colors: ThemeColors,
    active_provider: Optional[str],
    available_providers: set[str],
) -> None:
    toggle_x, toggle_y = PROVIDER_TOGGLE
    _rounded_rectangle(context, toggle_x - 23, toggle_y - 10, 46, 20, 10)
    toggle_hovered = hovered == "provider" and len(available_providers) > 1
    _set_color(context, colors.control_hover if toggle_hovered else colors.control)
    context.fill()
    for index, provider in enumerate(("Codex", "Antigravity")):
        left = toggle_x - 22 + index * 22
        active = provider == active_provider
        enabled = provider in available_providers
        if active and enabled:
            _set_color(context, colors.control_active)
            _rounded_rectangle(context, left, toggle_y - 9, 22, 18, 8)
            context.fill()
        text_color = colors.primary if active and enabled else colors.icon if enabled else colors.tertiary
        _draw_text(context, "C" if index == 0 else "A", toggle_y, "Sans Bold 8", text_color, center_x=left + 11)
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
    active_provider: Optional[str] = None,
    available_providers: Optional[set[str]] = None,
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
    is_alternate = selected_limit is not None and selected_limit.window != "session"
    _set_color(
        context,
        colors.alternate_background if is_alternate else colors.background,
    )
    context.arc(120, 120, 112, 0, math.tau)
    context.fill()

    if error or not limits:
        _draw_text(context, "—", 107, "Sans Bold 34", colors.primary)
        _draw_text(context, "Não foi possível atualizar", 139, "Sans 9", colors.secondary)
        _draw_text(context, "Clique para tentar novamente", 163, "Sans 8", colors.tertiary)
        context.restore()
        _draw_controls(context, pinned, click_through, hovered_control, colors, active_provider, available_providers or set())
        return

    limit = limits[selected]
    window_label = {"session": "sessão", "weekly": "semanal", "5h": "5 horas"}.get(limit.window, limit.window)
    _draw_gradient_ring(context, limit.remaining_percent, colors)
    label_color = colors.alternate_label if is_alternate else colors.label
    _draw_text(context, limit.provider, 61, "Sans Bold 8", label_color, 190)
    _draw_text(
        context,
        f"{limit.name} · {window_label}",
        73,
        "Sans 7",
        label_color,
        200,
    )
    _draw_text(context, f"{limit.remaining_percent}%", 111, "Sans Bold 26", colors.primary)
    _draw_text(context, "restante", 137, "Sans 8", colors.secondary)
    _draw_text(context, format_reset_date(limit.resets_at), 163, "Sans 7", colors.tertiary)

    dot_gap = 10
    start_x = 120 - (len(limits) - 1) * dot_gap / 2
    for index in range(len(limits)):
        _set_color(context, colors.dot_active if index == selected else colors.dot_inactive)
        context.arc(start_x + index * dot_gap, 185, 2.2 if index == selected else 1.8, 0, math.tau)
        context.fill()

    context.restore()
    _draw_controls(context, pinned, click_through, hovered_control, colors, active_provider, available_providers or set())


class UsageLimitWidget(Gtk.Window if Gtk is not None else object):
    def __init__(self, application: Any = None):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        if application is not None:
            self.set_application(application)
        self._position_file = POSITION_FILE
        self._all_limits: list[UsageLimit] = []
        self._limits: list[UsageLimit] = []
        self._active_provider: Optional[str] = None
        self._selected_limit = 0
        self._error = False
        self._refreshing = False
        self._refresh_generation = 0
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
        self._visibility_check_pending = False
        self._widget_size = WIDGET_SIZE
        self._minimized = False
        self._profiles = configured_profiles()
        self._profile_index = 0

        self.set_title("Usage Limit")
        self.set_icon_name("usage-limit")
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
        self._all_limits = limits
        providers = {limit.provider for limit in limits}
        if self._active_provider not in providers:
            self._active_provider = next((provider for provider in ("Codex", "Antigravity") if provider in providers), None)
        self._limits = [limit for limit in limits if limit.provider == self._active_provider]
        self._selected_limit = max(0, min(self._selected_limit, len(self._limits) - 1))
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
            self._active_provider,
            {limit.provider for limit in self._all_limits},
        )
        context.restore()
        return False

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
        self._apply_native_theme_preference()

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

    def _apply_native_theme_preference(self) -> None:
        """Let GTK render native menus using the same system appearance."""
        if self._gtk_settings is None:
            return
        preferred = bool(self._gtk_settings.get_property("gtk-application-prefer-dark-theme"))
        if preferred != self._dark_mode:
            self._gtk_settings.set_property("gtk-application-prefer-dark-theme", self._dark_mode)

    def _on_system_theme_changed(self, _settings: Any, _key: str) -> None:
        previous = self._dark_mode
        self._sync_system_theme()
        self._apply_native_theme_preference()
        if self._dark_mode != previous:
            self.area.queue_draw()

    def _on_press(self, _area: Any, event: Any) -> bool:
        if event.button == 3:
            self._context_menu.popup_at_pointer(event)
            return True
        if event.button != 1:
            return False
        self._press_origin = (event.x_root, event.y_root)
        base_x, base_y = self._base_point(event.x, event.y)
        self._press_target = control_at(base_x, base_y)
        log_debug(f"Press at raw=({event.x}, {event.y}) base=({base_x}, {base_y}) target={self._press_target}")
        self._resize_start_size = self._widget_size
        self._did_drag = False
        return True

    def _build_context_menu(self) -> Any:
        menu = Gtk.Menu()
        refresh = Gtk.MenuItem.new_with_label("Atualizar agora")
        refresh.connect("activate", lambda _item: self.refresh())
        menu.append(refresh)
        toggle_prov = Gtk.MenuItem.new_with_label("Alternar provedor (Codex / Antigravity)")
        toggle_prov.connect("activate", lambda _item: self._toggle_provider())
        menu.append(toggle_prov)
        if len(self._profiles) > 1:
            account = Gtk.MenuItem.new_with_label("Alternar conta do Codex")
            account.connect("activate", lambda _item: self._next_account())
            menu.append(account)
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

    def _next_account(self) -> None:
        self._profile_index = (self._profile_index + 1) % len(self._profiles)
        self._all_limits = []
        self._limits = []
        self._error = False
        self.refresh(force=True)

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
        log_debug(f"Release target={target} did_drag={self._did_drag}")
        self._press_origin = None
        self._press_target = None
        if not self._did_drag:
            if target == "provider":
                self._toggle_provider()
            elif target == "pin":
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
        if target == "provider":
            providers = {limit.provider for limit in self._all_limits}
            if len(providers) < 2:
                if len(providers) == 1:
                    tooltip.set_text(f"Apenas {next(iter(providers))} está disponível")
                else:
                    tooltip.set_text(
                        "Provedores indisponíveis" if self._error else "Carregando provedores"
                    )
            else:
                next_provider = "Antigravity" if self._active_provider == "Codex" else "Codex"
                tooltip.set_text(f"Mostrar limites do {next_provider}")
        elif target == "pin":
            tooltip.set_text("Desfixar da tela" if self._pinned else "Fixar na tela")
        elif target == "passthrough":
            tooltip.set_text("Desativar modo intangível" if self._click_through else "Ativar modo intangível")
        elif target == "resize":
            tooltip.set_text("Arraste para redimensionar")
        else:
            tooltip.set_text("Limites de uso por provedor\nClique para alternar janelas")
        return True

    def _toggle_provider(self) -> None:
        providers = {limit.provider for limit in self._all_limits}
        log_debug(f"Toggle provider: all_limits={[(l.provider, l.name) for l in self._all_limits]}, providers={providers}")
        if len(providers) < 2:
            return
        self._active_provider = "Antigravity" if self._active_provider == "Codex" else "Codex"
        self._limits = [limit for limit in self._all_limits if limit.provider == self._active_provider]
        self._selected_limit = min(self._selected_limit, max(0, len(self._limits) - 1))
        log_debug(f"Switched provider to: {self._active_provider}, new limits length: {len(self._limits)}")
        self.area.queue_draw()

    def _update_cursor(self) -> None:
        window = self.area.get_window()
        if window is None:
            return
        provider_disabled = self._hovered_control == "provider" and len({limit.provider for limit in self._all_limits}) < 2
        cursor_name = "ne-resize" if self._hovered_control == "resize" else "pointer" if self._hovered_control and not provider_disabled else "default"
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
        region = cairo.Region(control_region(PASSTHROUGH_CONTROL, allocation.width, allocation.height))
        region.union(cairo.Region(control_region(PROVIDER_TOGGLE, allocation.width, allocation.height, 24, 11)))
        window.input_shape_combine_region(region, 0, 0)
        return False

    def _maintain_window_layer(self) -> bool:
        if self._pinned and not self._minimized:
            self._apply_window_layer()
        return True

    def _restore_position(self) -> None:
        position_file = POSITION_FILE if POSITION_FILE.is_file() else LEGACY_POSITION_FILE
        try:
            position = json.loads(position_file.read_text(encoding="utf-8"))
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

    def refresh(self, force: bool = False) -> None:
        if self._refreshing and not force:
            return
        self._refresh_generation += 1
        generation = self._refresh_generation
        home = self._profiles[self._profile_index]["home"]
        self._refreshing = True
        threading.Thread(target=self._load_limits, args=(home, generation), daemon=True).start()

    def _load_limits(self, home: str, generation: int) -> None:
        try:
            results: list[Optional[list[UsageLimit]]] = [None, None]
            workers = [
                threading.Thread(target=self._collect_source, args=(lambda: read_codex_limits(home), results, 0), daemon=True),
                threading.Thread(target=self._collect_source, args=(read_antigravity_limits, results, 1), daemon=True),
            ]
            for worker in workers:
                worker.start()
            deadline = time.monotonic() + 40
            for worker in workers:
                worker.join(max(0, deadline - time.monotonic()))
            limits = [item for result in results if result for item in result]
            if not limits:
                if any(worker.is_alive() for worker in workers):
                    raise TimeoutError("Timed out while loading usage limits")
                raise ValueError("No usage limits available")
            GLib.idle_add(self._finish_refresh, generation, limits, False)
        except PROVIDER_ERRORS:
            GLib.idle_add(self._finish_refresh, generation, [], True)

    def _collect_source(self, source: Any, results: list[Optional[list[UsageLimit]]], index: int) -> None:
        try:
            results[index] = source()
        except PROVIDER_ERRORS:
            results[index] = None

    def _finish_refresh(self, generation: int, limits: list[UsageLimit], error: bool) -> bool:
        log_debug(f"Finish refresh: error={error}, limits={[(l.provider, l.name, l.used_percent) for l in limits]}")
        if generation != self._refresh_generation:
            return False
        self._refreshing = False
        self._error = error
        if not error:
            if any(item.remaining_percent <= 20 for item in limits):
                notify("Usage Limit", "Uma janela de uso está com 20% ou menos restante.")
            self._render_limits(limits)
        else:
            self._all_limits = []
            self._limits = []
            self._active_provider = None
            self._selected_limit = 0
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
    GLib.set_prgname("usage-limit")
    Gdk.set_program_class("usage-limit")
    Gtk.Window.set_default_icon_name("usage-limit")
    application = Gtk.Application(
        application_id="io.github.mehiel.UsageLimit",
        flags=Gio.ApplicationFlags.FLAGS_NONE,
    )

    def activate(app: Any) -> None:
        windows = app.get_windows()
        widget = windows[0] if windows else UsageLimitWidget(app)
        widget.show_all()
        widget.present()

    application.connect("activate", activate)
    application.run(None)


if __name__ == "__main__":
    main()
