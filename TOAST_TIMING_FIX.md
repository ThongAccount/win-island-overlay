# Toast Timing Fix

**Date**: 2026-05-27
**Issue**: Toast dismisses too fast (10s → 5s), and on unhover it should restart timer instead of instant dismiss

## Changes Made

### 1. Added Toast Duration Constants (Line ~87)
```python
TOAST_DURATION = 5000  # 5 seconds for simple toasts
TOAST_DURATION_WITH_BUTTONS = 30000  # 30 seconds for actionable toasts
```

### 2. Fixed Unhover Behavior (Line ~563)
**Before**: Instant dismiss on unhover
```python
elif not in_zone and self._toast_hovered:
    self._toast_hovered = False
    self._toast_ignore_hover = True
    self._is_expanded = False
    self._expand_progress = 0.0
    self._dismiss_toast()  # ← Instant dismiss!
```

**After**: Restart timer on unhover
```python
elif not in_zone and self._toast_hovered:
    self._toast_hovered = False
    # Mouse left - restart the timer instead of instant dismiss
    duration = TOAST_DURATION_WITH_BUTTONS if self._toast_buttons else TOAST_DURATION
    self._toast_timer.start(duration)  # ← Restart timer
```

### 3. Updated Initial Timer (Line ~996)
```python
# Auto-dismiss: 30s if buttons, 5s otherwise
duration = TOAST_DURATION_WITH_BUTTONS if self._toast_buttons else TOAST_DURATION
self._toast_timer.stop()
self._toast_timer.start(duration)
```

## New Behavior

### Simple Toast (no buttons):
- **Initial display**: 5 seconds
- **On hover**: Timer stops, stays indefinitely
- **On unhover**: Timer restarts for another 5 seconds
- **Total**: Can stay visible as long as user keeps hovering

### Toast with Buttons:
- **Initial display**: 30 seconds
- **On hover**: Timer stops, stays indefinitely
- **On unhover**: Timer restarts for another 30 seconds
- **Total**: Can stay visible as long as user keeps hovering

## Benefits

1. ✅ **No instant dismiss**: Unhover restarts timer instead of dismissing immediately
2. ✅ **Hover keeps indefinitely**: User can read/interact without time pressure
3. ✅ **Reasonable default**: 5 seconds is enough for quick glance notifications
4. ✅ **Actionable toasts stay longer**: 30 seconds for toasts with buttons
5. ✅ **User-friendly**: Natural interaction pattern

## Test Scenarios

1. ✅ Show simple toast → Wait 5s → Dismisses
2. ✅ Show toast → Hover → Stays indefinitely
3. ✅ Show toast → Hover → Unhover → Wait 5s → Dismisses
4. ✅ Show toast → Hover → Unhover → Hover again → Stays indefinitely
5. ✅ Toast with buttons → Wait 30s → Dismisses
6. ✅ Toast with buttons → Hover → Unhover → Wait 30s → Dismisses
