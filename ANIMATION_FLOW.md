# Animation Flow - Before and After Fix

## BEFORE FIX (Buggy Behavior)

### Scenario 1: Toast dismissal during fullscreen
```
Toast Active + Fullscreen Window
    ↓
User dismisses toast OR timer expires
    ↓
_dismiss_toast() called
    ↓
Checks: _toast_ignore_hover == True?
    ↓ YES
self.hide() ← ABRUPT! No animation
```

### Scenario 2: Fullscreen window appears with toast
```
Toast Active + Normal Window
    ↓
User maximizes window
    ↓
_check_fullscreen() detects fullscreen
    ↓
Checks: not self._toast_active?
    ↓ NO (toast is active)
NOTHING HAPPENS ← Toast stays visible over fullscreen!
```

## AFTER FIX (Smooth Behavior)

### Scenario 1: Toast dismissal during fullscreen
```
Toast Active + Fullscreen Window
    ↓
User dismisses toast OR timer expires
    ↓
_dismiss_toast() called
    ↓
Checks: should_hide (fullscreen)?
    ↓ YES
_anim_to(50% width, -h offset, 175ms) ← SMOOTH animation
    ↓
Animation completes
    ↓
_on_anim_finished() → self.hide()
```

### Scenario 2: Fullscreen window appears with toast
```
Toast Active + Normal Window
    ↓
User maximizes window
    ↓
_check_fullscreen() detects fullscreen
    ↓
Checks: self._toast_active?
    ↓ YES
Stop toast timer
    ↓
Call _dismiss_toast()
    ↓
_dismiss_toast() → _anim_to() ← SMOOTH animation
    ↓
Animation completes
    ↓
_on_anim_finished() → self.hide()
```

### Scenario 3: Normal fullscreen dodge (no toast)
```
Normal State + Normal Window
    ↓
User maximizes window
    ↓
_check_fullscreen() detects fullscreen
    ↓
Checks: self._toast_active?
    ↓ NO
_anim_to(50% width, -h offset, 175ms) ← SMOOTH animation
    ↓
Animation completes
    ↓
_on_anim_finished() → self.hide()
```

## Key Changes

1. **Removed conditional hide()**: No more `if _toast_ignore_hover: self.hide()`
2. **Always animate**: All hide operations now use `_anim_to()` with proper easing
3. **Toast-aware fullscreen**: Fullscreen detection now handles active toasts properly
4. **Unified flow**: All paths lead to smooth animation → _on_anim_finished() → hide()

## Animation Parameters

- **Duration**: 175ms (fast but smooth)
- **Easing**: `_incubic_ease` (cubic ease-in for natural hiding)
- **Target width**: 50% of collapsed width (shrinks while moving up)
- **Y-offset**: -h (moves completely off-screen to top)
