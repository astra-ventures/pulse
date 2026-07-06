"""
Pulse v2 Runtime — Entry Point
================================
Starts the HypostasRuntime as a long-running process.

Usage:
    python -m pulse.runtime

Handles SIGTERM / SIGINT for graceful shutdown so the LaunchAgent can
restart cleanly.

Logs to stdout/stderr (LaunchAgent redirects to log files).
"""

import logging
import os
import signal
import socket
import sys
import time

from pulse.src.runtime import HypostasRuntime

_LOCK_FILE = os.path.expanduser("~/.pulse/runtime.lock")
_lock_socket = None  # module-level ref keeps the socket alive


def _acquire_lock() -> bool:
    """Return True if we got the lock (single-instance guard via Unix socket)."""
    global _lock_socket
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(_LOCK_FILE)
        _lock_socket = sock  # keep alive at module level
        return True
    except OSError:
        return False


def _release_lock() -> None:
    global _lock_socket
    if _lock_socket is not None:
        try:
            _lock_socket.close()
        except OSError:
            pass
        _lock_socket = None
    try:
        os.remove(_LOCK_FILE)
    except OSError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-20s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

logger = logging.getLogger("pulse.runtime.__main__")


def main() -> None:
    # Single-instance guard — exit cleanly if another runtime is already running
    if not _acquire_lock():
        logger.warning("Another HypostasRuntime instance is already running — exiting.")
        sys.exit(0)

    runtime = HypostasRuntime()

    def _shutdown(signum: int, frame) -> None:  # noqa: ANN001
        logger.info("Received signal %d — shutting down gracefully …", signum)
        runtime.stop()
        _release_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    runtime.start()
    logger.info(
        "HypostasRuntime running | health: http://127.0.0.1:%d/runtime/health",
        HypostasRuntime.PORT,
    )

    # Keep the main thread alive while background threads do the work
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        runtime.stop()


if __name__ == "__main__":
    main()
