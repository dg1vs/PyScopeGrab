from __future__ import annotations

import sys
from pathlib import Path
import importlib.resources as res

from PyQt6 import uic
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QColorDialog, QComboBox, QPushButton, QLineEdit, QSpinBox
)

# pyserial for enumerating ports
try:
    from serial.tools import list_ports
except Exception:
    list_ports = None

from pyscopegrap.app_settings import AppSettings


class PrefsDialog(QDialog):
    BAUDS = [AppSettings.DEFAULT_BAUD]

    def __init__(self, parent, tty: str, baud: int, fg: str, bg: str, cyclic_ms: int):
        super().__init__(parent)

        # Load the .ui
        try:
            ui_path = res.files("pyscopegrap.ui").joinpath("prefs_dialog.ui")
            with res.as_file(ui_path) as p:
                uic.loadUi(p, self)
        except Exception:
            # Fallback for dev tree
            here = Path(__file__).resolve().parent
            uic.loadUi(here / "ui" / "prefs_dialog.ui", self)

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

        # Interval
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
