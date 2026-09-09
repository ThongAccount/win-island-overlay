# Project iWindows 17 — Development Plan

## Status Overview

| Area           | Status       | Notes                                      |
|----------------|--------------|--------------------------------------------|
| Backend        | Functional   | Single-file `overlay.py` (~950 lines)      |
| OBS integration| Complete     | Detection + notifications + status dot     |
| Media playback | Complete     | SMTC detection + controls + timeline + viz |
| Animations     | Complete     | Expand/collapse, fade, notification        |
| Frontend       | Scaffold     | Empty Svelte project, not wired            |
| Windows helper | Stale        | `windows.py` not used                      |
| Media helper   | Stale        | `media.py` not used (logic in overlay.py)  |
| Config         | Empty        | `config.py` exists but unused              |

---

## ✅ Complete

### Overlay Window
- [x] Transparent, frameless, always-on-top pill widget
- [x] `Qt.Tool` flag to hide from Alt+Tab
- [x] Rounded corners (20px radius), dark glassmorphism background
- [x] Subtle white border (alpha 25)
- [x] `WA_TransparentForMouseEvents` for click-through when collapsed
- [x] Disables click-through when expanded (mouse events for buttons)

### Animation
- [x] QVariantAnimation (float 0→1) for sub-pixel geometry interpolation
- [x] Micro-expand (260px) on zone entry with InQuad (200ms)
- [x] Full expansion (400px) with OutBack (400ms)
- [x] Collapse with InCubic+OutBack custom split ease (600ms)
- [x] Instant `_reset_collapsed` for fullscreen restore
- [x] OBS icon fade-in/out (50% of OBS_ANIM_DURATION)
- [x] Notification expand with InQuad+OutBack (400ms)
- [x] Text-only fade during notification (50% timing)
- [x] Media text fade on title/artist change (300ms, 0→1)

### Proximity Detection
- [x] 100ms QTimer polling `QCursor.pos()`
- [x] Hot zone: `geo.adjusted(-5, -5, 5, 30)`
- [x] 200ms hover delay before full expansion
- [x] Collapse when cursor leaves zone

### Fullscreen Detection
- [x] 500ms Win32 polling via `GetForegroundWindow`
- [x] Checks `SW_SHOWMAXIMIZED` and window rect vs monitor rect
- [x] Excludes desktop shell by class name: `Progman`, `WorkerW`, `SysListView32`, `#32769`
- [x] Excludes own window and desktop handle
- [x] Instantly hides overlay, restores on exit fullscreen

### OBS Studio Integration
- [x] Process enumeration via `CreateToolhelp32Snapshot`
- [x] Detects `obs64.exe`/`obs32.exe` (idle = yellow dot)
- [x] Detects `obs-ffmpeg-mux.exe` (recording = green dot)
- [x] Three-state machine: 0=inactive, 1=idle, 2=recording
- [x] OBS icon rendered from SVG via cairosvg (64×64 base, scaled at draw)
- [x] Island widens by 50px when OBS is active
- [x] Recording start/stop notifications (520×85, 5s auto-dismiss)
- [x] Larger OBS icon (32px) + text + status dot in notification

### Media Playback Detection
- [x] Background COM/asyncio thread keeps SMTC manager alive
- [x] Event-driven via `sessions_changed` callback → instant updates
- [x] 2-second poll timer as fallback
- [x] Thread-safe result delivery via `QCoreApplication.postEvent`
- [x] Detects playing/paused states
- [x] Fetches media properties (title, artist, app name)
- [x] Fetches thumbnail (async with 2s timeout, fallback to ♪)
- [x] Fetches timeline (position + duration)
- [x] Stops session reference for playback control

### Media UI — Collapsed
- [x] Shows 18px thumbnail (or ♪ fallback) on left
- [x] Truncated title text
- [x] 5-bar mirrored visualizer on right side
- [x] Island widens by 120px when media is active

### Media UI — Expanded (120px height)
- [x] 40px thumbnail (or ♪ fallback)
- [x] App name (e.g. "Chrome") stripped of `.exe`, capitalized
- [x] Title (11pt bold, with fade animation)
- [x] Artist (9pt)
- [x] Prev / play-pause / next buttons (solid-filled triangles/pause bars)
- [x] 5-bar mirrored visualizer between text and buttons
- [x] Progress bar (3px height, blue fill)
- [x] Elapsed / total time labels (7pt)
- [x] Position interpolation via 500ms timer

### Playback Controls
- [x] `mousePressEvent` hit-tests button regions
- [x] Background thread with COM init calls winsdk API
- [x] `try_play_async` / `try_pause_async` / `try_skip_next_async` / `try_skip_previous_async`

### Audio Visualizer
- [x] 5 bars, random target heights (0.1–1.0), smooth interpolation (speed 0.15)
- [x] Mirrored (bars extend above and below centerline, total height = 2×h)
- [x] 80ms update timer
- [x] Only triggers `update()` when bars change

---

## 🔧 In Progress / Needs Polish

- [ ] **Layout polish** — buttons/visualizer/timeline positioning may need tuning for different island widths

---

## ✅ Recently Fixed

- [x] **Thumbnail stream timeout** — root cause: `CoInitializeEx(COINIT_APARTMENTTHREADED)` on media thread breaks `open_read_async`; removed COM init from monitor thread, restored `DataReader` path
- [x] **Session selection bug** — empty-title sessions no longer block other sessions (`break` → `continue`); sessions sorted by playing > paused
- [x] **Playback button feedback** — hover and press states on prev/play/next buttons
- [x] **Progress bar seeking** — click progress bar to seek via `try_change_playback_position_async`
- [x] **Notification + media overlap** — dismiss restores correct collapsed width/height (includes media/OBS extras); hover state cleared on notification

---

## ❌ Blocked

- [ ] **Frontend integration** — Svelte + Vite scaffold exists but is empty. The `fronend/` dir has placeholder files only. The original plan was for HTML/CSS/JS dynamic content rendered in a web view, but the backend currently does all rendering with QPainter. Decision needed: keep QPainter or switch to QWebEngineView.
- [ ] **Config system** — `config.py` is empty. No command-line args or config file for customization (hot zone, sizes, durations, colors).

---

## 📋 Backlog / Future Ideas

### Short-term
- [x] Save thumbnail bytes as QByteArray to avoid re-fetching (cache)
- [x] Add hover/press feedback to playback buttons
- [x] Seek support on progress bar click
- [ ] Pulse animation for recording state (OBS)
- [ ] Handle edge cases: no OBS + media paused + fullscreen
- [ ] Graceful shutdown of media monitor thread

### Medium-term
- [ ] Try to fix thumbnail fetch (maybe use `thumbcache.dll` or direct file access)
- [ ] Configurable hot zone size and animation durations
- [ ] Multi-monitor support (choose monitor)
- [ ] Add control center (like iPhone) with volume/brightness sliders
- [ ] Add system tray icon with quit toggle
- [ ] Notification queue (prevent overlap of OBS + media events)

### Long-term
- [ ] Web-based frontend via QWebEngineView with Svelte
- [ ] Plugins / extensibility API
- [ ] Custom themes / accent colors
- [ ] Linux support (replace Win32 API with XDG/Wayland equivalents)

---

## Known Issues

1. **OBS icon shown as media thumbnail** — fixed: the expanded view now uses ♪ fallback instead of `self._obs_pixmap`
2. **`drawPolyline` crashes with tuple points** — fixed: uses `QPoint` objects and `drawPolygon` for solid shapes
3. **`QTimer.singleShot` from non-Qt thread** — fixed: replaced with `QCoreApplication.postEvent` (thread-safe)
4. **COM not initialized in worker threads** — fixed: added `pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)`
5. **Thumbnail `read_bytes` needed bytearray** — fixed: changed from `await reader.read_bytes(list)` to `reader.read_bytes(bytearray)`
6. **Free desktop clicks hide island** — fixed: added class name exclusions for `Progman`, `WorkerW`, etc.
7. **OBS window title doesn't contain "studio"** — fixed: switched from window title matching to process-based detection
8. **Session loop breaks on empty metadata** — fixed: `continue` instead of `break`; prioritize current/playing session
9. **Thumbnail fetch hangs** — fixed: `Buffer.read_async` + cache; session ordering improved
10. **Progress bar read-only** — fixed: click-to-seek via SMTC `try_change_playback_position_async`
11. **No button hover/press feedback** — fixed: mouse move/release handlers with visual states
12. **Notification dismiss ignores media width** — fixed: dismiss animates to dynamic `_collapsed` size

---

## Test Commands

```powershell
cd F:\project-iwin-17\dynamic-island\backend
.\venv\Scripts\python.exe main.py
```

No formal test framework is set up yet. Manual testing via the overlay window.

---

## Tech Stack Decisions Log

| Decision | Chosen | Rejected | Reason |
|----------|--------|----------|--------|
| GUI framework | PySide6 (Qt6) | Tkinter, wxPython | Animations, transparency, layers |
| Media API | winsdk (SMTC) | Audio session queries | Broader app support (Chrome, Spotify, etc.) |
| SVG rendering | cairosvg | QSvgRenderer | Qt produces broken output for complex SVGs |
| Click-through | WA_TransparentForMouseEvents | WS_EX_TRANSPARENT | Per-widget control |
| Event delivery to Qt | QCoreApplication.postEvent | QTimer.singleShot | Thread safety on non-Qt threads |
| Threading | daemon threading.Thread | QThread | Simpler lifecycle |
| Button icons | Solid-filled drawPolygon | drawPolyline outlines | No `isinstance` warnings, better looks |
| Media polling | SMTC event callbacks + fallback timer | Pure polling (2s) | Lower latency |
