- baud rate macht hier keinen Sinn. Es ist fix auf 1200 eingestellt. Und muss auch so bleiben
- Remove or wire up display_progress_bar() It’s defined but unused; either delete it or call it during the long read(payload_len) loop (switch to chunked reads to get progress). File: scope_grabber.py
- -g/-w doesn't work

- Replace sys.exit() in library code with exceptions Inside scope_grabber.py, raise custom exceptions (e.g., ScopeProtocolError) instead of exiting the interpreter. Let the CLI (PyScopeGrap.py) and GUI catch and present errors. file: scope_grabber.py
- Make length parsing more defensive In get_screenshot_image(), if the 4 ASCII digits aren’t digits, you fallback to 7454. Consider validating the comma separator and logging the raw header for future decoding tweaks. 
- Use chunked reads for large payloads Serial.read(N) may return fewer bytes; loop until you collect N, with an overall timeout, and optionally update a progress callback (GUI could display it in the status bar).  




cool—no pyproject.toml needed yet. Here’s the minimal, no-packaging way to get a clean entry point and python -m support for #23.

Goal

Run your app like:

python -m pyscopegrap --help


…and keep the door open to add pyproject.toml later.

Steps (quick + safe)

Make a package folder

mkdir -p pyscopegrap
touch pyscopegrap/__init__.py


Move your modules into it

git mv app_settings.py scope_grabber.py scope_gui_pyqt6.py PyScopeGrap.py pyscopegrap/


Fix imports to absolute package imports

In these files:

pyscopegrap/PyScopeGrap.py

pyscopegrap/scope_gui_pyqt6.py

pyscopegrap/scope_grabber.py

replace:

from app_settings import AppSettings
from scope_grabber import ScopeGrabber


with:

from pyscopegrap.app_settings import AppSettings
from pyscopegrap.scope_grabber import ScopeGrabber


(If you import anything else between these modules, make it from pyscopegrap.<module> import ... as well.)

Expose a main() in your CLI module

In pyscopegrap/PyScopeGrap.py, wrap your current top-level execution:

def main() -> int:
    args = process_arguments()
    LOG = init_logger(bool(args.verbose))
    # --- your existing program logic ---
    return 0

if __name__ == "__main__":
    raise SystemExit(main())


Add a module runner (lets you do python -m pyscopegrap)

Create pyscopegrap/__main__.py:

from .PyScopeGrap import main

if __name__ == "__main__":
    raise SystemExit(main())


Smoke test

python -m pyscopegrap --help
python -m pyscopegrap --withgui

(Optional) tiny convenience wrappers

Unix: create pyscopegrap script at repo root:

printf '%s\n' '#!/usr/bin/env bash' 'python -m pyscopegrap "$@"' > pyscopegrap
chmod +x pyscopegrap


Run with ./pyscopegrap --help.

Windows: pyscopegrap.bat:

@echo off
python -m pyscopegrap %*


That’s it. When you’re ready later, drop in pyproject.toml and add:

[project.scripts]
pyscopegrap = "pyscopegrap.PyScopeGrap:main"


so users can just run pyscopegrap.
