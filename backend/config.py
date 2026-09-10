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
    'obs_extra_width': 40,
    'media_extra_width': 100,
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
    'media': {
        'show_album_art': True,
        'show_controls': True,
        'show_visualizer': True,
        'num_bands': 8,
        'visualizer_color': '#00ff88',
        'title_scroll_speed': 12000,
    },
    'obs': {
        'check_interval_ms': 2000,
        'show_notifications': True,
        'notification_duration_ms': 4000,
        'icon_size': 24,
    },
    'notifications': {
        'enabled_apps': [],  # Empty = all apps
        'blocked_apps': [],
        'max_toasts': 5,
        'toast_duration_ms': 5000,
        'toast_duration_with_buttons_ms': 30000,
        'show_icons': True,
        'show_buttons': True,
        'position': 'bottom',
    },
    'activity': {
        'check_interval_ms': 500,
        'profiles': {},  # User-defined profiles (merged with built-in)
        'auto_switch': True,
        'notify_on_switch': True,
        'default_profile': 'default',
    },
}