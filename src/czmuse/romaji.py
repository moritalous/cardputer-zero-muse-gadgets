"""A small romaji -> hiragana converter for typing Japanese without an IME.

CardputerZero has no Japanese input method, but Muse reads hiragana just
fine, so typing ``konnichiha`` gives ``こんにちは``. Conversion is greedy and
incremental: :func:`convert` returns the kana it could settle and the romaji
tail that may still become something (``"k"``, ``"ky"``, ``"n"``...).
"""
from __future__ import annotations

from typing import Tuple

_BASE = {
    "a": "あ", "i": "い", "u": "う", "e": "え", "o": "お",
    "ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
    "sa": "さ", "si": "し", "shi": "し", "su": "す", "se": "せ", "so": "そ",
    "ta": "た", "ti": "ち", "chi": "ち", "tu": "つ", "tsu": "つ", "te": "て", "to": "と",
    "na": "な", "ni": "に", "nu": "ぬ", "ne": "ね", "no": "の",
    "ha": "は", "hi": "ひ", "hu": "ふ", "fu": "ふ", "he": "へ", "ho": "ほ",
    "ma": "ま", "mi": "み", "mu": "む", "me": "め", "mo": "も",
    "ya": "や", "yu": "ゆ", "yo": "よ",
    "ra": "ら", "ri": "り", "ru": "る", "re": "れ", "ro": "ろ",
    "wa": "わ", "wo": "を", "wi": "うぃ", "we": "うぇ",
    "nn": "ん", "n'": "ん", "xn": "ん",
    "ga": "が", "gi": "ぎ", "gu": "ぐ", "ge": "げ", "go": "ご",
    "za": "ざ", "zi": "じ", "ji": "じ", "zu": "ず", "ze": "ぜ", "zo": "ぞ",
    "da": "だ", "di": "ぢ", "du": "づ", "de": "で", "do": "ど",
    "ba": "ば", "bi": "び", "bu": "ぶ", "be": "べ", "bo": "ぼ",
    "pa": "ぱ", "pi": "ぴ", "pu": "ぷ", "pe": "ぺ", "po": "ぽ",
    "va": "ゔぁ", "vi": "ゔぃ", "vu": "ゔ", "ve": "ゔぇ", "vo": "ゔぉ",
    "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ",
    "ja": "じゃ", "ju": "じゅ", "je": "じぇ", "jo": "じょ",
    "sha": "しゃ", "shu": "しゅ", "she": "しぇ", "sho": "しょ",
    "cha": "ちゃ", "chu": "ちゅ", "che": "ちぇ", "cho": "ちょ",
    "tha": "てゃ", "thi": "てぃ", "thu": "てゅ", "the": "てぇ", "tho": "てょ",
    "dhi": "でぃ", "dhu": "でゅ", "twu": "とぅ", "dwu": "どぅ",
    "xa": "ぁ", "xi": "ぃ", "xu": "ぅ", "xe": "ぇ", "xo": "ぉ",
    "la": "ぁ", "li": "ぃ", "lu": "ぅ", "le": "ぇ", "lo": "ぉ",
    "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ", "lya": "ゃ", "lyu": "ゅ", "lyo": "ょ",
    "xtu": "っ", "xtsu": "っ", "ltu": "っ", "ltsu": "っ", "xwa": "ゎ",
    "-": "ー", ",": "、", ".": "。", "[": "「", "]": "」", "~": "〜",
    "?": "？", "!": "！",
}

# Contracted sounds: kya, gyo, ...
for _c, _row in {
    "k": "き", "g": "ぎ", "s": "し", "z": "じ", "t": "ち", "d": "ぢ", "c": "ち",
    "n": "に", "h": "ひ", "b": "び", "p": "ぴ", "m": "み", "r": "り", "j": "じ",
}.items():
    for _v, _small in (("a", "ゃ"), ("u", "ゅ"), ("o", "ょ"), ("e", "ぇ"), ("i", "ぃ")):
        _BASE.setdefault(_c + "y" + _v, _row + _small)

TABLE = _BASE
_PREFIXES = {key[:i] for key in TABLE for i in range(1, len(key))}
_MAX_KEY = max(len(k) for k in TABLE)
_VOWELS = set("aiueo")
_CONSONANTS = set("bcdfghjklmpqrstvwxyz")


def convert(text: str) -> Tuple[str, str]:
    """Convert as much of ``text`` as can be settled.

    Returns ``(kana, pending)``: ``pending`` is a romaji tail that might
    still turn into kana with more keystrokes. Characters that can never be
    romaji (digits, most symbols, upper-case letters) pass through as-is.
    """
    out = []
    i = 0
    src = text
    while i < len(src):
        rest = src[i:]
        lowered = rest.lower() if rest[:1].islower() else rest
        if lowered.startswith("nn"):
            # Like common IMEs: "konnichiha" -> こんにちは (one n is reused
            # when a vowel follows), "konnnichiha" works too.
            if len(lowered) == 2:
                return "".join(out), rest
            out.append("ん")
            i += 1 if (lowered[2] in _VOWELS or lowered[2] == "y") else 2
            continue
        matched = False
        for size in range(min(_MAX_KEY, len(rest)), 0, -1):
            piece = lowered[:size]
            if piece in TABLE:
                out.append(TABLE[piece])
                i += size
                matched = True
                break
        if matched:
            continue
        ch = lowered[0]
        nxt = lowered[1:2]
        if ch == "n" and nxt and nxt not in _VOWELS and nxt not in ("y", "n", "'"):
            out.append("ん")
            i += 1
            continue
        if ch in _CONSONANTS and nxt == ch and ch != "n":
            out.append("っ")
            i += 1
            continue
        if ch == "t" and nxt == "c":  # matcha -> まっちゃ
            out.append("っ")
            i += 1
            continue
        if lowered in _PREFIXES or lowered == "n":
            return "".join(out), rest
        out.append(rest[0])
        i += 1
    return "".join(out), ""


def flush(pending: str) -> str:
    """Settle a pending tail when the user commits (Enter, mode switch)."""
    if not pending:
        return ""
    kana, rest = convert(pending)
    if rest.lower() in ("n", "nn"):
        return kana + "ん"
    return kana + rest
