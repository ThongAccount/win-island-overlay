import asyncio, pythoncom, traceback

pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)

async def main():
    from winsdk.windows.ui.notifications.management import UserNotificationListener, UserNotificationListenerAccessStatus
    from winsdk.windows.ui.notifications import NotificationKinds, KnownNotificationBindings

    listener = UserNotificationListener.current
    access = await listener.request_access_async()
    print(f'Access: {access}', flush=True)
    if access != UserNotificationListenerAccessStatus.ALLOWED:
        return

    notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
    for n in list(notifs):
        app = n.app_info.display_info.display_name if n.app_info else '?'
        print(f'App: {app}  ID: {n.id}  Created: {n.creation_time}', flush=True)
        binding = n.notification.visual.get_binding("ToastGeneric")
        if binding:
            for text in binding.get_text_elements():
                print(f'  text: {text.text!r}', flush=True)
        else:
            print('  no binding', flush=True)

    def on_changed(sender, args):
        print('Changed!', flush=True)
        asyncio.run_coroutine_threadsafe(poll(), loop)

    async def poll():
        notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
        for n in list(notifs):
            app = n.app_info.display_info.display_name if n.app_info else '?'
            binding = n.notification.visual.get_binding("ToastGeneric")
            texts = [t.text for t in binding.get_text_elements()] if binding else []
            print(f'NEW: {app} | {texts}', flush=True)

    listener.add_notification_changed(on_changed)
    print('Listening 30s - send a notification!', flush=True)
    await asyncio.sleep(30)

loop = asyncio.new_event_loop()
loop.run_until_complete(main())
