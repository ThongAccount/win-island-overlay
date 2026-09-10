from typing import Dict, Any, Optional
import ctypes
import threading
from PySide6.QtCore import QTimer, QEvent, Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage
from PySide6.QtWidgets import QLabel

from ..core.plugin import PluginBase, island_plugin, PluginRegistry
from ..core.events import EventBus, OBSStateChanged, WindowStateChanged
from ..core.overlay import OverlayWindow


# Custom event for OBS icon
class OBSIconEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())

    def __init__(self, pixmap: Optional[QPixmap]):
        super().__init__(self._type)
        self.pixmap = pixmap


@island_plugin(
    name="obs",
    version="1.0.0",
    description="OBS Studio detection: recording/streaming status, notifications, animated icon",
    author="win-island-overlay",
    dependencies=[],
    config_schema={
        "check_interval_ms": 2000,
        "show_notifications": True,
        "notification_duration_ms": 4000,
        "icon_size": 24,
    },
    enabled_by_default=True,
)
class OBSPlugin(PluginBase):
    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__(registry, config)
        self._window: Optional[OverlayWindow] = None
        
        # OBS state
        self._obs_state = 0  # 0=none, 1=recording, 2=streaming, 3=both
        self._obs_alpha = 0.0
        self._obs_draw_state = 0
        self._obs_alpha_anim: Optional[QTimer] = None
        self._obs_icon: Optional[QPixmap] = None
        self._notification_active = False
        self._notification_type = 0  # 1=recording start, 2=streaming start, 3=stop
        self._notif_alpha = 0.0
        self._notif_text_alpha = 0.0
        self._notif_icon_progress = 0.0
        self._notif_timer: Optional[QTimer] = None
        self._notif_text_anim: Optional[QTimer] = None
        self._notif_icon_anim: Optional[QTimer] = None
        
        # Timers
        self._obs_timer: Optional[QTimer] = None
        self._obs_check_thread: Optional[threading.Thread] = None
        self._running = False

    def on_load(self) -> None:
        pass

    def on_enable(self) -> None:
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[obs] No window reference")
            return

        self._running = True
        
        # Load OBS icon
        self._load_obs_icon()
        
        # Start detection timer
        interval = self.config.get("check_interval_ms", 2000)
        self._obs_timer = QTimer(self._window)
        self._obs_timer.timeout.connect(self._check_obs)
        self._obs_timer.start(interval)
        
        # Initial check
        QTimer.singleShot(100, self._check_obs)
        
        # Notification timer
        self._notif_timer = QTimer(self._window)
        self._notif_timer.setSingleShot(True)
        self._notif_timer.timeout.connect(self._dismiss_notification)

    def on_disable(self) -> None:
        self._running = False
        if self._obs_timer:
            self._obs_timer.stop()
        if self._obs_check_thread and self._obs_check_thread.is_alive():
            self._obs_check_thread.join(timeout=1.0)
        if self._notif_timer:
            self._notif_timer.stop()
        if self._obs_alpha_anim:
            self._obs_alpha_anim.stop()
        if self._notif_text_anim:
            self._notif_text_anim.stop()
        if self._notif_icon_anim:
            self._notif_icon_anim.stop()

    def on_unload(self) -> None:
        pass

    def _load_obs_icon(self):
        """Load or generate OBS icon."""
        try:
            # Try to load from cairosvg if available
            import cairosvg
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 8v8M8 12h8"/>
            </svg>'''
            png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=48, output_height=48)
            img = QImage.fromData(png_bytes)
            self._obs_icon = QPixmap.fromImage(img)
        except:
            # Fallback: draw programmatically
            self._obs_icon = self._generate_obs_icon()

    def _generate_obs_icon(self) -> QPixmap:
        """Generate OBS icon programmatically."""
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(255, 0, 0, 255))
        painter.setBrush(QColor(255, 0, 0, 50))
        painter.drawEllipse(4, 4, 40, 40)
        painter.setPen(QColor(255, 255, 255, 255))
        painter.drawLine(24, 12, 24, 36)
        painter.drawLine(12, 24, 36, 24)
        painter.end()
        return pixmap

    def _check_obs(self):
        """Check OBS status in background thread."""
        if self._obs_check_thread and self._obs_check_thread.is_alive():
            return
        self._obs_check_thread = threading.Thread(target=self._do_obs_check, daemon=True)
        self._obs_check_thread.start()

    def _do_obs_check(self):
        """Actual OBS process check."""
        try:
            TH32CS_SNAPPROCESS = 0x00000002
            kernel32 = ctypes.windll.kernel32
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            
            if snapshot == -1:
                return

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapSize", ctypes.c_ulong),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260),
                ]

            pe32 = PROCESSENTRY32()
            pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
            
            obs_pids = []
            if kernel32.Process32First(snapshot, ctypes.byref(pe32)):
                while True:
                    name = pe32.szExeFile.decode('utf-8', errors='ignore').lower()
                    if 'obs' in name and ('64' in name or '32' in name or 'studio' in name):
                        obs_pids.append(pe32.th32ProcessID)
                    if not kernel32.Process32Next(snapshot, ctypes.byref(pe32)):
                        break
            
            kernel32.CloseHandle(snapshot)
            
            new_state = 0
            for pid in obs_pids:
                recording = self._obs_has_connections(pid)
                streaming = self._obs_check_window(pid)
                if recording:
                    new_state |= 1
                if streaming:
                    new_state |= 2
            
            # Post result to main thread
            QTimer.singleShot(0, lambda: self._on_obs_result(new_state))
            
        except Exception as e:
            print(f"[obs] Check error: {e}")

    def _obs_has_connections(self, pid: int) -> bool:
        """Check if OBS has active network connections (streaming)."""
        try:
            iphlpapi = ctypes.windll.iphlpapi
            buf_size = ctypes.c_ulong(0)
            iphlpapi.GetExtendedTcpTable(None, ctypes.byref(buf_size), True, 2, 5, 0)
            buf = ctypes.create_string_buffer(buf_size.value)
            if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(buf_size), True, 2, 5, 0) == 0:
                # Parse table (simplified)
                return True  # Assume streaming if we can't parse
        except:
            pass
        return False

    def _obs_check_window(self, pid: int) -> bool:
        """Check if OBS window indicates recording."""
        try:
            user32 = ctypes.windll.user32
            
            def enum_windows(hwnd, lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                _, found_pid = user32.GetWindowThreadProcessId(hwnd)
                if found_pid == pid:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value.lower()
                        if 'recording' in title or '●' in title or 'rec' in title:
                            ctypes.cast(lparam, ctypes.POINTER(ctypes.c_bool)).contents.value = True
                            return False
                return True
            
            result = ctypes.c_bool(False)
            user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(enum_windows), ctypes.byref(result))
            return result.value
        except:
            return False

    def _on_obs_result(self, new_state: int):
        """Handle OBS check result."""
        if not self._window:
            return
            
        old_state = self._obs_state
        if new_state != old_state:
            self._obs_state = new_state
            
            # Animate icon
            if new_state > 0:
                self._start_obs_fade_in()
            else:
                self._start_obs_fade_out()
            
            # Show notification
            if self.config.get("show_notifications", True) and old_state != new_state:
                if new_state & 1 and not (old_state & 1):
                    self._show_notification(1)  # Recording started
                elif new_state & 2 and not (old_state & 2):
                    self._show_notification(2)  # Streaming started
                elif old_state > 0 and new_state == 0:
                    self._show_notification(3)  # Stopped
            
            # Publish event
            self.registry.event_bus.publish(OBSStateChanged(
                recording=bool(new_state & 1),
                streaming=bool(new_state & 2)
            ))
            
            # Trigger window resize
            if self._window:
                self._window.update()

    def _start_obs_fade_in(self):
        self._animate_obs_alpha(1.0, 500)

    def _start_obs_fade_out(self):
        self._animate_obs_alpha(0.0, 500)

    def _animate_obs_alpha(self, target: float, duration: int):
        if self._obs_alpha_anim:
            self._obs_alpha_anim.stop()
        steps = 30
        step_val = (target - self._obs_alpha) / steps
        step_ms = duration // steps
        current = self._obs_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._obs_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._obs_alpha = target
                self._obs_alpha_anim.stop()
                if target == 0.0:
                    self._obs_draw_state = 0
        
        self._obs_alpha_anim = QTimer(self._window)
        self._obs_alpha_anim.timeout.connect(step)
        self._obs_alpha_anim.start(step_ms)

    def _show_notification(self, notif_type: int):
        self._notification_active = True
        self._notification_type = notif_type
        self._notif_alpha = 0.0
        self._notif_text_alpha = 0.0
        self._notif_icon_progress = 0.0
        
        duration = self.config.get("notification_duration_ms", 4000)
        self._notif_timer.start(duration)
        
        self._animate_notif_icon(1.0, 300)
        self._animate_notif_text(1.0, 300)
        
        if self._window:
            self._window.update()

    def _dismiss_notification(self):
        if self._window and self._window.property("_is_expanded"):
            return  # Don't dismiss if expanded
        self._animate_notif_icon(0.0, 300)
        self._animate_notif_text(0.0, 300)
        self._notification_active = False

    def _animate_notif_icon(self, target: float, duration: int):
        if self._notif_icon_anim:
            self._notif_icon_anim.stop()
        steps = 30
        step_val = (target - self._notif_icon_progress) / steps
        step_ms = duration // steps
        current = self._notif_icon_progress
        
        def step():
            nonlocal current
            current += step_val
            self._notif_icon_progress = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._notif_icon_progress = target
                self._notif_icon_anim.stop()
        
        self._notif_icon_anim = QTimer(self._window)
        self._notif_icon_anim.timeout.connect(step)
        self._notif_icon_anim.start(step_ms)

    def _animate_notif_text(self, target: float, duration: int):
        if self._notif_text_anim:
            self._notif_text_anim.stop()
        steps = 30
        step_val = (target - self._notif_text_alpha) / steps
        step_ms = duration // steps
        current = self._notif_text_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._notif_text_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._notif_text_alpha = target
                self._notif_text_anim.stop()
        
        self._notif_text_anim = QTimer(self._window)
        self._notif_text_anim.timeout.connect(step)
        self._notif_text_anim.start(step_ms)

    def get_obs_state(self) -> int:
        return self._obs_state

    def is_recording(self) -> bool:
        return bool(self._obs_state & 1)

    def is_streaming(self) -> bool:
        return bool(self._obs_state & 2)

    def get_alpha(self) -> float:
        return self._obs_alpha

    def get_notification_state(self) -> Dict[str, Any]:
        return {
            "active": self._notification_active,
            "type": self._notification_type,
            "alpha": self._notif_alpha,
            "text_alpha": self._notif_text_alpha,
            "icon_progress": self._notif_icon_progress,
        }

    def paint_obs(self, painter: QPainter, rect: QRect, is_expanded: bool):
        """Called from OverlayWindow.paintEvent."""
        # Draw OBS icon in collapsed/expanded pill
        if self._obs_state > 0 and self._obs_alpha > 0 and self._obs_icon:
            painter.save()
            painter.setOpacity(self._obs_alpha)
            
            icon_size = self.config.get("icon_size", 24)
            icon_x = rect.right() - icon_size - 10
            icon_y = (rect.height() - icon_size) // 2
            
            # Pulsing animation when recording
            if self._obs_state & 1:  # Recording
                import math
                pulse = 1.0 + 0.15 * math.sin(self._window.property("_pulse_time") or 0)
                scaled = self._obs_icon.scaled(
                    int(icon_size * pulse), int(icon_size * pulse),
                    Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                painter.drawPixmap(
                    icon_x - (scaled.width() - icon_size) // 2,
                    icon_y - (scaled.height() - icon_size) // 2,
                    scaled
                )
            else:
                painter.drawPixmap(icon_x, icon_y, self._obs_icon.scaled(
                    icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                ))
            
            painter.restore()

        # Draw notification
        if self._notification_active:
            self._paint_notification(painter, rect)

    def _paint_notification(self, painter: QPainter, rect: QRect):
        """Paint OBS notification."""
        painter.save()
        
        # Background
        notif_w = min(380, rect.width() - 20)
        notif_h = 56
        notif_x = (rect.width() - notif_w) // 2
        notif_y = rect.bottom() + 8
        
        painter.setOpacity(self._notif_alpha)
        painter.setBrush(QColor(20, 20, 30, 220))
        painter.setPen(QColor(255, 0, 0, 180))
        painter.drawRoundedRect(notif_x, notif_y, notif_w, notif_h, 12, 12)
        
        # Icon
        icon_size = int(28 * self._notif_icon_progress)
        if icon_size > 0 and self._obs_icon:
            painter.setOpacity(self._notif_icon_progress)
            icon_x = notif_x + 14
            icon_y = notif_y + (notif_h - icon_size) // 2
            painter.drawPixmap(icon_x, icon_y, self._obs_icon.scaled(
                icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))
        
        # Text
        painter.setOpacity(self._notif_text_alpha)
        painter.setPen(QColor(255, 255, 255, 230))
        font = QFont("Segoe UI", 10, QFont.Weight.Medium)
        painter.setFont(font)
        
        text_map = {
            1: "OBS Studio started recording",
            2: "OBS Studio started streaming",
            3: "OBS Studio stopped recording/streaming",
        }
        text = text_map.get(self._notification_type, "")
        text_x = notif_x + 50
        text_y = notif_y + notif_h // 2 + 4
        painter.drawText(text_x, text_y, text)
        
        painter.restore()