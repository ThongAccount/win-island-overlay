# Project iWindows 17 — Dynamic Island

A Windows Dynamic Island-style overlay — a transparent, always-on-top pill widget at the top-center of the primary monitor, inspired by the iPhone 14 Pro Dynamic Island.

Built with **Python + PySide6 (Qt6)** for the backend overlay window, with plans for a **Svelte + Vite** frontend.

## Features

- **Pill-shaped overlay** with glassmorphism aesthetics (dark translucent background, subtle border)
- **Proximity hover detection** — micro-expands on cursor approach, full expansion on hover
- **Auto-hide on fullscreen** — hides when foreground app is maximized or covers the monitor (excludes desktop shell)
- **OBS Studio integration** — detects OBS process; shows idle (yellow) or recording (green) status dot
- **OBS notification** — 5-second animated notification when recording starts/stops, with auto-expand and fade
- **Media playback control** — detects Windows media sessions (Chrome, Spotify, etc.) via SMTC
- **Album art** — fetches thumbnail from the media session (falls back to ♪ symbol)
- **Playback controls** — prev, play/pause, next buttons with solid-filled icons, click-to-act
- **App name** — shows source app (e.g. "Chrome") above title
- **Audio visualizer** — 8-band FFT real-time frequency visualization (20Hz-20kHz) via WASAPI loopback
- **Windows toast notifications** — displays system notifications with app name, title, body, and timestamps
- **Smooth animations** — custom easing curves (InCubic+OutBack, InQuad+OutBack, InCubic) for expand/collapse/notification/hide
- **Zero CPU idle** — event-driven media detection via SMTC callbacks; polling only as backup
- **Click-through** — `WA_TransparentForMouseEvents` when collapsed, disabled on hover expansion
- **Hidden from Alt+Tab** — uses `Qt.Tool` flag

## Requirements

- Python 3.12+
- Windows 10/11 (uses Win32 API and Windows Runtime SDK via `winsdk`)

### Dependencies

| Package         | Version        | Purpose                                    |
|-----------------|----------------|--------------------------------------------|
| PySide6         | >= 6.5.0       | Qt6 widget, painting, animation            |
| pywin32         | >= 305         | Win32 API (window classes, etc)            |
| winsdk          | >= 1.0.0b1     | Windows Runtime (media SMTC, notifications)|
| pycaw           | >= 20240210    | Windows audio API                          |
| comtypes        | >= 1.2.0       | COM interface support                      |
| numpy           | >= 1.24.0      | FFT audio processing                       |
| pyaudiowpatch   | >= 0.2.12.5    | WASAPI loopback audio capture              |
| cairosvg        | (optional)     | SVG→PNG for OBS icon rendering             |
| pythoncom       | (bundled)      | COM apartment init for threads             |

## Installation

```powershell
cd F:\project-iwin-17\dynamic-island\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt
pip install cairosvg  # for OBS icon rendering
```

## Usage

```powershell
cd F:\project-iwin-17\dynamic-island
.\backend\.venv\Scripts\python.exe -m backend.main
```

The overlay appears at the top-center of your primary monitor. Hover near it to expand.

## Architecture

```
backend/
├── main.py            # Entry point — QApplication, plugin registry, auto-reload watcher
├── config.py          # WINDOW_CONFIG + PLUGIN_CONFIG (window geometry, plugin options)
├── core/
│   ├── overlay.py     # OverlayWindow (QWidget) — sole owner of paint + animations
│   ├── plugin.py      # PluginBase, @island_plugin decorator, PluginRegistry (lifecycle)
│   └── events.py      # EventBus + typed events (plugin/overlay signaling)
├── plugins/
│   ├── media.py       # SMTC now-playing + album art + FFT visualizer data
│   ├── obs.py         # OBS Studio process/session detection
│   ├── notifications.py  # Windows toast listener (UserNotificationListener)
│   ├── weather.py     # OpenWeatherMap current conditions + AQI
│   └── activity.py    # Foreground-window detection → context/profile switching
├── assets/
│   └── obs_icon.svg   # OBS Studio logo rendered via cairosvg
└── __init__.py

test_pages.py          # Offscreen overlay interaction tests
test_activity.py       # Offscreen activity plugin (mocked Windows API) test
test_obs.py            # Offscreen OBS plugin lifecycle test
requirements.txt       # Python dependencies
```

**Plugin model**: plugins are data/event sources. They run background monitors
(threads / asyncio / timers) and deliver results to the overlay, which owns all
rendering, geometry, and animation state (`backend/core/overlay.py`). Plugins
must not own competing island animations.

### OverlayWindow components

| Component                  | Mechanism                                        |
|----------------------------|--------------------------------------------------|
| Proximity detection        | 100ms QTimer, QCursor.pos(), hot zone            |
| Hover delay                | 200ms single-shot QTimer                         |
| Expand/collapse animation  | Shared QVariantAnimation (float 0→1) with custom easing |
| Sideswiper pages           | Hold-drag 250ms / fast drag >12px, 30% threshold flip, wheel |
| Fullscreen detection       | 500ms Win32 polling + class name exclusions      |
| OBS state                  | 2000ms process snapshot (CreateToolhelp32) + TCP table |
| Media detection            | Background asyncio thread with SMTC event callbacks |
| Audio visualizer           | FFT-based 8-band frequency analysis via WASAPI   |
| Toast notifications        | UserNotificationListener polling thread → postEvent |
| Playback controls          | mousePressEvent → winsdk async action           |

## Key Design Decisions

- **Event-driven over polling** for media detection: a dedicated asyncio thread keeps the SMTC manager alive and subscribes to `sessions_changed` events, firing instant callbacks. A 2-second poll timer acts as a fallback.
- **COM initialization** on background threads via `pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)` — required for winsdk async operations.
- **Thread-safe result delivery**: `QCoreApplication.postEvent()` (thread-safe, unlike `QTimer.singleShot` from non-Qt threads).
- **cairosvg over QSvgRenderer**: Qt's SVG renderer produces broken output for complex SVGs with clip-paths and radial gradients (OBS icon).
- **Custom easing** splits at 35%: InCubic (t³) + OutBack for collapse; InQuad (t²) + OutBack for notification.
- **`drawPolygon` over `drawPolyline`**: solid-filled triangles for playback buttons (avoids `isinstance` warnings with parameterized generics in PySide6).
