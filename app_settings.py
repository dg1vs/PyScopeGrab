# app_settings.py
from __future__ import annotations
import sys
from PyQt6.QtCore import QSettings

class AppSettings:
    """
    Typed wrapper for QSettings.
    Stores user config in an INI file (per-user).
      Linux:   ~/.config/PyScopeGrap/Fluke105.ini
      Windows: HKEY_CURRENT_USER\Software\PyScopeGrap\Fluke105 (registry)
    """
    ORG = "PyScopeGrap"
    APP = "Fluke105"

    DEFAULT_PORT = "COM3" if sys.platform.startswith("win") else "/dev/ttyUSB0"
    DEFAULT_BAUD = 19200
    DEFAULT_FG = "#222222"
    DEFAULT_BG = "#b1e580"
    DEFAULT_CYCLIC_MS = 3000  # 3s

    def __init__(self):
        self._s = QSettings(QSettings.Format.IniFormat,
                            QSettings.Scope.UserScope,
                            self.ORG, self.APP)

    # ---- serial ----
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

    # ---- colors ----
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

    # ---- cyclic ----
    @property
    def cyclic_interval_ms(self) -> int:
        return int(self._s.value("cyclic/interval_ms", self.DEFAULT_CYCLIC_MS))

    @cyclic_interval_ms.setter
    def cyclic_interval_ms(self, v: int):
        self._s.setValue("cyclic/interval_ms", int(v))

    # ---- misc ----
    def sync(self):
        self._s.sync()

    def file_path(self) -> str:
        return self._s.fileName()
