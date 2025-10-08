
#!/usr/bin/env python3
from __future__ import annotations

import os
import logging
from io import BytesIO
from datetime import datetime

# Qt6 (PyQt6)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QAction, QPixmap, QShortcut, QKeySequence, QGuiApplication
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QStatusBar, QFrame, QSizePolicy, QTabWidget, QComboBox
)
from pyscopegrab.app_settings import AppSettings
from pyscopegrab.scope_grabber import ScopeGrabber
from pyscopegrab.prefs_dialog import PrefsDialog


# ------------------------------- Worker -------------------------------------
class GrabWorker(QThread):
    """Runs serial I/O off the UI thread."""
    grabbed_img = Signal(object)  # Pillow Image
    status = Signal(str)
    error = Signal(str)

    def __init__(self, tty: str, baud: int, fg: str, bg: str, comment: str, logger: logging.Logger | None = None):
        super().__init__()
        self.tty = tty
        self.baud = int(baud)
        self.fg = fg
        self.bg = bg
        self.comment = comment
        self.logger = logger or logging.getLogger(__name__)

    def run(self):
        grab = None
        try:
            self.status.emit(f"Connecting {self.tty} …")
            grab = ScopeGrabber(tty=self.tty, baud=self.baud, logger=self.logger)
            grab.initialize_port()

            self.status.emit("Querying identity …")
            grab.get_identity()

            self.status.emit("Grabbing screenshot …")
            img = grab.get_screenshot_image(fg=self.fg, bg=self.bg, comment=self.comment)
            self.grabbed_img.emit(img)
            self.status.emit("Grab complete")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                if grab:
                    grab.close()
            except Exception:
                pass


# ------------------------------- Main Window --------------------------------
class MainWindow(QMainWindow):
    def __init__(self, tty: str | None = None, fg="#222222", bg="#b1e580", comment=""):
        super().__init__()
        self.setWindowTitle("PyScopeGrap – Fluke 105")

        # Settings
        self.settings = AppSettings()
        self.tty = tty or self.settings.port
        self.baud = int(self.settings.baud)
        self.fg = fg or self.settings.fg
        self.bg = bg or self.settings.bg
        self.cyclic_interval_ms = self.settings.cyclic_interval_ms
        self.comment = comment

        self.last_img = None
        self._orig_pixmap: QPixmap | None = None
        self._worker: GrabWorker | None = None
        self.last_save_dir: str = os.getcwd()

        # Central: Tabs
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)

        # === Tab 1: Screenshot ===
        self._build_tab_screenshot()

        # === Tab 2: Measurements (placeholder) ===
        self._build_tab_measurements()

        # === Tab 3: Scope (instrument) settings placeholder (NOT app prefs) ===
        self._build_tab_scope()

        # Timer for cyclic scanning
        self._timer = QTimer(self)
        self._timer.setInterval(self.cyclic_interval_ms)
        self._timer.timeout.connect(self.on_grab)

        # Status bar
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

        # Menus (Preferences remains in menu; Tab 3 is for instrument settings)
        self._make_menus()

        # Make the window non-resizable and sized to content
        self.tabs.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setDocumentMode(True)

        # Fix window size to content + menu/status
        self.adjustSize()
        self.setFixedSize(self.size())

    # ---------------------- Tabs construction --------------------------------
    def _build_tab_screenshot(self):
        tab = QWidget()
        self.tabs.addTab(tab, "Screenshot")
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # Fixed preview label 480x480 with bg + black frame
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(480, 480)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_label.setContentsMargins(0, 0, 0, 0)
        self._apply_placeholder_style()

        vbox.addWidget(self.image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Buttons row
        row = QHBoxLayout()
        row.setSpacing(8)

        self.btn_grab = QPushButton("&Grab")  # Alt+G activates via mnemonic
        self.btn_grab.setShortcut(QKeySequence("G"))  # plain G triggers click
        self.btn_grab.clicked.connect(self.on_grab)  # connect after creating
        row.addWidget(self.btn_grab)

        self.btn_save_as = QPushButton("Save As…")
        self.btn_save_as.clicked.connect(self.on_save)

        self.btn_cyclic = QPushButton("Cyclic Scan")
        self.btn_cyclic.setCheckable(True)
        self.btn_cyclic.toggled.connect(self.on_cyclic_toggled)

        # Equal distribution: add each with same stretch and set expanding policy
        for b in (self.btn_grab, self.btn_save_as, self.btn_cyclic):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.addWidget(b, 1)

        vbox.addLayout(row)

    def _build_tab_measurements(self):
        tab = QWidget()
        self.tabs.addTab(tab, "Measurements")
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        hint = QLabel(
            "Reserved for measurement controls.\n\n"
            "Ideas:\n"
            "• Choose quantity (DC V, AC V, Freq, etc.)\n"
            "• ‘Read’ button → query via worker\n"
            "• Show result below"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        vbox.addWidget(hint)

        row = QHBoxLayout()
        self.meas_combo = QComboBox()
        self.meas_combo.addItems(["DC Voltage", "AC Voltage", "Frequency"])
        self.btn_meas_read = QPushButton("Read")
        self.btn_meas_read.clicked.connect(self.on_read_measurement)
        row.addWidget(self.meas_combo)
        row.addWidget(self.btn_meas_read)
        row.addStretch(1)
        vbox.addLayout(row)

        self.meas_result = QLabel("Result: —")
        vbox.addWidget(self.meas_result)

    def _build_tab_scope(self):
        tab = QWidget()
        self.tabs.addTab(tab, "Scope")
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        label = QLabel(
            "Instrument settings placeholder.\n"
            "This tab is for scope-specific controls (not application preferences)."
        )
        vbox.addWidget(label)
        vbox.addStretch(1)

    # ---------------------- Menus, shortcuts & helpers -----------------------
    def _make_menus(self):
        m_file = self.menuBar().addMenu("&File")
        act_prefs = QAction("&Preferences…", self)  # App preferences
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        act_prefs.triggered.connect(self.on_prefs)
        m_file.addAction(act_prefs)

        act_copy = QAction("&Copy to Clipboard", self)
        act_copy.setShortcut(QKeySequence("C"))
        act_copy.triggered.connect(self.on_copy)
        m_file.addAction(act_copy)

        act_save = QAction("&Save As…", self)
        act_save.setShortcut(QKeySequence("S"))  # 'S' as requested
        act_save.triggered.connect(self.on_save)
        m_file.addAction(act_save)

        m_file.addSeparator()
        act_exit = QAction("E&xit", self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        m_help = self.menuBar().addMenu("&Help")

        act_help = QAction("&Help Contents…", self)
        # F1 (StandardKey.HelpContents) where supported
        try:
            act_help.setShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents))
        except Exception:
            pass
        act_help.triggered.connect(self.on_help_contents)
        m_help.addAction(act_help)

        act_about_app = QAction("&About PyScopeGrap", self)
        act_about_app.triggered.connect(self.on_about)
        m_help.addAction(act_about_app)

        act_about_qt = QAction("About &Qt", self)
        act_about_qt.triggered.connect(self.on_about_qt)
        m_help.addAction(act_about_qt)




    def _apply_placeholder_style(self) -> None:
        self.image_label.clear()
        self.image_label.setStyleSheet(
            f"background-color: {self.bg};"
            "border: 2px solid black;"
            "padding: 2px;"
        )

    def _update_preview_pixmap(self):
        pm = getattr(self, "_orig_pixmap", None)
        if not pm or pm.isNull():
            return
        target = self.image_label.contentsRect().size()  # fixed ~480x480 minus border/padding
        scaled = pm.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _update_status(self, msg: str | None = None):
        self.lbl_action.setText("Idle" if msg is None else msg)

    def _timestamp_name(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"

    # --------------------------- Menu actions --------------------------------
    @Slot()
    def on_prefs(self):
        dlg = PrefsDialog(
            self,
            tty=self.tty,
            baud=self.baud,
            fg=self.fg,
            bg=self.bg,
            cyclic_ms=self.cyclic_interval_ms,
        )
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
            self._apply_placeholder_style()
            self._update_status()

    def closeEvent(self, ev):
        # Persist current values on exit
        self.settings.port = self.tty
        self.settings.baud = self.baud
        self.settings.fg = self.fg
        self.settings.bg = self.bg
        self.settings.cyclic_interval_ms = self.cyclic_interval_ms
        self.settings.sync()
        super().closeEvent(ev)

    # --------------------------- File/clipboard ops --------------------------
    @Slot()
    def on_save(self):
        if not hasattr(self, "last_img") or self.last_img is None:
            QMessageBox.information(self, "Save", "No image yet. Use Grab first.")
            return
        # Pre-fill with auto-named timestamp file in last used dir
        default_path = os.path.join(self.last_save_dir, self._timestamp_name())
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save PNG", default_path, "PNG Images (*.png)"
        )
        if not fn:
            return
        self.last_save_dir = os.path.dirname(fn)
        self.save_current(fn)
        self._update_status(f"Saved {fn}")

    @Slot()
    def on_copy(self):
        pm = self._orig_pixmap or self.image_label.pixmap()
        if not pm or pm.isNull():
            QMessageBox.information(self, "Copy", "No image yet. Use Grab first.")
            return
        QGuiApplication.clipboard().setPixmap(pm)
        self._update_status("Copied image to clipboard")

    @Slot()
    def on_about(self):
        QMessageBox.about(
            self,
            "About PyScopeGrap",
            "PyScopeGrap\n\nQt6 GUI (PyQt6) for Fluke 105 screen grabbing.\n"
            "Status bar shows Port (left) and Action (right).",
        )

    @Slot()
    def on_help_contents(self):
        QMessageBox.information(
            self,
            "Help Contents",
            "PyScopeGrap\n\n"
            "Screenshot tab:\n"
            "  • Grab (G) — capture a screenshot\n"
            "  • Save As… (S) — save PNG (auto timestamp default)\n"
            "  • Cyclic Scan — periodic capture\n\n"
            "Shortcuts:\n"
            "  G=Grab, C=Copy to Clipboard, S=Save As, Ctrl+=Preferences, Ctrl+Q=Quit\n\n"
            "Measurements/Scope tabs are placeholders for future features."
        )

    @Slot()
    def on_about_qt(self):
        QMessageBox.aboutQt(self)

        # --------------------------- Actions -------------------------------------
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

    @Slot()
    def on_read_measurement(self):
        kind = self.meas_combo.currentText()
        # Placeholder until wired to serial measurement query
        self.meas_result.setText(f"Result: (not implemented) — {kind}")

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
        if pm.loadFromData(data, "PNG"):
            self._orig_pixmap = pm
            self._update_preview_pixmap()
        self._update_status("Idle")

    @Slot(str)
    def _on_error(self, msg: str):
        if self.btn_cyclic.isChecked():
            self.btn_cyclic.setChecked(False)
        QMessageBox.critical(self, "Error", msg)
        self._update_status("Error")

    # --------------------------- Persistence ---------------------------------
    def save_current(self, path: str):
        if not hasattr(self, "last_img") or self.last_img is None:
            return
        pnginfo = ScopeGrabber.make_pnginfo(self.last_img)
        self.last_img.save(path, "PNG", pnginfo=pnginfo)
