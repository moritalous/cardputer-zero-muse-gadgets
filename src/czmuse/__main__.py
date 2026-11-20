"""Entry point: ``python -m czmuse`` (on the device, launched by APPLaunch)."""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from . import __version__
from .muse import DEFAULT_SOCKET, DEFAULT_WAIT_S, MockMuse, SocketMuse
from .notify import DEFAULT_NOTIFY_SOCKET, NotifyServer


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="czmuse", description="Muse Gadget for CardputerZero")
    p.add_argument("--backend", choices=("auto", "fb", "tk"), default="auto",
                   help="fb: /dev/fb0 + evdev (device), tk: desktop window (default: auto)")
    p.add_argument("--mock", action="store_true", help="fake Muse replies (no service needed)")
    p.add_argument("--socket", type=Path, default=DEFAULT_SOCKET,
                   help="musegadget service socket")
    p.add_argument("--session-id", help="Muse side chat to use (letters, digits, dashes); "
                                        "default: the main chat")
    p.add_argument("--wait", type=int, default=DEFAULT_WAIT_S,
                   help="seconds to wait for each answer (1-600)")
    p.add_argument("--kana", action="store_true", help="start in romaji-kana mode")
    p.add_argument("--notify-socket", type=Path, default=DEFAULT_NOTIFY_SOCKET,
                   help="socket for custom commands (set empty to disable)")
    p.add_argument("--no-notify", action="store_true", help="do not accept custom commands")
    p.add_argument("--scale", type=int, default=3, help="tk window scale")
    p.add_argument("--debug-keys", action="store_true", help="print raw evdev key codes")
    p.add_argument("--version", action="version", version=__version__)
    return p


def make_display(args):
    backend = args.backend
    if backend == "auto":
        backend = "fb" if sys.platform.startswith("linux") and Path("/dev/fb0").exists() else "tk"
    if backend == "fb":
        from .display import FramebufferDisplay
        return FramebufferDisplay(debug_keys=args.debug_keys)
    from .display import TkDisplay
    return TkDisplay(scale=args.scale)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.wait <= 600:
        print("--wait must be 1 to 600", file=sys.stderr)
        return 2
    muse = MockMuse() if args.mock else SocketMuse(args.socket, args.session_id, args.wait)

    from .app import ChatApp

    display = make_display(args)
    app = ChatApp(display, muse, kana_mode=args.kana)

    def stop(_signum, _frame):
        app.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    server = None
    if not args.no_notify:
        server = NotifyServer(args.notify_socket, app.handle_command)
        try:
            server.start()
            print(f"czmuse: accepting custom commands on {args.notify_socket}", file=sys.stderr)
        except OSError as exc:
            print(f"czmuse: custom commands disabled ({exc})", file=sys.stderr)
            server = None
    try:
        app.run()
    finally:
        if server is not None:
            server.close()
        display.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
