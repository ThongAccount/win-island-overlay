"""WASAPI loopback capture with FFT for frequency band visualization."""
import numpy as np
import threading
import time
import struct
import pythoncom
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities

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
        pythoncom.CoInitialize()
        try:
            import pyaudiowpatch as pyaudio
            
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
            # Fallback: use simple peak meter
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
            pythoncom.CoUninitialize()
