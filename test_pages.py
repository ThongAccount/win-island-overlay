"""Run: QT_QPA_PLATFORM=offscreen .venv/bin/python test_pages.py"""
import backend.main as m  # noqa: F401 (validates app imports)
from backend.core.overlay import OverlayWindow
from PySide6.QtGui import QPixmap, QPainter, QMouseEvent, QWheelEvent
from PySide6.QtCore import QPointF, QPoint, Qt, QEvent
from PySide6.QtWidgets import QApplication
from backend.core.plugin import PluginRegistry
from backend.core.events import EventBus

app = QApplication([])
cfg = {'window': {}, 'plugins': {}}
reg = PluginRegistry(EventBus(), cfg)
ov = OverlayWindow(reg, cfg)
ov._media_state = 2
ov._obs_draw_state = 2
ov._obs_pixmap = QPixmap(18, 18)
ov._is_expanded = True
ov._expand_progress = 1.0
ov.resize(480, 48)
ov._media_session = object()


def press(x, y=24):
    ov.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                                   Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                   Qt.KeyboardModifier.NoModifier))


def move(x):
    ov.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(x, 24), QPointF(x, 24),
                                  Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                                  Qt.KeyboardModifier.NoModifier))


def release(x, y=24):
    ov.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                     Qt.KeyboardModifier.NoModifier))


def finish_flip():
    """Drive animation to completion (no event loop in test)."""
    ov._on_page_flip_finished()


# 1) Press on media button -> classic click, no swipe arm
layout = ov._media_expanded_layout()
bx, by = layout['btn_rects'][1].center().x(), layout['btn_rects'][1].center().y()
press(bx, by)
assert not ov._page_hold and ov._pressed_btn == 1
release(bx, by)
assert ov._page == 0

# 2) Swipe next beyond threshold -> animated flip, commit on finish; wraps
press(170); ov._on_hold_armed(); move(60); release(10)
assert ov._page_dragging and ov._page_anim_target == 1, (ov._page, ov._page_dragging)
finish_flip()
assert ov._page == 1 and not ov._page_dragging and ov._page_drag_off == 0.0

press(170); ov._on_hold_armed(); move(60); release(10)
finish_flip()
assert ov._page == 0, ov._page

# 3) Sub-threshold -> synchronous snap back, no flip
press(170); ov._on_hold_armed(); move(80); release(50)
assert ov._page == 0 and not ov._page_dragging and ov._page_drag_off == 0.0
release(50)  # stray release no-op

# 4) Fast-drag arms immediately (no wait for hold timer)
press(200); move(180)
assert ov._page_dragging
release(180)
assert ov._page == 0

# 5) Wheel flip: animates, commits target on finish
ov.wheelEvent(QWheelEvent(QPointF(240, 24), QPointF(240, 24), QPoint(0, 0), QPoint(0, -120),
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                          Qt.ScrollPhase.NoScrollPhase, False))
assert ov._page_dragging and ov._page_anim_target == 1
finish_flip()
assert ov._page == 1 and not ov._page_dragging and ov._page_drag_off == 0.0

# 6) Proximity collapse suppressed while dragging
ov._page_hold = True
ov._check_mouse()   # would collapse if not guarded
assert ov._is_expanded
ov._page_hold = False

# 7) Render: rest + mid-drag two-page state + dots
img = QPixmap(480, 48)
p = QPainter(img)
ov.render(p, QPoint(0, 0))
ov._page = 0
ov._page_drag_off = -120.0
ov.render(p, QPoint(0, 0))
ov._page_drag_off = 0.0
p.end()

print('ALL PAGE TESTS PASS')
