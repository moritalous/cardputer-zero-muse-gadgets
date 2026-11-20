"""Key events shared by every input backend, and the Linux evdev keymap.

CardputerZero's keyboard is a TCA8418 matrix exposed as a normal evdev
keyboard, so standard Linux keycodes (``<linux/input-event-codes.h>``) are
used. Codes we don't know are reported with ``name == "unknown"`` so that
``--debug-keys`` can show them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class KeyEvent:
    """One key press (or auto-repeat).

    ``name`` is ``"char"`` for printable input (then ``char`` holds it) or a
    special key name: enter, backspace, delete, esc, tab, up, down, left,
    right, pageup, pagedown, home, end, unknown.
    """

    name: str
    char: Optional[str] = None
    ctrl: bool = False
    alt: bool = False
    code: int = 0

    @staticmethod
    def of_char(ch: str, ctrl: bool = False, alt: bool = False) -> "KeyEvent":
        return KeyEvent("char", ch, ctrl, alt)


# evdev code -> (normal, shifted)
CHAR_KEYS = {
    2: ("1", "!"), 3: ("2", "@"), 4: ("3", "#"), 5: ("4", "$"), 6: ("5", "%"),
    7: ("6", "^"), 8: ("7", "&"), 9: ("8", "*"), 10: ("9", "("), 11: ("0", ")"),
    12: ("-", "_"), 13: ("=", "+"),
    16: ("q", "Q"), 17: ("w", "W"), 18: ("e", "E"), 19: ("r", "R"), 20: ("t", "T"),
    21: ("y", "Y"), 22: ("u", "U"), 23: ("i", "I"), 24: ("o", "O"), 25: ("p", "P"),
    26: ("[", "{"), 27: ("]", "}"),
    30: ("a", "A"), 31: ("s", "S"), 32: ("d", "D"), 33: ("f", "F"), 34: ("g", "G"),
    35: ("h", "H"), 36: ("j", "J"), 37: ("k", "K"), 38: ("l", "L"),
    39: (";", ":"), 40: ("'", '"'), 41: ("`", "~"), 43: ("\\", "|"),
    44: ("z", "Z"), 45: ("x", "X"), 46: ("c", "C"), 47: ("v", "V"), 48: ("b", "B"),
    49: ("n", "N"), 50: ("m", "M"), 51: (",", "<"), 52: (".", ">"), 53: ("/", "?"),
    57: (" ", " "),
    # CardputerZero sym layer (reported by the TCA8418 keymap with these codes)
    93: ("?", "?"),      # sym+M
}

SPECIAL_KEYS = {
    1: "esc", 14: "backspace", 15: "tab", 28: "enter", 96: "enter",
    102: "home", 103: "up", 104: "pageup", 105: "left", 106: "right",
    107: "end", 108: "down", 109: "pagedown", 111: "delete",
    138: "help",          # fn+H on CardputerZero
}

SHIFT_CODES = {42, 54}
CTRL_CODES = {29, 97}
ALT_CODES = {56, 100}
CAPSLOCK = 58
# CardputerZero layer keys: fn (389) and sym (383); the kernel keymap
# already applies them (fn+F arrives as KEY_UP), so they are just ignored.
FN_CODES = {389, 464}
SYM_CODES = {383}
# Pure modifiers that never produce an event of their own.
MODIFIER_CODES = SHIFT_CODES | CTRL_CODES | ALT_CODES | FN_CODES | SYM_CODES | {CAPSLOCK, 125, 126}


class KeyTranslator:
    """Turns raw evdev (code, value) pairs into :class:`KeyEvent`.

    ``value`` is 1 for press, 2 for auto-repeat and 0 for release.
    """

    def __init__(self) -> None:
        self.shift = False
        self.ctrl = False
        self.alt = False
        self.capslock = False

    def feed(self, code: int, value: int) -> Optional[KeyEvent]:
        pressed = value != 0
        if code in SHIFT_CODES:
            self.shift = pressed
            return None
        if code in CTRL_CODES:
            self.ctrl = pressed
            return None
        if code in ALT_CODES:
            self.alt = pressed
            return None
        if code == CAPSLOCK:
            if value == 1:
                self.capslock = not self.capslock
            return None
        if not pressed or code in MODIFIER_CODES:
            return None
        if code in SPECIAL_KEYS:
            return KeyEvent(SPECIAL_KEYS[code], None, self.ctrl, self.alt, code)
        if code in CHAR_KEYS:
            normal, shifted = CHAR_KEYS[code]
            use_shift = self.shift
            if normal.isalpha() and self.capslock:
                use_shift = not use_shift
            ch = shifted if use_shift else normal
            return KeyEvent("char", ch, self.ctrl, self.alt, code)
        return KeyEvent("unknown", None, self.ctrl, self.alt, code)
