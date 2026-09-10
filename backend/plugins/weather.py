from typing import Dict, Any, Optional
import threading
import time
from PySide6.QtCore import QTimer, QEvent, Qt
from PySide6.QtWidgets import QLabel

from backend.core.plugin import PluginBase, island_plugin, PluginRegistry
from backend.core.events import EventBus
from backend.core.overlay import OverlayWindow, WeatherEvent


@island_plugin(
    name="weather",
    version="1.0.0",
    description="Weather notifications with current conditions, AQI, and location",
    author="win-island-overlay",
    dependencies=[],
    config_schema={
        "enabled": True,
        "api_key": "",  # OpenWeatherMap API key
        "location": "",  # Empty = auto-detect
        "update_interval_ms": 1800000,  # 30 minutes
        "duration_ms": 6000,
        "show_on_startup": False,
    },
    enabled_by_default=True,
)
class WeatherPlugin(PluginBase):
    def __init__(self, registry: PluginRegistry, config: Dict[str, Any]):
        super().__init__(registry, config)
        self._window: Optional[OverlayWindow] = None
        
        # Weather state (overlay owns rendering state)
        self._weather_data: Optional[Dict[str, Any]] = None
        self._weather_active = False
        self._weather_dismissed = False
        self._weather_hovered = False
        self._weather_alpha = 0.0
        self._weather_icon_progress = 0.0
        self._weather_text_alpha = 0.0
        
        # Timers
        self._weather_timer: Optional[QTimer] = None
        self._weather_icon_anim: Optional[QTimer] = None
        self._weather_text_anim: Optional[QTimer] = None
        self._update_thread: Optional[threading.Thread] = None
        self._running = False

    def on_load(self) -> None:
        pass

    def on_enable(self) -> None:
        self._window = self.registry.config.get('_window_ref')
        if not self._window:
            print("[weather] No window reference")
            return

        self._running = True
        
        # Initial fetch if enabled
        if self.config.get("show_on_startup", False):
            QTimer.singleShot(1000, self._fetch_weather)
        
        # Periodic updates
        interval = self.config.get("update_interval_ms", 1800000)
        self._weather_timer = QTimer(self._window)
        self._weather_timer.timeout.connect(self._fetch_weather)
        self._weather_timer.start(interval)

    def on_disable(self) -> None:
        self._running = False
        if self._weather_timer:
            self._weather_timer.stop()
        if self._weather_icon_anim:
            self._weather_icon_anim.stop()
        if self._weather_text_anim:
            self._weather_text_anim.stop()
        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=1.0)

    def on_unload(self) -> None:
        pass

    def _fetch_weather(self):
        """Fetch weather in background thread."""
        if self._update_thread and self._update_thread.is_alive():
            return
        self._update_thread = threading.Thread(target=self._do_weather_fetch, daemon=True)
        self._update_thread.start()

    def _do_weather_fetch(self):
        """Actual weather API call."""
        try:
            import requests
            api_key = self.config.get("api_key", "")
            location = self.config.get("location", "")
            
            if not api_key:
                # Mock data for testing
                data = {
                    'temp': '24',
                    'condition': 'Partly Cloudy',
                    'location': 'Your Location',
                    'feels_like': '22',
                    'humidity': '65',
                    'wind': '12 km/h',
                    'aqi': '42',
                    'aqi_level': 'Good',
                    'icon': '⛅'
                }
            else:
                base_url = "http://api.openweathermap.org/data/2.5/weather"
                params = {
                    'q': location or 'auto:ip',
                    'appid': api_key,
                    'units': 'metric'
                }
                
                response = requests.get(base_url, params=params, timeout=5)
                response.raise_for_status()
                data_json = response.json()
                
                weather_id = data_json['weather'][0]['id']
                icon = self._get_weather_icon(weather_id)
                
                # Get AQI
                aqi_data = self._get_aqi_data(api_key, data_json['coord']['lat'], data_json['coord']['lon'])
                
                data = {
                    'temp': str(int(data_json['main']['temp'])),
                    'condition': data_json['weather'][0]['main'],
                    'location': data_json['name'],
                    'feels_like': str(int(data_json['main']['feels_like'])),
                    'humidity': str(data_json['main']['humidity']),
                    'wind': f"{int(data_json['wind']['speed'] * 3.6)} km/h",
                    'aqi': str(aqi_data['aqi']),
                    'aqi_level': aqi_data['level'],
                    'icon': icon
                }
            
            QTimer.singleShot(0, lambda: self._on_weather(data))
            
        except Exception as e:
            print(f"[weather] Fetch error: {e}")

    def _get_weather_icon(self, weather_id: int) -> str:
        """Map OpenWeatherMap condition ID to emoji."""
        if weather_id < 300:
            return '⛈️'
        elif weather_id < 400:
            return '🌧️'
        elif weather_id < 600:
            return '🌧️'
        elif weather_id < 700:
            return '❄️'
        elif weather_id < 800:
            return '🌫️'
        elif weather_id == 800:
            return '☀️'
        elif weather_id == 801:
            return '🌤️'
        elif weather_id == 802:
            return '⛅'
        else:
            return '☁️'

    def _get_aqi_data(self, api_key: str, lat: float, lon: float) -> Dict[str, Any]:
        """Fetch Air Quality Index data."""
        try:
            url = "http://api.openweathermap.org/data/2.5/air_pollution"
            params = {'lat': lat, 'lon': lon, 'appid': api_key}
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            aqi = data['list'][0]['main']['aqi']
            levels = ['Good', 'Fair', 'Moderate', 'Poor', 'Very Poor']
            return {'aqi': aqi * 50, 'level': levels[aqi - 1] if 1 <= aqi <= 5 else 'Unknown'}
        except:
            return {'aqi': 0, 'level': 'Unknown'}

    def _on_weather(self, data: Dict[str, Any]):
        """Handle weather data on main thread."""
        if not self._window:
            return
        
        self._weather_data = data
        self._weather_dismissed = False
        
        # Show notification
        self._weather_active = True
        self._weather_alpha = 0.0
        self._weather_icon_progress = 0.0
        self._weather_text_alpha = 0.0
        self._weather_hovered = False
        
        self._animate_weather_icon(1.0, 300)
        self._animate_weather_text(1.0, 300)
        
        duration = self.config.get("duration_ms", 6000)
        QTimer.singleShot(duration, self._dismiss_weather)
        
        if self._window:
            self._window.update()

    def _dismiss_weather(self):
        if self._window and self._window.property("_is_expanded"):
            return  # Don't dismiss if expanded
        
        self._animate_weather_icon(0.0, 300)
        self._animate_weather_text(0.0, 300)
        self._weather_active = False
        self._weather_dismissed = True

    def _animate_weather_icon(self, target: float, duration: int):
        if self._weather_icon_anim:
            self._weather_icon_anim.stop()
        steps = 30
        step_val = (target - self._weather_icon_progress) / steps
        step_ms = duration // steps
        current = self._weather_icon_progress
        
        def step():
            nonlocal current
            current += step_val
            self._weather_icon_progress = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._weather_icon_progress = target
                self._weather_icon_anim.stop()
        
        self._weather_icon_anim = QTimer(self._window)
        self._weather_icon_anim.timeout.connect(step)
        self._weather_icon_anim.start(step_ms)

    def _animate_weather_text(self, target: float, duration: int):
        if self._weather_text_anim:
            self._weather_text_anim.stop()
        steps = 30
        step_val = (target - self._weather_text_alpha) / steps
        step_ms = duration // steps
        current = self._weather_text_alpha
        
        def step():
            nonlocal current
            current += step_val
            self._weather_text_alpha = max(0.0, min(1.0, current))
            if self._window:
                self._window.update()
            if (step_val > 0 and current >= target) or (step_val < 0 and current <= target):
                self._weather_text_alpha = target
                self._weather_text_anim.stop()
        
        self._weather_text_anim = QTimer(self._window)
        self._weather_text_anim.timeout.connect(step)
        self._weather_text_anim.start(step_ms)

    # --- Data getters for overlay ---
    def is_active(self) -> bool:
        return self._weather_active and self._weather_alpha > 0

    def get_weather_data(self) -> Optional[Dict[str, Any]]:
        return self._weather_data

    def get_alpha(self) -> float:
        return self._weather_alpha

    def get_icon_progress(self) -> float:
        return self._weather_icon_progress

    def get_text_alpha(self) -> float:
        return self._weather_text_alpha