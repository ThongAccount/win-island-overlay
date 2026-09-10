from typing import Dict, Any
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus, WindowStateChanged


@island_plugin(
    name="greeting",
    version="1.0.0",
    description="Shows a customizable greeting message on startup and hover",
    author="win-island-overlay",
    config_schema={
        "text": "Hello! 👋",
        "font_size": 14,
        "color": "#ffffff",
        "duration_ms": 3000,
        "show_on_startup": True,
        "show_on_hover": True,
    },
    enabled_by_default=True,
)
class GreetingPlugin(PluginBase):
    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__(registry, config)
        self._label: QLabel = None
        self._timer: QTimer = None
        self._window = None

    def on_load(self) -> None:
        pass

    def on_enable(self) -> None:
        # Get reference to main window
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[greeting] No window reference, cannot show greeting")
            return

        # Create label
        self._label = QLabel(self.config.get("text", "Hello! 👋"), self._window)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(f"""
            color: {self.config.get('color', '#ffffff')};
            font-size: {self.config.get('font_size', 14)}px;
            font-weight: 500;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 8px 16px;
        """)
        self._label.hide()

        # Timer for auto-hide
        self._timer = QTimer(self._window)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide_greeting)

        # Subscribe to window state changes
        self._unsub = self.registry.event_bus.subscribe(
            WindowStateChanged, self._on_window_state
        )

        # Show on startup if configured
        if self.config.get("show_on_startup", True):
            QTimer.singleShot(500, self._show_greeting)

    def on_disable(self) -> None:
        if hasattr(self, '_unsub'):
            self._unsub()
        if self._timer:
            self._timer.stop()
        if self._label:
            self._label.deleteLater()
            self._label = None

    def on_unload(self) -> None:
        pass

    def _show_greeting(self) -> None:
        if self._label and self._window:
            # Position in center of pill
            pill_rect = self._window.rect()
            label_size = self._label.sizeHint()
            x = (pill_rect.width() - label_size.width()) // 2
            y = (pill_rect.height() - label_size.height()) // 2
            self._label.move(x, y)
            self._label.show()
            self._label.raise_()
            self._timer.start(self.config.get("duration_ms", 3000))

    def _hide_greeting(self) -> None:
        if self._label:
            self._label.hide()

    def _on_window_state(self, event: WindowStateChanged) -> None:
        if event.state == "hover" and self.config.get("show_on_hover", True):
            self._show_greeting()
        elif event.state == "collapsed":
            self._hide_greeting()