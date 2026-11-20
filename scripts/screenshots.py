"""Render store/README screenshots (320x170 PNG) without a device: uv run scripts/screenshots.py"""
from pathlib import Path

from czmuse.app import ChatApp
from czmuse.display import HeadlessDisplay
from czmuse.keys import KeyEvent
from czmuse.muse import Answer, MockMuse
from czmuse.render import Message

OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def shot(app, name):
    app._dirty = True
    app.tick(0.0)
    app.display.frame.save(OUT / name)
    print("wrote", OUT / name)


display = HeadlessDisplay()
app = ChatApp(display, MockMuse(0))
app.status, app.status_text = "ok", "接続OK"
app.add(Message("user", "明日の東京の天気は？"))
app.add(Message("muse", "明日の東京は晴れ時々くもり、最高気温は14℃の予報です。朝は冷えるので上着があると安心です。"))
app.kana_mode = True
for ch in "kasawoirukana":
    app.on_key(KeyEvent.of_char(ch))
shot(app, "chat.png")

import time
app.banner_until = time.monotonic() + 60
app.banner = "15:00 から打ち合わせです。資料の準備をお忘れなく。"
shot(app, "notice.png")
app.banner = None

app.input_text, app.pending = "", ""
app.busy = True
app.status, app.status_text = "busy", "考え中"
app.add(Message("user", "ありがとう"))
shot(app, "busy.png")

app.busy = False
app.help_visible = True
shot(app, "help.png")
