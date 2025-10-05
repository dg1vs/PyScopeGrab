#!/usr/bin/env python3
from __future__ import annotations

# Qt6 (PyQt6)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal as Signal, pyqtSlot as Slot
#from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction, QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QStatusBar, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QFrame, QComboBox, QColorDialog, QSpinBox, QSizePolicy, QLabel, QSizePolicy, QLayout,
    QTabWidget
)

from io import BytesIO
from PyQt6.QtGui import QPixmap

from pyscopegrap.app_settings import AppSettings
from pyscopegrap.scope_grabber import ScopeGrabber
from pyscopegrap.prefs_dialog import PrefsDialog

class GrabWorker(QThread):
    """Runs serial I/O off the UI thread."""
    #grabbed_png = Signal(bytes)   # PNG bytes for display
    grabbed_img = Signal(object)  # emit Pillow Image

    status = Signal(str)          # status messages
    error = Signal(str)

    def __init__(self, tty: str, baud: int, fg: str, bg: str, comment: str, logger=None):
        super().__init__()
        self.tty = tty
        self.baud = int(baud)
        self.fg = fg
        self.bg = bg
        self.comment = comment
        self.logger = logger

    def run(self):
        try:
            self.status.emit(f"Connecting {self.tty} …")
            grab = ScopeGrabber(tty=self.tty, baud=self.baud, logger=self.logger)
            grab.initialize_port()

            self.status.emit("Querying identity …")
            grab.get_identity()

        #     with NamedTemporaryFile(prefix="scopemeter_", suffix=".png", delete=False) as tmp:
        #         tmp_path = Path(tmp.name)
        #
        #     opt = SimpleNamespace(
        #         fg=self.fg, bg=self.bg, auto=False, out=str(tmp_path), comment=self.comment
        #     )
        #
        #     self.status.emit("Grabbing screenshot …")
        #     grab.get_screenshot(opt)
        #
        #     img = grab.get_screenshot_image(fg=self.fg, bg=self.bg, comment=self.comment)
        #     self.grabbed_img.emit(img)
        #     self.status.emit("Grab complete")
        #
        # except Exception as e:
        #     self.error.emit(str(e))
            self.status.emit("Grabbing screenshot …")
            img = grab.get_screenshot_image(fg=self.fg, bg=self.bg, comment=self.comment)
            self.grabbed_img.emit(img)
            self.status.emit("Grab complete")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                grab.close()
            except Exception:
                pass



class MainWindow(QMainWindow):
    def __init__(self, tty: str | None = None, fg="#222222", bg="#b1e580", comment=""):
        super().__init__()
        self.setWindowTitle("PyScopeGrap – Fluke 105")
        self.resize(1000, 600)

        # Load settings
        self.settings = AppSettings()

        # Defaults (fallback if CLI passed None)
        #if tty is None:
        #    tty = self.settings.port
        #if baud is None:
        #    baud = self.settings.baud

        # Apply from settings (CLI values override if provided explicitly)
        self.tty = tty or self.settings.port
        self.baud = int(self.settings.baud)
        self.fg = fg or self.settings.fg
        self.bg = bg or self.settings.bg
        self.cyclic_interval_ms = self.settings.cyclic_interval_ms
        self.comment = comment
        self.last_png: bytes | None = None
        self._worker: GrabWorker | None = None

        # central image view
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(480, 480)  # <-- fixed preview area
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # don't grow
        self.image_label.setContentsMargins(0, 0, 0, 0)

        # style: bg color + black frame; no placeholder text
        self._apply_placeholder_style()

        # buttons
        self.btn_grab = QPushButton("Grab")
        self.btn_grab.clicked.connect(self.on_grab)

        self.btn_cyclic = QPushButton("Cyclic Scan")
        self.btn_cyclic.setCheckable(True)
        self.btn_cyclic.toggled.connect(self.on_cyclic_toggled)

        # right-side layout
        right_box = QVBoxLayout()
        right_box.addWidget(self.btn_grab)
        right_box.addWidget(self.btn_cyclic)
        right_box.addStretch(1)

        # main horizontal layout
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(self.image_label, 1)
        lay.addLayout(right_box)

        lay.setContentsMargins(8, 8, 8, 8)

        self.setCentralWidget(central)

        # timer for cyclic scanning
        self._timer = QTimer(self)
        self._timer.setInterval(self.cyclic_interval_ms)
        self._timer.timeout.connect(self.on_grab)


        # status bar (port left, action right, with separator)
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)

        self.lbl_port = QLabel(f"Port: {self.tty}")
        self.lbl_port.setFrameShape(QFrame.Shape.Panel)
        self.lbl_port.setFrameShadow(QFrame.Shadow.Sunken)
        self.statusbar.addWidget(self.lbl_port)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        self.statusbar.addWidget(sep)

        self.lbl_action = QLabel("Idle")
        self.lbl_action.setFrameShape(QFrame.Shape.Panel)
        self.lbl_action.setFrameShadow(QFrame.Shadow.Sunken)
        self.statusbar.addPermanentWidget(self.lbl_action, 1)

        # menus
        self._make_menus()

        # prevent layout from trying to expand
        self.centralWidget().layout().setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        # size the window to fit central + toolbars/menubar/statusbar, then lock it
        self.adjustSize()
        self.setFixedSize(self.size())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._update_preview_pixmap()

    def _apply_placeholder_style(self) -> None:
        self.image_label.clear()
        self.image_label.setStyleSheet(
            f"background-color: {self.bg};"
            "border: 2px solid black;"
            "padding: 2px;"  # <- keep image inside the border
        )

    def _update_preview_pixmap(self):
        """Scale the original pixmap to the label's available content area."""
        pm = getattr(self, "_orig_pixmap", None)
        if not pm or pm.isNull():
            return
        # contentsRect accounts for borders; use that size for scaling
        target = self.image_label.contentsRect().size()
        scaled = pm.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _make_menus(self):
        m_file = self.menuBar().addMenu("&File")
        act_prefs = QAction("&Preferences…", self)
        act_prefs.triggered.connect(self.on_prefs)
        m_file.addAction(act_prefs)
        act_save = QAction("&Save As…", self)
        act_save.triggered.connect(self.on_save)
        m_file.addAction(act_save)
        m_file.addSeparator()
        act_exit = QAction("E&xit", self)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        m_help = self.menuBar().addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self.on_about)
        m_help.addAction(act_about)

    def _update_status(self, msg: str | None = None):
        self.lbl_action.setText("Idle" if msg is None else msg)

    @Slot()
    def on_prefs(self):
        dlg = PrefsDialog(self,
                          tty=self.tty,
                          baud=self.baud,
                          fg=self.fg,
                          bg=self.bg,
                          cyclic_ms=self.cyclic_interval_ms)
        if dlg.exec():
            self.tty, self.baud, self.fg, self.bg, self.cyclic_interval_ms = dlg.values()

            # Save to settings
            self.settings.port = self.tty
            self.settings.baud = self.baud
            self.settings.fg = self.fg
            self.settings.bg = self.bg
            self.settings.cyclic_interval_ms = self.cyclic_interval_ms
            self.settings.sync()

            # Apply live
            self.lbl_port.setText(f"Port: {self.tty}")
            self._timer.setInterval(self.cyclic_interval_ms)
            self._update_status()

            # after updating self.fg/self.bg and syncing settings...
            self._apply_placeholder_style()

    def closeEvent(self, ev):
        # Persist current values on exit (extra safety)
        self.settings.port = self.tty
        self.settings.baud = self.baud
        self.settings.fg = self.fg
        self.settings.bg = self.bg
        self.settings.cyclic_interval_ms = self.cyclic_interval_ms
        self.settings.sync()
        super().closeEvent(ev)

    @Slot()
    def on_save(self):
        if not hasattr(self, "last_img") or self.last_img is None:
            QMessageBox.information(self, "Save", "No image yet. Use Grab first.")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Save PNG", "screenshot.png", "PNG Images (*.png)")
        if not fn:
            return
        self.save_current(fn)
        self._update_status(f"Saved {fn}")

        # if not self.last_png:
        #     QMessageBox.information(self, "Save", "No image yet. Use Grab first.")
        #     return
        # fn, _ = QFileDialog.getSaveFileName(self, "Save PNG", "screenshot.png", "PNG Images (*.png)")
        # if not fn:
        #     return
        # Path(fn).write_bytes(self.last_png)
        # self._update_status(f"Saved {fn}")

    @Slot()
    def on_about(self):
        QMessageBox.about(
            self, "About PyScopeGrap",
            "PyScopeGrap\n\nQt6 GUI (PyQt6) for Fluke 105 screen grabbing.\n"
            "Status bar shows Port (left) and Action (right)."
        )

    @Slot()
    def on_grab(self):
        if self._worker and self._worker.isRunning():
            return
        self.btn_grab.setEnabled(False)
        self._update_status("Connecting …")
        self._worker = GrabWorker(self.tty, self.baud, self.fg, self.bg, self.comment)
        self._worker.status.connect(self._update_status)
        self._worker.grabbed_img.connect(self.on_grabbed_img)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self.btn_grab.setEnabled(True))
        self._worker.start()

    @Slot(bool)
    def on_cyclic_toggled(self, checked: bool):
        if checked:
            self._timer.setInterval(self.cyclic_interval_ms)
            self._timer.start()
            self._update_status(f"Cyclic scan started ({int(self.cyclic_interval_ms / 1000)} s)")
        else:
            self._timer.stop()
            self._update_status("Cyclic scan stopped")

    @Slot(object)
    def on_grabbed_img(self, img):
        self.last_img = img
        buf = BytesIO()
        try:
            pnginfo = ScopeGrabber.make_pnginfo(img)
            img.save(buf, "PNG", pnginfo=pnginfo)
        except Exception:
            img.save(buf, "PNG")
        data = buf.getvalue()

        pm = QPixmap()
        pm.loadFromData(data, "PNG")
        if not pm.isNull():
            # Keep original, then scale to the content area (excludes border/padding)
            self._orig_pixmap = pm
            self._update_preview_pixmap()  # this already uses contentsRect()

    @Slot(str)
    def _on_error(self, msg: str):
        # Stop cyclic mode on error for safety/no spam
        if self.btn_cyclic.isChecked():
            self.btn_cyclic.setChecked(False)
        QMessageBox.critical(self, "Error", msg)
        self._update_status("Error")

    def save_current(self, path: str):
        if not hasattr(self, "last_img") or self.last_img is None:
            return
        pnginfo = ScopeGrabber.make_pnginfo(self.last_img)
        self.last_img.save(path, "PNG", pnginfo=pnginfo)