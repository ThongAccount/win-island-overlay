from typing import Dict, Any, List
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRect, QEasingCurve, QPropertyAnimation,
    QEvent, QVariantAnimation, QRectF, QCoreApplication
)
from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QCursor

import ctypes
import ctypes.wintypes

try:
    import win32gui
    WIN32GUI_AVAILABLE = True
except ImportError:
    WIN32GUI_AVAILABLE = False

from backend.core.plugin import PluginRegistry
from backend.core.events import EventBus, WindowStateChanged
from backend.plugins import discover_plugins


SW_SHOWMAXIMIZED = 3


class RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.wintypes.DWORD),
        ('rcMonitor', RECT),
        ('rcWork', RECT),
        ('dwFlags', ctypes.wintypes.DWORD),
    ]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ('length', ctypes.wintypes.UINT),
        ('flags', ctypes.wintypes.UINT),
        ('showCmd', ctypes.wintypes.UINT),
        ('ptMinPosition', ctypes.wintypes.POINT),
        ('ptMaxPosition', ctypes.wintypes.POINT),
        ('rcNormalPosition', RECT),
    ]


# Easing functions from main branch - EXACT copies
def _ease_incubic_outback(progress):
    overshoot = 1.70158
    split = 0.35
    if progress < split:
        t = progress / split
        return split * t * t * t
    else:
        t = (progress - split) / (1.0 - split)
        x = t - 1
        outback = 1 + (overshoot + 1) * x * x * x + overshoot * x * x
        return split + (1.0 - split) * outback


def _ease_inquad_outback(progress):
    overshoot = 1.70158
    split = 0.35
    if progress < split:
        t = progress / split
        return split * t * t
    else:
        t = (progress - split) / (1.0 - split)
        x = t - 1
        outback = 1 + (overshoot + 1) * x * x * x + overshoot * x * x
        return split + (1.0 - split) * outback


_outback_ease = QEasingCurve(QEasingCurve.Type.OutBack).valueForProgress
_inquad_ease = QEasingCurve(QEasingCurve.Type.InQuad).valueForProgress
_incubic_ease = QEasingCurve(QEasingCurve.Type.InCubic).valueForProgress


class OverlayWindow(QWidget):
    """Thin shell: glassmorphism pill, position, animation, event routing.
    
    Animation behavior EXACTLY matches main branch:
    - Expand: _outback_ease (500ms)
    - Collapse: _ease_inquad_outback (500ms) 
    - Fullscreen hide: _ease_incubic_outback (175ms)
    - Fullscreen show: _outback_ease (400ms)
    - OBS/Media/Toast/Weather resize: _ease_incubic_outback (OBS_ANIM_DURATION)
    - Micro-expand: _inquad_ease (200ms)
    """

    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__()
        self.registry = registry
        self.config = config
        self._window_config = config.get('window', {})

        # Window setup - click-through when collapsed
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setMouseTracking(True)

        # Base geometry (from main branch constants)
        self._base_margin_top = self._window_config.get('margin_top', 8.0)
        self._base_micro_width = self._window_config.get('micro_width', 240.0)
        self._base_expanded_width = self._window_config.get('expanded_width', 480.0)
        self._base_height = self._window_config.get('height', 48.0)
        self._obs_extra_width = self._window_config.get('obs_extra_width', 40.0)
        self._media_extra_width = self._window_config.get('media_extra_width', 100.0)

        # Animation - QVariantAnimation for custom easing (main branch style)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_step)
        self._anim.finished.connect(self._on_anim_finished)
        self._anim_start = QRectF()
        self._anim_end = QRectF()
        self._anim_ease = lambda p: p
        self._anim_ease_wh = None

        # State
        self._state = "collapsed"  # collapsed, expanded, hover, hidden
        self._is_expanded = False
        self._hover_animating = False
        self._expand_progress = 0.0
        self._hover_pending = False
        self._micro_expanded = False
        self._is_hiding = False
        self._hidden_by_fullscreen = False
        self._toast_hovered = False  # For notifications plugin

        # Hover timer
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_confirmed)

        # Proximity detection timer
        self._proximity_timer = QTimer(self)
        self._proximity_timer.timeout.connect(self._check_mouse)

        # Fullscreen detection timer
        self._fullscreen_timer = QTimer(self)
        self._fullscreen_timer.timeout.connect(self._check_fullscreen)

        # Layout for plugins to add widgets
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Plugin references (populated after plugins load)
        self._plugins: Dict[str, Any] = {}

        # Position initially
        self._move_to_top_center()

        # Start timers
        self._proximity_timer.start(100)
        self._fullscreen_timer.start(500)

    def _get_plugin(self, name: str):
        """Get plugin instance by name."""
        return self._plugins.get(name)

    def register_plugin(self, name: str, plugin):
        """Register a plugin for paint/event integration."""
        self._plugins[name] = plugin

    def _compute_widths(self):
        """Compute current widths based on active plugins."""
        extra = 0
        if self._plugins.get('obs') and self._plugins['obs'].get_obs_state() > 0:
            extra += self._obs_extra_width
        if self._plugins.get('media') and self._plugins['media'].get_media_state() > 0:
            extra += self._media_extra_width

        return {
            'micro': self._base_micro_width + extra,
            'expanded': self._base_expanded_width + extra,
            'height': self._base_height,
        }

    @property
    def _collapsed(self):
        widths = self._compute_widths()
        return (widths['micro'], widths['height'])

    @property
    def _expanded(self):
        widths = self._compute_widths()
        return (widths['expanded'], widths['height'])

    @property
    def _micro_width(self):
        return self._compute_widths()['micro']

    def _move_to_top_center(self):
        widths = self._compute_widths()
        screen = self.screen().availableGeometry()
        x = (screen.width() - widths['micro']) // 2
        y = int(self._base_margin_top)
        self.setGeometry(x, y, widths['micro'], widths['height'])

    def showEvent(self, event):
        super().showEvent(event)
        self._move_to_top_center()
        self.registry.config['_window_ref'] = self

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Glassmorphism background
        path = QPainterPath()
        radius = self.height() // 2
        path.addRoundedRect(0, 0, self.width(), self.height(), radius, radius)

        # Base glass
        painter.fillPath(path, QColor(20, 20, 30, 180))

        # Subtle border
        painter.setPen(QColor(255, 255, 255, 30))
        painter.drawPath(path)

        # Plugin painting (order matters - background to foreground)
        paint_order = ['obs', 'media', 'notifications', 'greeting', 'activity', 'weather']
        for name in paint_order:
            plugin = self._plugins.get(name)
            if plugin and hasattr(plugin, 'paint_obs'):
                plugin.paint_obs(painter, self.rect(), self._is_expanded)
            elif plugin and hasattr(plugin, 'paint_media'):
                plugin.paint_media(painter, self.rect(), self._is_expanded)
            elif plugin and hasattr(plugin, 'paint_notifications'):
                plugin.paint_notifications(painter, self.rect())
            elif plugin and hasattr(plugin, 'paint_activity'):
                plugin.paint_activity(painter, self.rect())
            elif plugin and hasattr(plugin, 'paint_weather'):
                plugin.paint_weather(painter, self.rect())

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._state == "collapsed":
            self._set_state("hover")
            self._expand()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._state in ("hover", "expanded"):
            self._hover_timer.start(200)

    def _on_hover_confirmed(self):
        self._hover_pending = False
        self._micro_expanded = False
        self._expand()

    # --- Proximity detection (micro-expand) ---
    def _check_mouse(self):
        if not self.isVisible() or self._is_hiding:
            return
        if self._hidden_by_fullscreen:
            self._check_toast_weather_hover()
            return

        cursor = QCursor.pos()
        geo = self.geometry()
        hot_zone = geo.adjusted(-5, -5, 5, 30)
        in_zone = hot_zone.contains(cursor)

        # Check toast/weather hover first
        if self._check_toast_weather_hover(in_zone):
            return

        # Check notifications
        notif_plugin = self._plugins.get('notifications')
        if notif_plugin and notif_plugin.is_showing():
            if not in_zone and self._is_expanded:
                self._is_expanded = False
                self._expand_progress = 0.0
                self._animate_collapse()
                notif_plugin._dismiss_toast()
            return

        # Normal proximity behavior - EXACT main branch logic
        if in_zone and not self._is_expanded and not self._hover_pending:
            self._hover_pending = True
            self._hover_timer.start(self._window_config.get('hover_delay', 200))
            if not self._micro_expanded:
                self._micro_expanded = True
                self._anim_to(self._micro_width, self._collapsed[1], 200, _inquad_ease)
        elif in_zone and self._is_expanded:
            pass  # Stay expanded
        elif not in_zone and self._hover_pending:
            self._hover_pending = False
            self._hover_timer.stop()
            self._micro_expanded = False
            self._animate_collapse()
        elif not in_zone and self._is_expanded:
            self._animate_collapse()

    def _check_toast_weather_hover(self, in_zone: bool = None) -> bool:
        """Check toast/weather hover. Returns True if handled."""
        if in_zone is None:
            cursor = QCursor.pos()
            geo = self.geometry()
            hot_zone = geo.adjusted(-5, -5, 5, 30)
            in_zone = hot_zone.contains(cursor)

        # Toast hover handling
        notif_plugin = self._plugins.get('notifications')
        if notif_plugin and notif_plugin.is_showing():
            if not in_zone and getattr(notif_plugin, '_toast_hovered', False):
                notif_plugin._toast_hovered = False
                notif_plugin._dismiss_toast()
                return True
            elif in_zone and not getattr(notif_plugin, '_toast_hovered', False):
                notif_plugin._toast_hovered = True
                duration = notif_plugin.config.get("toast_duration_with_buttons_ms", 30000) if notif_plugin._toast_buttons else notif_plugin.config.get("toast_duration_ms", 5000)
                notif_plugin._toast_timer.stop()
                notif_plugin._toast_timer.start(duration)
                return True

        # Weather hover handling
        weather_plugin = self._plugins.get('weather')
        if weather_plugin and weather_plugin.is_active():
            if in_zone and not getattr(weather_plugin, '_weather_hovered', False):
                weather_plugin._weather_hovered = True
                weather_plugin._weather_timer.stop()
                return True
            elif not in_zone and getattr(weather_plugin, '_weather_hovered', False):
                weather_plugin._weather_hovered = False
                weather_plugin._dismiss_weather()
                return True

        return False

    # --- Fullscreen detection ---
    def _check_fullscreen(self):
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd or hwnd == int(self.winId()):
            return

        if WIN32GUI_AVAILABLE:
            cls = win32gui.GetClassName(hwnd)
            if cls in ('Progman', 'WorkerW', 'SysListView32', '#32769'):
                return
        desktop = ctypes.windll.user32.GetDesktopWindow()
        if hwnd == desktop:
            return

        is_fullscreen = False

        placement = WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(placement)
        ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(placement))
        if placement.showCmd == SW_SHOWMAXIMIZED:
            is_fullscreen = True

        if not is_fullscreen:
            rect = RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
            if monitor:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(mi)
                ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
                fw = rect.right - rect.left
                fh = rect.bottom - rect.top
                mw = mi.rcMonitor.right - mi.rcMonitor.left
                mh = mi.rcMonitor.bottom - mi.rcMonitor.top
                if fw >= mw and fh >= mh:
                    is_fullscreen = True

        if is_fullscreen:
            if not self._hidden_by_fullscreen:
                self._hidden_by_fullscreen = True
                self._hover_pending = False
                self._hover_timer.stop()

                notif_plugin = self._plugins.get('notifications')
                toast_active = notif_plugin and notif_plugin.is_showing()
                weather_plugin = self._plugins.get('weather')
                weather_active = weather_plugin and weather_plugin.is_active()
                obs_plugin = self._plugins.get('obs')
                obs_active = obs_plugin and obs_plugin.get_obs_state() > 0

                if toast_active or weather_active or obs_active:
                    # Keep visible but note we're in dodge mode
                    self._is_expanded = True
                    self._expand_progress = 1.0
                else:
                    # Normal hide animation - EXACT main branch
                    self._anim.stop()
                    self._hover_animating = False
                    self._expand_progress = 0.0
                    self._is_expanded = False
                    self._is_hiding = True
                    self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                    w, h = self._collapsed
                    self._anim_to(int(w * 0.50), h, 175, _ease_incubic_outback, y_pos=-h)
        else:
            if self._hidden_by_fullscreen:
                self._hidden_by_fullscreen = False

                notif_plugin = self._plugins.get('notifications')
                toast_active = notif_plugin and notif_plugin.is_showing()
                weather_plugin = self._plugins.get('weather')
                weather_active = weather_plugin and weather_plugin.is_active()

                if toast_active or weather_active:
                    return

                w, h = self._collapsed
                self._is_expanded = False
                self._hover_pending = False
                self._anim.stop()
                self._expand_progress = 0.0
                self._hover_animating = False
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                screen = QApplication.primaryScreen().geometry()
                x_sq = (screen.width() - int(w * 0.75)) / 2.0
                self.setGeometry(int(x_sq), -h, int(w * 0.75), int(h))
                self.show()
                self._anim_to(w, h, 400, _outback_ease)

    # --- Animation helpers (EXACT main branch) ---
    def _anim_to(self, width, height, duration, ease_fn=None, y_pos=None, ease_wh=None):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - width) / 2.0
        y = self._base_margin_top if y_pos is None else y_pos
        self._anim_ease = ease_fn or (lambda p: p)
        self._anim_ease_wh = ease_wh
        self._anim_start = QRectF(self.geometry())
        self._anim_end = QRectF(x, y, width, height)
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._hover_animating = True
        self._anim.start()

    def _on_anim_step(self, t):
        if self._hover_animating:
            if self._is_expanded:
                self._expand_progress = t
            else:
                self._expand_progress = 1.0 - t
        
        t_pos = self._anim_ease(t)
        t_wh = self._anim_ease_wh(t) if self._anim_ease_wh else t_pos
        r = self._anim_start
        s = self._anim_end
        x = r.x() + (s.x() - r.x()) * t_pos
        y = r.y() + (s.y() - r.y()) * t_pos
        w = r.width() + (s.width() - r.width()) * t_wh
        h = r.height() + (s.height() - r.height()) * t_wh
        self.setGeometry(QRectF(x, y, w, h).toRect())

    def _on_anim_finished(self):
        self._anim_ease_wh = None
        if self._is_hiding:
            self._is_hiding = False
            self.hide()
            return
        if self._hover_animating:
            self._expand_progress = 1.0 if self._is_expanded else 0.0
            self._hover_animating = False
        if not self._is_expanded:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _expand(self):
        if self._is_expanded:
            return
        self._is_expanded = True
        self._hover_animating = True
        self._expand_progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        # EXACT main branch: _outback_ease for expand
        self._anim_to(*self._expanded, self._window_config.get('expand_duration', 500), _outback_ease)

    def _animate_collapse(self):
        self._is_expanded = False
        self._hover_animating = True
        self._expand_progress = 1.0
        self._hover_pending = False
        # EXACT main branch: _ease_incubic_outback for collapse
        self._anim_to(self._collapsed[0], self._collapsed[1], self._window_config.get('collapse_duration', 500), _ease_incubic_outback)

    def _reset_collapsed(self):
        self._is_expanded = False
        self._hover_pending = False
        self._expand_progress = 0.0
        self._hover_animating = False
        self._anim_ease_wh = None
        self._anim.stop()
        w, h = self._collapsed
        screen = QApplication.primaryScreen().geometry()
        x = int((screen.width() - w) / 2.0)
        self.setGeometry(x, int(self._base_margin_top), int(w), int(h))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def _collapse(self):
        if self._state == "collapsed":
            return
        self._set_state("collapsed")
        self._animate_collapse()

    def _set_state(self, state: str):
        old = self._state
        self._state = state
        self.registry.event_bus.publish(WindowStateChanged(state=state))

    def get_state(self) -> str:
        return self._state

    def property(self, name):
        """Override property for dynamic values."""
        if name == "_pulse_time":
            import time
            return time.time() * 3
        if name == "_hidden_by_fullscreen":
            return self._hidden_by_fullscreen
        if name == "_is_expanded":
            return self._is_expanded
        if name == "_is_hiding":
            return self._is_hiding
        return super().property(name)

    # --- Mouse event forwarding ---
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_move'):
                plugin.handle_mouse_move(pos)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        pos = event.position().toPoint()
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_press'):
                plugin.handle_mouse_press(pos)
            if hasattr(plugin, 'handle_click') and plugin.handle_click(pos):
                return

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pos = event.position().toPoint()
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_release'):
                plugin.handle_mouse_release(pos)