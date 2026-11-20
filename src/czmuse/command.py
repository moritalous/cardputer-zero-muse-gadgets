"""``czmuse-command <name>``: the program behind this gadget's Muse commands.

The musegadget service runs it for the drop-in definitions in
``/etc/musegadget/commands.d/cardputer.*.json``, passing the parameters as
one JSON object on stdin. It prints one JSON object as the result, or exits
non-zero with the reason on stderr.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

from . import notify

MAX_STDIN = 64 * 1024


def _read_params() -> dict:
    data = sys.stdin.read(MAX_STDIN) if not sys.stdin.isatty() else ""
    if not data.strip():
        return {}
    params = json.loads(data)
    if not isinstance(params, dict):
        raise ValueError("parameters must be a JSON object")
    return params


def battery() -> dict:
    """Battery state from /sys/class/power_supply, when the kernel exposes it."""
    for supply in sorted(glob.glob("/sys/class/power_supply/*")):
        def read(name):
            try:
                return Path(supply, name).read_text().strip()
            except OSError:
                return None
        if read("type") != "Battery":
            continue
        info = {"name": os.path.basename(supply)}
        capacity = read("capacity")
        if capacity is not None and capacity.isdigit():
            info["percent"] = int(capacity)
        status = read("status")
        if status:
            info["status"] = status
        voltage = read("voltage_now")
        if voltage and voltage.lstrip("-").isdigit():
            info["voltage_v"] = round(int(voltage) / 1_000_000, 3)
        return info
    return {"available": False}


def screen_show(params: dict) -> dict:
    text = params.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    try:
        reply = notify.send({"op": "screen.show", "text": text})
    except OSError:
        raise RuntimeError("the Muse Gadget app is not open on the CardputerZero screen")
    if not reply.get("ok"):
        raise RuntimeError(str(reply.get("error") or "the app refused the message"))
    return {"shown": True}


def status_read(_params: dict) -> dict:
    try:
        app_open = bool(notify.send({"op": "ping"}, timeout=2).get("ok"))
    except (OSError, ValueError):
        app_open = False
    return {"device": "M5Stack CardputerZero", "app_open": app_open, "battery": battery()}


COMMANDS = {
    "screen.show": screen_show,
    "status.read": status_read,
}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(f"usage: czmuse-command {{{','.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    try:
        result = COMMANDS[argv[0]](_read_params())
    except Exception as exc:
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
