import pytest

from czmuse.romaji import convert, flush


def type_all(text):
    """Simulate typing one key at a time, as the app does."""
    out, pending = "", ""
    for ch in text:
        kana, pending = convert(pending + ch)
        out += kana
    return out + flush(pending)


@pytest.mark.parametrize("romaji,kana", [
    ("konnichiha", "こんにちは"),
    ("arigatou", "ありがとう"),
    ("kyou", "きょう"),
    ("shinbun", "しんぶん"),
    ("kitte", "きって"),
    ("matcha", "まっちゃ"),
    ("tenki", "てんき"),
    ("hon'ya", "ほんや"),
    ("ra-men", "らーめん"),
    ("sou.", "そう。"),
    ("densha", "でんしゃ"),
    ("fairu", "ふぁいる"),
    ("123desu", "123です"),
])
def test_typing(romaji, kana):
    assert type_all(romaji) == kana


def test_pending_prefixes():
    assert convert("k") == ("", "k")
    assert convert("ky") == ("", "ky")
    assert convert("n") == ("", "n")
    assert convert("na") == ("な", "")
    assert convert("nk") == ("ん", "k")


def test_flush_trailing_n():
    assert flush("n") == "ん"
    assert flush("k") == "k"
    assert flush("") == ""


def test_uppercase_passes_through():
    assert type_all("AIは") == "AIは"


def test_double_n_variants():
    assert type_all("konnnichiha") == "こんにちは"
    assert type_all("annka") == "あんか"
    assert type_all("hon") == "ほん"
    assert type_all("honn") == "ほん"
