from typing import Dict, Any
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QEasingCurve, QPropertyAnimation, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QColor, QPainter, QPainterPath, QFont, QCursor

from ..core.plugin import PluginRegistry
from ..core.events import EventBus, WindowStateChanged
from ..plugins import discover_plugins


class OverlayWindow(QWidget):
    """Thin shell: glassmorphism pill, position, animation, event routing."""

    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__()
        self.registry = registry
        self.config = config
        self._window_config = config.get('window', {})

        # Window setup
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        # Geometry
        self._margin_top = self._window_config.get('margin_top', 8)
        self._micro_width = self._window_config.get('micro_width', 240)
        self._expanded_width = self._window_config.get('expanded_width', 480)
        self._height = self._window_config.get('height', 48)

        # Animation
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.setDuration(self._window_config.get('expand_duration', 500))
        self._anim.finished.connect(self._on_anim_finished)

        # State
        self._state = "collapsed"  # collapsed, expanded, hover, hidden
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._on_hover_timeout)

        # Layout for plugins to add widgets
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Position initially
        self._move_to_top_center()

    def _move_to_top_center(self):
        screen = self.screen().availableGeometry()
        x = (screen.width() - self._micro_width) // 2
        y = self._margin_top
        self.setGeometry(x, y, self._micro_width, self._height)

    def showEvent(self, event):
        super().showEvent(event)
        self._move_to_top_center()
        # Publish window ref to registry for plugins
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

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._state == "collapsed":
            self._set_state("hover")
            self._expand()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._state in ("hover", "expanded"):
            self._hover_timer.start(200)  # delay before collapse

    def _on_hover_timeout(self):
        if self._state in ("hover", "expanded"):
            # Check if mouse still over
            if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
                self._collapse()

    def _set_state(self, state: str):
        old = self._state
        self._state = state
        self.registry.event_bus.publish(WindowStateChanged(state=state))

    def _expand(self):
        if self._state == "expanded":
            return
        self._set_state("expanded")
        screen = self.screen().availableGeometry()
        x = (screen.width() - self._expanded_width) // 2
        y = self._margin_top
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(x, y, self._expanded_width, self._height))
        self._anim.start()

    def _collapse(self):
        if self._state == "collapsed":
            return
        self._set_state("collapsed")
        screen = self.screen().availableGeometry()
        x = (screen.width() - self._micro_width) // 2
        y = self._margin_top
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(x, y, self._micro_width, self._height))
        self._anim.start()

    def _on_anim_finished(self):
        if self._state == "hover":
            self._set_state("expanded")

    def get_state(self) -> str:
        return self._state