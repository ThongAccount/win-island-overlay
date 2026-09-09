# Bug Fix: Abrupt Hiding Animation

## Problem
The Dynamic Island had abrupt hiding (no smooth animation effect) in these scenarios:
1. When dodging fullscreen windows while a toast is active
2. When dismissing toasts that were shown during fullscreen dodge mode
3. When receiving toasts while a fullscreen window is active

## Root Causes

### Issue 1: Direct hide() call in _dismiss_toast()
**Location**: Line 1037-1041 in overlay.py

**Original Code**:
```python
if self._toast_ignore_hover:
    self.hide()
    self._is_hiding = False
else:
    self._anim_to(int(w * 0.50), h, 175, _incubic_ease, -h)
```

**Problem**: When `_toast_ignore_hover` was True, the code directly called `self.hide()` without animation, causing an abrupt disappearance.

**Fix**: Always use smooth animation regardless of `_toast_ignore_hover` state:
```python
# Always animate smoothly, even if ignore hover was set
self._anim_to(int(w * 0.50), h, 175, _incubic_ease, -h)
```

### Issue 2: No hiding when toast is active during fullscreen detection
**Location**: Line 638 in overlay.py

**Original Code**:
```python
if not self._hidden_by_fullscreen and not self._toast_active:
    # ... hide animation code
```

**Problem**: The condition `not self._toast_active` prevented the island from hiding when a toast was active and a fullscreen window appeared. This meant toasts would stay visible over fullscreen apps.

**Fix**: Remove the toast check and handle toast dismissal properly:
```python
if not self._hidden_by_fullscreen:
    # Hide smoothly regardless of toast state
    self._hidden_by_fullscreen = True
    self._hover_pending = False
    self._hover_timer.stop()
    
    # If toast is active, dismiss it first with animation
    if self._toast_active:
        self._toast_timer.stop()
        self._dismiss_toast()
    else:
        # Normal hide animation for non-toast states
        self._anim.stop()
        self._hover_animating = False
        self._expand_progress = 0.0
        self._is_expanded = False
        self._is_hiding = True
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        w, h = self._collapsed
        self._anim_to(int(w * 0.50), h, 175, _incubic_ease, -h)
```

## Changes Made

### File: backend/overlay.py

#### Change 1: _dismiss_toast() method (lines ~1032-1047)
- Removed the conditional `if self._toast_ignore_hover: self.hide()` branch
- Now always uses `_anim_to()` for smooth animation when hiding due to fullscreen
- Updated comment to reflect the change

#### Change 2: _check_fullscreen() method (lines ~638-657)
- Removed `and not self._toast_active` condition from fullscreen detection
- Added logic to properly dismiss toast with animation when fullscreen is detected
- Separated toast dismissal path from normal hide path
- Both paths now use smooth animations

## Expected Behavior After Fix

1. **Toast dismissal during fullscreen**: When a toast is dismissed while a fullscreen window is active, it will smoothly animate out instead of disappearing abruptly.

2. **Fullscreen window appears with toast**: When a fullscreen window appears while a toast is showing, the toast will be dismissed with smooth animation and the island will hide smoothly.

3. **Toast with ignore hover**: Even when `_toast_ignore_hover` is set (toast shown during fullscreen), dismissal will use smooth animation.

## Testing Recommendations

1. Show a toast notification, then maximize a window → Should hide smoothly
2. Maximize a window, then trigger a toast → Toast should appear, then dismiss smoothly when timer expires
3. Show a toast, move mouse away to trigger ignore hover, then dismiss → Should animate smoothly
4. Rapidly switch between fullscreen and windowed modes with toasts active → All transitions should be smooth

## Technical Details

- Animation duration: 175ms for fullscreen hide
- Easing function: `_incubic_ease` for hiding animation
- Target size when hiding: 50% of collapsed width
- Y-offset: -h (moves off-screen to top)
