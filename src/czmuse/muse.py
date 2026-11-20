"""Talking to Muse through the musegadget service's local socket.

The SDK's systemd service (``musegadget run``) keeps the encrypted session
to Muse and accepts one JSON line per connection on
``/run/musegadget/musegadget.sock``::

    {"message": "...", "session_id": "...", "wait": 180}

With ``wait`` it answers with Muse's reply text (``"reply"``). This module
wraps that, plus a mock for development without a paired device.
"""
from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_SOCKET = Path(os.environ.get("MUSEGADGET_SOCKET", "/run/musegadget/musegadget.sock"))
DEFAULT_WAIT_S = 180
MAX_REPLY_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class Answer:
    ok: bool
    text: str = ""
    error: str = ""
    partial: bool = False


class MuseError(Exception):
    pass


class SocketMuse:
    """Client for the local socket of the musegadget service."""

    def __init__(self, path: Path = DEFAULT_SOCKET, session_id: Optional[str] = None,
                 wait_s: int = DEFAULT_WAIT_S):
        self.path = Path(path)
        self.session_id = session_id
        self.wait_s = wait_s

    def describe(self) -> str:
        return f"socket {self.path}"

    def check(self) -> Optional[str]:
        """Return None when the service socket is usable, else a short reason."""
        if not self.path.exists():
            return "musegadget サービスが動いていません"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)
                sock.connect(str(self.path))
        except PermissionError:
            return "ソケットへのアクセス権がありません"
        except OSError:
            return "musegadget サービスに接続できません"
        return None

    def ask(self, message: str) -> Answer:
        request = {"message": message, "wait": self.wait_s}
        if self.session_id:
            request["session_id"] = self.session_id
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.wait_s + 30)
                sock.connect(str(self.path))
                sock.sendall(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
                line = sock.makefile("rb").readline(MAX_REPLY_BYTES)
        except PermissionError:
            return Answer(False, error="ソケットへのアクセス権がありません")
        except OSError as exc:
            return Answer(False, error=f"musegadget サービスに接続できません ({type(exc).__name__})")
        return parse_reply(line)


def parse_reply(line: bytes) -> Answer:
    """Interpret one reply line from the service socket."""
    try:
        reply = json.loads(line)
    except ValueError:
        return Answer(False, error="サービスから不正な応答がありました")
    if not isinstance(reply, dict):
        return Answer(False, error="サービスから不正な応答がありました")
    if not reply.get("ok"):
        error = str(reply.get("error") or "送信できませんでした")
        if error == "not connected to the Muse":
            error = "Muse に未接続です（ペアリング・ネットワークを確認）"
        if reply.get("sent") == "unknown":
            error = "届いたか不明です: " + error
        return Answer(False, error=error)
    text = reply.get("reply")
    if not isinstance(text, str):
        detail = str(reply.get("detail") or "")
        return Answer(False, error="送信しましたが返答がありませんでした" + (f" ({detail})" if detail else ""))
    if not text:
        return Answer(True, text="（Muse はテキストなしで応答を終えました）")
    return Answer(True, text=text, partial=bool(reply.get("partial")))


class MockMuse:
    """Pretends to be Muse, for running the UI without a paired device."""

    def __init__(self, delay_s: float = 1.2):
        self.delay_s = delay_s

    def describe(self) -> str:
        return "mock"

    def check(self) -> Optional[str]:
        return None

    def ask(self, message: str) -> Answer:
        time.sleep(self.delay_s)
        if message.strip() in ("err", "エラー"):
            return Answer(False, error="（モック）わざと失敗しました")
        return Answer(True, text=(
            f"（モック）「{message}」を受け取りました。"
            "これは CardputerZero 上の Muse Gadget の表示テストです。"
            "長い返答は自動で折り返され、↑↓キーでスクロールできます。"
        ))
