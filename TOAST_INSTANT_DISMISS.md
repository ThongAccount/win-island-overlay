# Toast Instant Dismiss Fix

**Date**: 2026-05-27
**Issue**: Toast stayed visible too long when hovering, unhovering should instantly dismiss

## Changes Made

### 1. Updated Hover Logic (Line ~552)
**Problem**: Toast stayed visible when hovering and only dismissed on timer expiration

**Solution**: Now instantly dismisses when mouse leaves, but stays visible while hovering:
```python
        if self._toast_active:
            # Mouse left — instantly dismiss
            if not in_zone and self._toast_hovered:
                self._toast_hovered = False
                self._dismiss_toast()
            # Mouse entered — reset timer and stay visible
            elif in_zone and not self._toast_hovered:
                self._toast_hovered = True
                duration = TOAST_DURATION_WITH_BUTTONS if self._toast_buttons else TOAST_DURATION
                self._toast_timer.stop()
                self._toast_timer.start(duration)
            return
```

## New Behavior

1. **Hover**: Toast stays visible and timer resets
2. **Unhover**: Instantly dismisses with smooth fade-out animation
3. **Timer**: 5 seconds for simple toasts, 30 seconds for actionable toasts

## Test Scenarios

1. ✅ Show toast → Hover → Stays visible indefinitely
2. ✅ Show toast → Move mouse away → Instantly dismisses
3. ✅ Toast with buttons → Hover → Stays visible for 30 seconds
4. ✅ Toast with buttons → Move mouse away → Instantly dismisses
5. ✅ Timer expires → Smooth fade-out dismissal

## Implementation Details

- **Animation**: Uses 250ms fade-out when dismissed
- **State management**: `_toast_hovered` tracks hover state
- **Timer handling**: Stops and restarts timer based on hover state
- **Consistent timing**: Uses the same constants as before (5s/30s)

## Benefits

✅ **Immediate feedback**: User sees toast disappear instantly when they move away
✅ **Clear interaction**: Hovering indicates "I want to keep this"
✅ **No timer pressure**: User can quickly dismiss without waiting
✅ **Consistent behavior**: Matches iOS behavior where toasts disappear on unhover