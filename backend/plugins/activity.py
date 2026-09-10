from typing import Dict, Any, Optional, Callable
import ctypes
import threading
import time
from dataclasses import dataclass, field
from PySide6.QtCore import QTimer, QEvent, Qt
from PySide6.QtWidgets import QLabel

from ..core.plugin import PluginBase, island_plugin, PluginRegistry
from ..core.events import EventBus, ForegroundWindowChanged, ConfigChanged
from ..core.overlay import OverlayWindow


# Custom event for foreground window change
class ForegroundEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())

    def __init__(self, hwnd: int, title: str, class_name: str, process_name: str):
        super().__init__(self._type)
        self.hwnd = hwnd
        self.title = title
        self.class_name = class_name
        self.process_name = process_name


@dataclass
class AppProfile:
    """Profile configuration for an app/context."""
    name: str
    match: Dict[str, Any]  # process, title_contains, class_contains
    plugins: Dict[str, bool]  # plugin_name -> enabled
    window_config: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = more specific


# Built-in profiles
BUILTIN_PROFILES = [
    AppProfile(
        name="coding",
        match={
            "process_contains": ["code", "devenv", "pycharm", "idea", "vim", "nvim", "emacs", "sublime", "notepad++"],
            "title_contains": ["visual studio", "jetbrains", "vim", "nvim"],
        },
        plugins={
            "greeting": False,
            "media": True,
            "obs": True,
            "notifications": True,
            "activity": True,
        },
        window_config={"expanded_width": 520},
        priority=10,
    ),
    AppProfile(
        name="gaming",
        match={
            "process_contains": ["steam", "epicgames", "battle.net", "origin", "riot", "valorant", "csgo", "dota2", "overwatch", "league"],
            "class_contains": ["SDL_app", "UnityWndClass", "UnrealEngine"],
        },
        plugins={
            "greeting": False,
            "media": True,
            "obs": True,
            "notifications": False,  # Suppress notifications while gaming
            "activity": True,
        },
        window_config={"expanded_width": 400, "height": 40},
        priority=10,
    ),
    AppProfile(
        name="meeting",
        match={
            "process_contains": ["teams", "zoom", "meet", "webex", "discord", "slack"],
            "title_contains": ["meeting", "call", "meet"],
        },
        plugins={
            "greeting": False,
            "media": False,
            "obs": True,
            "notifications": True,
            "activity": True,
        },
        window_config={"expanded_width": 480},
        priority=10,
    ),
    AppProfile(
        name="media",
        match={
            "process_contains": ["chrome", "firefox", "edge", "brave", "vlc", "mpv", "spotify", "music"],
            "title_contains": ["youtube", "netflix", "twitch", "spotify", "music"],
        },
        plugins={
            "greeting": False,
            "media": True,
            "obs": True,
            "notifications": True,
            "activity": True,
        },
        window_config={"expanded_width": 560},
        priority=5,
    ),
    AppProfile(
        name="terminal",
        match={
            "process_contains": ["cmd", "powershell", "pwsh", "wt", "terminal", "mintty", "conhost"],
            "class_contains": ["ConsoleWindowClass", "CASCADIA", "WindowsTerminal"],
        },
        plugins={
            "greeting": True,
            "media": False,
            "obs": True,
            "notifications": True,
            "activity": True,
        },
        window_config={"expanded_width": 400},
        priority=5,
    ),
    AppProfile(
        name="browser",
        match={
            "process_contains": ["chrome", "firefox", "edge", "brave", "safari", "opera", "vivaldi"],
        },
        plugins={
            "greeting": False,
            "media": True,
            "obs": True,
            "notifications": True,
            "activity": True,
        },
        window_config={"expanded_width": 520},
        priority=1,
    ),
]


@island_plugin(
    name="activity",
    version="1.0.0",
    description="Foreground window detection → context inference → auto-profile switching",
    author="win-island-overlay",
    dependencies=[],
    config_schema={
        "check_interval_ms": 500,
        "profiles": {},  # User-defined profiles (merged with built-in)
        "auto_switch": True,
        "notify_on_switch": True,
        "default_profile": "default",
    },
    enabled_by_default=True,
)
class ActivityPlugin(PluginBase):
    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__(registry, config)
        self._window: Optional[OverlayWindow] = None
        
        # State
        self._current_hwnd = 0
        self._current_title = ""
        self._current_class = ""
        self._current_process = ""
        self._current_profile: Optional[AppProfile] = None
        self._profiles: Dict[str, AppProfile] = {}
        self._default_profile_name = config.get("default_profile", "default")
        
        # Timers
        self._check_timer: Optional[QTimer] = None
        self._check_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Callbacks
        self._on_profile_change: Optional[Callable[[str, str], None]] = None

    def on_load(self) -> None:
        self._load_profiles()

    def on_enable(self) -> None:
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[activity] No window reference")
            return

        self._running = True
        
        interval = self.config.get("check_interval_ms", 500)
        self._check_timer = QTimer(self._window)
        self._check_timer.timeout.connect(self._check_foreground)
        self._check_timer.start(interval)
        
        # Initial check
        QTimer.singleShot(100, self._check_foreground)
        
        # Subscribe to config changes
        self._unsub_config = self.registry.event_bus.subscribe(
            ConfigChanged, self._on_config_changed
        )

    def on_disable(self) -> None:
        self._running = False
        if self._check_timer:
            self._check_timer.stop()
        if self._check_thread and self._check_thread.is_alive():
            self._check_thread.join(timeout=1.0)
        if hasattr(self, '_unsub_config'):
            self._unsub_config()

    def on_unload(self) -> None:
        pass

    def _load_profiles(self):
        """Load built-in and user profiles."""
        # Built-in
        for profile in BUILTIN_PROFILES:
            self._profiles[profile.name] = profile
        
        # User profiles from config
        user_profiles = self.config.get("profiles", {})
        for name, data in user_profiles.items():
            self._profiles[name] = AppProfile(
                name=name,
                match=data.get("match", {}),
                plugins=data.get("plugins", {}),
                window_config=data.get("window_config", {}),
                priority=data.get("priority", 0),
            )

    def _on_config_changed(self, event: ConfigChanged):
        if event.plugin_name == "activity" and event.key == "profiles":
            self._load_profiles()
            # Re-evaluate current window
            QTimer.singleShot(0, self._check_foreground)

    def _check_foreground(self):
        """Check foreground window in background thread."""
        if self._check_thread and self._check_thread.is_alive():
            return
        self._check_thread = threading.Thread(target=self._do_foreground_check, daemon=True)
        self._check_thread.start()

    def _do_foreground_check(self):
        """Get foreground window info."""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            
            hwnd = user32.GetForegroundWindow()
            if not hwnd or hwnd == self._current_hwnd:
                # Still same window, but check if title changed
                if hwnd == self._current_hwnd:
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buff, length + 1)
                        new_title = buff.value
                        if new_title != self._current_title:
                            self._current_title = new_title
                            QTimer.singleShot(0, lambda: self._on_foreground(hwnd, new_title, self._current_class, self._current_process))
                return
            
            if hwnd == int(self._window.winId()) if self._window else False:
                return  # Ignore our own window
            
            # Get window title
            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
            
            # Get class name
            class_name = ""
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            class_name = class_buff.value
            
            # Get process name
            _, pid = user32.GetWindowThreadProcessId(hwnd)
            process_name = ""
            if pid:
                h_process = kernel32.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ
                if h_process:
                    try:
                        exe_buff = ctypes.create_unicode_buffer(1024)
                        size = ctypes.c_ulong(1024)
                        if psapi.GetModuleFileNameExW(h_process, 0, exe_buff, size):
                            import os
                            process_name = os.path.basename(exe_buff.value).lower()
                    finally:
                        kernel32.CloseHandle(h_process)
            
            # Post to main thread
            QTimer.singleShot(0, lambda: self._on_foreground(hwnd, title, class_name, process_name))
            
        except Exception as e:
            print(f"[activity] Foreground check error: {e}")

    def _on_foreground(self, hwnd: int, title: str, class_name: str, process_name: str):
        """Handle foreground window change on main thread."""
        if hwnd == self._current_hwnd and title == self._current_title:
            return  # No actual change
        
        old_hwnd = self._current_hwnd
        self._current_hwnd = hwnd
        self._current_title = title
        self._current_class = class_name
        self._current_process = process_name
        
        # Match profile
        new_profile = self._match_profile(title, class_name, process_name)
        
        if new_profile and new_profile != self._current_profile:
            old_name = self._current_profile.name if self._current_profile else "none"
            new_name = new_profile.name
            self._switch_profile(new_profile)
            
            if self.config.get("notify_on_switch", True):
                print(f"[activity] Profile: {old_name} → {new_name}")
        
        # Publish event
        self.registry.event_bus.publish(ForegroundWindowChanged(
            hwnd=hwnd,
            title=title,
            class_name=class_name,
            process_name=process_name
        ))

    def _match_profile(self, title: str, class_name: str, process_name: str) -> Optional[AppProfile]:
        """Match current window to a profile."""
        title_lower = title.lower()
        class_lower = class_name.lower()
        process_lower = process_name.lower()
        
        best_profile = None
        best_priority = -1
        
        for profile in self._profiles.values():
            match = profile.match
            matched = True
            
            # Check process_contains
            if "process_contains" in match:
                if not any(p in process_lower for p in match["process_contains"]):
                    matched = False
            
            # Check title_contains
            if matched and "title_contains" in match:
                if not any(t in title_lower for t in match["title_contains"]):
                    matched = False
            
            # Check class_contains
            if matched and "class_contains" in match:
                if not any(c in class_lower for c in match["class_contains"]):
                    matched = False
            
            if matched and profile.priority > best_priority:
                best_profile = profile
                best_priority = profile.priority
        
        return best_profile

    def _switch_profile(self, profile: AppProfile):
        """Switch to a new profile."""
        self._current_profile = profile
        
        # Enable/disable plugins
        for plugin_name, enabled in profile.plugins.items():
            if enabled:
                self.registry.enable(plugin_name)
            else:
                self.registry.disable(plugin_name)
        
        # Apply window config
        if self._window and profile.window_config:
            for key, value in profile.window_config.items():
                if hasattr(self._window, f"_{key}"):
                    setattr(self._window, f"_{key}", value)
            # Trigger resize
            self._window.update()

    def get_current_profile(self) -> Optional[AppProfile]:
        return self._current_profile

    def get_current_window_info(self) -> Dict[str, Any]:
        return {
            "hwnd": self._current_hwnd,
            "title": self._current_title,
            "class": self._current_class,
            "process": self._current_process,
        }

    def get_profiles(self) -> Dict[str, AppProfile]:
        return self._profiles.copy()

    def add_profile(self, profile: AppProfile):
        """Add a custom profile at runtime."""
        self._profiles[profile.name] = profile
        # Save to config
        if "profiles" not in self.config:
            self.config["profiles"] = {}
        self.config["profiles"][profile.name] = {
            "match": profile.match,
            "plugins": profile.plugins,
            "window_config": profile.window_config,
            "priority": profile.priority,
        }

    def remove_profile(self, name: str) -> bool:
        """Remove a custom profile."""
        if name in self._profiles and name not in [p.name for p in BUILTIN_PROFILES]:
            del self._profiles[name]
            if "profiles" in self.config and name in self.config["profiles"]:
                del self.config["profiles"][name]
            return True
        return False

    def set_profile(self, name: str) -> bool:
        """Manually set profile by name."""
        profile = self._profiles.get(name)
        if profile:
            self._switch_profile(profile)
            return True
        return False

    def paint_activity(self, painter, rect):
        """Optional: paint current profile indicator."""
        if not self._current_profile:
            return
        
        painter.save()
        painter.setPen(QColor(100, 200, 100, 180))
        font = QFont("Segoe UI", 7)
        painter.setFont(font)
        painter.drawText(rect.right() - 80, rect.bottom() - 4, f"[{self._current_profile.name}]")
        painter.restore()