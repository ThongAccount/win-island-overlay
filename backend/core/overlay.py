from typing import Dict, Any, Optional
from PySide6.QtCore import Qt, QTimer, QRect, QRectF, QEasingCurve, QPropertyAnimation
from PySide6.QtCore import QEvent, QVariantAnimation, QCoreApplication, QPoint
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QCursor, QPen, QBrush, QRadialGradient
from PySide6.QtGui import QPixmap, QFontMetrics

import ctypes
import ctypes.wintypes
import os
import time

try:
    import win32gui
    WIN32GUI_AVAILABLE = True
except ImportError:
    WIN32GUI_AVAILABLE = False

from backend.core.plugin import PluginRegistry
from backend.core.events import EventBus, WindowStateChanged


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


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ('dwState', ctypes.c_ulong),
        ('dwLocalAddr', ctypes.c_ulong),
        ('dwLocalPort', ctypes.c_ulong),
        ('dwRemoteAddr', ctypes.c_ulong),
        ('dwRemotePort', ctypes.c_ulong),
        ('dwOwningPid', ctypes.c_ulong),
    ]


MIB_TCP_STATE_ESTAB = 5
TCP_TABLE_OWNER_PID_ALL = 5


# Main branch constants
MARGIN_TOP = 8.0
HOVER_DELAY = 200
EXPAND_DURATION = 500
COLLAPSE_DURATION = 500
MICRO_WIDTH = 240.0
OBS_EXTRA_WIDTH = 40.0
OBS_ANIM_DURATION = 500
NOTIFICATION_DURATION = 4000
NOTIFICATION_SIZE = (420, 72)
TOAST_DURATION = 5000
TOAST_DURATION_WITH_BUTTONS = 30000
WEATHER_DURATION = 6000

RECORDING_TEXT = "OBS Studio is currently recording your screen and audio"
STOPPED_TEXT = "OBS Studio has stopped recording your screen and audio"

MEDIA_EXTRA_WIDTH = 100.0
MEDIA_EXPANDED_HEIGHT = 72.0
MEDIA_PLAYING_TEXT = "Now Playing"
MEDIA_PAUSED_TEXT = "Paused"


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


# Events for plugin communication
class MediaResultEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())
    def __init__(self, result):
        super().__init__(self._type)
        self.result = result


class ToastNotifEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())
    def __init__(self, data):
        super().__init__(self._type)
        self.data = data  # dict: app_name, title, body, timestamp, icon_bytes, buttons


class WeatherEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())
    def __init__(self, data):
        super().__init__(self._type)
        self.data = data  # dict: temp, condition, location, feels_like, humidity, wind, aqi, aqi_level, icon


class OverlayWindow(QWidget):
    """Full overlay window with all rendering - matches main branch behavior.
    
    Plugins provide data via registry; overlay handles all painting, animations,
    and event routing. This separation matches the main branch's monolithic approach
    while allowing plugins to manage background threads and data.
    """

    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__()
        self.registry = registry
        self.config = config
        self._window_config = config.get('window', {}) or {
            'margin_top': MARGIN_TOP,
        }

        # Geometry
        self._base_collapsed = (200.0, 36.0)
        self._base_expanded = (420.0, 72.0)

        # State flags
        self._is_expanded = False
        self._hover_pending = False
        self._hidden_by_fullscreen = False
        
        # OBS state
        self._obs_state = 0  # 0=inactive, 1=idle, 2=recording/streaming
        self._obs_draw_state = 0  # lags behind _obs_state for fade-out
        self._obs_alpha = 0.0
        self._notification_active = False
        self._notification_type = 0  # 0=off, 1=recording started, 2=recording stopped
        self._notif_icon_progress = 0.0
        self._notif_text_alpha = 0.0

        # Media state
        self._media_state = 0  # 0=none, 1=paused, 2=playing
        self._media_title = ''
        self._media_artist = ''
        self._media_app = ''
        self._media_thumb = QPixmap()
        self._viz_bars = [0.0] * 8
        self._viz_targets = [0.0] * 8
        self._audio_levels = [0.0] * 8
        self._media_text_alpha = 1.0
        self._media_alpha = 0.0
        self._media_position = 0.0
        self._media_duration = 0.0
        self._pos_display = 0.0
        self._media_session = None
        self._media_position_fetch_time = 0.0
        self._media_thumb_key = ''
        self._media_thumb_cache = None
        self._hovered_btn = -1
        self._pressed_btn = -1
        self._expand_progress = 0.0
        self._hover_animating = False
        self._is_hiding = False
        self._title_scroll = 0.0
        self._media_loop = None
        self._media_was_active = False
        self._media_seq = 0
        self._micro_expanded = False
        self._split_progress = 0.0

        # Toast notification state
        self._toast_active = False
        self._toast_alpha = 0.0
        self._toast_app = ''
        self._toast_title = ''
        self._toast_body = ''
        self._toast_time = ''
        self._toast_icon = QPixmap()
        self._toast_buttons = []
        self._toast_image = QPixmap()
        self._toast_aumid = None
        self._toast_notif_id = None
        self._toast_hovered_btn = -1
        self._toast_pressed_btn = -1
        self._toast_hovered = False

        # Weather notification state
        self._weather_active = False
        self._weather_alpha = 0.0
        self._weather_temp = ''
        self._weather_condition = ''
        self._weather_location = ''
        self._weather_feels_like = ''
        self._weather_humidity = ''
        self._weather_wind = ''
        self._weather_aqi = ''
        self._weather_aqi_level = ''
        self._weather_icon = '☀️'
        self._weather_dismissed = False
        self._weather_hovered = False

        # Load OBS icon
        try:
            import cairosvg
            svg_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'obs_icon.svg')
            if os.path.exists(svg_path):
                with open(svg_path, 'rb') as f:
                    svg_data = f.read()
                    png_data = cairosvg.svg2png(bytestring=svg_data, output_width=64, output_height=64, dpi=96)
                self._obs_pixmap = QPixmap()
                self._obs_pixmap.loadFromData(png_data, 'PNG')
            else:
                self._obs_pixmap = self._generate_obs_icon()
        except Exception:
            self._obs_pixmap = self._generate_obs_icon()

        self._setup_window()
        self._setup_animations()
        self._setup_hover_delay()
        self._setup_proximity_detection()
        self._setup_fullscreen_detection()

        # Plugin references
        self._plugins: Dict[str, Any] = {}

    def _generate_obs_icon(self) -> QPixmap:
        """Generate OBS icon programmatically if SVG asset not available."""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(255, 0, 0, 255))
        painter.setBrush(QColor(255, 0, 0, 50))
        painter.drawEllipse(4, 4, 56, 56)
        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawLine(32, 16, 32, 48)
        painter.drawLine(16, 32, 48, 32)
        painter.end()
        return pixmap

    def register_plugin(self, name: str, plugin):
        """Register a plugin for data integration."""
        self._plugins[name] = plugin

    def _get_plugin(self, name: str):
        return self._plugins.get(name)

    # --- Window setup ---
    def _setup_window(self):
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

        self.setGeometry(0, 0, int(self._collapsed[0]), int(self._collapsed[1]))
        self._center()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        x = int((screen.width() - self._collapsed[0]) / 2.0)
        self.setGeometry(x, int(self._window_config.get('margin_top', MARGIN_TOP)), int(self._collapsed[0]), int(self._collapsed[1]))

    def showEvent(self, event):
        super().showEvent(event)
        self._center()
        self.registry.config['_window_ref'] = self

    # --- Event handling (plugin messages) ---
    def event(self, event):
        if event.type() == MediaResultEvent._type:
            self._on_media_result(event.result)
            return True
        if event.type() == ToastNotifEvent._type:
            self._on_toast(event.data)
            return True
        if event.type() == WeatherEvent._type:
            self._on_weather(event.data)
            return True
        return super().event(event)

    # --- Animation setup (main branch exact) ---
    def _setup_animations(self):
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._on_anim_step)
        self._anim.finished.connect(self._on_anim_finished)
        self._anim_start = QRectF()
        self._anim_end = QRectF()
        self._anim_ease = lambda p: p
        self._anim_ease_wh = None

        self._obs_alpha_anim = QPropertyAnimation(self, b"_obs_alpha_prop")
        self._obs_alpha_anim.valueChanged.connect(self._on_obs_alpha_step)
        self._obs_alpha_anim.finished.connect(self._on_obs_alpha_finished)

        self._obs_fade_timer = QTimer(self)
        self._obs_fade_timer.setSingleShot(True)
        self._obs_fade_timer.timeout.connect(self._start_obs_fade_in)

        self._notif_timer = QTimer(self)
        self._notif_timer.setSingleShift(True if False else True)
        self._notif_timer.timeout.connect(self._dismiss_notification)

        self._notif_progress_anim = QPropertyAnimation(self, b"_notif_icon_progress")
        self._notif_progress_anim.valueChanged.connect(self._on_notif_progress_step)
        self._notif_progress_anim.finished.connect(self._on_notif_progress_finished)

        self._notif_text_anim = QPropertyAnimation(self, b"_notif_text_alpha")
        self._notif_text_anim.valueChanged.connect(self._on_notif_text_step)

        self._notif_text_timer = QTimer(self)
        self._notif_text_timer.setSingleShot(True)
        self._notif_text_timer.timeout.connect(self._start_notif_text_fade_in)

        self._media_text_anim = QPropertyAnimation(self, b"_media_text_alpha")
        self._media_text_anim.valueChanged.connect(self._on_media_text_step)

        self._media_alpha_anim = QPropertyAnimation(self, b"_media_alpha")
        self._media_alpha_anim.valueChanged.connect(self._on_media_alpha_step)
        self._media_alpha_anim.finished.connect(self._on_media_alpha_finished)

        self._title_scroll_anim = QPropertyAnimation(self, b"_title_scroll")
        self._title_scroll_anim.valueChanged.connect(self._on_title_scroll_step)
        self._title_scroll_anim.finished.connect(self._on_title_scroll_finished)

        self._split_anim = QPropertyAnimation(self, b"_split_progress")
        self._split_anim.valueChanged.connect(self._on_split_step)

        self._toast_alpha_anim = QPropertyAnimation(self, b"_toast_alpha")
        self._toast_alpha_anim.valueChanged.connect(lambda v: setattr(self, '_toast_alpha', v) or self.update())

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._dismiss_toast)

    def _setup_hover_delay(self):
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_confirmed)

    # --- Properties (main branch exact) ---
    @property
    def _collapsed(self):
        extra = OBS_EXTRA_WIDTH if self._obs_state > 0 else 0
        if self._media_state > 0:
            extra += MEDIA_EXTRA_WIDTH
        return (self._base_collapsed[0] + extra, self._base_collapsed[1])

    @property
    def _expanded(self):
        extra = OBS_EXTRA_WIDTH if self._obs_state > 0 else 0
        h = self._base_expanded[1]
        if self._media_state > 0:
            extra += MEDIA_EXTRA_WIDTH
            h = MEDIA_EXPANDED_HEIGHT
        return (self._base_expanded[0] + extra, h)

    @property
    def _micro_width(self):
        extra = OBS_EXTRA_WIDTH if self._obs_state > 0 else 0
        if self._media_state > 0:
            extra += MEDIA_EXTRA_WIDTH
        return MICRO_WIDTH + extra

    def _move_to_top_center(self):
        screen = self.screen().availableGeometry()
        x = (screen.width() - self._collapsed[0]) // 2
        y = int(self._window_config.get('margin_top', MARGIN_TOP))
        self.setGeometry(x, y, int(self._collapsed[0]), int(self._collapsed[1]))

    # --- Animation handlers (main branch exact) ---
    def _on_title_scroll_step(self, v):
        self._title_scroll = v
        if self._media_state > 0:
            self.update()

    def _on_split_step(self, v):
        self._split_progress = v
        self.update()

    def _on_title_scroll_finished(self):
        if self._media_state > 0:
            self._start_title_scroll()

    def _start_title_scroll(self):
        self._title_scroll_anim.stop()
        self._title_scroll = 0.0
        self._title_scroll_anim.setDuration(12000)
        self._title_scroll_anim.setStartValue(0.0)
        self._title_scroll_anim.setEndValue(2.0)
        self._title_scroll_anim.start()

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

    def _on_obs_alpha_step(self, v):
        self._obs_alpha = v
        self.update()

    def _on_obs_alpha_finished(self):
        if self._obs_state == 0:
            self._obs_draw_state = 0
        self.update()

    def _run_obs_fade(self, target_alpha, duration):
        self._obs_alpha_anim.stop()
        self._obs_alpha_anim.setDuration(duration)
        self._obs_alpha_anim.setStartValue(self._obs_alpha)
        self._obs_alpha_anim.setEndValue(target_alpha)
        self._obs_alpha_anim.start()

    def _start_obs_fade_in(self):
        if self._obs_state > 0:
            self._run_obs_fade(1.0, int(OBS_ANIM_DURATION * 0.50))

    def _show_notification(self, notif_type):
        # Delegated to OBS plugin
        obs_plugin = self._plugins.get('obs')
        if obs_plugin:
            obs_plugin._show_notification(notif_type)

    def _dismiss_notification(self):
        self._notification_active = False
        self._notification_type = 0
        self._notif_icon_progress = 0.0
        if not self._is_expanded:
            self._dismiss_toast()

    def _on_notif_progress_step(self, v):
        self._notif_icon_progress = v
        self.update()

    def _on_notif_progress_finished(self):
        if not self._notif_timer.isActive():
            self._notification_active = False

    def _on_notif_text_step(self, v):
        self._notif_text_alpha = v
        self.update()

    def _start_notif_text_fade_in(self):
        if self._notif_text_anim:
            self._notif_text_anim.stop()
        self._notif_text_anim.setDuration(int(OBS_ANIM_DURATION * 0.50))
        self._notif_text_anim.setStartValue(self._notif_text_alpha)
        self._notif_text_anim.setEndValue(1.0)
        self._notif_text_anim.start()

    def _on_media_text_step(self, v):
        self._media_text_alpha = v
        self.update()

    def _on_media_alpha_step(self, v):
        self._media_alpha = v
        self.update()

    def _on_media_alpha_finished(self):
        if self._media_state == 0:
            self._media_title = ''
            self._media_artist = ''
            self.update()

    # --- Expansion/collapse (main branch exact) ---
    def _anim_to(self, width, height, duration, ease_fn=None, y_pos=None, ease_wh=None):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - width) / 2.0
        y = self._window_config.get('margin_top', MARGIN_TOP) if y_pos is None else y_pos
        self._anim_ease = ease_fn or (lambda p: p)
        self._anim_ease_wh = ease_wh
        self._anim_start = QRectF(self.geometry())
        self._anim_end = QRectF(x, y, width, height)
        self._anim.stop()
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_hover_confirmed(self):
        self._hover_pending = False
        self._micro_expanded = False
        self._expand()

    def _expand(self):
        if self._is_expanded:
            return
        self._is_expanded = True
        self._hover_animating = True
        self._expand_progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._anim_to(*self._expanded, EXPAND_DURATION, _outback_ease)

    def _animate_collapse(self):
        self._is_expanded = False
        self._hover_animating = True
        self._expand_progress = 1.0
        self._hover_pending = False
        self._anim_to(self._collapsed[0], self._collapsed[1], COLLAPSE_DURATION, _ease_inquad_outback)

    def _reset_collapsed(self):
        self._is_expanded = False
        self._hover_pending = False
        self._expand_progress = 0.0
        self._hover_animating = False
        self._title_scroll = 0.0
        self._is_hiding = False
        self._anim_ease_wh = None
        self._anim.stop()
        w, h = self._collapsed
        screen = QApplication.primaryScreen().geometry()
        x = int((screen.width() - w) / 2.0)
        self.setGeometry(x, int(self._window_config.get('margin_top', MARGIN_TOP)), int(w), int(h))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # --- Proximity detection ---
    def _setup_proximity_detection(self):
        self._hover_pending = False
        self._proximity_timer = QTimer(self)
        self._proximity_timer.timeout.connect(self._check_mouse)
        self._proximity_timer.start(100)

    def _check_mouse(self):
        if not self.isVisible() or self._is_hiding:
            return
        cursor = QCursor.pos()
        geo = self.geometry()

        if self._hidden_by_fullscreen and not self._toast_active:
            return

        hot_zone = geo.adjusted(-5, -5, 5, 30)
        in_zone = hot_zone.contains(cursor)

        if self._toast_active:
            if not in_zone and self._toast_hovered:
                self._toast_hovered = False
                self._dismiss_toast()
            elif in_zone and not self._toast_hovered:
                self._toast_hovered = True
                duration = TOAST_DURATION_WITH_BUTTONS if self._toast_buttons else TOAST_DURATION
                self._toast_timer.stop()
                self._toast_timer.start(duration)
            return
        if self._weather_active:
            if in_zone and not self._weather_hovered:
                self._weather_hovered = True
                self._weather_timer.stop()
            elif not in_zone and self._weather_hovered:
                self._weather_hovered = False
                self._dismiss_weather()
            return
        if self._notification_active:
            if not in_zone and self._is_expanded:
                self._is_expanded = False
                self._expand_progress = 0.0
                self._animate_collapse()
                if self._notif_timer.isActive():
                    self._notif_timer.stop()
                    self._dismiss_notification()
            return

        if in_zone and not self._is_expanded and not self._hover_pending:
            self._hover_pending = True
            self._hover_timer.start(HOVER_DELAY)
            if not self._micro_expanded:
                self._micro_expanded = True
                self._anim_to(self._micro_width, self._collapsed[1], 200, _inquad_ease)
        elif in_zone and self._is_expanded:
            pass
        elif not in_zone and self._hover_pending:
            self._hover_pending = False
            self._hover_timer.stop()
            self._micro_expanded = False
            self._animate_collapse()
        elif not in_zone and self._is_expanded:
            self._animate_collapse()

    # --- Fullscreen detection ---
    def _setup_fullscreen_detection(self):
        self._fullscreen_timer = QTimer(self)
        self._fullscreen_timer.timeout.connect(self._check_fullscreen)
        self._fullscreen_timer.start(500)

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

                if self._toast_active or self._notification_active:
                    self._is_expanded = True
                    self._expand_progress = 1.0
                else:
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

                if self._toast_active or self._notification_active:
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

    # --- Paint event (main branch exact) ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        pill = min(rect.height() / 2, 999.0)

        painter.setBrush(QColor(30, 30, 40, 255))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, pill, pill)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), pill, pill)

        if self._notification_active:
            self._paint_notification(painter, rect)
        elif self._toast_active or self._toast_alpha > 0.01:
            self._paint_toast(painter, rect)
        elif self._weather_active or self._weather_alpha > 0.01:
            self._paint_weather(painter, rect)
        
        self._paint_main_content(painter, rect)

    def _paint_notification(self, painter, rect):
        """Paint OBS notification (main branch exact)."""
        painter.save()
        cy = rect.center().y()
        icon_size = int(18 + 14 * self._notif_icon_progress)
        ix = 14
        painter.drawPixmap(ix, cy - icon_size // 2, icon_size, icon_size, self._obs_pixmap)
        painter.setOpacity(self._notif_text_alpha)
        text = RECORDING_TEXT if self._notification_type == 1 else STOPPED_TEXT
        painter.setFont(QFont('Segoe UI', 11))
        painter.setPen(QColor(220, 220, 230, 240))
        text_x = ix + icon_size + 12
        text_w = rect.width() - text_x - 40
        painter.drawText(QRect(text_x, 6, text_w, rect.height() - 12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.setOpacity(1.0)
        dot_size = int(8 + 4 * self._notif_icon_progress)
        dot_x = rect.right() - 30
        dot_y = cy - dot_size // 2
        gradient = QRadialGradient(dot_x + dot_size / 2, dot_y + dot_size / 2, dot_size / 2)
        if self._notification_type == 1:
            gradient.setColorAt(0.0, QColor(140, 255, 140, 240))
            gradient.setColorAt(1.0, QColor(30, 150, 30, 240))
        else:
            gradient.setColorAt(0.0, QColor(255, 240, 100, 240))
            gradient.setColorAt(1.0, QColor(200, 150, 20, 240))
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)
        painter.restore()

    def _paint_toast(self, painter, rect):
        """Paint toast notification (main branch exact)."""
        painter.save()
        painter.setOpacity(self._toast_alpha)
        ix = 12
        iy = 18
        icon_size = 36
        if not self._toast_icon.isNull():
            painter.drawPixmap(ix, iy, icon_size, icon_size, self._toast_icon)
        else:
            painter.setFont(QFont('Segoe UI', 18))
            painter.setPen(QColor(180, 180, 220, 220))
            painter.drawText(QRect(ix, iy, icon_size, icon_size), Qt.AlignmentFlag.AlignCenter, '🔔')

        tx = ix + icon_size + 10
        tw = rect.width() - tx - 12
        h = rect.height()

        row_h = 14
        y0 = 12

        painter.setFont(QFont('Segoe UI', 10))
        painter.setPen(QColor(180, 180, 220, 255))
        painter.drawText(QRect(tx, y0 - 2, tw - 50, row_h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._toast_app)
        painter.setFont(QFont('Segoe UI', 7))
        painter.setPen(QColor(160, 160, 200, 220))
        painter.drawText(QRect(tx, y0, tw - 24, row_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._toast_time)

        painter.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        painter.setPen(QColor(230, 230, 250, 240))
        painter.drawText(QRect(tx, y0 + row_h + 3, tw, row_h + 2), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._toast_title)

        painter.setFont(QFont('Segoe UI', 8))
        painter.setPen(QColor(200, 200, 230, 240))
        body_bottom = rect.height() - 12
        if self._toast_buttons:
            body_bottom = rect.height() - 34
        body_rect = QRect(tx, y0 + row_h * 2 + 5, tw, body_bottom - (y0 + row_h * 2 + 5))
        painter.drawText(body_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self._toast_body)

        if not self._toast_image.isNull():
            img_h = 60
            img_w = int(img_h * self._toast_image.width() / max(1, self._toast_image.height()))
            img_x = tx
            img_y = body_rect.bottom() + 6
            painter.drawPixmap(img_x, img_y, img_w, img_h, self._toast_image)

        if self._toast_buttons:
            btn_y = rect.height() - 22
            btn_w = min(80, (tw - (len(self._toast_buttons) - 1) * 6) // len(self._toast_buttons))
            for i, btn in enumerate(self._toast_buttons):
                label = btn['text'] if isinstance(btn, dict) else btn
                bx = tx + i * (btn_w + 6)
                br = QRect(bx, btn_y, btn_w, 18)
                if self._toast_pressed_btn == i:
                    painter.setBrush(QColor(100, 100, 180, 200))
                elif self._toast_hovered_btn == i:
                    painter.setBrush(QColor(70, 70, 140, 160))
                else:
                    painter.setBrush(QColor(50, 50, 100, 140))
                painter.setPen(QPen(QColor(150, 150, 220, 180), 1))
                painter.drawRoundedRect(br, 4, 4)
                painter.setPen(QColor(210, 210, 240, 230))
                painter.setFont(QFont('Segoe UI', 7))
                painter.drawText(br, Qt.AlignmentFlag.AlignCenter, label)

        painter.restore()

    def _paint_weather(self, painter, rect):
        """Paint weather notification (main branch exact)."""
        painter.save()
        painter.setOpacity(self._weather_alpha)

        ix = 16
        icon_size = 50
        iy = (rect.height() - icon_size) // 2
        painter.setFont(QFont('Segoe UI Emoji', 36))
        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawText(QRect(ix, iy, icon_size, icon_size), Qt.AlignmentFlag.AlignCenter, self._weather_icon)

        tx = ix + icon_size + 16
        tw = rect.width() // 2 - tx - 10

        left_group_height = 16 + 32 + 16
        left_start_y = (rect.height() - left_group_height) // 2

        painter.setFont(QFont('Segoe UI', 11, QFont.Weight.Bold))
        painter.setPen(QColor(180, 180, 220, 180))
        painter.drawText(QRect(tx, left_start_y, tw, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._weather_location)

        painter.setFont(QFont('Segoe UI', 28, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255, 255))
        temp_text = f"{self._weather_temp}°C"
        painter.drawText(QRect(tx, left_start_y + 16, tw, 32), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, temp_text)

        painter.setFont(QFont('Segoe UI', 12))
        painter.setPen(QColor(200, 200, 220, 200))
        painter.drawText(QRect(tx, left_start_y + 48, tw, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._weather_condition)

        right_margin = 20
        right_x = rect.width() // 2 + 20
        right_w = rect.width() - right_x - right_margin

        group_height = 14 + 5 + 14 + 5 + 14
        start_y = (rect.height() - group_height) // 2

        painter.setFont(QFont('Segoe UI', 11))
        painter.setPen(QColor(180, 180, 220, 180))

        painter.drawText(QRect(right_x, start_y, right_w, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"Feels {self._weather_feels_like}°")
        painter.drawText(QRect(right_x, start_y + 19, right_w, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"💧 {self._weather_humidity}%")
        painter.drawText(QRect(right_x, start_y + 38, right_w, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"💨 {self._weather_wind}")

        painter.restore()

    def _paint_main_content(self, painter, rect):
        """Paint OBS, media, toast, weather content - main branch exact."""
        # OBS recording/streaming status in pill
        if self._obs_draw_state > 0:
            if self._media_state > 0 and self._is_expanded:
                painter.setOpacity(self._obs_alpha)
                painter.drawPixmap(14, rect.center().y() - 9, 18, 18, self._obs_pixmap)
                painter.setOpacity(1.0)
            else:
                painter.setOpacity(self._obs_alpha)
                painter.drawPixmap(16, rect.center().y() - 9, 18, 18, self._obs_pixmap)
                painter.setOpacity(1.0)

        if self._obs_draw_state > 0 and (not self._media_state or self._expand_progress < 0.5):
            painter.setOpacity(self._obs_alpha)
            dot_size = 10 if self._obs_draw_state == 2 else 8
            dot_x = rect.right() - 24
            dot_y = rect.center().y() - dot_size // 2
            gradient = QRadialGradient(dot_x + dot_size / 2, dot_y + dot_size / 2, dot_size / 2)
            if self._obs_draw_state == 2:
                gradient.setColorAt(0.0, QColor(140, 255, 140, 240))
                gradient.setColorAt(1.0, QColor(30, 150, 30, 240))
            else:
                gradient.setColorAt(0.0, QColor(255, 240, 100, 240))
                gradient.setColorAt(1.0, QColor(200, 150, 20, 240))
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(dot_x, dot_y, dot_size, dot_size)
        elif self._expand_progress > 0.5 and self._obs_draw_state == 0:
            fade = (self._expand_progress - 0.5) * 2
            painter.setOpacity(fade)
            painter.setFont(QFont('Segoe UI', 11))
            painter.setPen(QColor(150, 150, 200, 220))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Nothing to see here!")
            painter.setOpacity(1.0)

        # Media rendering
        if (self._media_state > 0 or self._media_alpha > 0.01) and not self._notification_active and not self._toast_active and self._toast_alpha <= 0.01 and not self._weather_active and self._weather_alpha <= 0.01:
            cy = rect.center().y()
            b = self._expand_progress
            painter.setOpacity(1.0)

            collapsed_thumb_x = 16
            if self._obs_draw_state > 0:
                collapsed_thumb_x += 24

            layout = self._media_expanded_layout()
            text_x = layout['text_x']
            text_w = layout['text_w']
            text_top = layout['text_top']
            btn_rects = layout['btn_rects']
            thumb_rect = layout['thumb_rect']
            viz_left = layout['viz_left']

            painter.setOpacity(self._media_alpha)

            # Blended thumbnail
            ts = 14 + (24 - 14) * b
            thumb_x = collapsed_thumb_x + (thumb_rect.x() - collapsed_thumb_x) * b
            thumb_y = cy - ts / 2

            if not self._media_thumb.isNull():
                painter.drawPixmap(int(thumb_x), int(thumb_y), int(ts), int(ts), self._media_thumb)
            else:
                thumb_font = int(9 + (13 - 9) * b)
                painter.setFont(QFont('Segoe UI', thumb_font))
                painter.setPen(QColor(150, 150, 220, 240))
                painter.drawText(QRect(int(thumb_x), int(thumb_y), int(ts), int(ts)), Qt.AlignmentFlag.AlignCenter, '♪')

            # Blended title
            collapsed_title_x = int(collapsed_thumb_x + 14 + 5)
            title_x = collapsed_title_x + (text_x - collapsed_title_x) * b
            title_font = 8 + (10 - 8) * b
            if b < 0.5:
                title_w = int(rect.width() - title_x - 52)
            else:
                title_w = int(text_w)
            painter.setFont(QFont('Segoe UI', int(title_font), QFont.Weight.Bold))
            painter.setPen(QColor(230, 230, 250, 240))
            title_y = int(cy - 8 - 4 * b)
            if b > 0.3:
                title_y += 3
            title_rect = QRect(int(title_x), title_y, int(title_w), 16)
            fm = QFontMetrics(painter.font())
            full_w = fm.horizontalAdvance(self._media_title)
            if full_w > title_w:
                max_s = full_w - title_w + 30
                s = self._title_scroll
                if s < 1.0:
                    off = -max_s * s
                else:
                    off = -max_s * (2.0 - s)
                painter.save()
                painter.setClipRect(title_rect)
                painter.drawText(int(title_x + off), title_y, int(full_w + 50), 16,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._media_title)
                painter.restore()
            else:
                painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._media_title)

            # Visualizer
            bw2, gap2 = 2, 1
            viz_h = 6 + (10 - 6) * b
            viz_x_collapsed = rect.right() - 40
            viz_x = viz_x_collapsed + (viz_left - viz_x_collapsed) * b
            painter.setPen(Qt.NoPen)
            for i in range(8):
                h2 = max(1, int(viz_h * self._viz_bars[i]))
                painter.setBrush(QColor(100, 180 + i * 10, 255, 200))
                painter.drawRoundedRect(int(viz_x + i * (bw2 + gap2)), int(cy - h2), bw2, h2 * 2, 2, 2)

            painter.setOpacity(1.0)

            # Expanded-only elements
            if b > 0.3:
                fade = min(1.0, (b - 0.3) / 0.5) * self._media_alpha

                app_name = self._media_app.replace('.exe', '').capitalize() if self._media_app else ''
                painter.setOpacity(fade)
                app_font_size = 7 + int(b * 1.5)
                painter.setFont(QFont('Segoe UI', app_font_size))
                painter.setPen(QColor(150, 150, 200, 220))
                painter.drawText(text_x, text_top + 5, app_name)

                art_rect = QRect(text_x, text_top + 29, text_w, 14)
                artist_font_size = 7 + int(b * 1.5)
                painter.setFont(QFont('Segoe UI', artist_font_size))
                painter.setPen(QColor(180, 180, 220, 230))
                art_fm = QFontMetrics(painter.font())
                art_full = art_fm.horizontalAdvance(self._media_artist)
                if art_full > text_w:
                    art_max_s = art_full - text_w + 20
                    s = self._title_scroll
                    if s < 1.0:
                        art_off = -art_max_s * s
                    else:
                        art_off = -art_max_s * (2.0 - s)
                    painter.save()
                    painter.setClipRect(art_rect)
                    painter.drawText(int(text_x + art_off), text_top + 26, int(art_full + 30), 14,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._media_artist)
                    painter.restore()
                else:
                    painter.drawText(art_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._media_artist)

                for i, br in enumerate(btn_rects):
                    if self._pressed_btn == i:
                        fill = QColor(150, 150, 220, 160)
                        border = QColor(200, 200, 255, 200)
                    elif self._hovered_btn == i:
                        fill = QColor(135, 135, 200, 120)
                        border = QColor(180, 180, 240, 170)
                    else:
                        fill = QColor(120, 120, 180, 80)
                        border = QColor(160, 160, 220, 120)
                    painter.setOpacity(fade)
                    painter.setBrush(fill)
                    painter.setPen(QPen(border, 1))
                    painter.drawRoundedRect(br, 3, 3)
                bc1 = btn_rects[1].center()
                painter.setOpacity(fade)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(200, 200, 240, 200))
                if self._media_state == 2:
                    painter.drawRect(bc1.x() - 3, bc1.y() - 4, 2, 8)
                    painter.drawRect(bc1.x() + 1, bc1.y() - 4, 2, 8)
                else:
                    painter.drawPolygon([QPoint(bc1.x() - 3, bc1.y() - 4), QPoint(bc1.x() - 3, bc1.y() + 4), QPoint(bc1.x() + 4, bc1.y())])
                for bi in (0, 2):
                    bc2 = btn_rects[bi].center()
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(200, 200, 240, 200))
                    if bi == 0:
                        painter.drawPolygon([QPoint(bc2.x() - 3, bc2.y() - 4), QPoint(bc2.x() - 3, bc2.y() + 4), QPoint(bc2.x() + 4, bc2.y())])
                    else:
                        painter.drawPolygon([QPoint(bc2.x() + 3, bc2.y() - 4), QPoint(bc2.x() + 3, bc2.y() + 4), QPoint(bc2.x() - 4, bc2.y())])

                if self._obs_draw_state > 0:
                    painter.setOpacity(self._obs_alpha)
                    dot_size = 10 if self._obs_draw_state == 2 else 8
                    dot_x = layout['obs_dot_x']
                    dot_y = layout['obs_dot_y'] - dot_size // 2
                    gradient = QRadialGradient(dot_x, dot_y + dot_size / 2, dot_size / 2)
                    if self._obs_draw_state == 2:
                        gradient.setColorAt(0.0, QColor(140, 255, 140, 240))
                        gradient.setColorAt(1.0, QColor(30, 150, 30, 240))
                    else:
                        gradient.setColorAt(0.0, QColor(255, 240, 100, 240))
                        gradient.setColorAt(1.0, QColor(200, 150, 20, 240))
                    painter.setBrush(QBrush(gradient))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(dot_x - dot_size // 2, dot_y, dot_size, dot_size)

                painter.setOpacity(1.0)

    def _media_expanded_layout(self):
        r = self.rect()
        pad = 12
        h = r.height()
        island_cy = r.center().y()
        obs_icon_w = 24 if self._obs_draw_state > 0 else 0
        obs_dot_w = 16 if self._obs_draw_state > 0 else 0

        left = pad + obs_icon_w
        right = r.right() - pad
        ts = 28
        thumb_rect = QRect(left, island_cy - ts // 2, ts, ts)

        btn_size = 20
        btn_gap = 6
        btn_total = 3 * btn_size + 2 * btn_gap
        viz_w = 5 * 2 + 4 * 2
        gap = 10

        viz_left = right - obs_dot_w - 4 - viz_w
        buttons_left = viz_left - gap - btn_total
        btn_y = island_cy - btn_size // 2
        btn_rects = tuple(
            QRect(buttons_left + i * (btn_size + btn_gap), btn_y, btn_size, btn_size)
            for i in range(3)
        )
        viz_cy = island_cy

        text_x = thumb_rect.right() + 10
        text_right = buttons_left - gap
        text_w = text_right - text_x
        text_top = island_cy - 18

        pb_y = h - 12
        pb_w = max(40, right - obs_dot_w - 8 - text_x)
        progress_rect = QRect(text_x, pb_y, pb_w, 2)

        obs_dot_x = right - obs_dot_w // 2
        obs_dot_y = island_cy

        return {
            'thumb_rect': thumb_rect,
            'text_x': text_x,
            'text_top': text_top,
            'text_right': text_right,
            'text_w': text_w,
            'btn_rects': btn_rects,
            'viz_left': viz_left,
            'viz_cy': viz_cy,
            'progress_rect': progress_rect,
            'progress_hit_rect': progress_rect.adjusted(0, -10, 0, 8),
            'obs_dot_x': obs_dot_x,
            'obs_dot_y': obs_dot_y,
        }

    # --- OBS state management (called by OBS plugin) ---
    def _obs_alpha_prop(self, value):
        """Property setter for QPropertyAnimation."""
        self._obs_alpha = value
        self.update()

    def _notif_icon_progress(self, value):
        self._notif_icon_progress = value
        self.update()

    def _notif_text_alpha(self, value):
        self._notif_text_alpha = value
        self.update()

    def _media_text_alpha(self, value):
        self._media_text_alpha = value
        self.update()

    def _media_alpha(self, value):
        self._media_alpha = value
        self.update()

    def _title_scroll(self, value):
        self._title_scroll = value
        self.update()

    def _split_progress(self, value):
        self._split_progress = value
        self.update()

    def _toast_alpha(self, value):
        self._toast_alpha = value
        self.update()

    # --- Media handlers ---
    def _on_media_result(self, result):
        """Handle media result from SMTC plugin (called via event)."""
        # Publish to media plugin
        media_plugin = self._plugins.get('media')
        if media_plugin:
            media_plugin._on_media_result(result)

    def _dismiss_toast(self):
        self._toast_active = False
        self._toast_alpha = 0.0
        self._toast_buttons = []
        self._toast_pressed_btn = -1
        self._toast_hovered_btn = -1
        self._toast_hovered = False
        self.update()

    def _dismiss_weather(self):
        self._weather_alpha = 0.0
        self._weather_active = False
        self.update()

    def _do_media_action(self, action, seek_seconds=None):
        """Delegate to media plugin."""
        media_plugin = self._plugins.get('media')
        if media_plugin:
            media_plugin.do_action(action, seek_seconds)

    def _btn_at(self, pos):
        layout = self._media_expanded_layout()
        for i, rect in enumerate(layout['btn_rects']):
            if rect.contains(pos):
                return i
        return -1

    def _toast_btn_at(self, pos):
        if not self._toast_buttons or not self._toast_active:
            return -1
        rect = self.rect()
        btn_count = len(self._toast_buttons)
        btn_w = min(80, (rect.width() - 100) // btn_count)
        btn_y = rect.height() - 22
        for i in range(btn_count):
            bx = rect.width() // 2 - (btn_count * (btn_w + 6)) // 2 + i * (btn_w + 6)
            br = QRect(bx, btn_y, btn_w, 18)
            if br.contains(pos):
                return i
        return -1

    def _launch_app(self, aumid):
        try:
            import subprocess
            subprocess.Popen(['explorer.exe', f'shell:AppsFolder\\{aumid}'], shell=True)
        except Exception:
            pass

    def _rehide_toast(self):
        if not self._hidden_by_fullscreen or self._toast_active:
            return
        self._is_hiding = True

    # --- Mouse events (main branch exact) ---
    def mousePressEvent(self, event):
        pos = event.position().toPoint()
        if self._toast_active:
            btn = self._toast_btn_at(pos)
            if btn >= 0:
                self._toast_pressed_btn = btn
                self.update()
                return
        if self._media_state == 0 or not self._media_session or not self._is_expanded:
            super().mousePressEvent(event)
            return
        btn = self._btn_at(pos)
        if btn >= 0:
            self._pressed_btn = btn
            self.update()

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        if self._toast_pressed_btn >= 0:
            if self._toast_btn_at(pos) == self._toast_pressed_btn:
                self._dismiss_toast()
            self._toast_pressed_btn = -1
            self.update()
            return
        if self._pressed_btn >= 0:
            layout_btns = self._media_expanded_layout()['btn_rects']
            if layout_btns[self._pressed_btn].contains(pos):
                if self._pressed_btn == 1:
                    action = 'pause' if self._media_state == 2 else 'play'
                    self._do_media_action(action)
                elif self._pressed_btn == 0:
                    self._do_media_action('prev')
                elif self._pressed_btn == 2:
                    self._do_media_action('next')
            self._pressed_btn = -1
            self.update()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._toast_active:
            hovered = self._toast_btn_at(pos)
            if hovered != self._toast_hovered_btn:
                self._toast_hovered_btn = hovered
                self.update()
        if self._media_state == 0 or not self._is_expanded:
            super().mouseMoveEvent(event)
            return
        hovered = self._btn_at(pos)
        if hovered != self._hovered_btn:
            self._hovered_btn = hovered
            self.update()
        super().mouseMoveEvent(event)
        # Also forward to plugins
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_move'):
                plugin.handle_mouse_move(pos)

    def leaveEvent(self, event):
        if self._hovered_btn >= 0 or self._pressed_btn >= 0:
            self._hovered_btn = -1
            self._pressed_btn = -1
            self.update()
        
        if self._media_loop and self._is_expanded:
            import asyncio
            async def verify_state():
                try:
                    await asyncio.sleep(0.3)
                    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
                    mgr = await GlobalSystemMediaTransportControlsSessionManager.request_async()
                    media_plugin = self._plugins.get('media')
                    if media_plugin and media_plugin._media_loop:
                        await media_plugin._query_and_post(media_plugin._media_loop, mgr, False)
                except:
                    pass
            if self._media_loop:
                asyncio.run_coroutine_threadsafe(verify_state(), self._media_loop)
        
        super().leaveEvent(event)

    def property(self, name):
        """Override property for dynamic values."""
        if name == "_pulse_time":
            return time.time() * 3
        if name == "_hidden_by_fullscreen":
            return self._hidden_by_fullscreen
        if name == "_is_expanded":
            return self._is_expanded
        if name == "_is_hiding":
            return self._is_hiding
        if name == "_notification_active":
            return self._notification_active
        if name == "_notification_type":
            return self._notification_type
        if name == "_toast_active":
            return self._toast_active
        if name == "_weather_active":
            return self._weather_active
        return super().property(name)

    def get_state(self) -> str:
        return self._state if hasattr(self, '_state') else ('expanded' if self._is_expanded else 'collapsed')

    @property
    def _state(self):
        return 'expanded' if self._is_expanded else 'collapsed'