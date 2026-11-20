"""Output/input backends: the real framebuffer, a Tk window for desktop
development, and a headless one for tests and screenshots.

Every backend has the same small surface:

- ``size``: ``(width, height)``
- ``show(image)``: draw a PIL RGB image of exactly ``size``
- ``poll(timeout)``: wait up to ``timeout`` seconds and return key events
- ``close()``
"""
from __future__ import annotations

import base64
import fcntl
import glob
import io
import mmap
import os
import queue
import select
import struct
import sys
import time
from typing import Iterable, List, Optional, Sequence

from PIL import Image

from .keys import KeyEvent, KeyTranslator

WIDTH, HEIGHT = 320, 170

# --- Linux framebuffer -----------------------------------------------------------

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602
_VAR_FMT = "8I"
_FIX_FMT = "16sL" + "I" * 6 + "HHHI"

# struct input_event on 64-bit Linux: timeval(2 x long), u16 type, u16 code, s32 value
_EV_FMT = "llHHi"
_EV_SIZE = struct.calcsize(_EV_FMT)
_EV_KEY = 0x01
_EV_REL = 0x02
_EVIOCGBIT_0 = 0x80004520
CARDPUTER_KEYPAD = "/dev/input/by-path/platform-3f804000.i2c-event"

try:  # numpy makes RGB565 conversion ~50x faster; it is optional.
    import numpy as _np
except ImportError:  # pragma: no cover - depends on the machine
    _np = None


def to_rgb565(img: Image.Image) -> bytes:
    """Pack an RGB image as little-endian RGB565."""
    if _np is not None:
        arr = _np.asarray(img.convert("RGB"), dtype=_np.uint16)
        packed = ((arr[..., 0] >> 3) << 11) | ((arr[..., 1] >> 2) << 5) | (arr[..., 2] >> 3)
        return packed.astype("<u2").tobytes()
    raw = img.convert("RGB").tobytes()
    out = bytearray(len(raw) // 3 * 2)
    for j, i in enumerate(range(0, len(raw), 3)):
        v = ((raw[i] >> 3) << 11) | ((raw[i + 1] >> 2) << 5) | (raw[i + 2] >> 3)
        out[2 * j] = v & 0xFF
        out[2 * j + 1] = v >> 8
    return bytes(out)


def _supports(fd: int, ev_type: int) -> bool:
    try:
        buf = bytearray(4)
        fcntl.ioctl(fd, _EVIOCGBIT_0 | (len(buf) << 16), buf)
    except OSError:
        return False
    return bool(int.from_bytes(buf, "little") & (1 << ev_type))


def open_keyboards(explicit: Optional[str] = None) -> List[int]:
    """Open evdev keyboards non-blocking, preferring the CardputerZero keypad.

    Pointer-like devices (HDMI-CEC pseudo keyboards report EV_REL) are skipped.
    """
    candidates: List[str] = []
    for path in (explicit, os.environ.get("INPUT_DEV")):
        if path:
            candidates.append(path)
    candidates.append(CARDPUTER_KEYPAD)
    candidates.extend(sorted(glob.glob("/dev/input/event*")))
    fds: List[int] = []
    seen = set()
    for path in candidates:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        if not _supports(fd, _EV_KEY) or _supports(fd, _EV_REL):
            os.close(fd)
            continue
        fds.append(fd)
    return fds


class FramebufferDisplay:
    """Draws to ``/dev/fb0`` (RGB565) and reads the keyboard through evdev."""

    def __init__(self, device: str = "", input_device: str = "", debug_keys: bool = False):
        device = device or os.environ.get("APPLAUNCH_LINUX_FBDEV_DEVICE", "/dev/fb0")
        self._fd = os.open(device, os.O_RDWR)
        try:
            var = bytearray(160)
            fcntl.ioctl(self._fd, FBIOGET_VSCREENINFO, var)
            xres, yres, _xv, _yv, _xo, _yo, bpp, _g = struct.unpack_from(_VAR_FMT, var, 0)
            fix = bytearray(struct.calcsize(_FIX_FMT))
            fcntl.ioctl(self._fd, FBIOGET_FSCREENINFO, fix)
            fields = struct.unpack(_FIX_FMT, fix)
            smem_len, self._line_length = fields[2], fields[8]
            if bpp != 16:
                raise RuntimeError(f"expected a 16 bpp (RGB565) framebuffer, got {bpp} bpp")
            self._mm = mmap.mmap(self._fd, smem_len, mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE)
        except Exception:
            os.close(self._fd)
            raise
        self.size = (xres, yres)
        self._keyboards = open_keyboards(input_device)
        self._translator = KeyTranslator()
        self._debug_keys = debug_keys
        if not self._keyboards:
            print("czmuse: no keyboard found under /dev/input (are you in the 'input' group?)",
                  file=sys.stderr)

    def show(self, image: Image.Image) -> None:
        if image.size != self.size:
            image = image.resize(self.size)
        data = to_rgb565(image)
        w, h = self.size
        row = w * 2
        if self._line_length == row:
            self._mm.seek(0)
            self._mm.write(data)
            return
        for y in range(h):
            self._mm.seek(y * self._line_length)
            self._mm.write(data[y * row:(y + 1) * row])

    def poll(self, timeout: float) -> List[KeyEvent]:
        if not self._keyboards:
            time.sleep(timeout)
            return []
        try:
            ready, _, _ = select.select(self._keyboards, [], [], timeout)
        except (OSError, ValueError):
            return []
        events: List[KeyEvent] = []
        for fd in ready:
            try:
                data = os.read(fd, _EV_SIZE * 64)
            except OSError:
                continue
            for off in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                _s, _u, etype, code, value = struct.unpack(_EV_FMT, data[off:off + _EV_SIZE])
                if etype != _EV_KEY:
                    continue
                if self._debug_keys and value == 1:
                    print(f"czmuse: key code={code}", file=sys.stderr)
                event = self._translator.feed(code, value)
                if event is not None:
                    events.append(event)
        return events

    def close(self) -> None:
        for fd in self._keyboards:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            self._mm.close()
        finally:
            os.close(self._fd)


# --- Tk window (desktop development) ---------------------------------------------

_TK_SPECIAL = {
    "Return": "enter", "KP_Enter": "enter", "BackSpace": "backspace", "Delete": "delete",
    "Escape": "esc", "Tab": "tab", "Up": "up", "Down": "down", "Left": "left",
    "Right": "right", "Prior": "pageup", "Next": "pagedown", "Home": "home", "End": "end",
}


class TkDisplay:
    """A scaled window that mimics the 320x170 screen, for development on a PC."""

    def __init__(self, scale: int = 3, title: str = "CardputerZero - Muse Gadget"):
        import tkinter as tk

        self._tk = tk
        self.size = (WIDTH, HEIGHT)
        self._scale = max(1, scale)
        self._root = tk.Tk()
        self._root.title(title)
        self._root.resizable(False, False)
        self._label = tk.Label(self._root, borderwidth=0, highlightthickness=0, bg="black")
        self._label.pack()
        self._photo = None
        self._queue: "queue.Queue[KeyEvent]" = queue.Queue()
        self._closed = False
        self._root.bind("<Key>", self._on_key)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_key(self, event) -> None:
        ctrl = bool(event.state & 0x4)
        alt = bool(event.state & 0x8) or bool(event.state & 0x10)
        name = _TK_SPECIAL.get(event.keysym)
        if name:
            self._queue.put(KeyEvent(name, None, ctrl, alt))
        elif event.char and event.char.isprintable():
            self._queue.put(KeyEvent.of_char(event.char, ctrl, alt))
        elif ctrl and len(event.keysym) == 1:
            self._queue.put(KeyEvent.of_char(event.keysym.lower(), True, alt))

    def _on_close(self) -> None:
        self._closed = True
        self._queue.put(KeyEvent("quit"))

    def show(self, image: Image.Image) -> None:
        if self._closed:
            return
        w, h = self.size
        big = image.resize((w * self._scale, h * self._scale), Image.NEAREST)
        buf = io.BytesIO()
        big.save(buf, format="PNG")
        self._photo = self._tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self._label.configure(image=self._photo)
        self._root.update()

    def poll(self, timeout: float) -> List[KeyEvent]:
        deadline = time.monotonic() + timeout
        events: List[KeyEvent] = []
        while True:
            if not self._closed:
                self._root.update()
            while not self._queue.empty():
                events.append(self._queue.get_nowait())
            if events or time.monotonic() >= deadline:
                return events
            time.sleep(0.01)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._root.destroy()


# --- Headless (tests, screenshots) -----------------------------------------------

class HeadlessDisplay:
    """Keeps the last frame in memory and replays scripted key events."""

    def __init__(self, keys: Iterable[KeyEvent] = ()):
        self.size = (WIDTH, HEIGHT)
        self.frame: Optional[Image.Image] = None
        self.frames_shown = 0
        self._keys: List[KeyEvent] = list(keys)

    def feed(self, keys: Sequence[KeyEvent]) -> None:
        self._keys.extend(keys)

    def show(self, image: Image.Image) -> None:
        self.frame = image.copy()
        self.frames_shown += 1

    def poll(self, timeout: float) -> List[KeyEvent]:
        if self._keys:
            events, self._keys = self._keys, []
            return events
        time.sleep(min(timeout, 0.01))
        return []

    def close(self) -> None:
        pass
