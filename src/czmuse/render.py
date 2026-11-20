"""Drawing the 320x170 chat screen with Pillow."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    # Debian / Raspberry Pi OS (fonts-noto-cjk, fonts-ipafont, fonts-vlgothic)
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf", 0),
    ("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 0),
    ("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf", 0),
    ("/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf", 0),
    # macOS, for desktop development
    ("/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
    # Last resort: no Japanese glyphs
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]

BG = (8, 10, 16)
HEADER_BG = (24, 28, 44)
FG = (232, 234, 240)
DIM = (130, 136, 150)
USER = (120, 200, 255)
MUSE = (232, 234, 240)
ERROR = (255, 120, 110)
NOTICE_BG = (60, 44, 110)
ACCENT = (150, 120, 255)
OK = (90, 210, 120)
WARN = (240, 190, 70)
INPUT_BG = (20, 24, 36)


def find_font_path() -> Tuple[Optional[str], int]:
    override = os.environ.get("CZMUSE_FONT")
    if override and os.path.exists(override):
        return override, 0
    for path, index in FONT_CANDIDATES:
        if os.path.exists(path):
            return path, index
    return None, 0


def load_font(size: int):
    path, index = find_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            pass
    return ImageFont.load_default()


def wrap(text: str, font, width: int) -> List[str]:
    """Wrap text to ``width`` pixels, character by character (CJK-friendly),
    preferring to break Latin text at a space."""
    lines: List[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        line = ""
        for ch in para:
            candidate = line + ch
            if font.getlength(candidate) <= width or not line:
                line = candidate
                continue
            cut = line.rfind(" ")
            if ch != " " and cut > 0 and len(line) - cut < 16:
                lines.append(line[:cut])
                line = line[cut + 1:] + ch
            else:
                lines.append(line)
                line = "" if ch == " " else ch
        lines.append(line)
    return lines


@dataclass
class Message:
    role: str  # "user", "muse", "error", "system", "notice"
    text: str


@dataclass
class ViewState:
    messages: Sequence[Message]
    input_text: str = ""
    pending: str = ""          # romaji not yet converted (underlined)
    kana_mode: bool = False
    status: str = "ok"          # ok | busy | down
    status_text: str = ""
    scroll: int = 0             # lines scrolled up from the bottom
    spinner: int = 0
    banner: Optional[str] = None
    title: str = "Muse"
    help_visible: bool = False
    max_scroll: int = field(default=0)


class Renderer:
    def __init__(self, size=(320, 170), font_size: int = 12):
        self.size = size
        self.font = load_font(font_size)
        self.small = load_font(10)
        self.line_h = font_size + 3
        self._wrap_cache: dict = {}

    # -- layout helpers --
    def _wrapped(self, msg: Message, width: int) -> List[str]:
        prefix = {"user": "› ", "error": "! ", "system": "", "notice": "★ "}.get(msg.role, "")
        key = (msg.role, msg.text, width)
        cached = self._wrap_cache.get(key)
        if cached is None:
            cached = wrap(prefix + msg.text, self.font, width)
            if len(self._wrap_cache) > 512:
                self._wrap_cache.clear()
            self._wrap_cache[key] = cached
        return cached

    def chat_lines(self, messages: Sequence[Message], width: int) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for i, msg in enumerate(messages):
            if i:
                out.append(("gap", ""))
            for line in self._wrapped(msg, width):
                out.append((msg.role, line))
        return out

    # -- drawing --
    def draw(self, state: ViewState) -> Image.Image:
        w, h = self.size
        img = Image.new("RGB", self.size, BG)
        d = ImageDraw.Draw(img)

        # header
        header_h = 16
        d.rectangle([0, 0, w, header_h - 1], fill=HEADER_BG)
        dot = {"ok": OK, "busy": WARN, "down": ERROR}.get(state.status, DIM)
        d.ellipse([5, 4, 12, 11], fill=dot)
        d.text((17, 1), state.title, font=self.small, fill=FG)
        status = state.status_text
        if state.status == "busy":
            status = (status or "考え中") + "." * (state.spinner % 4)
        d.text((60, 2), status, font=self.small, fill=DIM)
        mode = "あ" if state.kana_mode else "A"
        mw = d.textlength(mode, font=self.small)
        d.rounded_rectangle([w - mw - 12, 2, w - 3, header_h - 3], radius=3,
                            fill=ACCENT if state.kana_mode else (60, 64, 80))
        d.text((w - mw - 7, 1), mode, font=self.small, fill=FG)

        # input box (bottom)
        input_lines = wrap(state.input_text + state.pending + "▏", self.font, w - 12) or [""]
        input_lines = input_lines[-2:]
        box_h = len(input_lines) * self.line_h + 6
        box_top = h - box_h
        d.rectangle([0, box_top, w, h], fill=INPUT_BG)
        d.line([0, box_top, w, box_top], fill=(50, 56, 78))
        y = box_top + 3
        if not state.input_text and not state.pending:
            hint = "メッセージを入力  Tab:あ/A  ?:ヘルプ"
            d.text((6, y), "▏", font=self.font, fill=FG)
            d.text((14, y + 1), hint, font=self.small, fill=DIM)
        else:
            for line in input_lines:
                d.text((6, y), line, font=self.font, fill=FG)
                y += self.line_h
            if state.pending:
                last = input_lines[-1].rstrip("▏")
                if last.endswith(state.pending):
                    x0 = 6 + d.textlength(last[: -len(state.pending)], font=self.font)
                    x1 = 6 + d.textlength(last, font=self.font)
                    uy = box_top + 3 + (len(input_lines) - 1) * self.line_h + self.line_h - 1
                    d.line([x0, uy, x1, uy], fill=ACCENT)

        # chat area
        top = header_h + 2
        bottom = box_top - 2
        lines = self.chat_lines(state.messages, w - 12)
        visible = max(1, (bottom - top) // self.line_h)
        state.max_scroll = max(0, len(lines) - visible)
        scroll = min(state.scroll, state.max_scroll)
        end = len(lines) - scroll
        start = max(0, end - visible)
        y = top
        colors = {"user": USER, "muse": MUSE, "error": ERROR, "system": DIM, "notice": WARN}
        for role, text in lines[start:end]:
            if role != "gap":
                d.text((6, y), text, font=self.font, fill=colors.get(role, FG))
            y += self.line_h if role != "gap" else self.line_h // 3
        if scroll:
            d.text((w - 22, bottom - 12), f"↑{scroll}", font=self.small, fill=DIM)

        if state.banner:
            self._draw_banner(d, state.banner)
        if state.help_visible:
            self._draw_help(d)
        return img

    def _draw_banner(self, d: ImageDraw.ImageDraw, text: str) -> None:
        w, h = self.size
        lines = wrap(text, self.font, w - 32)[:6]
        bh = len(lines) * self.line_h + 22
        top = (h - bh) // 2
        d.rounded_rectangle([10, top, w - 10, top + bh], radius=6, fill=NOTICE_BG, outline=ACCENT)
        d.text((18, top + 3), "Muse からのお知らせ", font=self.small, fill=WARN)
        y = top + 17
        for line in lines:
            d.text((18, y), line, font=self.font, fill=FG)
            y += self.line_h

    def _draw_help(self, d: ImageDraw.ImageDraw) -> None:
        w, h = self.size
        rows = [
            ("Enter", "送信"),
            ("Tab", "英数 ⇄ ローマ字かな"),
            ("↑ ↓", "スクロール"),
            ("Ctrl+L", "表示をクリア"),
            ("Esc", "入力を消す / 閉じる"),
            ("Ctrl+Q", "終了"),
        ]
        d.rounded_rectangle([20, 18, w - 20, h - 8], radius=6, fill=(16, 18, 30), outline=ACCENT)
        y = 24
        for key, desc in rows:
            d.text((30, y), key, font=self.font, fill=ACCENT)
            d.text((92, y), desc, font=self.font, fill=FG)
            y += self.line_h + 2
