"""A tiny local socket so that Muse's custom commands can reach the running UI.

The musegadget service runs custom commands (``/etc/musegadget/commands.d``)
as a separate process. ``czmuse-command`` forwards them here, one JSON line
per connection, and gets one JSON line back.
"""
from __future__ import annotations

import json
import os
import queue
import socket
import threading
from pathlib import Path
from typing import Callable, Optional

DEFAULT_NOTIFY_SOCKET = Path(os.environ.get("CZMUSE_NOTIFY_SOCKET", "/tmp/czmuse-notify.sock"))
MAX_REQUEST = 64 * 1024


class NotifyServer:
    """Accepts requests on a Unix socket and hands them to ``handler``.

    ``handler(request) -> dict`` runs on the server thread; keep it quick
    (the UI only queues the request).
    """

    def __init__(self, path: Path, handler: Callable[[dict], dict]):
        self.path = Path(path)
        self.handler = handler
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self.path.exists() or self.path.is_symlink():
            self.path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.path))
        # The command helper runs as musegadget's run-as account, which may
        # differ from the account that launched the UI. Requests only put
        # text on this screen, so any local account may send them.
        os.chmod(self.path, 0o666)
        sock.listen(4)
        sock.settimeout(0.5)
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, name="czmuse-notify", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(3)
                try:
                    line = conn.makefile("rb").readline(MAX_REQUEST)
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("expected a JSON object")
                    reply = self.handler(request)
                except Exception as exc:  # report, never crash the UI
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                try:
                    conn.sendall(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
                except OSError:
                    pass

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self.path.unlink()
        except OSError:
            pass


def send(request: dict, path: Path = DEFAULT_NOTIFY_SOCKET, timeout: float = 5) -> dict:
    """Send one request to a running UI. Raises OSError when it isn't running."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
        return json.loads(sock.makefile("rb").readline(MAX_REQUEST))


class Inbox:
    """Thread-safe queue of things for the UI loop to apply."""

    def __init__(self) -> None:
        self._q: "queue.Queue[tuple]" = queue.Queue()

    def put(self, kind: str, payload) -> None:
        self._q.put((kind, payload))

    def drain(self):
        while True:
            try:
                yield self._q.get_nowait()
            except queue.Empty:
                return
