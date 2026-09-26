"""Offscreen unit smoke for activity.py foreground-check bugfixes.

Asserts:
(a) _do_foreground_check no longer raises NameError (class_name was undefined),
(b) a new foreground hwnd publishes exactly one ForegroundWindowChanged, and
    title/class are populated (title=="" bug / class extraction restored).
"""
import ctypes
from types import SimpleNamespace
from unittest import mock

from PySide6.QtCore import QObject, QCoreApplication

from backend.core.events import EventBus, ForegroundWindowChanged
from backend.plugins.activity import ActivityPlugin

TITLE = "MyWindow"
CLASS = "MyClass"


def _make_windll(fg_hwnd=0x1000):
    def _getfghwnd():
        return fg_hwnd

    def _gettl_w(hwnd):
        return len(TITLE)

    def _getwt_w(hwnd, buff, n):
        buff.value = TITLE
        return len(TITLE)

    def _getcls_w(hwnd, buff, n):
        buff.value = CLASS
        return len(CLASS)

    def _getpid(hwnd, pidref):
        # pidref is a ctypes CArgObject (from byref) — not writable via a Mock.
        # Leave pid at 0 (no process_name); this test asserts title/class/event only.
        return 0

    def _exe0(h_process, module, buff, size):
        buff.value = "app.exe"
        return 1

    user32 = mock.Mock()
    user32.GetForegroundWindow.side_effect = _getfghwnd
    user32.GetWindowTextLengthW.side_effect = _gettl_w
    user32.GetWindowTextW.side_effect = _getwt_w
    user32.GetClassNameW.side_effect = _getcls_w
    user32.GetWindowThreadProcessId.side_effect = _getpid
    kernel32 = mock.Mock()
    kernel32.OpenProcess.return_value = 0x1234
    kernel32.CloseHandle.return_value = True
    psapi = mock.Mock()
    psapi.GetModuleFileNameExW.side_effect = _exe0

    class _W:
        pass

    w = _W()
    w.user32 = user32
    w.kernel32 = kernel32
    w.psapi = psapi
    return w


class FakeWindow(QObject):
    def winId(self):
        return 0


def main():
    app = QCoreApplication.instance() or QCoreApplication(["test"])
    windll = _make_windll()

    bus = EventBus()
    counts = {"n": 0}
    bus.subscribe(ForegroundWindowChanged, lambda e: counts.__setitem__("n", counts["n"] + 1))

    window = FakeWindow()
    reg = SimpleNamespace(
        event_bus=bus,
        config={"_window_ref": window, "plugins": {}},
        enable=lambda n: None,
        disable=lambda n: None,
    )
    plugin = ActivityPlugin(reg, {"default_profile": "default", "auto_switch": True,
                                  "notify_on_switch": False})
    plugin.on_enable()

    # _do_foreground_check must not swallow-and-None (NameError) and must marshal
    # exactly one event; deliver it by processing the posted Qt event on this thread.
    with mock.patch.object(ctypes, "windll", create=True, new=windll):
        plugin._do_foreground_check()
    app.processEvents()

    assert counts["n"] == 1, f"expected 1 ForegroundWindowChanged, got {counts['n']}"
    assert plugin._current_title == TITLE, f"title dead: {plugin._current_title!r}"
    assert plugin._current_class == CLASS, f"class dead: {plugin._current_class!r}"
    print("ACTIVITY TEST OK")


if __name__ == "__main__":
    main()