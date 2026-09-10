from typing import Dict, Any, Optional
import threading
import asyncio
from PySide6.QtCore import QTimer, QEvent, Qt, QRect
from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPainterPath, QImage

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus, MediaSessionChanged, WindowStateChanged
from backend.core.overlay import OverlayWindow


# Custom event for media updates from background thread
class MediaResultEvent(QEvent):
    _type = QEvent.Type(QEvent.registerEventType())

    def __init__(self, result):
        super().__init__(self._type)
        self.result = result  # (title, artist, app_name, status, thumb_bytes, pos, dur, session)


# Audio FFT capture (extracted from old overlay)
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

    def _capture_loop(self):
        try:
            import pyaudiowpatch as pyaudio
            import numpy as np
            import comtypes
            comtypes.CoInitialize()
            
            p = pyaudio.PyAudio()
            # Find WASAPI loopback device
            device_index = None
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if 'WASAPI' in info.get('name', '') and info.get('maxInputChannels', 0) > 0:
                    device_index = i
                    break
            
            if device_index is None:
                print("[media] No WASAPI loopback device found")
                return

            stream = p.open(
                format=pyaudio.paFloat32,
                channels=2,
                rate=44100,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=1024,
            )

            while self._running:
                data = stream.read(1024, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                if len(audio) < 1024:
                    continue
                # Stereo to mono
                audio = audio.reshape(-1, 2).mean(axis=1)
                # FFT
                fft = np.fft.rfft(audio)
                mag = np.abs(fft)
                # Split into bands
                band_size = len(mag) // self.num_bands
                for i in range(self.num_bands):
                    start = i * band_size
                    end = start + band_size
                    if end <= len(mag):
                        self.bands[i] = float(np.mean(mag[start:end]) * 10.0)
                        # Clamp
                        if self.bands[i] > 1.0:
                            self.bands[i] = 1.0
        except Exception as e:
            print(f"[media] Audio FFT error: {e}")
        finally:
            try:
                stream.stop_stream()
                stream.close()
                p.terminate()
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
        
        # Media state
        self._media_state = 0  # 0=none, 1=playing, 2=paused
        self._media_title = ""
        self._media_artist = ""
        self._media_app = ""
        self._media_thumb_bytes = b""
        self._media_pos = 0.0
        self._media_dur = 0.0
        self._media_session = None
        self._media_loop = None
        self._media_seq = 0
        self._media_thumb_pixmap: Optional[QPixmap] = None
        
        # Visualizer
        self._audio_fft: Optional[AudioFFT] = None
        self._viz_timer: Optional[QTimer] = None
        
        # Animation
        self._media_alpha = 0.0
        self._media_text_alpha = 0.0
        self._title_scroll = 0.0
        self._title_scroll_anim: Optional[QTimer] = None
        self._media_alpha_anim: Optional[QTimer] = None
        self._media_text_anim: Optional[QTimer] = None
        
        # UI
        self._title_label: Optional[QLabel] = None
        self._artist_label: Optional[QLabel] = None
        self._thumb_label: Optional[QLabel] = None
        
        # Threading
        self._media_thread: Optional[threading.Thread] = None

    def on_load(self) -> None:
        pass

    def on_enable(self) -> None:
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[media] No window reference")
            return

        # Setup visualizer
        if self.config.get("show_visualizer", True):
            self._audio_fft = AudioFFT(num_bands=self.config.get("num_bands", 8))
            self._audio_fft.start()
            
            self._viz_timer = QTimer(self._window)
            self._viz_timer.timeout.connect(self._update_viz)
            self._viz_timer.start(80)  # ~12.5 FPS

        # Start SMTC monitor thread
        self._media_thread = threading.Thread(target=self._media_monitor_thread, daemon=True)
        self._media_thread.start()

        # Subscribe to window state for resize triggers
        self._unsub_state = self.registry.event_bus.subscribe(
            WindowStateChanged, self._on_window_state
        )

    def on_disable(self) -> None:
        if hasattr(self, '_unsub_state'):
            self._unsub_state()
        if self._viz_timer:
            self._viz_timer.stop()
        if self._audio_fft:
            self._audio_fft.stop()
        if self._media_loop:
            self._media_loop.call_soon_threadsafe(self._media_loop.stop)
        # Cleanup UI
        for attr in ['_title_label', '_artist_label', '_thumb_label']:
            widget = getattr(self, attr)
            if widget:
                widget.deleteLater()
                setattr(self, attr, None)

    def on_unload(self) -> None:
        pass

    def _on_window_state(self, event: WindowStateChanged) -> None:
        if event.state in ("expanded", "hover") and self._media_state > 0:
            # Trigger resize to expanded layout
            QTimer.singleShot(0, self._delayed_media_resize)

    def _update_viz(self) -> None:
        if self._media_state == 0 or not self._audio_fft:
            return
        if self._window:
            self._window.update()  # Trigger repaint for visualizer

    def _media_monitor_thread(self):
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._media_loop = loop
        
        async def run_monitor():
            try:
                from winsdk.windows.media.control import (
                    GlobalSystemMediaTransportControlsSessionManager,
                    GlobalSystemMediaTransportControlsSessionPlaybackStatus
                )
                mgr = await GlobalSystemMediaTransportControlsSessionManager.request_async()
                
                # Initial query
                await self._query_and_post(loop, mgr, is_poll=False)
                
                # Poll every 500ms
                while self._running:
                    await asyncio.sleep(0.5)
                    if not self._running:
                        break
                    await self._query_and_post(loop, mgr, is_poll=True)
            except Exception as e:
                print(f"[media] Monitor error: {e}")
        
        loop.run_until_complete(run_monitor())

    async def _query_and_post(self, loop, mgr, is_poll=True):
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionPlaybackStatus
            )
            
            sessions = []
            current = mgr.get_current_session()
            if current:
                sessions.append(current)
            
            # Get all sessions
            try:
                all_sessions = mgr.get_sessions()
                for s in all_sessions:
                    if s not in sessions:
                        sessions.append(s)
            except:
                pass

            for session in sessions:
                try:
                    info = await session.try_get_media_properties_async()
                    playback = session.get_playback_info()
                    
                    if playback.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
                        status = "playing"
                    elif playback.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED:
                        status = "paused"
                    else:
                        continue  # Skip stopped/closed
                    
                    title = str(info.title) if info.title else "Unknown"
                    artist = str(info.artist) if info.artist else ""
                    app_name = str(session.source_app_user_model_id) if session.source_app_user_model_id else "Unknown"
                    
                    # Thumbnail
                    thumb_bytes = b""
                    if info.thumbnail:
                        try:
                            thumb_ref = info.thumbnail
                            stream = await asyncio.wait_for(thumb_ref.open_read_async(), timeout=3.0)
                            from winsdk.windows.storage.streams import DataReader
                            reader = DataReader(stream)
                            size = stream.size
                            await reader.load_async(size)
                            thumb_bytes = reader.read_buffer(size)
                        except:
                            pass
                    
                    # Position
                    try:
                        timeline = playback.playback_position
                        pos_sec = timeline.duration / 10_000_000 if timeline else 0
                    except:
                        pos_sec = 0
                    
                    try:
                        dur_sec = info.playback_duration / 10_000_000 if info.playback_duration else 0
                    except:
                        dur_sec = 0
                    
                    self._media_seq += 1
                    seq = self._media_seq
                    
                    # Post result to main thread
                    def post_result():
                        if seq == self._media_seq:  # Still current
                            QApplication.postEvent(self._window, MediaResultEvent((
                                title, artist, app_name, status, thumb_bytes, pos_sec, dur_sec, session
                            )))
                    
                    # Run on main thread
                    import ctypes
                    ctypes.windll.user32.PostThreadMessageW(
                        ctypes.windll.kernel32.GetCurrentThreadId(),
                        0x0400 + 1,  # Custom message
                        0, 0
                    )
                    # Actually use QTimer.singleShot for thread safety
                    QTimer.singleShot(0, post_result)
                    
                    return  # Only report first active session
                    
                except Exception as e:
                    print(f"[media] Session query error: {e}")
                    continue
            
            # No active session
            if is_poll and self._media_state > 0:
                QTimer.singleShot(0, lambda: self._on_media_result(("", "", "", "stopped", b"", 0, 0, None)))
                
        except Exception as e:
            print(f"[media] Query error: {e}")

    def _on_media_result(self, result) -> None:
        """Handle media result from background thread."""
        if not self._window:
            return
            
        title, artist, app_name, status, thumb_bytes, pos_sec, dur_sec, session = result
        
        new_state = 0
        if status == "playing":
            new_state = 1
        elif status == "paused":
            new_state = 2
        
        changed = (
            new_state != self._media_state or
            title != self._media_title or
            artist != self._media_artist or
            app_name != self._media_app
        )
        
        self._media_state = new_state
        self._media_title = title
        self._media_artist = artist
        self._media_app = app_name
        self._media_pos = pos_sec
        self._media_dur = dur_sec
        self._media_session = session
        
        if thumb_bytes and thumb_bytes != self._media_thumb_bytes:
            self._media_thumb_bytes = thumb_bytes
            self._load_thumbnail(thumb_bytes)
        
        if changed:
            # Animate in/out
            if new_state > 0:
                self._start_media_fade_in()
            else:
                self._start_media_fade_out()
            
            # Publish event for other plugins
            self.registry.event_bus.publish(MediaSessionChanged(
                playing=(new_state == 1),
                title=title,
                artist=artist,
                album_art=self._media_thumb_bytes
            ))
        
        if self._window:
            self._window.update()

    def _load_thumbnail(self, thumb_bytes: bytes):
        if not thumb_bytes:
            self._media_thumb_pixmap = None
            return
        try:
            img = QImage.fromData(thumb_bytes)
            if not img.isNull():
                self._media_thumb_pixmap = QPixmap.fromImage(img).scaled(
                    48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
        except:
            self._media_thumb_pixmap = None

    def _start_media_fade_in(self):
        # Simple alpha animation using timer
        self._media_alpha = 0.0
        self._media_text_alpha = 0.0
        self._animate_media_alpha(1.0, 300)
        self._animate_media_text_alpha(1.0, 300)
        self._start_title_scroll()

    def _start_media_fade_out(self):
        self._animate_media_alpha(0.0, 300)
        self._animate_media_text_alpha(0.0, 300)

    def _animate_media_alpha(self, target: float, duration: int):
        if self._media_alpha_anim:
            self._media_alpha_anim.stop()
        self._media_alpha_anim = QTimer(self._window)
        steps = 30
        step_val = (target - self._media_alpha) / steps
        step_ms = duration // steps
        current = self._media_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._media_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._media_alpha = target
                self._media_alpha_anim.stop()
        
        self._media_alpha_anim.timeout.connect(step)
        self._media_alpha_anim.start(step_ms)

    def _animate_media_text_alpha(self, target: float, duration: int):
        if self._media_text_anim:
            self._media_text_anim.stop()
        self._media_text_alpha = 0.0
        steps = 30
        step_val = (target - self._media_text_alpha) / steps
        step_ms = duration // steps
        current = self._media_text_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._media_text_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._media_text_alpha = target
                self._media_text_anim.stop()
        
        self._media_text_anim.timeout.connect(step)
        self._media_text_anim.start(step_ms)

    def _start_title_scroll(self):
        if self._title_scroll_anim:
            self._title_scroll_anim.stop()
        self._title_scroll = 0.0
        # Scroll over 12 seconds
        self._title_scroll_anim = QTimer(self._window)
        self._title_scroll_anim.timeout.connect(lambda: self._window.update() if self._window else None)
        self._title_scroll_anim.start(16)  # 60 FPS for smooth scroll

    def _delayed_media_resize(self):
        if self._window and not self._window.property("_hidden_by_fullscreen"):
            # Window will handle its own resize based on media state
            pass

    def get_media_state(self) -> int:
        return self._media_state

    def get_media_info(self) -> Dict[str, Any]:
        return {
            "state": self._media_state,
            "title": self._media_title,
            "artist": self._media_artist,
            "app": self._media_app,
            "position": self._media_pos,
            "duration": self._media_dur,
            "thumb_pixmap": self._media_thumb_pixmap,
        }

    def get_visualizer_bands(self) -> list:
        if self._audio_fft:
            return self._audio_fft.bands[:]
        return [0.0] * self.config.get("num_bands", 8)

    def get_alpha(self) -> float:
        return self._media_alpha

    def get_text_alpha(self) -> float:
        return self._media_text_alpha

    def get_title_scroll(self) -> float:
        return self._title_scroll

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
                elif action == "seek" and seek_seconds is not None:
                    from winsdk.windows.foundation import TimeSpan
                    ts = TimeSpan(int(seek_seconds * 10_000_000))
                    await self._media_session.try_change_playback_position_async(ts)
            except Exception as e:
                print(f"[media] Action error: {e}")
        
        asyncio.run_coroutine_threadsafe(do_async(), self._media_loop)

    def paint_media(self, painter: QPainter, rect: QRect, is_expanded: bool):
        """Called from OverlayWindow.paintEvent to render media UI."""
        if self._media_state == 0 or self._media_alpha <= 0:
            return
        
        painter.save()
        painter.setOpacity(self._media_alpha)
        
        # Album art
        if self.config.get("show_album_art", True) and self._media_thumb_pixmap:
            thumb_rect = QRect(rect.left() + 12, rect.top() + 12, 48, 48)
            painter.drawPixmap(thumb_rect, self._media_thumb_pixmap)
        
        # Title/artist text
        if self._media_text_alpha > 0:
            painter.setOpacity(self._media_text_alpha)
            font = QFont("Segoe UI", 10, QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 230))
            
            text_x = rect.left() + 72
            text_y = rect.top() + 18
            
            # Scroll long titles
            title_text = self._media_title
            if self._media_artist:
                title_text += f" — {self._media_artist}"
            
            metrics = painter.fontMetrics()
            text_width = metrics.horizontalAdvance(title_text)
            available = rect.width() - 84
            
            if text_width > available:
                # Scroll
                scroll = self._title_scroll % (text_width + available + 50)
                draw_x = text_x - scroll
                painter.drawText(draw_x, text_y, title_text)
                # Draw second copy for seamless loop
                painter.drawText(draw_x + text_width + 50, text_y, title_text)
            else:
                painter.drawText(text_x, text_y, title_text)
            
            # Playback status
            status_text = "Now Playing" if self._media_state == 1 else "Paused"
            painter.setPen(QColor(180, 180, 180, 200))
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(text_x, text_y + 18, status_text)
        
        # Visualizer bars
        if self.config.get("show_visualizer", True) and self._audio_fft:
            bands = self._audio_fft.bands
            bar_w = 4
            gap = 2
            total_w = len(bands) * (bar_w + gap) - gap
            start_x = rect.right() - total_w - 12
            base_y = rect.bottom() - 8
            max_h = rect.height() - 20
            
            color = QColor(self.config.get("visualizer_color", "#00ff88"))
            for i, band in enumerate(bands):
                h = int(band * max_h)
                x = start_x + i * (bar_w + gap)
                painter.fillRect(x, base_y - h, bar_w, h, color)
        
        # Playback controls (expanded only)
        if is_expanded and self.config.get("show_controls", True):
            self._paint_controls(painter, rect)
        
        painter.restore()

    def _paint_controls(self, painter: QPainter, rect: QRect):
        """Paint playback controls in expanded mode."""
        btn_size = 28
        spacing = 16
        total_w = 5 * btn_size + 4 * spacing
        start_x = (rect.width() - total_w) // 2
        y = rect.bottom() - btn_size - 8
        
        icons = ["⏮", "⏪", "⏸" if self._media_state == 1 else "▶", "⏩", "⏭"]
        actions = ["prev", "rewind", "play_pause", "forward", "next"]
        
        for i, (icon, action) in enumerate(zip(icons, actions)):
            x = start_x + i * (btn_size + spacing)
            btn_rect = QRect(x, y, btn_size, btn_size)
            
            # Highlight hover (simplified - would need mouse tracking)
            painter.setPen(QColor(255, 255, 255, 100))
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.drawRoundedRect(btn_rect, 14, 14)
            
            # Icon
            font = QFont("Segoe UI Emoji", 14)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 220))
            painter.drawText(btn_rect, Qt.AlignmentFlag.AlignCenter, icon)
            
            # Store rect for hit testing
            if not hasattr(self, '_control_rects'):
                self._control_rects = []
            while len(self._control_rects) <= i:
                self._control_rects.append(QRect())
            self._control_rects[i] = btn_rect

    def handle_click(self, pos) -> bool:
        """Handle click on media controls. Returns True if handled."""
        if not hasattr(self, '_control_rects'):
            return False
        for i, rect in enumerate(self._control_rects):
            if rect.contains(pos):
                actions = ["prev", "rewind", "play_pause", "forward", "next"]
                if i < len(actions):
                    self.do_action(actions[i])
                    return True
        return False