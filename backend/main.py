import sys
import signal
import os
from pathlib import Path
from PySide6.QtCore import QTimer, QFileSystemWatcher
from PySide6.QtWidgets import QApplication

from core.overlay import OverlayWindow
from core.plugin import PluginRegistry
from core.events import EventBus
from plugins import discover_plugins


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
            spec = __import__('config', fromlist=['*'])
            if hasattr(spec, 'PLUGIN_CONFIG'):
                config['plugins'].update(spec.PLUGIN_CONFIG)
            if hasattr(spec, 'WINDOW_CONFIG'):
                config['window'].update(spec.WINDOW_CONFIG)
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

    # Discover and load plugins
    discover_plugins(registry)
    registry.load_all()
    registry.enable_all()

    # Create overlay window
    overlay = OverlayWindow(registry, config)

    # Register plugins with overlay for paint/event integration
    for name in ['obs', 'media', 'notifications', 'greeting', 'activity']:
        plugin = registry.get(name)
        if plugin:
            overlay.register_plugin(name, plugin)

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