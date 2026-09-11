from typing import Dict, Any, List
import threading
from PySide6.QtCore import QCoreApplication

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus, NotificationReceived, WindowStateChanged
from backend.core.overlay import OverlayWindow, ToastNotifEvent

@island_plugin(
    name="notifications",
    version="1.0.0",
    description="Windows toast notifications listener: displays toasts, per-app filtering",
    author="win-island-overlay",
    dependencies=[],
    config_schema={
        "enabled_apps": [],  # Empty = all apps
        "blocked_apps": [],  # Apps to ignore
        "max_toasts": 5,
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
        """Background thread: poll UserNotificationListener (main branch approach).

        The change-event API is unavailable via winsdk's python projection
        (add_notification_changed only), so poll every 0.5s and diff ids.
        """
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        import asyncio
        import datetime
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def poll():
            try:
                from winsdk.windows.ui.notifications.management import UserNotificationListener, UserNotificationListenerAccessStatus
                from winsdk.windows.ui.notifications import NotificationKinds

                # UserNotificationListener is not activatable — static Current only
                listener = UserNotificationListener.current
                access = await asyncio.wait_for(listener.request_access_async(), timeout=5.0)
                if access != UserNotificationListenerAccessStatus.ALLOWED:
                    print(f"[notifications] Access denied: {access}")
                    return

                seen_ids = set()

                # Pre-populate with existing notifications to skip them
                existing = await asyncio.wait_for(listener.get_notifications_async(NotificationKinds.TOAST), timeout=3.0)
                for n in list(existing):
                    seen_ids.add(n.id)

                print(f"[notifications] Listener started, skipping {len(seen_ids)} existing notifications")

                while self._running:
                    try:
                        notifs = await asyncio.wait_for(listener.get_notifications_async(NotificationKinds.TOAST), timeout=2.0)
                        current_ids = set()
                        for n in list(notifs):
                            nid = n.id
                            current_ids.add(nid)
                            if nid in seen_ids:
                                continue
                            seen_ids.add(nid)
                            try:
                                app = 'Unknown app'
                                try:
                                    if n.app_info and n.app_info.display_info:
                                        app = n.app_info.display_info.display_name or 'Unknown app'
                                except:
                                    pass

                                binding = n.notification.visual.get_binding("ToastGeneric")
                                if not binding:
                                    continue
                                texts = [t.text for t in binding.get_text_elements() if t.text]
                                if not texts:
                                    continue
                                title = texts[0] if texts else ''
                                body = texts[1] if len(texts) > 1 else ''

                                # UserNotificationListener API exposes no action buttons/images
                                buttons = []
                                image_path = None

                                # AUMID for app launch
                                aumid = None
                                try:
                                    if n.app_info:
                                        aumid = n.app_info.id
                                except:
                                    pass

                                ct = n.creation_time
                                now = datetime.datetime.now(datetime.timezone.utc)
                                diff = int((now - ct).total_seconds())
                                if diff < 60:
                                    time_str = 'just now'
                                elif diff < 3600:
                                    time_str = f'{diff // 60}m ago'
                                else:
                                    time_str = ct.astimezone().strftime('%H:%M')

                                self.registry.event_bus.publish(NotificationReceived(
                                    app_name=app, title=title, body=body,
                                    icon_bytes=b"", buttons=[],
                                ))

                                print(f"[notifications] New: {app} - {title}")
                                QCoreApplication.postEvent(self._window, ToastNotifEvent({
                                    'app': app, 'title': title, 'body': body,
                                    'time': time_str, 'icon': None, 'buttons': buttons,
                                    'image': image_path, 'aumid': aumid, 'notif_id': nid
                                }))
                            except Exception as e:
                                print(f"[notifications] Parse error: {e}")
                        seen_ids &= current_ids
                        await asyncio.sleep(0.5)
                    except asyncio.TimeoutError:
                        print("[notifications] Poll timeout, continuing...")
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        print(f"[notifications] Fetch error: {e}")
                        await asyncio.sleep(1.0)
            except Exception as e:
                print(f"[notifications] Listener error: {e}")

        loop.run_until_complete(poll())

