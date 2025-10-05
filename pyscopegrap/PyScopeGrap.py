#!/usr/bin/env python3
"""
PyScopeGrap - Serial capture & PNG export for Fluke ScopeMeter 105.

This script:
  - Opens a serial connection to the ScopeMeter 105
  - Sends simple ASCII commands (ending with CR '\r')
  - Reads the device's EPSON-graphics formatted screen bytes
  - Renders a 240x240 PNG with optional metadata and color mapping

Protocol notes:
  - Command ACK: device returns two bytes: <code><CR>. Code '0' means OK.
  - Screenshot transfer: 'QP' -> ASCII length (4 chars), ',' separator,
    then ~7.4 KiB EPSON graphics payload, then 1-byte checksum (sum % 256).
  - Image is 240 px wide by 240 px tall; bytes stream bit-packed (LSB first)
    across columns; lines advance every 240 bytes.
"""

from __future__ import annotations

import sys
import os
import argparse
import logging

from pyscopegrap.app_settings import AppSettings
from pyscopegrap.scope_grabber import ScopeGrabber
from pyscopegrap.scpi_server import run_scpi_server, SCPIConfig


def init_logger(opt):
    """"
    Attach two handlers to the same logger, a console handler (to stderr) that shows only the “important stuff” (e.g., INFO and above), and
    a file handler that captures everything (e.g., DEBUG and above) with rich formatting.

    That way there is no need for calling print() and just do LOG.info(...)

    LOG.info("...") for user-facing progress/status (these show on console + file).
    LOG.debug("...") for detailed internals (file only unless -v).
    LOG.warning(...) / LOG.error(...) for problems (both console + file).
    """
    logger = logging.getLogger("PyScopeGrap")
    logger.handlers.clear()
    logger.propagate = False   # don’t double-log via root

    # Master level: keep at DEBUG so handlers decide what to show/store
    logger.setLevel(logging.DEBUG)

    # -------- Console handler (to terminal) --------
    if not getattr(opt, "quiet", False):
        ch = logging.StreamHandler(sys.stderr)   # safe when piping stdout
        # Show INFO+ on console (use -v to get DEBUG on console if you want)
        ch.setLevel(logging.DEBUG if getattr(opt, "verbose", False) else logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(ch)

    # -------- File handler (full detail) --------
    if getattr(opt, "logging", False):
        log_path = getattr(opt, "log_file", None) or "pyscopegrap.log"
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8", mode="w")
        fh.setLevel(logging.DEBUG)  # capture everything to file
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(name)s %(levelname)s [%(filename)s:%(lineno)d %(funcName)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(fh)

    return logger

# --- Defaults & settings resolution ------------------------------------------
def apply_settings(args, settings, use_saved: bool = True) -> None:
    """
    Fill missing CLI args from either saved QSettings (use_saved=True)
    or from AppSettings' compile-time defaults (use_saved=False).
    Also normalizes a few fields and (optionally) persists back.
    """
    # Source for defaults
    if use_saved:
        defaults = {
            "tty": settings.port,
            "baud": settings.baud,
            "fg": settings.fg,
            "bg": settings.bg,
            "comment": "",
        }
    else:
        defaults = {
            "tty": AppSettings.DEFAULT_PORT,
            "baud": AppSettings.DEFAULT_BAUD,
            "fg": AppSettings.DEFAULT_FG,
            "bg": AppSettings.DEFAULT_BG,
            "comment": "",
        }

    # Fill only when user did not pass a value
    for key, val in defaults.items():
        if getattr(args, key, None) is None:
            setattr(args, key, val)

    # Persist (only if explicitly requested)
    if getattr(args, "save_settings", False):
        settings.port = args.tty
        try:
            # keep tolerant while baud handling is being redesigned
            settings.baud = int(args.baud)
        except Exception:
            pass
        settings.fg = args.fg
        settings.bg = args.bg
        settings.sync()


def process_arguments():
    """Parse CLI flags.
    regarding action="store_true" https://stackoverflow.com/questions/8203622/argparse-store-false-if-unspecified
    """
    settings_for_help = AppSettings()
    p = argparse.ArgumentParser(
        prog='PyScopeGrap',
        description='Handles communication with Fluke 105 (CLI or --withgui)'
    )
    # Communication
    p.add_argument('-t', '--tty', dest='tty', help='serial port to use', default=None)
    #ToDo remove boud, it's fixed
    p.add_argument('-b', '--baud', dest='baud', help=f'[currently ignored] Baudrate [default: {settings_for_help.baud}]', default=None)

    # Actions (keep original truthiness: default True → do it; flag sets False)
    # p.add_argument('-i', '--info',   help='retrieve info about the scope',     action='store_true')  # disabled: identity is printed anyway
    # p.add_argument('-s', '--status', help='retrieve status info about the scope', action='store_true')

    # Output
    p.add_argument('-o', '--out',  dest='out',  help='output-file')
    p.add_argument('-a', '--auto', dest='auto', help='open the grabbed image with the system viewer', action='store_true')

    # Colors & picture
    p.add_argument('-f', '--foreground', dest='fg', help=f'foreground color in #rrggbb [default: {settings_for_help.fg}]', default=None)
    p.add_argument('-y', '--background', dest='bg', help=f'background color in #rrggbb [default: {settings_for_help.bg}]', default=None)
    p.add_argument('-c', '--comment', help='add extra comment to picture', default=None)

    # Misc
    p.add_argument('-v', '--verbose', help='increase output verbosity', action='store_true')
    p.add_argument('-l', '--logging', help='enable logging to file/console', action='store_true')
    p.add_argument('--log-file', help='log file path (used with --logging)', default=None)
    p.add_argument('--quiet', help='suppress console log output', action='store_true')
    p.add_argument('--tap', dest='tap', help='dump all raw serial bytes to this file while waiting/reading', default=None)

    p.add_argument('--no-settings', help='ignore config file defaults', action='store_true')
    p.add_argument('--save-settings', help='save provided options to the user config', action='store_true')

    #Todo either gui or grab
    act = p.add_mutually_exclusive_group()
    act.add_argument('-g', '--grab', action='store_true', help='grab screen now')
    act.add_argument('--meter', action='store_true', help='print first meter value (QM1)')
    act.add_argument('--withgui', help='launch Qt6 GUI (PyQt6)', action='store_true')
    act.add_argument('--scpi-server', action='store_true', help='run SCPI server on 127.0.0.1:5025')

    # SCPI network options
    p.add_argument('--scpi-host', default='127.0.0.1', help='SCPI bind host [default: 127.0.0.1]')
    p.add_argument('--scpi-port', type=int, default=5025, help='SCPI TCP port [default: 5025]')
    return p.parse_args()

# -----------------
# GUI launcher (only when --withgui)
# -----------------
def run_gui_from_separate_file(args, LOG):
    # Lazy import so CLI users don’t need PyQt6
    try:
        from PyQt6.QtWidgets import QApplication
        from pyscopegrap.scope_gui_pyqt6 import MainWindow  # your separate GUI file
    except Exception as e:
        LOG.info("GUI dependencies are missing (PyQt6) or scope_gui_pyqt6.py not found.")
        LOG.info(f"Details: {e}")
        sys.exit(1)

    app = QApplication(sys.argv)
    # Pass current CLI defaults into the GUI
    w = MainWindow(
        tty=args.tty,
        # baud=int(args.baud),
        #Todo baud=None,
        fg=args.fg,
        bg=args.bg,
        comment=args.comment
    )
    w.show()
    sys.exit(app.exec())


def _make_grabber_from_args(args):
    # Single place to build a configured ScopeGrabber
    return ScopeGrabber(
        tty=args.tty,
        baud=19200,        # your current policy; adjust when baud handling is refactored
        logger=logging.getLogger("PyScopeGrap"),
    )


# -----------------
# Main
# -----------------
def main() -> int:
    args = process_arguments()
    LOG = init_logger(args)
    LOG.info('PyScopeGrap')

    # Load settings unless suppressed
    settings = AppSettings()
    apply_settings(args, settings, use_saved=not args.no_settings)

    if args.scpi_server:
        cfg = SCPIConfig(host=args.scpi_host, port=args.scpi_port)
        run_scpi_server(cfg, grabber_factory=lambda: _make_grabber_from_args(args))
        exit(0)


    if args.withgui:
        run_gui_from_separate_file(args, LOG)  # never returns

    # Default to grab if neither action provided
    if not getattr(args, 'grab', False) and not getattr(args, 'sniff', None) and not getattr(args, 'meter', False):
        args.grab = True

    grab = ScopeGrabber(tty=args.tty, baud=19200, logger=LOG)  # baud fixed internally (1200→19200)
    grab.initialize_port()
    # Identity is printed by the class (kept as-is)
    grab.get_identity()

    if args.scpi_server:
        cfg = SCPIConfig(host=args.scpi_host, port=args.scpi_port)
        run_scpi_server(cfg, grabber_factory=lambda: _make_grabber_from_args(args))
        exit(0)

    #if args.status:
    #    grab.get_status()

    # the minimal useful stuff, get the scope picture
    if args.grab:
        img = grab.get_screenshot_image(fg=args.fg, bg=args.bg, comment=(args.comment or ""))
        if args.out:
            pnginfo = grab.make_pnginfo(img)
            img.save(args.out, "PNG", pnginfo=pnginfo)
            LOG.info(args.out + " saved")
        elif args.auto:
            img.show()

    # ----- Meter mode (passive) -----
    if args.meter:
        # We read QM1 with full triplet: "<type>,<value>,<unit>"
        try:
            mtype, value, unit = grab.query_measurement(field=1, numeric_only=False)
        except Exception as e:
            LOG.error("Meter read failed: %s", e)
            sys.exit(1)

        # Print a clean, parseable line to stdout (not via logger)
        print(f"{mtype},{value},{unit}")
        sys.exit(0)

    sys.exit(0)

if __name__ == '__main__':
    raise SystemExit(main())