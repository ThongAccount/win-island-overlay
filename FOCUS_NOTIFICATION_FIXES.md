# Focus Change and Notification Override Fixes

**Date**: 2026-05-27
**Issues Fixed**:
1. Changing focus (fullscreen state change) causes unwanted island collapse
2. Notifications don't override hide state and expand state properly

## Bug 1: Focus Change Causes Unwanted Collapse

### Problem
When switching between fullscreen and windowed mode, the island would collapse even when a toast or notification was active, interrupting the user's interaction.

### Root Cause
The `_check_fullscreen()` method in the "exiting fullscreen" branch (line ~640-655) would always collapse the island without checking if a toast or notification was active.

### Solution
Added checks to prevent collapse when toast or notification is active:

```python
else:
    if self._hidden_by_fullscreen:
        self._hidden_by_fullscreen = False
        
        # Don't collapse if toast or notification is active
        if self._toast_active or self._notification_active:
            # Keep current state, just mark as no longer hidden
            return
        
        # ... normal collapse animation
```

## Bug 2: Notification Doesn't Override Hide State

### Problem
When showing a notification (OBS recording start/stop), it didn't properly override the hide state, causing the notification to not appear when the island was in fullscreen dodge mode.

### Root Cause
`_show_notification()` didn't reset `_hidden_by_fullscreen` or `_is_hiding` flags, and didn't ensure the widget was visible.

### Solution
Added explicit state overrides at the start of `_show_notification()`:

```python
def _show_notification(self, notif_type):
    print(f"Showing OBS notification: type={notif_type}")
    self._notification_active = True
    self._notification_type = notif_type
    
    # OVERRIDE: Force visible state and full expansion
    self._hidden_by_fullscreen = False
    self._is_hiding = False
    self._is_expanded = True
    self._expand_progress = 1.0
    self._hover_pending = False
    self._hover_timer.stop()
    self._hovered_btn = -1
    self._pressed_btn = -1
    self._notif_timer.stop()
    
    # Show if hidden
    if not self.isVisible():
        w, h = self._expanded
        screen = QApplication.primaryScreen().geometry()
        x = int((screen.width() - w) / 2.0)
        self.setGeometry(x, int(MARGIN_TOP), int(w), int(h))
        self.show()
    
    # ... rest of notification setup
```

## Changes Made

### File: backend/overlay.py

#### Change 1: _show_notification() method (lines ~393-428)
- Added `_hidden_by_fullscreen = False` to override hide state
- Added `_is_hiding = False` to cancel any ongoing hide animation
- Added visibility check and `self.show()` if widget is hidden
- Properly positions widget before showing

#### Change 2: _check_fullscreen() method (lines ~627-670)
- Added check for `self._notification_active` in fullscreen entry
- Added early return when exiting fullscreen if toast or notification is active
- Prevents unwanted collapse during active user interactions

## Expected Behavior After Fix

### Scenario 1: Notification During Fullscreen
1. User has fullscreen window open (island is hidden)
2. OBS starts recording → Notification appears
3. ✅ Island shows with notification, overriding hide state
4. User switches to windowed mode
5. ✅ Island stays expanded with notification visible
6. Notification timer expires
7. ✅ Island collapses normally

### Scenario 2: Toast During Focus Changes
1. Toast is showing
2. User maximizes a window
3. ✅ Island stays visible with toast (doesn't collapse)
4. User restores window
5. ✅ Island stays visible with toast (doesn't collapse)
6. User moves mouse away from toast
7. ✅ Toast dismisses instantly as expected

### Scenario 3: Notification During Focus Changes
1. Notification is showing (OBS recording)
2. User switches between fullscreen and windowed apps
3. ✅ Island stays expanded with notification visible
4. No unwanted collapse animations

## Test Scenarios

1. ✅ Start OBS recording while in fullscreen → Notification appears
2. ✅ Show toast → Maximize window → Toast stays visible
3. ✅ Show notification → Switch focus → Notification stays visible
4. ✅ Show toast → Restore window → Toast stays visible
5. ✅ Notification expires → Island collapses normally
6. ✅ Toast dismissed → Island hides if in fullscreen mode

## Technical Details

- **State flags**: `_hidden_by_fullscreen`, `_is_hiding`, `_is_expanded`
- **Override priority**: Notifications and toasts take precedence over fullscreen dodge
- **Clean state management**: Proper flag resets prevent state conflicts
- **Visibility handling**: Explicit `show()` call ensures widget appears when needed
