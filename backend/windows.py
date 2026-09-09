from PySide6.QtGui import QWindow
from PySide6.QtCore import QTimer

class WindowDetector:
    def __init__(self, overlay):
        self.overlay = overlay
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_windows)
        self.timer.start(1000)  # Check every second

    def check_windows(self):
        # Get the current active window
        active_window = QWindow.fromWinId(QApplication.desktop().winId())
        
        # Check if the overlay is overlapping with the active window
        if self.is_overlapping(active_window):
            self.overlay.hide()
        else:
            self.overlay.show()

    def is_overlapping(self, window):
        # Implement logic to check if overlay is overlapping with the given window
        # This is a simplified version - you may need to adjust based on your needs
        overlay_rect = self.overlay.geometry()
        window_rect = window.geometry()
        
        return overlay_rect.intersects(window_rect)
