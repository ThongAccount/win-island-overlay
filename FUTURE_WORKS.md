# Future Works

Planned features and enhancements for the Dynamic Island overlay.

## High Priority

### System Integration
- [ ] **System tray integration** — Right-click menu to toggle auto-start, adjust sensitivity, or quit
- [ ] **Battery indicator** — Show battery % and charging status for laptops, animate on low battery
- [ ] **Volume control** — Expand to show volume slider when system volume changes
- [ ] **Multi-monitor support** — Choose which monitor to display on
- [ ] **Keyboard shortcuts** — Global hotkey to expand/collapse

### Productivity
- [ ] **Calendar/time widget** — Click to expand and show upcoming events from Windows Calendar
- [ ] **Focus timer** — Pomodoro timer with break reminders
- [ ] **Quick notes** — Click to jot down quick text notes
- [ ] **Weather widget** — Current temp and condition icon
- [ ] **Network speed** — Show upload/download speed on network activity
- [ ] **Clipboard history** — Show recent clipboard items on Ctrl+C, click to paste

## Media Enhancements

- [ ] **Lyrics display** — Fetch and scroll synced lyrics during playback (Spotify/Apple Music)
- [ ] **Queue preview** — Show next 3 tracks in expanded state
- [ ] **Smooth app icon transitions** — Morph between different app icons when media source changes

## Notification Enhancements

**Note:** Current implementation uses Python `winsdk` which has limitations accessing full notification data.

### Current Status
- ✅ App name, title, body text
- ✅ Timestamps
- ✅ Dynamic height based on text wrapping
- ❌ Action buttons (not exposed by UserNotificationListener API)
- ❌ Image previews (not exposed by Python winsdk bindings)
- ❌ App launch on click (removed)

### Possible Solutions
1. **C# helper executable** (requires .NET runtime)
   - Full WinRT API access
   - Extract buttons, images, full XML
   - Output JSON to Python via stdout
   - **Blocker:** Requires .NET installation

2. **Alternative approach**
   - Custom notification system (apps send directly to overlay)
   - Focus on other features instead

### If C# Helper Implemented
- [ ] **Action buttons** — Display and invoke notification action buttons
- [ ] **Image previews** — Show hero images, app logos, inline images
- [ ] **App launch** — Click notification to open source app
- [ ] **Notification history** — Click to expand and show last 5 notifications
- [ ] **Priority filtering** — Only show high-priority notifications, filter by app

## Polish & Customization

- [ ] **Themes** — Light mode, custom colors, blur intensity
- [ ] **Configuration UI** — Settings panel for customization
- [ ] **Auto-start** — Launch on Windows startup
- [ ] **Performance monitoring** — CPU/RAM usage display
- [ ] **Animation presets** — Different easing curve options

## Technical Improvements

- [ ] **Svelte frontend** — Replace Qt painting with web-based UI
- [ ] **Plugin system** — Allow third-party extensions
- [ ] **IPC optimization** — Reduce latency for media updates
- [ ] **Memory optimization** — Reduce idle memory footprint
- [ ] **Crash recovery** — Auto-restart on unexpected errors

## Known Limitations

### Windows API Constraints
- **UserNotificationListener** (Python winsdk) doesn't expose:
  - Action buttons
  - Image elements
  - Full notification XML
  - Interactive callbacks
  
- **WASAPI loopback** requires audio to be playing
- **SMTC** only works with apps that implement media controls
- **Fullscreen detection** may not work with all games/apps

### Performance
- FFT audio processing adds ~2-5% CPU when music is playing
- Notification listener polls every 2-3 seconds
- OBS detection polls every 2 seconds

## Contributing

Feature requests and pull requests are welcome! Please check this document before implementing new features to avoid duplicate work.
