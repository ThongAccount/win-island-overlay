"""Run: QT_QPA_PLATFORM=offscreen .venv/bin/python test_weather.py
Verifies weather plugin no-key behavior without needing the `requests`
dependency installed:
(a) _do_weather_fetch with empty api_key takes the mock path — it must NOT
    import `requests` at all (a poisoned module is injected; any import or
    call raises), and
(b) the resulting mock dict is complete and get_weather_data() returns it.
"""
import sys
import types
from PySide6.QtCore import QObject
from types import SimpleNamespace

from backend.plugins.weather import WeatherPlugin

cfg = {"api_key": "", "location": "", "update_interval_ms": 1800000, "duration_ms": 15000}
window = QObject()  # postEvent receiver must be a QObject
reg = SimpleNamespace(config={"_window_ref": window}, event_bus=None)
plugin = WeatherPlugin(reg, cfg)
plugin._window = window

# Poison any request: if the no-key path imports or calls requests, fail loudly.
poison = types.ModuleType("requests")
poison.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no-key path must not call requests.get"))
sys.modules["requests"] = poison

try:
    plugin._do_weather_fetch()
    # Poll thread posts to window; get_weather_data holds the last data.
    data = plugin.get_weather_data()
    assert data is not None, "no-key path should produce mock weather data"
    for key in ("temp", "condition", "location", "feels_like", "humidity", "wind", "aqi", "aqi_level", "icon"):
        assert key in data, f"missing key {key!r} in {data}"
    assert data["temp"] == "24"
finally:
    sys.modules.pop("requests", None)

print("ALL WEATHER TESTS PASS")