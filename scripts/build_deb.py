#!/usr/bin/env python3
"""Build the APPLaunch .deb for CardputerZero without dpkg-deb.

    uv run scripts/build_deb.py            # -> dist/cz-muse-gadget_<ver>_arm64.deb

The package is pure Python (it runs on the device's system python3), so
nothing is cross-compiled. Layout follows AppBuilder's APPLaunch convention:

    /usr/share/APPLaunch/applications/<pkg>.desktop
    /usr/share/APPLaunch/bin/<pkg>, czmuse-command
    /usr/share/APPLaunch/apps/<pkg>/czmuse/*.py
    /usr/share/APPLaunch/share/images/<pkg>.png
    /etc/musegadget/commands.d/cardputer.*.json   (Muse custom commands)
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "usr/share/APPLaunch"


class Tree:
    """An in-memory file tree that becomes a tar.gz with root ownership."""

    def __init__(self, mtime: int):
        self.files: dict[str, tuple[bytes, int]] = {}
        self.mtime = mtime

    def add(self, path: str, data: bytes, mode: int = 0o644) -> None:
        self.files[path.lstrip("/")] = (data, mode)

    def dirs(self):
        out = set()
        for path in self.files:
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                out.add("/".join(parts[:i]))
        return sorted(out)

    def targz(self) -> bytes:
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
            def info(name, size, mode, kind):
                ti = tarfile.TarInfo("./" + name if name else ".")
                ti.size, ti.mode, ti.type, ti.mtime = size, mode, kind, self.mtime
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = "root"
                return ti
            tar.addfile(info("", 0, 0o755, tarfile.DIRTYPE))
            for d in self.dirs():
                tar.addfile(info(d, 0, 0o755, tarfile.DIRTYPE))
            for path in sorted(self.files):
                data, mode = self.files[path]
                tar.addfile(info(path, len(data), mode, tarfile.REGTYPE), io.BytesIO(data))
        return gzip.compress(raw.getvalue(), mtime=self.mtime)


def ar_archive(members: list[tuple[str, bytes]], mtime: int) -> bytes:
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = (f"{name:<16}{mtime:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}").encode() + b"`\n"
        out += header + data
        if len(data) % 2:
            out += b"\n"
    return bytes(out)


def build(output_dir: Path) -> Path:
    manifest = json.loads((ROOT / "app-builder.json").read_text())
    deb = json.loads((ROOT / "packaging" / "deb.json").read_text())
    pkg, version = manifest["package_name"], manifest["version"]
    app_name, bin_name = manifest.get("app_name", pkg), manifest["bin_name"]
    mtime = int(time.time())
    app_dir = f"/usr/share/APPLaunch/apps/{pkg}"

    data = Tree(mtime)
    for src in sorted((ROOT / "src" / "czmuse").glob("*.py")):
        data.add(f"{app_dir}/czmuse/{src.name}", src.read_bytes())
    data.add(f"/{PREFIX}/bin/{bin_name}", (
        "#!/bin/sh\n"
        "# Launched by APPLaunch. Logs go to /tmp/czmuse.log for troubleshooting.\n"
        f"export PYTHONPATH={app_dir}\n"
        'exec python3 -m czmuse "$@" 2>>/tmp/czmuse.log\n').encode(), 0o755)
    data.add(f"/{PREFIX}/bin/czmuse-command", (
        "#!/bin/sh\n"
        "# Run by the musegadget service for /etc/musegadget/commands.d/cardputer.*.json\n"
        f"export PYTHONPATH={app_dir}\n"
        'exec python3 -m czmuse.command "$@"\n').encode(), 0o755)
    data.add(f"/{PREFIX}/applications/{pkg}.desktop", (
        "[Desktop Entry]\n"
        f"Name={app_name}\n"
        f"Exec=/{PREFIX}/bin/{bin_name}\n"
        "Terminal=false\n"
        "Sysplause=true\n"
        f"Icon=share/images/{pkg}.png\n"
        "Type=Application\n").encode())
    data.add(f"/{PREFIX}/share/images/{pkg}.png", (ROOT / "packaging" / "icon.png").read_bytes())
    conffiles = []
    for cmd in sorted((ROOT / "commands.d").glob("*.json")):
        json.loads(cmd.read_text())  # fail early on a broken definition
        path = f"/etc/musegadget/commands.d/{cmd.name}"
        data.add(path, cmd.read_bytes())
        conffiles.append(path)

    installed_kb = sum(len(d) for d, _ in data.files.values()) // 1024 + 1
    md5sums = "".join(f"{hashlib.md5(d).hexdigest()}  {p}\n" for p, (d, _) in sorted(data.files.items()))
    description = manifest.get("description") or app_name
    control = Tree(mtime)
    control.add("control", (
        f"Package: {pkg}\n"
        f"Version: {version}\n"
        "Architecture: arm64\n"
        f"Maintainer: {deb['maintainer']}\n"
        f"Installed-Size: {installed_kb}\n"
        f"Depends: {deb['depends']}\n"
        f"Section: {deb.get('section', 'APPLaunch')}\n"
        "Priority: optional\n"
        f"Homepage: {deb['homepage']}\n"
        f"Description: {description}\n").encode())
    control.add("md5sums", md5sums.encode())
    control.add("conffiles", "".join(p + "\n" for p in conffiles).encode())
    for hook in ("preinst", "postinst", "prerm", "postrm"):
        script = ROOT / "packaging" / hook
        if script.exists():
            control.add(hook, script.read_bytes(), 0o755)

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{pkg}_{version}_arm64.deb"
    out.write_bytes(ar_archive([
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control.targz()),
        ("data.tar.gz", data.targz()),
    ], mtime))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    out = build(args.output_dir)
    print(f"built {out} ({out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
