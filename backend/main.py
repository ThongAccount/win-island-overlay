import sys
import signal
import os
from pathlib import Path
from PySide6.QtCore import QTimer, QFileSystemWatcher
from PySide6.QtWidgets import QApplication

from .core.overlay import OverlayWindow
from .core.plugin import PluginRegistry
from .core.events import EventBus
from .plugins import discover_plugins


def load_config() -> dict:
    """Load configuration from config.py and optional user config."""
    config = {
        'window': {
            'margin_top': 8,
            'micro_width': 240,
            'expanded_width': 480,
            'height': 48,
            'expand_duration': 500,
        },
        'plugins': {},
    }

    # Load from config.py if exists
    config_path = Path(__file__).parent / "config.py"
    if config_path.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("backend.config", config_path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["backend.config"] = mod
            spec.loader.exec_module(mod)
            if hasattr(mod, 'PLUGIN_CONFIG'):
                config['plugins'].update(mod.PLUGIN_CONFIG)
            if hasattr(mod, 'WINDOW_CONFIG'):
                config['window'].update(mod.WINDOW_CONFIG)
        except Exception as e:
            print(f"[config] Failed to load config.py: {e}")

    return config


def main():
    app = QApplication(sys.argv)

    # Keep event loop responsive
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)

    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # Core systems
    event_bus = EventBus()
    config = load_config()
    registry = PluginRegistry(event_bus, config)

    # Discover and load plugins (do not enable yet — need window ref first)
    discover_plugins(registry)
    registry.load_all()

    # Create overlay before enabling plugins so on_enable can bind to it
    overlay = OverlayWindow(registry, config)
    registry.config['_window_ref'] = overlay

    # Now enable plugins (monitors/listeners start with a valid window)
    registry.enable_all()

    # Register plugins with overlay for paint/event integration
    for name in ['obs', 'media', 'notifications', 'weather', 'greeting', 'activity']:
        plugin = registry.get(name)
        if plugin:
            overlay.register_plugin(name, plugin)

    overlay._center()
    overlay.show()

    # Auto-reload on .py file changes
    watcher = QFileSystemWatcher()
    backend_dir = Path(__file__).parent
    for py_file in backend_dir.rglob("*.py"):
        watcher.addPath(str(py_file))

    def on_changed(path):
        print(f"[reload] {path} changed, restarting...")
        app.quit()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    watcher.fileChanged.connect(on_changed)
    overlay._watcher = watcher

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
