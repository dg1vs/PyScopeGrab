from __future__ import annotations

import sys
import importlib.resources as res
from PyQt6 import uic
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QColorDialog, QComboBox, QPushButton, QLineEdit, QSpinBox)
from serial.tools import list_ports
from pyscopegrap.app_settings import AppSettings


class PrefsDialog(QDialog):
    # We have only 1200 at start, later will be switched to 19200
    BAUDS = [AppSettings.DEFAULT_BAUD]

    def __init__(self, parent, tty: str, baud: int, fg: str, bg: str, cyclic_ms: int):
        super().__init__(parent)

        # Load the .ui
        ui_path = res.files("pyscopegrap.ui").joinpath("prefs_dialog.ui")
        with res.as_file(ui_path) as p:
            uic.loadUi(p, self)

        self.setModal(True)

        # Access widgets from .ui
        self.cb_tty: QComboBox
        self.btn_refresh: QPushButton
        self.cb_baud: QComboBox
        self.btn_fg: QPushButton
        self.le_fg: QLineEdit
        self.btn_bg: QPushButton
        self.le_bg: QLineEdit
        self.sb_interval: QSpinBox
        self.buttonBox: QDialogButtonBox

        # Wire signals
        self.btn_refresh.clicked.connect(lambda: self._populate_ports(prefer=self._current_device()))
        self.btn_fg.clicked.connect(lambda: self._pick_color(self.btn_fg, self.le_fg))
        self.btn_bg.clicked.connect(lambda: self._pick_color(self.btn_bg, self.le_bg))
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        # Populate port list
        self._populate_ports(prefer=tty)
        if tty and self._index_of_port(tty) == -1:
            self.cb_tty.insertItem(0, tty, tty)
            self.cb_tty.setCurrentIndex(0)

        # Baud
        self.cb_baud.clear()
        for b in self.BAUDS:
            self.cb_baud.addItem(str(b), b)
        idx = self.cb_baud.findData(int(baud))
        self.cb_baud.setCurrentIndex(idx if idx >= 0 else 0)

        # Colors
        self._apply_color_to_button(self.btn_fg, fg); self.le_fg.setText(fg)
        self._apply_color_to_button(self.btn_bg, bg); self.le_bg.setText(bg)

        # Interval (stored in ms; shown in seconds)
        self.sb_interval.setRange(1, 60)  # 1 s … 60 s
        self.sb_interval.setSingleStep(1)
        self.sb_interval.setSuffix(" s")
        self.sb_interval.setValue(max(1, int(cyclic_ms / 1000)))

    # ---- Helpers ----
    def _current_device(self) -> str:
        return self.cb_tty.currentData() or self.cb_tty.currentText().split(" — ")[0]

    def _populate_ports(self, prefer: str | None = None):
        if prefer is None:
            prefer = self._current_device()

        self.cb_tty.blockSignals(True)
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
                if prefer:
                    self.cb_tty.insertItem(0, prefer, prefer)
                    self.cb_tty.setCurrentIndex(0)
                else:
                    self.cb_tty.setCurrentIndex(0)
        else:
            # explicit “no ports found” hint, but keep an editable sensible default
            if not prefer:
                prefer = "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"
            display = f"{prefer} — (no ports found)"
            self.cb_tty.addItem(display, prefer)
            self.cb_tty.setCurrentIndex(0)
            self.cb_tty.setToolTip("No serial ports were detected. You can still type a device path manually.")
            # Optional: allow manual typing if your .ui sets it to non-editable
            # self.cb_tty.setEditable(True)

        self.cb_tty.blockSignals(False)

    def _index_of_port(self, device: str) -> int:
        for i in range(self.cb_tty.count()):
            if self.cb_tty.itemData(i) == device or self.cb_tty.itemText(i).startswith(device):
                return i
        return -1

    def _apply_color_to_button(self, button: QPushButton, color_hex: str):
        if not color_hex.startswith("#"):
            color_hex = "#" + color_hex
        color = QColor(color_hex)
        if not color.isValid():
            color = QColor("#000000")

        # Compute a simple contrast-aware text color (WCAG-ish luminance)
        r, g, b, _ = color.getRgb()
        luminance = 0.2126 * (r / 255.0) + 0.7152 * (g / 255.0) + 0.0722 * (b / 255.0)
        text_color = QColor("#000000") if luminance > 0.6 else QColor("#FFFFFF")

        pal = QPalette(button.palette())
        pal.setColor(QPalette.ColorRole.Button, color)
        pal.setColor(QPalette.ColorRole.ButtonText, text_color)
        button.setAutoFillBackground(True)
        button.setPalette(pal)

        # Visible label + usability tweaks
        button.setText(color.name(QColor.NameFormat.HexRgb).upper())
        button.setMinimumWidth(120)
        button.setMinimumHeight(28)
        button.setToolTip(f"Current color: {button.text()}")

    def _pick_color(self, button: QPushButton, line: QLineEdit):
        initial = button.text().strip() or line.text().strip()
        col = QColor(initial) if initial else QColor("#000000")
        chosen = QColorDialog.getColor(col, self, "Select color",
                                       options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if chosen.isValid():
            hex_rgb = chosen.name()
            self._apply_color_to_button(button, hex_rgb)
            line.setText(hex_rgb)

    def values(self):
        tty = self.cb_tty.currentData() or self.cb_tty.currentText().split(" — ")[0]
        baud = int(self.cb_baud.currentData())
        fg = self.le_fg.text().strip()
        bg = self.le_bg.text().strip()
        cyclic_ms = int(self.sb_interval.value()) * 1000
        return tty, baud, fg, bg, cyclic_ms
