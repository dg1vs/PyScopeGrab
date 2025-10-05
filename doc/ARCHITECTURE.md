# PyScopeGrap — Architecture & How-To

This document explains how the pieces fit together, with ASCII sketches and practical command‑line examples.

> Targets the Fluke ScopeMeter 105; code lives in this package:
> `app_settings.py`, `scope_grabber.py`, `scope_gui_pyqt6.py`, `PyScopeGrap.py`, `scpi_server.py`, `prefs_dialog.py`.

---

## 1) High‑level overview

```
+-------------------+     serial (1200→19200)     +------------------------+
|  PyScopeGrap CLI  | <--------------------------> |  ScopeMeter 105 device |
|  or GUI or SCPI   |                              +------------------------+
+----+----------+---+
     |          |
     |          +-------------------+
     |                              |
     v                              v
+----+----------------+    +--------+---------------------+
|  scope_grabber.py   |    |  scpi_server.py (optional)   |
|  (serial protocol   |    |  TCP server + SCPI commands  |
|   + Epson decode)   |    |  -> delegates to grabber     |
+---------------------+    +------------------------------+
            ^
            |
            v
+---------------------------+
| scope_gui_pyqt6.py (Qt6)  |
| - MainWindow (UI thread)  |
| - GrabWorker (QThread)    |
+---------------------------+
```

- **`scope_grabber.py`**: the core logic — open serial, handshakes (1200→19200), send `QP`, read ~7.4 KiB, verify checksum, decode Epson graphics ➜ Pillow Image, write PNG and optional metadata.
- **`scope_gui_pyqt6.py`**: a small GUI that calls the grabber from a `QThread` so the UI stays responsive.
- **`scpi_server.py`**: optional mini TCP server speaking SCPI (`*IDN?`, `MEAS:VOLT:DC?`, `HCOPY:DATA?`). It protects the single serial link with a lock so multiple clients can’t collide.
- **`app_settings.py`**: typed wrapper around `QSettings` (persists port, colors, cyclic interval).

---

## 2) GUI threading model — `MainWindow` ⇄ `GrabWorker`

**Goal:** never block the UI while talking to serial. The window spawns a worker thread for each “Grab” action.

```
UI thread (Qt)                                          Worker thread (QThread)
--------------------------------------------------------------------------------
MainWindow.on_grab()
  ├─ disable Grab button
  ├─ create GrabWorker(tty, baud, fg, bg, comment)
  ├─ connect signals:
  │     worker.status       -> MainWindow._update_status(text)
  │     worker.grabbed_img  -> MainWindow.on_grabbed_img(Image)
  │     worker.error        -> MainWindow._on_error(text)
  │     worker.finished     -> re‑enable Grab
  └─ worker.start()
                                                         GrabWorker.run()
                                                           ├─ status: "Connecting…"
                                                           ├─ grab = ScopeGrabber(...)
                                                           ├─ grab.initialize_port()
                                                           ├─ status: "Querying identity…"
                                                           ├─ grab.get_identity()  (logs model/fw)
                                                           ├─ status: "Grabbing screenshot…"
                                                           ├─ img = grab.get_screenshot_image(fg,bg,comment)
                                                           ├─ emit grabbed_img(img)
                                                           └─ finally: grab.close()
```

**Cyclic mode:** `QTimer` in `MainWindow` calls `on_grab()` every *N* milliseconds (`AppSettings.cyclic_interval_ms`). The window checks that no worker is already running (so grabs never overlap).

**Displaying the image:** the slot converts the Pillow image to PNG bytes in memory (optionally adds PNG text via the grabber helper) and updates a `QLabel` with a `QPixmap`.

---

## 3) SCPI server — components & flow

The SCPI server is a small threaded TCP server. It accepts text commands terminated by `\n`, executes them under a **lock** using a **single** `ScopeGrabber` instance, and replies with either a text line or a binary block.

### Components

```
+--------------------------------------------------------------+
| run_scpi_server(SCPIConfig, grabber_factory)                 |
|  ├─ eager serial open (logs 1200→19200 handshake)            |
|  ├─ _SCPIState: { _grabber, _lock, _ensure_open() }          |
|  └─ Threading TCP server (serve_forever)                     |
+--------------------------------------------------------------+
         ^                                        |
         | binds                                   v
+----------------------------+         +------------------------------+
|  _BoundSCPIHandler         |  <----  |  _SCPIHandler(StreamHandler) |
|  STATE, COMMANDS injected  |         |  - handle(): read lines      |
+----------------------------+         |  - _dispatch(cmd)            |
                                       |  - write text or binblock    |
                                       +------------------------------+
```

### Implemented commands

- `*IDN?` → returns a vendor/model string (e.g., `FLUKE,ScopeMeter 105 Series II,-,V7.15`).  
- `MEAS:VOLT:DC?` → returns numeric DC value via the meter query.  
- `HCOPY:DATA?` → returns a **definite‑length binary block** (IEEE‑488.2) containing a PNG screenshot:

```
Response framing:  # <ndigits> <len> <payload> \n
Example:           #  7        0123456  <PNG bytes> \n
```

> The trailing newline helps VISA clients; binary parsers should not require it.

**Concurrency:** every command runs inside `_SCPIState.with_grabber(fn)`, which acquires a lock. This guarantees that only one client is on the serial line at a time.

**Errors:** if anything fails (serial unavailable, wrong TTY, etc.), the server returns a short textual error (`ERR:…`) instead of closing the socket — clients won’t hang on timeouts.

---

## 4) Command‑line usage

> All examples assume you’ve installed dependencies (PyQt6, pyserial, Pillow, pyvisa/pyvisa‑py for the client). Replace `/dev/ttyUSB0` with your actual port on Windows (`COM5` etc.).

### 4.1 One‑shot screenshot to file (no GUI)
```bash
# Minimal: auto‑name based on date or use -o to name the file
python3 -m pyscopegrap -t /dev/ttyUSB0 -o out.png -v
```

### 4.2 Start the GUI
```bash
python3 -m pyscopegrap --with-gui -v
# File → Preferences to set the serial port and colors, then click “Grab”.
```

### 4.3 Run the SCPI server
```bash
# Start the server (opens serial, then listens on TCP 5025)
python3 -m pyscopegrap --scpi-server -t /dev/ttyUSB0 --scpi-host 127.0.0.1 --scpi-port 5025 -v
# Stop with Ctrl+C
```

### 4.4 Quick SCPI smoke tests from a shell
```bash
# Query identity
printf '*IDN?\n' | nc 127.0.0.1 5025

# Measure DC voltage (server returns a number)
printf 'MEAS:VOLT:DC?\n' | nc 127.0.0.1 5025

# Fetch hardcopy (PNG): save the block as a file
# (Binblock begins with '#', so we need a little helper—use the Python client below.)
```

### 4.5 PyVISA client examples

**Identity and hardcopy** (manual binblock parser; robust for sockets):

```python
#!/usr/bin/env python3
import pyvisa

def read_binblock(inst):
    prev = inst.read_termination
    inst.read_termination = None
    try:
        hdr = inst.read_bytes(2)           # b'#' + ndigits
        if not hdr or hdr[0] != ord('#'):
            raise RuntimeError(f"Expected '#', got {hdr!r}")
        ndigits = int(chr(hdr[1]))
        length = int(inst.read_bytes(ndigits).decode('ascii'))
        data = inst.read_bytes(length)
        # optional: consume trailing LF if present
        try:
            inst.timeout = 50
            inst.read_bytes(1)
        except Exception:
            pass
        return data
    finally:
        inst.read_termination = prev

def main():
    rm = pyvisa.ResourceManager('@py')  # pyvisa-py
    inst = rm.open_resource('TCPIP::127.0.0.1::5025::SOCKET')
    inst.timeout = 15000
    inst.write_termination = '\n'
    inst.read_termination  = '\n'

    print('*IDN? ->', inst.query('*IDN?').strip())

    inst.write('HCOPY:DATA?')
    png = read_binblock(inst)
    with open('scpi_grab.png', 'wb') as f:
        f.write(png)
    print('Saved scpi_grab.png')

if __name__ == '__main__':
    main()
```

**Alternative using `query_binary_values`** (works if your backend honors terminators as sent):
```python
png = inst.query_binary_values('HCOPY:DATA?', datatype='B', container=bytes, expect_termination=False)
```

### 4.6 Settings & defaults

- The app loads/saves settings via `QSettings` under `PyScopeGrap/Fluke105`. Typical locations:
  - Linux: `~/.config/PyScopeGrap/Fluke105.ini`
  - Windows: `HKEY_CURRENT_USER\Software\PyScopeGrap\Fluke105`
- Useful flags:
  - `-t, --tty` — serial device (e.g., `/dev/ttyUSB0`, `COM5`)
  - `-o, --out` — output PNG path for one‑shot CLI grab
  - `-v` — verbose (show INFO logs on console)
  - `--with-gui` — launch the Qt GUI
  - `--scpi-server` `--scpi-host` `--scpi-port` — start SCPI TCP server

> When using `--scpi-server`, the CLI path does **not** open the serial itself; the server owns the port and opens it once at startup (with clear log messages).

---

## 5) Notes on robustness

- The serial device is accessed from one place at a time:
  - GUI: `GrabWorker` (one worker at a time, enforced in the window).
  - SCPI: `_SCPIState` lock (one command at a time across clients).
- Errors are surfaced as **signals** in the GUI and as **text replies** (`ERR:...`) in SCPI so callers never hang.
- The image path verifies length and checksum before decoding; decoding produces a Pillow `Image` which is then saved to PNG with optional metadata.

---

## 6) Glossary

- **SCPI** — Standard Commands for Programmable Instruments (ASCII commands like `*IDN?`).
- **Binblock** — SCPI binary block framing: `#<d><len><payload>` (definite length).
- **QThread** — Qt thread object; its `run()` executes in a background thread to keep the UI responsive.
- **QSettings** — Simple persistent key/value store for user settings.
