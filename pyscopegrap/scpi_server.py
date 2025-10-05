# scpi_server.py
from __future__ import annotations

import socketserver
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional
import io
import logging

# top of file
try:
    from pyscopegrap.app_settings import AppSettings
    _FG_DEFAULT = AppSettings.DEFAULT_FG
    _BG_DEFAULT = AppSettings.DEFAULT_BG
except Exception:
    # Fallback if settings module isn't available
    _FG_DEFAULT = "#222222"
    _BG_DEFAULT = "#b1e580"



__all__ = ["run_scpi_server", "SCPIConfig"]

@dataclass(frozen=True)
class SCPIConfig:
    host: str = "127.0.0.1"
    port: int = 5025

# --- Shared state -------------------------------------------------------------
class _SCPIState:
    """
    Holds a single ScopeGrabber instance and ensures its serial port is opened
    exactly once (lazy). We keep a lock around every grabber access so multiple
    client threads can't poke the serial line concurrently.
    """
    def __init__(self, grabber_factory: Callable[[], object]) -> None:
        self._grabber_factory = grabber_factory
        self._grabber = None
        self._lock = threading.Lock()
        self._opened = False

    def _ensure_open(self) -> None:
        if self._opened:
            return
        with self._lock:
            if self._grabber is None:
                self._grabber = self._grabber_factory()
            if not self._opened:
                import logging
                logging.getLogger("PyScopeGrap").info("[SCPI] Opening serial on first command …")
                try:
                    self._grabber.initialize_port()  # correct API
                except Exception as e:
                    raise RuntimeError(f"open failed: {e}") from e
                self._opened = True


    def with_grabber(self, fn):
        self._ensure_open()
        with self._lock:
            return fn(self._grabber)

# helper to encode a SCPI definite-length arbitrary block (binblock)
def _scpi_binblock(payload: bytes) -> bytes:
    n = len(payload)
    n_str = str(n)
    header = b"#" + str(len(n_str)).encode("ascii") + n_str.encode("ascii")
    return header + payload


# --- Request handler ----------------------------------------------------------
class _SCPIHandler(socketserver.StreamRequestHandler):
    COMMANDS: Dict[str, Callable[["_SCPIHandler", str], Optional[str]]] = {}
    STATE: _SCPIState

    def handle(self) -> None:
        LOG = logging.getLogger("PyScopeGrap")
        try:
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                cmd = line.decode("ascii", errors="ignore").strip()
                if not cmd:
                    continue
                resp = self._dispatch(cmd)
                if resp is None:
                    continue
                # --- WRITE TEXT vs BINARY RESPONSES CORRECTLY ---
                if isinstance(resp, bytes):
                    self.wfile.write(resp)  # binblock
                    self.wfile.write(b"\n")  # <-- add this: SCPI-style line terminator
                else:
                    self.wfile.write((resp + "\n").encode("ascii", errors="ignore"))
                self.wfile.flush()


        except Exception as e:
            LOG.debug("[SCPI] handler error: %r", e, exc_info=True)
            return

    def _dispatch(self, raw: str) -> Optional[str | bytes]:
        up = raw.upper()

        # *IDN?
        if up == "*IDN?":
            try:
                def fn(g):
                    try:
                        return g.scpi_idn_string()
                    except Exception as e:
                        return f"ERR:IDN {e}"
                return self.STATE.with_grabber(fn)
            except Exception as e:
                return f"ERR:OPEN {e}"

        # HCOPY:DATA?  -> return PNG as SCPI binblock
        # inside _SCPIHandler._dispatch
        if up == "HCOPY:DATA?":
            try:
                # scpi_server.py — inside _SCPIHandler._dispatch, in the HCOPY:DATA? branch
                def fn(g):
                    try:
                        img = g.get_screenshot_image(fg=_FG_DEFAULT, bg=_BG_DEFAULT, comment="SCPI HCOPY")
                        buf = io.BytesIO()
                        img.save(buf, "PNG")
                        payload = buf.getvalue()
                        logging.getLogger("PyScopeGrap").info("[SCPI] HCOPY:DATA? sending %d bytes", len(payload))
                        return _scpi_binblock(payload)  # header + payload; trailing '\n' added in handle()
                    except Exception as e:
                        return f"ERR:HCOPY:DATA {e}"


                return self.STATE.with_grabber(fn)
            except Exception as e:
                return f"ERR:OPEN {e}"


        # (existing example)
        if up == "MEAS:VOLT:DC?":
            try:
                def fn(g):
                    try:
                        val = g.query_measurement(field=1, numeric_only=True)
                    except Exception as e:
                        return f"ERR:MEAS:VOLT:DC {e}"
                    return str(val)
                return self.STATE.with_grabber(fn)
            except Exception as e:
                return f"ERR:OPEN {e}"

        # Optional SCPI-style:
        # return '-113,"Undefined header"'
        return f"ERR:UNRECOGNIZED {raw}"


def _dispatch(self, raw: str) -> Optional[str]:
    up = raw.upper()

    if up == "*IDN?":
        try:
            def fn(g):
                try:
                    return g.scpi_idn_string()  # e.g., "FLUKE,<model>,-,<fw>"
                except Exception as e:
                    return f"ERR:IDN {e}"
            return self.STATE.with_grabber(fn)
        except Exception as e:
            return f"ERR:OPEN {e}"

    if up == "MEAS:VOLT:DC?":
        try:
            def fn(g):
                try:
                    val = g.query_measurement(field=1, numeric_only=True)
                except Exception as e:
                    return f"ERR:MEAS:VOLT:DC {e}"
                return str(val)  # numeric only; client adds " V"
            return self.STATE.with_grabber(fn)
        except Exception as e:
            return f"ERR:OPEN {e}"

    return f"ERR:UNRECOGNIZED {raw}"

def run_scpi_server(config: SCPIConfig,
                    grabber_factory: Callable[[], object]) -> None:
    """
    Start a simple SCPI server. Blocks until interrupted.

    How to stop:
      Press Ctrl+C in this terminal, or send SIGINT to the process.
    """
    LOG = logging.getLogger("PyScopeGrap")

    state = _SCPIState(grabber_factory)
    handler_cls = _make_handler(state)

    # --- EAGER SERIAL OPEN (for immediate visibility) -----------------------
    # Build a grabber now (without opening previously), log target, then try
    # the real initialization so users see serial messages right away.
    if state._grabber is None:
        state._grabber = state._grabber_factory()
    g = state._grabber

    # Tell the user what we're aiming for (even before open)
    tty = getattr(g, "tty", "<unknown>")
    baud = getattr(g, "baud", "<unknown>")
    LOG.info("[SCPI] Target serial: %s (configured baud %s). Opening now…", tty, baud)

    try:
        # This logs “Opening and configuring serial port…”, “Init with 1200 done”, etc.
        # inside ScopeGrabber (visible with -v / INFO). :contentReference[oaicite:2]{index=2}
        g.initialize_port()
        state._opened = True
        # If pyserial exposes real settings, show them:
        p = getattr(g, "port", None)
        real_baud = getattr(p, "baudrate", baud) if p else baud
        LOG.info("[SCPI] Serial open on %s at %s baud.", tty, real_baud)
    except Exception as e:
        # Don’t abort the server; we’ll retry on first command and return ERR:OPEN
        LOG.warning("[SCPI] Serial open failed: %s", e)

    addr = (config.host, config.port)
    with _ThreadedTCPServer(addr, handler_cls) as srv:
        LOG.info("[SCPI] Serving on %s:%s  —  press Ctrl+C to stop.", *addr)
        try:
            srv.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            LOG.info("[SCPI] Shutting down (Ctrl+C).")
        finally:
            try:
                if state._grabber is not None:
                    close = getattr(state._grabber, "close", None)
                    if callable(close):
                        close()
            except Exception:
                pass

# --- Default command table (currently handled inline in _dispatch) ------------
def _make_handler(state: _SCPIState):
    # Bind state into a new handler subclass so each server has its own STATE
    return type("_BoundSCPIHandler", (_SCPIHandler,), {"STATE": state})

# --- Threaded server ----------------------------------------------------------
class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

