import sys
import signal
from PySide6.QtCore import QTimer
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
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
