from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

async def get_current_media_info():
    sessions = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    current_session = sessions.get_current_session()
    if current_session:
        info = await current_session.try_get_media_properties_async()
        return {
            'title': info.title,
            'artist': info.artist,
            'album': info.album_title
        }
    return None
