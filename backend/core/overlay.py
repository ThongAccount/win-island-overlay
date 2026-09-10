from typing import Dict, Any, List
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

        # Base geometry
        self._base_margin_top = self._window_config.get('margin_top', 8)
        self._base_micro_width = self._window_config.get('micro_width', 240)
        self._base_expanded_width = self._window_config.get('expanded_width', 480)
        self._base_height = self._window_config.get('height', 48)

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
        self._is_expanded = False
        self._hover_animating = False
        self._expand_progress = 0.0

        # Layout for plugins to add widgets
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Plugin references (populated after plugins load)
        self._plugins: Dict[str, Any] = {}

        # Position initially
        self._move_to_top_center()

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
            extra += self._window_config.get('obs_extra_width', 40)
        if self._plugins.get('media') and self._plugins['media'].get_media_state() > 0:
            extra += self._window_config.get('media_extra_width', 100)
        
        return {
            'micro': self._base_micro_width + extra,
            'expanded': self._base_expanded_width + extra,
            'height': self._base_height,
        }

    def _move_to_top_center(self):
        widths = self._compute_widths()
        screen = self.screen().availableGeometry()
        x = (screen.width() - widths['micro']) // 2
        y = self._base_margin_top
        self.setGeometry(x, y, widths['micro'], widths['height'])

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

        # Plugin painting (order matters - background to foreground)
        paint_order = ['obs', 'media', 'notifications', 'greeting', 'activity']
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
            # greeting draws its own QLabel widget

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

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        
        # Forward to plugins
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_move'):
                plugin.handle_mouse_move(pos)
            elif hasattr(plugin, 'handle_click'):  # Some plugins use click for hover
                pass

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        pos = event.position().toPoint()
        
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_press'):
                plugin.handle_mouse_press(pos)
            if hasattr(plugin, 'handle_click') and plugin.handle_click(pos):
                return  # Handled

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pos = event.position().toPoint()
        
        for plugin in self._plugins.values():
            if hasattr(plugin, 'handle_mouse_release'):
                plugin.handle_mouse_release(pos)

    def _set_state(self, state: str):
        old = self._state
        self._state = state
        self.registry.event_bus.publish(WindowStateChanged(state=state))

    def _expand(self):
        if self._state == "expanded":
            return
        self._set_state("expanded")
        self._is_expanded = True
        self._hover_animating = True
        self._expand_progress = 0.0
        
        widths = self._compute_widths()
        screen = self.screen().availableGeometry()
        x = (screen.width() - widths['expanded']) // 2
        y = self._base_margin_top
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(x, y, widths['expanded'], widths['height']))
        self._anim.start()

    def _collapse(self):
        if self._state == "collapsed":
            return
        self._set_state("collapsed")
        self._is_expanded = False
        self._hover_animating = True
        self._expand_progress = 1.0
        
        widths = self._compute_widths()
        screen = self.screen().availableGeometry()
        x = (screen.width() - widths['micro']) // 2
        y = self._base_margin_top
        self._anim.stop()
        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(QRect(x, y, widths['micro'], widths['height']))
        self._anim.start()

    def _on_anim_finished(self):
        self._hover_animating = False
        if self._state == "hover":
            self._set_state("expanded")
        elif self._state == "collapsed":
            self._expand_progress = 0.0

    def get_state(self) -> str:
        return self._state

    def property(self, name):
        """Override property for dynamic values."""
        if name == "_pulse_time":
            import time
            return time.time() * 3
        if name == "_hidden_by_fullscreen":
            return getattr(self, '_hidden_by_fullscreen', False)
        if name == "_is_expanded":
            return self._is_expanded
        return super().property(name)