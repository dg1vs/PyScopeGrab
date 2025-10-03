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

from app_settings import AppSettings
from scope_grabber import ScopeGrabber


# -----------------
# Logging
# -----------------
def init_logger(opt):
    """Configure module logger.

    Behavior:
      - If --logging is not set, attach a NullHandler so LOG calls are no-ops.
      - If --logging is set, write to file (and optionally to STDERR for console).
      - Log level: DEBUG when --verbose, else INFO.

    Rationale:
      - Avoid stdout contamination so piping binary output/prints remains clean.
      - Clearing handlers prevents duplicate logs when script is reloaded.
    """

    logger = logging.getLogger("PyScopeGrap")
    logger.handlers.clear()
    level = logging.DEBUG if getattr(opt, "verbose", False) else logging.INFO
    logger.setLevel(level)

    # By default, stay silent (no stdout pollution)
    if not getattr(opt, "logging", False):
        logger.addHandler(logging.NullHandler())
        return logger

    # File logger
    fmt = logging.Formatter('%(lineno)s -%(funcName)s %(levelname)s %(message)s')
    fh = logging.FileHandler('example.log', encoding='utf-8', mode='w')
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Optional console to STDERR (safe for piping)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(ch)

    return logger


def process_arguments():
    """Parse CLI flags.
    regarding action="store_true" https://stackoverflow.com/questions/8203622/argparse-store-false-if-unspecified
    """

    p = argparse.ArgumentParser(
        prog='PyScopeGrap',
        description='Handles communication with Fluke 105 (CLI or --withgui)'
    )
    # Communication
    p.add_argument('-t', '--tty', dest='tty', help='serial port to use', default=None)
    p.add_argument('-b', '--baud', dest='baud', help='Baudrate [1200]', default=None)

    # Actions (keep original truthiness: default True → do it; flag sets False)
    p.add_argument('-i', '--info',   help='retrieve info about the scope',     action='store_true')
    p.add_argument('-s', '--status', help='retrieve status info about the scope', action='store_false')
    p.add_argument('-g', '--grab',   help='grab the screen of the scope',      action='store_false')
    p.add_argument('-w', '--wait',   help='wait for start print from the scope', action='store_true')

    # Output
    p.add_argument('-o', '--out',  dest='out',  help='output-file')
    p.add_argument('-a', '--auto', dest='auto', help='auto display image', action='store_true')

    # Colors
    p.add_argument('-f', '--foreground', dest='fg', help='foreground color in #rrggbb', default=None)
    p.add_argument('-y', '--background', dest='bg', help='background color in #rrggbb', default=None)

    # Misc
    p.add_argument('-v', '--verbose', help='increase output verbosity', action='store_true')
    p.add_argument('-l', '--logging', help='enable logging to file/console', action='store_true')
    p.add_argument('-c', '--comment', help='add extra comment to picture', default=None)

    # GUI toggle
    p.add_argument('-u', '--withgui', help='launch Qt6 GUI (PyQt6)', action='store_true')

    p.add_argument('--no-settings', help='ignore config file defaults', action='store_true')
    p.add_argument('--save-settings', help='save provided options to the user config', action='store_true')

    return p.parse_args()

def check_arguments(opt, LOG):
    """Validate incompatible options.
    'grab' (immediate fetch) and 'wait' (idle until device prints) are mutually exclusive for now.
    With the original flag semantics, grab=True by default; wait=False by default.
    """

    if opt.grab and opt.wait:
        LOG.error("It doesn't make sense to have wait and grab enabled the same time")
        sys.exit(20)


# -----------------
# GUI launcher (only when --withgui)
# -----------------
def run_gui_from_separate_file(args, LOG):
    # Lazy import so CLI users don’t need PyQt6
    try:
        from PyQt6.QtWidgets import QApplication
        from scope_gui_pyqt6 import MainWindow  # your separate GUI file
    except Exception as e:
        print("GUI dependencies are missing (PyQt6) or scope_gui_pyqt6.py not found.")
        print(f"Details: {e}")
        sys.exit(1)

    app = QApplication(sys.argv)
    # Pass current CLI defaults into the GUI
    w = MainWindow(
        tty=args.tty,
        baud=int(args.baud),
        fg=args.fg,
        bg=args.bg,
        comment=args.comment
    )
    w.show()
    sys.exit(app.exec())


# -----------------
# Main
# -----------------
if __name__ == '__main__':
    args = process_arguments()
    LOG = init_logger(args)
    LOG.info('PyScopeGrap')

    # Load settings unless suppressed
    settings = AppSettings()
    if not args.no_settings:
        # Only fill values the user did NOT pass
        if args.tty is None: args.tty = settings.port
        if args.baud is None: args.baud = settings.baud
        if args.fg is None: args.fg = settings.fg
        if args.bg is None: args.bg = settings.bg
        if args.comment is None: args.comment = ""  # comment default if omitted
    else:
        # maintain previous hardcoded defaults if ignoring settings
        if args.tty is None: args.tty = '/dev/ttyUSB0' if os.name != 'nt' else 'COM3'
        if args.baud is None: args.baud = 1200
        if args.fg is None: args.fg = '#222222'
        if args.bg is None: args.bg = '#b1e580'
        if args.comment is None: args.comment = ""

    # ---- CLI mode (default; unchanged behavior) ----
    check_arguments(args, LOG)

    # Persist passed-in values if requested
    if args.save_settings:
        settings.port = args.tty
        try:
            settings.baud = int(args.baud)
        except Exception:
            pass
        settings.fg = args.fg
        settings.bg = args.bg
        # If you later add --cyclic-interval to CLI, save it here too.
        settings.sync()

    if args.withgui:
        run_gui_from_separate_file(args, LOG)  # never returns


    grab = ScopeGrabber(tty=args.tty, baud=int(args.baud), logger=LOG)
    grab.initialize_port()

    # Identity is printed by the class (kept as-is)
    grab.get_identity()

    if args.status:
        grab.get_status()

    if args.wait:
        print("Waiting for print job… Press PRINT on the ScopeMeter.")
        if not hasattr(args, 'bg') or args.bg is None: args.bg = '#b1e580'
        if not hasattr(args, 'fg') or args.fg is None: args.fg = '#222222'
        img = grab.wait_for_print_image(fg=args.fg, bg=args.bg, comment=(args.comment or ""))
        if args.out:
            pnginfo = grab.make_pnginfo(img)
            img.save(args.out, "PNG", pnginfo=pnginfo)
            print(args.out, "saved")
        elif args.auto:
            img.show()

    if args.grab:
        # Make sure the arg namespace has the fields expected by the class
        if not hasattr(args, 'bg'):
            args.bg = '#b1e580'
        if not hasattr(args, 'fg'):
            args.fg = '#222222'

        img = grab.get_screenshot_image(fg=args.fg, bg=args.bg, comment=(args.comment or ""))

        if args.out:
            pnginfo = grab.make_pnginfo(img)
            img.save(args.out, "PNG", pnginfo=pnginfo)
            print(args.out + " saved")
        elif args.auto:
            img.show()

    sys.exit(0)
