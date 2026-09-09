import sys
import signal
import os
from pathlib import Path
from PySide6.QtCore import QTimer, QFileSystemWatcher
from PySide6.QtWidgets import QApplication
from overlay import OverlayWindow


def main():
    app = QApplication(sys.argv)

    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)

    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    overlay = OverlayWindow()
    overlay.show()

    # Auto-reload on .py file changes
    watcher = QFileSystemWatcher()
    backend_dir = Path(__file__).parent
    for py_file in backend_dir.rglob("*.py"):
        watcher.addPath(str(py_file))

    def on_changed(path):
        print(f"[reload] {path} changed, restarting...")
        app.quit()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    watcher.fileChanged.connect(on_changed)
    overlay._watcher = watcher

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
