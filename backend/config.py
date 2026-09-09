# win-island-overlay config

from pathlib import Path

ROOT = Path(__file__).parent
VENVDIR = ROOT / ".venv"
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

# Window configuration
WINDOW_CONFIG = {
    'margin_top': 8,
    'micro_width': 240,
    'expanded_width': 480,
    'height': 48,
    'expand_duration': 500,
}

# Plugin configuration
PLUGIN_CONFIG = {
    'greeting': {
        'text': 'Hello! 👋',
        'font_size': 14,
        'color': '#ffffff',
        'duration_ms': 3000,
        'show_on_startup': True,
        'show_on_hover': True,
    },
}