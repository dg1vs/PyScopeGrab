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

# -----------------
# Logging
# -----------------
# def init_logger(opt):
#     """Configure module logger.
#
#     Behavior:
#       - If --logging is not set, attach a NullHandler so LOG calls are no-ops.
#       - If --logging is set, write to file (and optionally to STDERR for console).
#       - Log level: DEBUG when --verbose, else INFO.
#
#     Rationale:
#       - Avoid stdout contamination so piping binary output/prints remains clean.
#       - Clearing handlers prevents duplicate logs when script is reloaded.
#     """
#
#     logger = logging.getLogger("PyScopeGrap")
#     logger.handlers.clear()
#     level = logging.DEBUG if getattr(opt, "verbose", False) else logging.INFO
#     logger.setLevel(level)
#
#     # By default, stay silent (no stdout pollution)
#     if not getattr(opt, "logging", False):
#         logger.addHandler(logging.NullHandler())
#         return logger
#
#     # File logger
#     fmt = logging.Formatter('%(lineno)s -%(funcName)s %(levelname)s %(message)s')
#     fh = logging.FileHandler('example.log', encoding='utf-8', mode='w')
#     fh.setLevel(level)
#     fh.setFormatter(fmt)
#     logger.addHandler(fh)
#
#     # Optional console to STDERR (safe for piping)
#     ch = logging.StreamHandler(sys.stderr)
#     ch.setLevel(level)
#     ch.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
#     logger.addHandler(ch)
#
#     return logger


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
    #p.add_argument('-s', '--status', help='retrieve status info about the scope', action='store_true')

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

    # GUI toggle
    p.add_argument('--withgui', help='launch Qt6 GUI (PyQt6)', action='store_true')

    p.add_argument('--no-settings', help='ignore config file defaults', action='store_true')
    p.add_argument('--save-settings', help='save provided options to the user config', action='store_true')

    act = p.add_mutually_exclusive_group()
    act.add_argument('-g', '--grab', action='store_true', help='grab screen now')
    act.add_argument('-w', '--wait', action='store_true', help='wait for PRINT event from device')
    act.add_argument('--sniff', type=float, metavar='SECONDS', help='sniff raw serial for SECONDS (no commands sent)')

    return p.parse_args()

def check_arguments(opt, LOG):
    """Validate incompatible options.
    'grab' (immediate fetch) and 'wait' (idle until device prints) are mutually exclusive for now.
    With the original flag semantics, grab=True by default; wait=False by default.
    """

    if opt.grab and opt.wait:
        LOG.info("It doesn't make sense to have wait and grab enabled the same time")
        sys.exit(20)

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


# -----------------
# Main
# -----------------
def main() -> int:
    args = process_arguments()
    LOG = init_logger(args)
    LOG.info('PyScopeGrap')

    # Load settings unless suppressed
    settings = AppSettings()
    if not args.no_settings:
        # Only fill values the user did NOT pass
        if args.tty is None: args.tty = settings.port
        #if args.baud is None: args.baud = settings.baud
        if args.fg is None: args.fg = settings.fg
        if args.bg is None: args.bg = settings.bg
        if args.comment is None: args.comment = ""  # comment default if omitted
    else:
        # ignore saved INI, but still source defaults from AppSettings constants
        if args.tty is None: args.tty = AppSettings.DEFAULT_PORT
        #if args.baud is None: args.baud = AppSettings.DEFAULT_BAUD
        if args.fg is None: args.fg = AppSettings.DEFAULT_FG
        if args.bg is None: args.bg = AppSettings.DEFAULT_BG
        if args.comment is None: args.comment = ""

    # ---- Sniff mode (no commands) ----
    if getattr(args, 'sniff', None):
        baud = int(args.baud) if hasattr(args, 'baud') and args.baud else int(settings.baud)
        LOG.info('Sniffing %s at %d baud for %.1f s', args.tty, baud, float(args.sniff))
        sniffer = ScopeGrabber(tty=args.tty, baud=baud, logger=LOG)
        sniffer.sniff(seconds=float(args.sniff), dump_to=args.tap, echo=(args.tap is None))
        sys.exit(0)

    # ---- CLI mode ----
    # Default to grab if neither -g nor -w provided
    if not getattr(args, 'grab', False) and not getattr(args, 'wait', False):
        args.grab = True
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

    if not hasattr(args, 'bg') or args.bg is None: args.bg = settings.bg
    if not hasattr(args, 'fg') or args.fg is None: args.fg = settings.fg

    grab = ScopeGrabber(tty=args.tty, baud=19200, logger=LOG)  # baud fixed internally (1200→19200)
    grab.initialize_port()

    # Identity is printed by the class (kept as-is)
    grab.get_identity()

    #if args.status:
    #    grab.get_status()


    if args.wait:
        LOG.info("Waiting for print job… Press PRINT on the ScopeMeter.")
        img = grab.wait_for_print_image(fg=args.fg, bg=args.bg, comment=(args.comment or " "), dump_to=args.tap)
        if args.out:
            pnginfo = grab.make_pnginfo(img)
            img.save(args.out, "PNG", pnginfo=pnginfo)
            LOG.info(args.out, "saved")
        elif args.auto:
            img.show()

    if args.grab:
        img = grab.get_screenshot_image(fg=args.fg, bg=args.bg, comment=(args.comment or ""))
        if args.out:
            pnginfo = grab.make_pnginfo(img)
            img.save(args.out, "PNG", pnginfo=pnginfo)
            LOG.info(args.out + " saved")
        elif args.auto:
            img.show()

    sys.exit(0)

if __name__ == '__main__':
    raise SystemExit(main())