from typing import Dict, Any, Optional, List
import threading
import pythoncom
from PySide6.QtCore import QTimer, QEvent, Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage
from PySide6.QtWidgets import QLabel

from ..core.plugin import PluginBase, island_plugin, PluginRegistry
from ..core.events import EventBus, NotificationReceived, WindowStateChanged
from ..core.overlay import OverlayWindow


# Custom event for toast from background thread
class ToastEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())

    def __init__(self, data: Dict[str, Any]):
        super().__init__(self._type)
        self.data = data  # app_name, title, body, timestamp, icon_bytes, buttons


@island_plugin(
    name="notifications",
    version="1.0.0",
    description="Windows toast notifications listener: displays toasts with actions, per-app filtering",
    author="win-island-overlay",
    dependencies=[],
    config_schema={
        "enabled_apps": [],  # Empty = all apps
        "blocked_apps": [],  # Apps to ignore
        "max_toasts": 5,
        "toast_duration_ms": 5000,
        "toast_duration_with_buttons_ms": 30000,
        "show_icons": True,
        "show_buttons": True,
        "position": "bottom",  # bottom, top, center
    },
    enabled_by_default=True,
)
class NotificationsPlugin(PluginBase):
    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__(registry, config)
        self._window: Optional[OverlayWindow] = None
        
        # Toast state
        self._toasts: List[Dict[str, Any]] = []
        self._toast_alpha = 0.0
        self._toast_text_alpha = 0.0
        self._toast_anim: Optional[QTimer] = None
        self._toast_text_anim: Optional[QTimer] = None
        self._toast_timer: Optional[QTimer] = None
        self._toast_buttons: List[Dict[str, Any]] = []
        self._hovered_btn = -1
        self._pressed_btn = -1
        
        # Listener thread
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False

    def on_load(self) -> None:
        pass

    def on_enable(self) -> None:
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[notifications] No window reference")
            return

        self._running = True
        
        # Start Windows toast listener thread
        self._listener_thread = threading.Thread(target=self._listener_thread_func, daemon=True)
        self._listener_thread.start()
        
        # Timer for toast dismissal
        self._toast_timer = QTimer(self._window)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._dismiss_toast)

    def on_disable(self) -> None:
        self._running = False
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=1.0)
        if self._toast_timer:
            self._toast_timer.stop()
        if self._toast_anim:
            self._toast_anim.stop()
        if self._toast_text_anim:
            self._toast_text_anim.stop()

    def on_unload(self) -> None:
        pass

    def _listener_thread_func(self):
        """Background thread for Windows toast notifications."""
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            
            # Import Windows Runtime
            from winsdk.windows.ui.notifications.management import UserNotificationListener
            from winsdk.windows.ui.notifications import NotificationKinds
            
            async def listen():
                listener = UserNotificationListener.get_current()
                # Request access
                access = await listener.request_access_async()
                if access != UserNotificationListenerAccessStatus.ALLOWED:
                    print("[notifications] Access denied")
                    return
                
                # Get existing notifications
                notifications = await listener.get_notifications_async(NotificationKinds.TOAST)
                for notif in notifications:
                    self._process_notification(notif)
                
                # Listen for new notifications
                def on_notification_changed(sender, args):
                    if args.kind == NotificationKinds.TOAST and args.change == NotificationChangeType.ADDED:
                        notif = sender.get_notification(args.notification_id)
                        self._process_notification(notif)
                
                listener.notification_changed += on_notification_changed
                
                # Keep thread alive
                while self._running:
                    pythoncom.PumpWaitingMessages()
                    import time
                    time.sleep(0.1)
            
            import asyncio
            asyncio.run(listen())
            
        except Exception as e:
            print(f"[notifications] Listener error: {e}")

    def _process_notification(self, notification):
        """Extract data from Windows notification."""
        try:
            app_name = notification.app_info.display_info.display_name if notification.app_info else "Unknown"
            
            # Check filters
            enabled_apps = self.config.get("enabled_apps", [])
            blocked_apps = self.config.get("blocked_apps", [])
            
            if enabled_apps and app_name not in enabled_apps:
                return
            if app_name in blocked_apps:
                return
            
            # Extract text content
            binding = notification.notification.visual.get_binding(ToastTemplateType.TOAST_GENERIC)
            if not binding:
                binding = notification.notification.visual.get_binding(ToastTemplateType.TOAST_IMAGE_AND_TEXT01)
            if not binding:
                binding = notification.notification.visual.get_binding(ToastTemplateType.TOAST_TEXT01)
            
            title = ""
            body = ""
            if binding:
                texts = binding.get_text_elements()
                for text in texts:
                    if not title:
                        title = str(text.text)
                    elif not body:
                        body = str(text.text)
            
            # Extract icon
            icon_bytes = b""
            if self.config.get("show_icons", True) and binding:
                try:
                    images = binding.get_image_elements()
                    for img in images:
                        if img.image:
                            # This is simplified - actual extraction is more complex
                            pass
                except:
                    pass
            
            # Extract buttons/actions
            buttons = []
            if self.config.get("show_buttons", True):
                try:
                    actions = notification.notification.actions
                    for action in actions:
                        buttons.append({
                            "id": str(action.id),
                            "label": str(action.content),
                            "type": str(action.activation_type),
                        })
                except:
                    pass
            
            data = {
                "app": app_name,
                "title": title,
                "body": body,
                "timestamp": notification.timestamp,
                "icon_bytes": icon_bytes,
                "buttons": buttons,
                "notification_id": str(notification.id),
            }
            
            # Post to main thread
            QTimer.singleShot(0, lambda: self._on_toast(data))
            
        except Exception as e:
            print(f"[notifications] Process error: {e}")

    def _on_toast(self, data: Dict[str, Any]):
        """Handle incoming toast on main thread."""
        if not self._window:
            return
        
        # Add to queue
        self._toasts.insert(0, data)
        max_toasts = self.config.get("max_toasts", 5)
        if len(self._toasts) > max_toasts:
            self._toasts = self._toasts[:max_toasts]
        
        # Show latest
        self._show_latest_toast()
        
        # Publish event
        self.registry.event_bus.publish(NotificationReceived(
            app_name=data["app"],
            title=data["title"],
            body=data["body"],
            icon_bytes=data["icon_bytes"],
            buttons=[b["label"] for b in data["buttons"]]
        ))

    def _show_latest_toast(self):
        if not self._toasts:
            return
        
        toast = self._toasts[0]
        self._toast_buttons = toast.get("buttons", [])
        
        # Animate in
        self._toast_alpha = 0.0
        self._toast_text_alpha = 0.0
        self._animate_toast_alpha(1.0, 300)
        self._animate_toast_text_alpha(1.0, 300)
        
        # Set dismissal timer
        duration = self.config.get("toast_duration_ms", 5000)
        if self._toast_buttons:
            duration = self.config.get("toast_duration_with_buttons_ms", 30000)
        self._toast_timer.start(duration)
        
        if self._window:
            self._window.update()

    def _dismiss_toast(self):
        if not self._toasts:
            return
        
        self._animate_toast_alpha(0.0, 300)
        self._animate_toast_text_alpha(0.0, 300)
        
        # Remove after animation
        QTimer.singleShot(300, self._remove_current_toast)

    def _remove_current_toast(self):
        if self._toasts:
            self._toasts.pop(0)
            self._toast_buttons = []
            self._hovered_btn = -1
            self._pressed_btn = -1
            
            # Show next toast
            if self._toasts:
                QTimer.singleShot(100, self._show_latest_toast)
            elif self._window:
                self._window.update()

    def _animate_toast_alpha(self, target: float, duration: int):
        if self._toast_anim:
            self._toast_anim.stop()
        steps = 30
        step_val = (target - self._toast_alpha) / steps
        step_ms = duration // steps
        current = self._toast_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._toast_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._toast_alpha = target
                self._toast_anim.stop()
        
        self._toast_anim = QTimer(self._window)
        self._toast_anim.timeout.connect(step)
        self._toast_anim.start(step_ms)

    def _animate_toast_text_alpha(self, target: float, duration: int):
        if self._toast_text_anim:
            self._toast_text_anim.stop()
        steps = 30
        step_val = (target - self._toast_text_alpha) / steps
        step_ms = duration // steps
        current = self._toast_text_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._toast_text_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._toast_text_alpha = target
                self._toast_text_anim.stop()
        
        self._toast_text_anim = QTimer(self._window)
        self._toast_text_anim.timeout.connect(step)
        self._toast_text_anim.start(step_ms)

    def get_toasts(self) -> List[Dict[str, Any]]:
        return self._toasts[:]

    def is_showing(self) -> bool:
        return len(self._toasts) > 0 and self._toast_alpha > 0

    def get_alpha(self) -> float:
        return self._toast_alpha

    def get_text_alpha(self) -> float:
        return self._toast_text_alpha

    def get_buttons(self) -> List[Dict[str, Any]]:
        return self._toast_buttons[:]

    def handle_click(self, pos) -> bool:
        """Handle click on toast buttons. Returns True if handled."""
        if not self._toast_buttons or self._toast_alpha <= 0:
            return False
        
        # Calculate button rects (simplified)
        if not self._window:
            return False
            
        rect = self._window.rect()
        btn_count = len(self._toast_buttons)
        if btn_count == 0:
            return False
        
        btn_w = 100
        btn_h = 32
        spacing = 8
        total_w = btn_count * btn_w + (btn_count - 1) * spacing
        start_x = (rect.width() - total_w) // 2
        y = rect.bottom() - btn_h - 40
        
        for i, btn in enumerate(self._toast_buttons):
            x = start_x + i * (btn_w + spacing)
            btn_rect = QRect(x, y, btn_w, btn_h)
            if btn_rect.contains(pos):
                self._on_button_click(i, btn)
                return True
        
        return False

    def _on_button_click(self, index: int, btn: Dict[str, Any]):
        """Handle toast button click."""
        # Launch associated app (simplified)
        if self._toasts:
            notif = self._toasts[0]
            aumid = notif.get("app")
            if aumid:
                self._launch_app(aumid)
        
        # Dismiss toast
        self._dismiss_toast()

    def _launch_app(self, aumid: str):
        """Launch app by AUMID."""
        try:
            import subprocess
            subprocess.Popen(
                ['explorer.exe', f'shell:AppsFolder\\{aumid}'],
                shell=True
            )
        except Exception as e:
            print(f"[notifications] Launch error: {e}")

    def handle_mouse_move(self, pos):
        """Update hovered button."""
        if not self._toast_buttons or not self._window:
            self._hovered_btn = -1
            return
        
        rect = self._window.rect()
        btn_count = len(self._toast_buttons)
        btn_w = 100
        btn_h = 32
        spacing = 8
        total_w = btn_count * btn_w + (btn_count - 1) * spacing
        start_x = (rect.width() - total_w) // 2
        y = rect.bottom() - btn_h - 40
        
        old_hover = self._hovered_btn
        self._hovered_btn = -1
        
        for i in range(btn_count):
            x = start_x + i * (btn_w + spacing)
            btn_rect = QRect(x, y, btn_w, btn_h)
            if btn_rect.contains(pos):
                self._hovered_btn = i
                break
        
        if old_hover != self._hovered_btn and self._window:
            self._window.update()

    def handle_mouse_press(self, pos):
        if self._hovered_btn >= 0:
            self._pressed_btn = self._hovered_btn
            if self._window:
                self._window.update()

    def handle_mouse_release(self, pos):
        if self._pressed_btn >= 0 and self._hovered_btn == self._pressed_btn:
            if self._toast_buttons and self._pressed_btn < len(self._toast_buttons):
                self._on_button_click(self._pressed_btn, self._toast_buttons[self._pressed_btn])
        self._pressed_btn = -1
        if self._window:
            self._window.update()

    def paint_notifications(self, painter: QPainter, rect: QRect):
        """Called from OverlayWindow.paintEvent."""
        if not self._toasts or self._toast_alpha <= 0:
            return
        
        painter.save()
        painter.setOpacity(self._toast_alpha)
        
        # Draw each toast (stacked)
        for i, toast in enumerate(self._toasts):
            if i >= 3:  # Max 3 visible
                break
            
            offset_y = i * 80
            self._paint_single_toast(painter, rect, toast, offset_y, i == 0)
        
        painter.restore()

    def _paint_single_toast(self, painter: QPainter, rect: QRect, toast: Dict[str, Any], offset_y: int, is_top: bool):
        """Paint a single toast notification."""
        # Background
        toast_w = min(420, rect.width() - 40)
        toast_h = 72
        toast_x = (rect.width() - toast_w) // 2
        toast_y = rect.bottom() + 16 + offset_y
        
        # Apply text alpha for text
        text_opacity = self._toast_text_alpha if is_top else self._toast_text_alpha * 0.7
        
        # Background
        painter.setBrush(QColor(20, 20, 30, int(220 * self._toast_alpha)))
        painter.setPen(QColor(255, 255, 255, int(30 * self._toast_alpha)))
        painter.drawRoundedRect(toast_x, toast_y, toast_w, toast_h, 12, 12)
        
        # App name
        painter.setOpacity(text_opacity)
        painter.setPen(QColor(180, 180, 180, 200))
        font = QFont("Segoe UI", 8, QFont.Weight.Medium)
        painter.setFont(font)
        painter.drawText(toast_x + 16, toast_y + 16, toast.get("app", "Unknown"))
        
        # Title
        painter.setPen(QColor(255, 255, 255, 230))
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(toast_x + 16, toast_y + 36, toast.get("title", ""))
        
        # Body
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(200, 200, 200, 200))
        painter.drawText(toast_x + 16, toast_y + 54, toast.get("body", ""))
        
        # Buttons (only for top toast)
        if is_top and self._toast_buttons and self._toast_text_alpha > 0:
            self._paint_toast_buttons(painter, rect, toast_y + toast_h + 8)

    def _paint_toast_buttons(self, painter: QPainter, rect: QRect, y: int):
        """Paint toast action buttons."""
        btn_count = len(self._toast_buttons)
        if btn_count == 0:
            return
        
        btn_w = 100
        btn_h = 32
        spacing = 8
        total_w = btn_count * btn_w + (btn_count - 1) * spacing
        start_x = (rect.width() - total_w) // 2
        
        for i, btn in enumerate(self._toast_buttons):
            x = start_x + i * (btn_w + spacing)
            btn_rect = QRect(x, y, btn_w, btn_h)
            
            # Button background
            if i == self._pressed_btn:
                painter.setBrush(QColor(255, 255, 255, 60))
            elif i == self._hovered_btn:
                painter.setBrush(QColor(255, 255, 255, 40))
            else:
                painter.setBrush(QColor(255, 255, 255, 20))
            
            painter.setPen(QColor(255, 255, 255, 80))
            painter.drawRoundedRect(btn_rect, 16, 16)
            
            # Button text
            painter.setOpacity(self._toast_text_alpha)
            painter.setPen(QColor(255, 255, 255, 220))
            font = QFont("Segoe UI", 9, QFont.Weight.Medium)
            painter.setFont(font)
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, btn.get("label", ""))


# Need to import ToastTemplateType etc. at top level for the thread
try:
    from winsdk.windows.ui.notifications import ToastTemplateType
    from winsdk.windows.ui.notifications.management import NotificationChangeType
    from winsdk.windows.ui.notifications.management import UserNotificationListenerAccessStatus
except ImportError:
    # Define dummy classes for type checking when winsdk not available
    class ToastTemplateType:
        TOAST_GENERIC = 0
        TOAST_IMAGE_AND_TEXT01 = 1
        TOAST_TEXT01 = 2
    class NotificationChangeType:
        ADDED = 0
        REMOVED = 1
        MODIFIED = 2
    class UserNotificationListenerAccessStatus:
        ALLOWED = 0
        DENIED = 1
        UNSET = 2