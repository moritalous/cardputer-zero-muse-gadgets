"""The chat application: state, key handling and the main loop."""
from __future__ import annotations

import threading
import time
from typing import List, Optional

from . import romaji
from .keys import KeyEvent
from .muse import Answer
from .notify import Inbox
from .render import Message, Renderer, ViewState

MAX_MESSAGES = 200
MAX_INPUT_CHARS = 2000
BANNER_SECONDS = 15
STATUS_CHECK_S = 10


class ChatApp:
    def __init__(self, display, muse, *, kana_mode: bool = False, title: str = "Muse"):
        self.display = display
        self.muse = muse
        self.renderer = Renderer(display.size)
        self.inbox = Inbox()
        self.messages: List[Message] = [Message("system", "CardputerZero × Muse Gadget")]
        self.input_text = ""
        self.pending = ""
        self.kana_mode = kana_mode
        self.title = title
        self.scroll = 0
        self.busy = False
        self.status = "ok"
        self.status_text = ""
        self.banner: Optional[str] = None
        self.banner_until = 0.0
        self.help_visible = False
        self.running = True
        self.spinner = 0
        self._dirty = True
        self._last_check = 0.0
        self._last_state: Optional[ViewState] = None

    # -- Muse ----------------------------------------------------------------------

    def check_connection(self) -> None:
        if self.busy:
            return
        problem = self.muse.check()
        new_status = "down" if problem else "ok"
        new_text = problem or "接続OK"
        if (new_status, new_text) != (self.status, self.status_text):
            self.status, self.status_text = new_status, new_text
            self._dirty = True

    def send(self, text: str) -> None:
        text = text.strip()
        if not text or self.busy:
            return
        self.add(Message("user", text))
        self.busy = True
        self.status, self.status_text = "busy", "考え中"

        def work():
            try:
                answer = self.muse.ask(text)
            except Exception as exc:  # keep the UI alive whatever happens
                answer = Answer(False, error=f"{type(exc).__name__}: {exc}")
            self.inbox.put("answer", answer)

        threading.Thread(target=work, name="czmuse-ask", daemon=True).start()

    def _apply_answer(self, answer: Answer) -> None:
        self.busy = False
        if answer.ok:
            text = answer.text + ("\n（途中までの返答です）" if answer.partial else "")
            self.add(Message("muse", text))
            self.status, self.status_text = "ok", "接続OK"
        else:
            self.add(Message("error", answer.error))
            self.status, self.status_text = "down", "エラー"
            self._last_check = time.monotonic()  # recheck soon

    # -- notifications from custom commands ---------------------------------------------

    def handle_command(self, request: dict) -> dict:
        """Runs on the notify-server thread: validate and queue only."""
        op = request.get("op")
        if op == "screen.show":
            text = request.get("text")
            if not isinstance(text, str) or not text.strip():
                return {"ok": False, "error": "text is required"}
            self.inbox.put("banner", text.strip()[:500])
            return {"ok": True, "shown": True}
        if op == "chat.read":
            count = request.get("count", 5)
            count = count if isinstance(count, int) and 1 <= count <= 50 else 5
            recent = [{"role": m.role, "text": m.text} for m in self.messages[-count:]]
            return {"ok": True, "messages": recent}
        if op == "ping":
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op!r}"}

    # -- state ------------------------------------------------------------------------

    def add(self, message: Message) -> None:
        self.messages.append(message)
        del self.messages[:-MAX_MESSAGES]
        self.scroll = 0
        self._dirty = True

    def commit_pending(self) -> None:
        if self.pending:
            self.input_text += romaji.flush(self.pending)
            self.pending = ""

    def type_char(self, ch: str) -> None:
        if len(self.input_text) + len(self.pending) >= MAX_INPUT_CHARS:
            return
        if not self.kana_mode:
            self.input_text += ch
            return
        kana, rest = romaji.convert(self.pending + ch)
        self.input_text += kana
        self.pending = rest

    def backspace(self) -> None:
        if self.pending:
            self.pending = self.pending[:-1]
        else:
            self.input_text = self.input_text[:-1]

    def on_key(self, ev: KeyEvent) -> None:
        self._dirty = True
        if ev.name == "quit" or (ev.ctrl and ev.char in ("q", "Q")):
            self.running = False
            return
        if self.banner:
            self.banner = None
            return
        if self.help_visible:
            self.help_visible = False
            return
        if ev.name == "help" or (ev.ctrl and ev.char in ("h", "H")):
            self.help_visible = True
            return
        if ev.ctrl and ev.char in ("l", "L"):
            self.messages = [Message("system", "会話の表示をクリアしました")]
            self.scroll = 0
            return
        if ev.name == "char" and ev.char == "?" and not self.input_text and not self.pending:
            self.help_visible = True
            return
        if ev.name == "char" and ev.char and not ev.ctrl:
            self.type_char(ev.char)
        elif ev.name == "backspace":
            self.backspace()
        elif ev.name == "enter":
            self.commit_pending()
            if not self.busy and self.input_text.strip():
                text, self.input_text = self.input_text, ""
                self.send(text)
        elif ev.name == "tab":
            self.commit_pending()
            self.kana_mode = not self.kana_mode
        elif ev.name == "esc":
            if self.input_text or self.pending:
                self.input_text, self.pending = "", ""
            else:
                self.scroll = 0
        elif ev.name in ("up", "pageup"):
            self.scroll += 1 if ev.name == "up" else 5
        elif ev.name in ("down", "pagedown"):
            self.scroll = max(0, self.scroll - (1 if ev.name == "down" else 5))
        elif ev.name == "home":
            self.scroll = 10 ** 6
        elif ev.name == "end":
            self.scroll = 0
        else:
            self._dirty = False

    def view(self) -> ViewState:
        state = ViewState(
            messages=self.messages, input_text=self.input_text, pending=self.pending,
            kana_mode=self.kana_mode, status=self.status, status_text=self.status_text,
            scroll=self.scroll, spinner=self.spinner, banner=self.banner, title=self.title,
            help_visible=self.help_visible,
        )
        return state

    def render(self):
        state = self.view()
        image = self.renderer.draw(state)
        self.scroll = min(self.scroll, state.max_scroll)  # clamp after layout
        return image

    # -- loop -----------------------------------------------------------------------

    def tick(self, timeout: float = 0.05) -> None:
        for ev in self.display.poll(timeout):
            self.on_key(ev)
        for kind, payload in self.inbox.drain():
            if kind == "answer":
                self._apply_answer(payload)
            elif kind == "banner":
                self.banner = payload
                self.banner_until = time.monotonic() + BANNER_SECONDS
                self.add(Message("notice", payload))
            self._dirty = True
        now = time.monotonic()
        if self.banner and now > self.banner_until:
            self.banner = None
            self._dirty = True
        if self.busy:
            spin = int(now * 3)
            if spin != self.spinner:
                self.spinner = spin
                self._dirty = True
        if now - self._last_check > STATUS_CHECK_S:
            self._last_check = now
            self.check_connection()
        if self._dirty:
            self._dirty = False
            self.display.show(self.render())

    def run(self) -> None:
        self.check_connection()
        self._last_check = time.monotonic()
        while self.running:
            self.tick()
