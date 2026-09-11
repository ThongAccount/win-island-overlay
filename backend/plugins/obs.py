from typing import Dict, Any, Optional
import ctypes
import ctypes.wintypes
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage
from PySide6.QtWidgets import QLabel

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus, OBSStateChanged, WindowStateChanged
from backend.core.overlay import OverlayWindow


# Structures from main branch
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
        
        # Data source only — overlay owns all rendering/animation state
        # Timers
        self._obs_timer: Optional[QTimer] = None
        self._obs_check_thread: Optional[threading.Thread] = None
        self._running = False
        
        # OBS icon
        self._obs_icon: Optional[QPixmap] = None

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

    def on_disable(self) -> None:
        self._running = False
        if self._obs_timer:
            self._obs_timer.stop()
        if self._notif_timer:
            self._notif_timer.stop()
        if self._obs_check_thread and self._obs_check_thread.is_alive():
            self._obs_check_thread.join(timeout=1.0)
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
            import cairosvg
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M12 8v8M8 12h8"/>
            </svg>'''
            png_bytes = cairosvg.svg2png(bytestring=svg.encode(), output_width=64, output_height=64)
            img = QImage.fromData(png_bytes)
            self._obs_icon = QPixmap.fromImage(img)
        except:
            # Fallback: draw programmatically
            self._obs_icon = self._generate_obs_icon()

    def _generate_obs_icon(self) -> QPixmap:
        """Generate OBS icon programmatically."""
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

    def _check_obs(self):
        """Check OBS status in background thread."""
        if self._obs_check_thread and self._obs_check_thread.is_alive():
            return
        self._obs_check_thread = threading.Thread(target=self._do_obs_check, daemon=True)
        self._obs_check_thread.start()

    def _do_obs_check(self):
        """Actual OBS process check (main branch implementation)."""
        try:
            TH32CS_SNAPPROCESS = 0x00000002
            kernel32 = ctypes.windll.kernel32
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            
            if snapshot == -1:
                return

            found = False
            recording = False
            obs_pid = 0
            try:
                entry = PROCESSENTRY32()
                entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
                if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                    while True:
                        name = entry.szExeFile.lower()
                        if name in ('obs64.exe', 'obs32.exe'):
                            found = True
                            obs_pid = entry.th32ProcessID
                        elif name in ('obs-ffmpeg-mux.exe', 'obs-ffmpeg-mux64.exe'):
                            recording = True
                        if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                            break
            finally:
                kernel32.CloseHandle(snapshot)

            new_state = 0
            if found:
                streaming = obs_pid > 0 and self._obs_has_connections(obs_pid)
                win = self._obs_check_window()
                if win['recording']:
                    recording = True
                if win['streaming']:
                    streaming = True
                if recording or streaming:
                    new_state = 2
                else:
                    new_state = 1

            # Post result to main thread
            QTimer.singleShot(0, lambda: self._on_obs_result(new_state, recording, streaming))
            
        except Exception as e:
            print(f"[obs] Check error: {e}")

    def _obs_has_connections(self, pid: int) -> bool:
        """Check if OBS has active TCP connections (streaming)."""
        try:
            iphlpapi = ctypes.windll.iphlpapi
            buf_size = ctypes.c_ulong(0)
            r = iphlpapi.GetExtendedTcpTable(None, ctypes.byref(buf_size), False, 2, TCP_TABLE_OWNER_PID_ALL, 0)
            if buf_size.value <= 0:
                return False
            buf = ctypes.create_string_buffer(buf_size.value)
            r = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(buf_size), False, 2, TCP_TABLE_OWNER_PID_ALL, 0)
            if r != 0:
                return False
            num_entries = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ulong)).contents.value
            row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
            count = 0
            for i in range(num_entries):
                offset = 4 + i * row_size
                row = MIB_TCPROW_OWNER_PID.from_buffer(buf, offset)
                if row.dwOwningPid == pid and row.dwState == MIB_TCP_STATE_ESTAB:
                    count += 1
                    if count >= 3:
                        return True
        except Exception:
            return False
        return False

    def _obs_check_window(self) -> Dict[str, bool]:
        """Check OBS window title for recording/streaming status."""
        try:
            user32 = ctypes.windll.user32
            result = {'recording': False, 'streaming': False}

            def enum_proc(hwnd, lparam):
                length = user32.GetWindowTextLengthW(hwnd) + 1
                if length <= 1:
                    return True
                buf = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(hwnd, buf, length)
                t = buf.value.lower()
                if any(x in t for x in ('obs studio', 'streamlabs obs', 'slobs')):
                    if 'rec' in t:
                        result['recording'] = True
                    if 'live' in t or 'streaming' in t:
                        result['streaming'] = True
                return True

            CB_TYPE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            cb = CB_TYPE(enum_proc)
            user32.EnumWindows(cb, 0)
            return result
        except Exception:
            return {'recording': False, 'streaming': False}

    def _on_obs_result(self, new_state: int, recording: bool, streaming: bool):
        """Handle OBS check result on main thread — overlay owns animations."""
        if not self._window:
            return

        old_state = self._obs_state
        if new_state == old_state:
            return

        self._obs_state = new_state
        if new_state > 0:
            self._obs_draw_state = new_state

        # Drive overlay shell/paint state (main-branch motions)
        if self.config.get("show_notifications", True):
            self._window.apply_obs_state(new_state)
        else:
            self._window._obs_state = new_state
            if new_state > 0:
                self._window._obs_draw_state = new_state
                self._window._obs_alpha = 1.0
            else:
                self._window._obs_alpha = 0.0
                self._window._obs_draw_state = 0
            self._window.update()

        self.registry.event_bus.publish(OBSStateChanged(
            recording=recording,
            streaming=streaming
        ))
