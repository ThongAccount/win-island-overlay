from typing import Dict, Any, Optional
import threading
import asyncio
from PySide6.QtCore import QTimer, QCoreApplication

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus, MediaSessionChanged, WindowStateChanged
from backend.core.overlay import OverlayWindow, MediaResultEvent


# Audio FFT capture (from main branch - WASAPI loopback with frequency band mapping)
class AudioFFT:
    def __init__(self, num_bands=8):
        self.num_bands = num_bands
        self.bands = [0.0] * num_bands
        self._running = False
        self._thread = None
        
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        
    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            
    def get_bands(self):
        return self.bands.copy()
        
    def _capture_loop(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                import pyaudiowpatch as pyaudio
                import numpy as np
                
                p = pyaudio.PyAudio()
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
                
                if not default_speakers["isLoopbackDevice"]:
                    for loopback in p.get_loopback_device_info_generator():
                        if default_speakers["name"] in loopback["name"]:
                            default_speakers = loopback
                            break
                
                chunk_size = 2048
                sample_rate = int(default_speakers["defaultSampleRate"])
                
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=default_speakers["maxInputChannels"],
                    rate=sample_rate,
                    input=True,
                    input_device_index=default_speakers["index"],
                    frames_per_buffer=chunk_size
                )
                
                while self._running:
                    try:
                        data = stream.read(chunk_size, exception_on_overflow=False)
                        audio_data = np.frombuffer(data, dtype=np.int16)
                        
                        # Convert to mono if stereo
                        if default_speakers["maxInputChannels"] == 2:
                            audio_data = audio_data.reshape(-1, 2).mean(axis=1)
                        
                        # Apply FFT
                        fft = np.abs(np.fft.rfft(audio_data))
                        freqs = np.fft.rfftfreq(chunk_size, 1/sample_rate)
                        
                        # Map to frequency bands (bass to treble)
                        band_ranges = [
                            (20, 150),      # Sub-bass
                            (150, 300),     # Bass
                            (300, 600),     # Low mids
                            (600, 1200),    # Mids
                            (1200, 2500),   # Upper mids
                            (2500, 5000),   # Presence
                            (5000, 10000),  # Brilliance
                            (10000, 20000)  # Air
                        ]
                        
                        for i, (low, high) in enumerate(band_ranges[:self.num_bands]):
                            mask = (freqs >= low) & (freqs < high)
                            if mask.any():
                                # Use max for better dynamics, apply log scaling
                                raw_val = np.max(fft[mask])
                                self.bands[i] = min(1.0, np.log10(raw_val + 1) / 7.5)
                            else:
                                self.bands[i] = 0.0
                                
                    except:
                        time.sleep(0.02)
                        
                stream.stop_stream()
                stream.close()
                p.terminate()
            except:
                # Fallback: use simple peak meter via pycaw
                try:
                    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
                    while self._running:
                        try:
                            sessions = AudioUtilities.GetAllSessions()
                            max_peak = 0.0
                            for session in sessions:
                                if session.Process:
                                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                                    peak = meter.GetPeakValue()
                                    max_peak = max(max_peak, peak)
                            
                            # Simulate bands from peak
                            for i in range(self.num_bands):
                                variation = 0.7 + (i * 0.05)
                                self.bands[i] = min(1.0, max_peak * variation * 2)
                            
                            time.sleep(0.05)
                        except:
                            time.sleep(0.1)
                except:
                    pass
        finally:
            try:
                pythoncom.CoUninitialize()
            except:
                pass


@island_plugin(
    name="media",
    version="1.0.0",
    description="System Media Transport Controls (SMTC) integration: now playing, album art, playback controls, FFT visualizer",
    author="win-island-overlay",
    dependencies=[],
    config_schema={
        "show_album_art": True,
        "show_controls": True,
        "show_visualizer": True,
        "num_bands": 8,
        "visualizer_color": "#00ff88",
        "title_scroll_speed": 12000,
    },
    enabled_by_default=True,
)
class MediaPlugin(PluginBase):
    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__(registry, config)
        self._window: Optional[OverlayWindow] = None
        
        # Data source only — overlay owns all rendering/animation state
        self._media_session = None
        self._media_loop = None
        self._media_seq = 0
        self._media_was_active = False
        self._media_thumb_key = ""
        self._media_thumb_cache = None
        
        # Visualizer
        self._audio_fft: Optional[AudioFFT] = None
        self._viz_timer: Optional[QTimer] = None
        
        # Threading
        self._media_thread: Optional[threading.Thread] = None
        self._running = False

    def on_load(self) -> None:
        pass

    def on_enable(self) -> None:
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[media] No window reference")
            return

        self._running = True
        
        # Setup visualizer — drive overlay paint state
        if self.config.get("show_visualizer", True):
            self._audio_fft = AudioFFT(num_bands=self.config.get("num_bands", 8))
            self._audio_fft.start()

            self._viz_timer = QTimer(self._window)
            self._viz_timer.timeout.connect(self._window._update_viz)
            self._viz_timer.start(80)  # ~12.5 FPS

        # Start SMTC monitor thread (main branch implementation)
        self._media_thread = threading.Thread(target=self._media_monitor_thread, daemon=True)
        self._media_thread.start()

    def on_disable(self) -> None:
        self._running = False
        if self._viz_timer:
            self._viz_timer.stop()
        if self._audio_fft:
            self._audio_fft.stop()
        if self._media_loop:
            self._media_loop.call_soon_threadsafe(self._media_loop.stop)
        if self._media_thread and self._media_thread.is_alive():
            self._media_thread.join(timeout=1.0)

    def on_unload(self) -> None:
        pass

    def _media_monitor_thread(self):
        """Main branch SMTC monitor with sessions_changed event + polling."""
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._media_loop = loop
        if self._window:
            self._window._media_loop = loop

        async def init_mgr():
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            return await GlobalSystemMediaTransportControlsSessionManager.request_async()

        try:
            mgr = loop.run_until_complete(init_mgr())

            def sessions_changed(sender, args):
                asyncio.run_coroutine_threadsafe(self._query_and_post(loop, mgr, False), loop)

            mgr.add_sessions_changed(sessions_changed)

            asyncio.run_coroutine_threadsafe(self._query_and_post(loop, mgr, False), loop)

            def poll():
                if self._running:
                    asyncio.run_coroutine_threadsafe(self._query_and_post(loop, mgr, True), loop)
                    loop.call_later(0.5, poll)

            loop.call_soon(poll)
            loop.run_forever()
        except Exception as e:
            print(f"[media] Monitor thread error: {e}")

    async def _read_thumbnail(self, thumbnail_ref):
        """Read thumbnail from Windows Storage streams."""
        from winsdk.windows.storage.streams import DataReader
        try:
            stream = await asyncio.wait_for(thumbnail_ref.open_read_async(), timeout=3.0)
            size = int(stream.size)
            if size <= 0 or size > 5_000_000:
                return None
            reader = DataReader(stream)
            await reader.load_async(size)
            buf = bytearray(size)
            reader.read_bytes(buf)
            return bytes(buf)
        except Exception:
            return None

    def _ordered_media_sessions(self, mgr):
        """Get sessions ordered by playback status (playing first)."""
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus
        sessions = []
        current = mgr.get_current_session()
        if current:
            sessions.append(current)
        for session in mgr.get_sessions():
            if session is not current:
                sessions.append(session)

        def sort_key(session):
            try:
                status = session.get_playback_info().playback_status
            except Exception:
                status = GlobalSystemMediaTransportControlsSessionPlaybackStatus.CLOSED
            if status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
                return 0
            if status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED:
                return 1
            return 2

        sessions.sort(key=sort_key)
        return sessions

    async def _query_and_post(self, loop, mgr=None, is_poll=True):
        """Query media sessions and post result to main thread."""
        _captured_seq = self._media_seq
        try:
            from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus
            if mgr is None:
                from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
                mgr = await GlobalSystemMediaTransportControlsSessionManager.request_async()
            
            for session in self._ordered_media_sessions(mgr):
                try:
                    playback = session.get_playback_info()
                    status = playback.playback_status
                    if status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.CLOSED:
                        continue
                    info = await session.try_get_media_properties_async()
                    if not info or not (info.title or info.artist):
                        continue
                    title = info.title or ''
                    artist = info.artist or ''
                    app_id = session.source_app_user_model_id or ''
                    thumb_key = f'{title}|{artist}|{app_id}'
                    thumb_bytes = None
                    if info.thumbnail:
                        thumb_bytes = await self._read_thumbnail(info.thumbnail)
                    if not thumb_bytes and thumb_key == self._media_thumb_key and self._media_thumb_cache:
                        thumb_bytes = self._media_thumb_cache
                    
                    pos_sec = 0.0
                    dur_sec = 0.0
                    try:
                        tl = session.get_timeline_properties()
                        dur_sec = tl.end_time.total_seconds() if tl.end_time else 0.0
                        pos_sec = tl.position.total_seconds() if tl.position else 0.0
                        if dur_sec < 0:
                            dur_sec = 0.0
                        if pos_sec < 0:
                            pos_sec = 0.0
                    except Exception:
                        pass
                    
                    if self._media_seq != _captured_seq:
                        return
                    
                    self._media_was_active = True
                    # status.value: 4=PLAYING, 5=PAUSED
                    result = (title, artist, app_id, status.value, thumb_bytes, pos_sec, dur_sec, session)
                    QCoreApplication.postEvent(self._window, MediaResultEvent(result))
                    return
                except Exception:
                    continue
        except Exception:
            pass
        
        if not is_poll:
            self._media_was_active = False
            self._media_seq += 1
            QCoreApplication.postEvent(self._window, MediaResultEvent(('', '', '', 0, None, 0.0, 0.0, None)))
        elif self._media_was_active:
            self._media_was_active = False
            self._media_seq += 1
            QCoreApplication.postEvent(self._window, MediaResultEvent(('', '', '', 0, None, 0.0, 0.0, None)))

    def do_action(self, action: str, seek_seconds: Optional[float] = None):
        """Play/pause/next/prev/seek."""
        if not self._media_session or not self._media_loop:
            return

        async def do_async():
            try:
                if action == "play":
                    await self._media_session.try_play_async()
                elif action == "pause":
                    await self._media_session.try_pause_async()
                elif action == "next":
                    await self._media_session.try_skip_next_async()
                elif action == "prev":
                    await self._media_session.try_skip_previous_async()
            except Exception as e:
                print(f"[media] Action error: {e}")
        
        asyncio.run_coroutine_threadsafe(do_async(), self._media_loop)