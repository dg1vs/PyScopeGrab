#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
#from tempfile import NamedTemporaryFile
#from types import SimpleNamespace

# Qt6 (PyQt6)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction, QPixmap, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QStatusBar, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QFrame, QComboBox, QColorDialog, QSpinBox
)
from io import BytesIO
from PyQt6.QtGui import QPixmap

# pyserial for enumerating ports
try:
    from serial.tools import list_ports
except Exception:
    list_ports = None

from app_settings import AppSettings
from scope_grabber import ScopeGrabber

# --- Application settings wrapper -------------------------------------------


class AppSettings:
    """
    Thin wrapper around QSettings providing typed getters/setters + defaults.
    Uses per-user INI config (on Linux: ~/.config/PyScopeGrap/Fluke105.ini).
    """
    ORG = "PyScopeGrap"
    APP = "Fluke105"

    # defaults
    DEFAULT_PORT = "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"
    DEFAULT_BAUD = 19200
    DEFAULT_FG   = "#222222"
    DEFAULT_BG   = "#b1e580"
    DEFAULT_CYCLIC_MS = 3000  # 3s

    def __init__(self):
        # Use INI files so the config is easy to find/edit
        self._s = QSettings(QSettings.Format.IniFormat,
                            QSettings.Scope.UserScope,
                            self.ORG, self.APP)

    # --- typed properties ----------------------------------------------------
    @property
    def port(self) -> str:
        return self._s.value("serial/port", self.DEFAULT_PORT, str)

    @port.setter
    def port(self, v: str):
        self._s.setValue("serial/port", v)

    @property
    def baud(self) -> int:
        return int(self._s.value("serial/baud", self.DEFAULT_BAUD))

    @baud.setter
    def baud(self, v: int):
        self._s.setValue("serial/baud", int(v))

    @property
    def fg(self) -> str:
        return self._s.value("colors/fg", self.DEFAULT_FG, str)

    @fg.setter
    def fg(self, v: str):
        self._s.setValue("colors/fg", v)

    @property
    def bg(self) -> str:
        return self._s.value("colors/bg", self.DEFAULT_BG, str)

    @bg.setter
    def bg(self, v: str):
        self._s.setValue("colors/bg", v)

    @property
    def cyclic_interval_ms(self) -> int:
        return int(self._s.value("cyclic/interval_ms", self.DEFAULT_CYCLIC_MS))

    @cyclic_interval_ms.setter
    def cyclic_interval_ms(self, v: int):
        self._s.setValue("cyclic/interval_ms", int(v))

    # convenience
    def sync(self):
        """Force write to disk."""
        self._s.sync()

    #def file_path(self) -> str:
    #    """Physical INI path (useful for logging/help)."""
    #    return self._s.fileName()


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

class PrefsDialog(QDialog):
    BAUDS = [1200]

    def __init__(self, parent, tty: str, baud: int, fg: str, bg: str, cyclic_ms: int):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)

        # --- Serial Port ---
        self.cb_tty = QComboBox()

        # Populate with the INI value pre-selected
        self._populate_ports(prefer=tty)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(lambda: self._populate_ports(prefer=self._current_device()))

        self._populate_ports()
        if tty and self._index_of_port(tty) == -1:
            self.cb_tty.insertItem(0, tty)
            self.cb_tty.setCurrentIndex(0)

        # --- Baud rate ---
        self.cb_baud = QComboBox()
        for b in self.BAUDS:
            self.cb_baud.addItem(str(b), b)
        idx = self.cb_baud.findData(int(baud))
        self.cb_baud.setCurrentIndex(idx if idx >= 0 else 0)

        # --- Colors ---
        self.btn_fg = QPushButton()
        self.btn_fg.clicked.connect(lambda: self._pick_color(self.btn_fg))
        self._apply_color_to_button(self.btn_fg, fg)
        self.btn_fg.setToolTip("Choose foreground color")
        self.le_fg = QLineEdit(fg); self.le_fg.setReadOnly(True)

        self.btn_bg = QPushButton()
        self.btn_bg.clicked.connect(lambda: self._pick_color(self.btn_bg))
        self._apply_color_to_button(self.btn_bg, bg)
        self.btn_bg.setToolTip("Choose background color")
        self.le_bg = QLineEdit(bg); self.le_bg.setReadOnly(True)

        # --- Cyclic interval (seconds) ---
        self.sb_interval = QSpinBox()
        self.sb_interval.setRange(1, 3600)   # 1..3600 seconds
        self.sb_interval.setSuffix(" s")
        self.sb_interval.setValue(max(1, int(cyclic_ms / 1000)))

        # Layout
        form = QFormLayout()

        port_row = QHBoxLayout(); port_row.addWidget(self.cb_tty, 1); port_row.addWidget(self.btn_refresh, 0)
        port_wrap = QWidget(); port_wrap.setLayout(port_row)
        form.addRow("Serial port:", port_wrap)

        form.addRow("Baud rate:", self.cb_baud)

        fg_row = QHBoxLayout(); fg_row.addWidget(self.btn_fg, 0); fg_row.addWidget(self.le_fg, 1)
        fg_wrap = QWidget(); fg_wrap.setLayout(fg_row)
        form.addRow("Foreground:", fg_wrap)

        bg_row = QHBoxLayout(); bg_row.addWidget(self.btn_bg, 0); bg_row.addWidget(self.le_bg, 1)
        bg_wrap = QWidget(); bg_wrap.setLayout(bg_row)
        form.addRow("Background:", bg_wrap)

        form.addRow("Cyclic interval:", self.sb_interval)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _current_device(self) -> str:
        """Return the currently selected device path (e.g. '/dev/ttyUSB0' or 'COM3')."""
        return self.cb_tty.currentData() or self.cb_tty.currentText().split(" — ")[0]

    def _populate_ports(self, prefer: str | None = None):
        """Fill the combobox with available ports and select 'prefer' if found."""
        # Remember currently selected (so Refresh can preserve when prefer is None)
        if prefer is None:
            prefer = self._current_device()

        self.cb_tty.blockSignals(True)  # avoid spurious signals while refilling
        self.cb_tty.clear()

        ports = []
        if list_ports is not None:
            try:
                ports = list(list_ports.comports())
            except Exception:
                ports = []

        selected_index = -1
        if ports:
            for i, p in enumerate(ports):
                dev = p.device
                display = f"{dev} — {p.description or 'Serial'}"
                self.cb_tty.addItem(display, dev)
                if prefer and dev == prefer:
                    selected_index = i
            if selected_index >= 0:
                self.cb_tty.setCurrentIndex(selected_index)
            else:
                # If preferred device not in list, insert it at top so user sees it
                if prefer:
                    self.cb_tty.insertItem(0, prefer, prefer)
                    self.cb_tty.setCurrentIndex(0)
                else:
                    self.cb_tty.setCurrentIndex(0)
        else:
            # No ports found; still show the preferred or a sensible guess
            if not prefer:
                prefer = "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"
            self.cb_tty.addItem(prefer, prefer)
            self.cb_tty.setCurrentIndex(0)

        self.cb_tty.blockSignals(False)

    def _index_of_port(self, device: str) -> int:
        for i in range(self.cb_tty.count()):
            if self.cb_tty.itemData(i) == device or self.cb_tty.itemText(i).startswith(device):
                return i
        return -1

    def _apply_color_to_button(self, button: QPushButton, color_hex: str):
        # Normalize hex like "#RRGGBB"
        if not color_hex.startswith("#"):
            color_hex = "#" + color_hex
        button.setText(color_hex.upper())
        button.setMinimumWidth(120)
        button.setMinimumHeight(28)
        button.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {color_hex};"
            f"  border: 1px solid #666;"
            f"  border-radius: 6px;"
            f"}}"
        )

    def _pick_color(self, button: QPushButton):
        initial = button.text().strip()
        col = QColor(initial) if initial else QColor("#000000")
        chosen = QColorDialog.getColor(col, self, "Select color",
                                       options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if chosen.isValid():
            hex_rgb = chosen.name()  # "#RRGGBB"
            self._apply_color_to_button(button, hex_rgb)
            if button is self.btn_fg:
                self.le_fg.setText(hex_rgb)
            else:
                self.le_bg.setText(hex_rgb)

    def values(self):
        tty = self.cb_tty.currentData() or self.cb_tty.currentText().split(" — ")[0]
        baud = int(self.cb_baud.currentData())
        fg = self.le_fg.text().strip()
        bg = self.le_bg.text().strip()
        cyclic_ms = int(self.sb_interval.value()) * 1000
        return tty, baud, fg, bg, cyclic_ms


class MainWindow(QMainWindow):
    def __init__(self, tty: str | None = None, baud: int = 19200, fg="#222222", bg="#b1e580", comment=""):
        super().__init__()
        self.setWindowTitle("PyScopeGrap – Fluke 105")
        self.resize(1000, 600)

        # Load settings
        self.settings = AppSettings()

        # Defaults (fallback if CLI passed None)
        if tty is None:
            tty = self.settings.port
        if baud is None:
            baud = self.settings.baud

        # Apply from settings (CLI values override if provided explicitly)
        self.tty = tty or self.settings.port
        self.baud = int(baud or self.settings.baud)
        self.fg = fg or self.settings.fg
        self.bg = bg or self.settings.bg
        self.cyclic_interval_ms = self.settings.cyclic_interval_ms
        self.comment = comment
        self.last_png: bytes | None = None
        self._worker: GrabWorker | None = None

        # central image view
        self.image_label = QLabel("File → Preferences to set the port, then click Grab.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(480, 480)

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
        # Keep the Pillow Image for Save...
        self.last_img = img
        # Convert to PNG bytes in memory (safer than ImageQt on some systems)
        buf = BytesIO()
        try:
            pnginfo = ScopeGrabber.make_pnginfo(img)
            img.save(buf, "PNG", pnginfo=pnginfo)
        except Exception:
            img.save(buf, "PNG")
        data = buf.getvalue()
        # Preview from bytes
        pm = QPixmap()
        pm.loadFromData(data, "PNG")
        if not pm.isNull():
            pm = pm.scaled(
                480, 480,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(pm)
        self._update_status("Idle")

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