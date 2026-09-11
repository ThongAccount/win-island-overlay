from typing import Dict, Any, List
import threading
from PySide6.QtCore import QCoreApplication

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus, NotificationReceived, WindowStateChanged
from backend.core.overlay import OverlayWindow, ToastNotifEvent


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
        
        # Data source only — overlay owns all rendering/animation state
        self._toasts: List[Dict[str, Any]] = []

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

    def on_disable(self) -> None:
        self._running = False
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=1.0)

    def on_unload(self) -> None:
        pass

    def _listener_thread_func(self):
        """Background thread for Windows toast notifications."""
        try:
            import pythoncom
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            
            # Import Windows Runtime
            from winsdk.windows.ui.notifications.management import UserNotificationListener
            from winsdk.windows.ui.notifications import NotificationKinds
            
            async def listen():
                listener = UserNotificationListener()
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
            
            # Post to overlay (main-thread) with main-branch payload shape
            import datetime
            time_str = 'just now'
            try:
                ct = notification.timestamp
                now = datetime.datetime.now(datetime.timezone.utc)
                if hasattr(ct, 'astimezone'):
                    diff = int((now - ct).total_seconds())
                    if diff < 60:
                        time_str = 'just now'
                    elif diff < 3600:
                        time_str = f'{diff // 60}m ago'
                    else:
                        time_str = ct.astimezone().strftime('%H:%M')
            except Exception:
                pass

            aumid = None
            try:
                if notification.app_info:
                    aumid = notification.app_info.id
            except Exception:
                pass

            overlay_payload = {
                'app': app_name,
                'title': title,
                'body': body,
                'time': time_str,
                'icon': icon_bytes or None,
                'buttons': [b.get('label', '') for b in buttons] if buttons else [],
                'image': None,
                'aumid': aumid,
                'notif_id': str(notification.id),
            }
            if self._window:
                QCoreApplication.postEvent(self._window, ToastNotifEvent(overlay_payload))

            # Keep plugin queue for bookkeeping / event bus
            QTimer.singleShot(0, lambda: self._on_toast(data))
            
        except Exception as e:
            print(f"[notifications] Process error: {e}")

    def _on_toast(self, data: Dict[str, Any]):
        """Bookkeeping / event bus — overlay owns display via ToastNotifEvent."""
        self._toasts.insert(0, data)
        max_toasts = self.config.get("max_toasts", 5)
        if len(self._toasts) > max_toasts:
            self._toasts = self._toasts[:max_toasts]

        self.registry.event_bus.publish(NotificationReceived(
            app_name=data["app"],
            title=data["title"],
            body=data["body"],
            icon_bytes=data["icon_bytes"],
            buttons=[b["label"] for b in data["buttons"]] if data.get("buttons") else []
        ))