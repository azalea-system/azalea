import logging
import sys
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)


class _LogSignal(QObject):
    message = pyqtSignal(str)


_log_signal = None


class LogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if _log_signal is not None:
                _log_signal.message.emit(self.format(record))
        except Exception:
            self.handleError(record)


class LogWindow(QMainWindow):
    def __init__(self, stop_callback, management_ui_url: str | None = None):
        super().__init__()
        self._stop_callback = stop_callback
        self._management_ui_url = management_ui_url
        self._buffer: list[str] = []
        self._auto_scroll = True
        self.setWindowTitle("Azalea Media Server")
        self.resize(800, 500)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(10000)
        layout.addWidget(self.text, 1)

        scrollbar = self.text.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll)

        button_column = QWidget()
        button_layout = QVBoxLayout(button_column)
        button_layout.setContentsMargins(4, 4, 4, 4)
        button_layout.setSpacing(8)

        minimise_btn = QPushButton("Minimise to tray")
        minimise_btn.clicked.connect(self.hide)
        button_layout.addWidget(minimise_btn)

        if management_ui_url:
            mgmt_btn = QPushButton("Management UI")
            mgmt_btn.clicked.connect(self._open_management_ui)
            button_layout.addWidget(mgmt_btn)

        stop_btn = QPushButton("Stop Azalea")
        stop_btn.clicked.connect(self._stop)
        button_layout.addWidget(stop_btn)

        button_layout.addStretch()
        layout.addWidget(button_column)

        self.setCentralWidget(central)

        _log_signal.message.connect(
            self._append_log, Qt.ConnectionType.QueuedConnection
        )

    def _on_scroll(self):
        scrollbar = self.text.verticalScrollBar()
        self._auto_scroll = scrollbar.value() >= scrollbar.maximum() - 2

    def _scroll_to_bottom(self):
        if not self._auto_scroll:
            return
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text.setTextCursor(cursor)

    def _append_log(self, msg: str) -> None:
        if self.isVisible():
            self.text.appendPlainText(msg)
            self._scroll_to_bottom()
        else:
            self._buffer.append(msg)

    def _flush_buffer(self):
        if not self._buffer:
            return
        self.text.appendPlainText("\n".join(self._buffer))
        self._buffer.clear()
        self._scroll_to_bottom()

    def showEvent(self, event):
        super().showEvent(event)
        self._flush_buffer()

    def _open_management_ui(self):
        if self._management_ui_url:
            webbrowser.open(self._management_ui_url)

    def _stop(self):
        try:
            self._stop_callback()
        except Exception:
            pass
        QApplication.instance().quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def run_tray(stop_callback, management_ui_url: str | None = None) -> None:
    global _log_signal

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    _log_signal = _LogSignal()

    window = LogWindow(stop_callback, management_ui_url)

    icon_path = Path(__file__).parent / "app_icon.ico"
    icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()

    tray = QSystemTrayIcon(icon)
    tray.setToolTip("Azalea Media Server")

    menu = QMenu()
    show_action = menu.addAction("Show/Hide Logs")
    show_action.triggered.connect(
        lambda: window.show() if window.isHidden() else window.hide()
    )
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(window._stop)
    tray.setContextMenu(menu)

    tray.activated.connect(
        lambda reason: (
            (window.show() if window.isHidden() else window.hide())
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
    )

    tray.show()
    window.show()

    root = logging.getLogger()
    root.addHandler(LogHandler())

    sys.exit(app.exec())
