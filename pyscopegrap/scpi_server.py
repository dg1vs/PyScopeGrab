# scpi_server.py
from __future__ import annotations

import socketserver
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

# Public API of this module
__all__ = ["run_scpi_server", "SCPIConfig"]

@dataclass(frozen=True)
class SCPIConfig:
    host: str = "127.0.0.1"
    port: int = 5025
    # Optionally add: read_timeout, write_timeout, banner text, etc.

class _SCPIState:
    """
    Shared state for handlers: a single ScopeGrabber instance + a lock.
    We inject a 'grabber' factory so this module doesn't depend on scope_grabber.py.
    """
    def __init__(self, grabber_factory: Callable[[], object]) -> None:
        self._grabber = grabber_factory()
        self._lock = threading.Lock()

    def with_grabber(self, fn: Callable[[object], str]) -> str:
        with self._lock:
            return fn(self._grabber)

class _SCPIHandler(socketserver.StreamRequestHandler):
    """
    Very small line-oriented SCPI handler. One command per line, LF-terminated.
    """
    # Populated by server at construction time
    COMMANDS: Dict[str, Callable[["_SCPIHandler", str], str]] = {}
    STATE: _SCPIState

    def handle(self) -> None:
        # Optional: write banner; clients like pyvisa don't require it
        while True:
            line = self.rfile.readline()
            if not line:
                break
            cmd = line.decode("ascii", errors="ignore").strip()
            if not cmd:
                continue
            response = self._dispatch(cmd)
            if response is None:
                # No response (e.g., set-only command)
                continue
            try:
                self.wfile.write((response + "\n").encode("ascii", errors="ignore"))
                self.wfile.flush()
            except BrokenPipeError:
                break

    # --- command routing -----------------------------------------------------
    def _dispatch(self, raw: str) -> Optional[str]:
        # Normalize (e.g., "*IDN?" vs "ID?")
        key = raw.upper()
        handler = self.COMMANDS.get(key)
        if handler:
            return handler(self, raw)

        # Minimal pattern support: allow parameters after space
        head, _, arg = key.partition(" ")
        handler = self.COMMANDS.get(head)
        if handler:
            # pass the original raw (with case) if you need args
            return handler(self, raw)

        # Unknown command
        return "ERR:UNRECOGNIZED"

# --- Command implementations --------------------------------------------------
def _register_default_commands() -> Dict[str, Callable[[_SCPIHandler, str], str]]:
    def idn(self: _SCPIHandler, _: str) -> str:
        # Example using the serial/ScopeGrabber with thread safety
        def fn(grab) -> str:
            try:
                ident = grab.get_identity()  # should raise exceptions, not sys.exit()
            except Exception as e:
                return f"ERR:IDN {e}"
            return ident or "UNKNOWN"
        return self.STATE.with_grabber(fn)

    def is_busy(self: _SCPIHandler, _: str) -> str:
        # Example: map to your grabber status or return "0"/"1"
        return "0"

    def grab_png(self: _SCPIHandler, raw: str) -> str:
        # Example with arg parsing: "GRAB fname.png"
        _, _, arg = raw.partition(" ")
        filename = arg.strip() or "grab.png"
        def fn(grab) -> str:
            try:
                img = grab.grab_screen_png()
                img.save(filename)
            except Exception as e:
                return f"ERR:GRAB {e}"
            return f"OK {filename}"
        return self.STATE.with_grabber(fn)

    return {
        "*IDN?": idn,
        "IS?": is_busy,
        "GRAB": grab_png,
    }

# --- Server runner -----------------------------------------------------------
class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_scpi_server(config: SCPIConfig,
                    grabber_factory: Callable[[], object],
                    register_commands: Optional[Callable[[Dict], None]] = None) -> None:
    """
    Start a Threading TCP SCPI server. Blocks until server is closed.
    - grabber_factory: a callable that returns a configured ScopeGrabber
    - register_commands: optional hook to add/override commands
    """
    # Prepare shared state and command table
    state = _SCPIState(grabber_factory)
    commands = _register_default_commands()
    if register_commands:
        register_commands(commands)

    # Bind state/commands into handler class
    handler_cls = type(
        "_BoundSCPIHandler",
        (_SCPIHandler,),
        {"STATE": state, "COMMANDS": commands},
    )

    with _ThreadedTCPServer((config.host, config.port), handler_cls) as srv:
        try:
            srv.serve_forever(poll_interval=0.5)
        finally:
            # If your grabber needs cleanup, do it here
            # e.g., state._grabber.close()
            pass
