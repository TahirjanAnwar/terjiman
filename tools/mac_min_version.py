"""Checks that every program file inside Terjiman.app runs on an old enough macOS.

Each Mac program file says the oldest macOS it needs (LC_BUILD_VERSION "minos", or LC_VERSION_MIN_MACOSX
"version"). One file that needs a newer macOS is enough to stop the whole app from opening there, so this reads
them all and fails if any needs more than the target.

    python3 tools/mac_min_version.py dist/Terjiman.app x86_64 10.15
"""
import re
import subprocess
import sys
from pathlib import Path


def version(text: str) -> tuple:
    return tuple(int(n) for n in text.split("."))


def main() -> int:
    app, arch, target = Path(sys.argv[1]), sys.argv[2], version(sys.argv[3])
    worst, offenders, checked = (0,), [], 0
    for path in sorted(p for p in app.rglob("*") if p.is_file() and not p.is_symlink()):
        with path.open("rb") as f:
            magic = f.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe"):   # Mach-O or universal
            continue
        out = subprocess.run(["otool", "-arch", arch, "-l", str(path)], capture_output=True, text=True).stdout
        found = re.findall(r"(?:minos|^\s*version)\s+(\d+\.\d+(?:\.\d+)?)", out, re.M)
        if not found:
            continue
        checked += 1
        needed = max(version(v) for v in found)
        worst = max(worst, needed)
        if needed > target:
            offenders.append(f"{'.'.join(map(str, needed))}  {path.relative_to(app)}")
    print(f"{checked} program files checked for {arch}; the newest macOS any of them needs: "
          f"{'.'.join(map(str, worst))} (target {sys.argv[3]})")
    for line in offenders[:40]:
        print("  needs newer macOS:", line)
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
