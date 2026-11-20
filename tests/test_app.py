import json
import shutil
import tempfile
from pathlib import Path
import socket
import threading
import time

from czmuse.app import ChatApp
from czmuse.display import HeadlessDisplay, to_rgb565
from czmuse.keys import KeyEvent, KeyTranslator
from czmuse.muse import Answer, SocketMuse, parse_reply
from czmuse.notify import NotifyServer, send

import pytest


@pytest.fixture
def sock_dir():
    # AF_UNIX paths are limited to ~104 bytes on macOS; pytest's tmp_path is too long.
    d = Path(tempfile.mkdtemp(prefix="czm"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


class FakeMuse:
    def __init__(self, answer=None):
        self.asked = []
        self.answer = answer or Answer(True, text="こんにちは！")

    def check(self):
        return None

    def ask(self, message):
        self.asked.append(message)
        return self.answer


def chars(text):
    return [KeyEvent.of_char(c) for c in text]


def run_until(app, cond, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.tick(0.01)
        if cond():
            return True
    return False


def test_send_and_reply_rendered():
    display = HeadlessDisplay(chars("hello") + [KeyEvent("enter")])
    muse = FakeMuse()
    app = ChatApp(display, muse)
    assert run_until(app, lambda: any(m.role == "muse" for m in app.messages))
    assert muse.asked == ["hello"]
    assert app.messages[-1].text == "こんにちは！"
    assert not app.busy
    app.tick(0.01)
    assert display.frame is not None and display.frame.size == (320, 170)


def test_kana_mode_and_backspace():
    display = HeadlessDisplay([KeyEvent("tab")] + chars("konnichiha") + [KeyEvent("backspace")])
    app = ChatApp(display, FakeMuse())
    app.tick(0.01)
    assert app.kana_mode
    assert app.input_text + app.pending == "こんにち"


def test_pending_n_is_flushed_on_enter():
    display = HeadlessDisplay([KeyEvent("tab")] + chars("hon") + [KeyEvent("enter")])
    muse = FakeMuse()
    app = ChatApp(display, muse)
    assert run_until(app, lambda: muse.asked)
    assert muse.asked == ["ほん"]


def test_error_answer_shown():
    display = HeadlessDisplay(chars("x") + [KeyEvent("enter")])
    app = ChatApp(display, FakeMuse(Answer(False, error="Muse に未接続です")))
    assert run_until(app, lambda: any(m.role == "error" for m in app.messages))
    assert app.status == "down"


def test_banner_from_command():
    display = HeadlessDisplay()
    app = ChatApp(display, FakeMuse())
    assert app.handle_command({"op": "screen.show", "text": "会議まで5分"})["ok"]
    assert not app.handle_command({"op": "screen.show", "text": ""})["ok"]
    app.tick(0.01)
    assert app.banner == "会議まで5分"
    display.feed([KeyEvent.of_char("a")])
    app.tick(0.01)
    assert app.banner is None
    assert app.input_text == ""  # the key only dismissed the banner


def test_long_history_scrolls_and_clamps():
    display = HeadlessDisplay()
    app = ChatApp(display, FakeMuse())
    for i in range(30):
        app._apply_answer(Answer(True, text=f"line {i} " * 8))
    display.feed([KeyEvent("pageup")] * 100)
    app.tick(0.01)
    assert 0 < app.scroll <= app.view().scroll


def test_quit_key():
    display = HeadlessDisplay([KeyEvent.of_char("q", ctrl=True)])
    app = ChatApp(display, FakeMuse())
    app.tick(0.01)
    assert not app.running


def test_key_translator_shift_and_ctrl():
    t = KeyTranslator()
    assert t.feed(30, 1).char == "a"
    t.feed(42, 1)
    assert t.feed(30, 1).char == "A"
    assert t.feed(2, 1).char == "!"
    t.feed(42, 0)
    t.feed(29, 1)
    ev = t.feed(16, 1)
    assert ev.char == "q" and ev.ctrl
    assert t.feed(16, 0) is None
    assert t.feed(999, 1).name == "unknown"


def test_rgb565_packing():
    from PIL import Image
    img = Image.new("RGB", (2, 1), (255, 0, 0))
    img.putpixel((1, 0), (0, 0, 255))
    assert to_rgb565(img) == bytes([0x00, 0xF8, 0x1F, 0x00])


def test_parse_reply_variants():
    assert parse_reply(b'{"ok": true, "reply": "hi"}') == Answer(True, text="hi")
    assert not parse_reply(b'{"ok": false, "error": "not connected to the Muse"}').ok
    assert "返答がありません" in parse_reply(b'{"ok": true, "reply": null, "detail": "x"}').error
    assert parse_reply(b'{"ok": true, "reply": "a", "partial": true}').partial
    assert not parse_reply(b"garbage").ok


def test_socket_muse_roundtrip(sock_dir):
    path = sock_dir / "s.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    seen = {}

    def serve():
        conn, _ = server.accept()
        with conn:
            seen["request"] = json.loads(conn.makefile("rb").readline())
            conn.sendall(json.dumps({"ok": True, "reply": "はい"}).encode() + b"\n")

    t = threading.Thread(target=serve)
    t.start()
    answer = SocketMuse(path, session_id="cardputer", wait_s=30).ask("テスト")
    t.join(2)
    server.close()
    assert answer == Answer(True, text="はい")
    assert seen["request"] == {"message": "テスト", "wait": 30, "session_id": "cardputer"}


def test_socket_muse_missing_service(sock_dir):
    muse = SocketMuse(sock_dir / "none.sock")
    assert muse.check() is not None
    assert not muse.ask("x").ok


def test_notify_roundtrip(sock_dir):
    path = sock_dir / "n.sock"
    got = []
    server = NotifyServer(path, lambda req: (got.append(req), {"ok": True})[1])
    server.start()
    try:
        assert send({"op": "ping"}, path) == {"ok": True}
    finally:
        server.close()
    assert got == [{"op": "ping"}]
    assert not path.exists()


def test_cardputer_zero_keycodes():
    """Codes reported by a real CardputerZero (fn=389, sym=383, fn+H=138, sym+M=93)."""
    t = KeyTranslator()
    assert t.feed(389, 1) is None          # fn alone
    assert t.feed(103, 1).name == "up"     # fn+F
    assert t.feed(389, 0) is None
    assert t.feed(138, 1).name == "help"   # fn+H
    assert t.feed(383, 1) is None          # sym alone
    assert t.feed(93, 1).char == "?"       # sym+M


def test_help_key_opens_help():
    display = HeadlessDisplay([KeyEvent("help")])
    app = ChatApp(display, FakeMuse())
    app.tick(0.01)
    assert app.help_visible


def test_notify_close_keeps_a_newer_socket(sock_dir):
    path = sock_dir / "n.sock"
    old = NotifyServer(path, lambda req: {"ok": True, "who": "old"})
    old.start()
    new = NotifyServer(path, lambda req: {"ok": True, "who": "new"})
    new.start()          # replaces the old socket, like a second app instance
    old.close()          # must not delete the new instance's socket
    try:
        assert send({"op": "ping"}, path)["who"] == "new"
    finally:
        new.close()
    assert not path.exists()


def test_default_socket_path_prefers_runtime_dir(monkeypatch):
    from czmuse import notify
    monkeypatch.delenv("CZMUSE_NOTIFY_SOCKET", raising=False)
    path = notify.default_socket_path()
    assert path.name.startswith("czmuse-notify")
    monkeypatch.setenv("CZMUSE_NOTIFY_SOCKET", "/x/y.sock")
    assert notify.default_socket_path() == Path("/x/y.sock")
