# Feature Roadmap — win-island-overlay

Sideswiper architecture shipped (`3d0e338`): active content stacks as pages in plugin load order; hold 250ms (or fast drag >12px) arms swipe, drag past 30% width flips, wheel flips too. New content pages append to `_active_pages()` in `backend/core/overlay.py`.

## Tiny
- [ ] **GIF greeter** — replaces weather slot; plugin loads GIF frames via `QImageReader` on startup/unlock, own swipeable page. Trigger on hover (activity plugin knows foreground)
- [ ] **Battery pill** — `ctypes` `GetSystemPowerStatus`, shows `87% ⚡` while charging. ~40 lines, zero deps
- [ ] **Rain-only weather** — weather panel dies; alert appears only if rain in next hour (OWM one-call, key already in config)
- [ ] **Deadline countdown chips** — config list of dates, island shows `3d to launch`

## Medium
- [ ] **Volume HUD** — pycaw `IAudioEndpointVolume` callback, island flashes volume bar like macOS. Reuses toast-slot motion
- [ ] **Lyrics ticker** — LRCLIB API (free, no key), media plugin's position tracking syncs the current line, scrolls in expanded island
- [ ] **Focus timer / pomodoro** — countdown ring on island; activity plugin's context system auto-starts when in "code" context
- [ ] **Eye-rest pulse** — every 20 min island does subtle pulse + "look away". One QTimer + one paint branch

## Bigger
- [ ] **Clipboard peek** — clipboard listener page; hover shows last 3 items, click copies back. Reuses `_btn_at` hit-rect pattern
- [ ] **Screenshot shutter** — `WH_KEYBOARD_LL` hook detects PrintScreen, island flashes white + saves path. Global-hook risk

## Suggested order
GIF greeter → volume HUD → battery pill → lyrics ticker (flashiest ROI first; first two reuse existing motion/paint slots)
