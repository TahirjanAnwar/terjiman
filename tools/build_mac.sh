#!/bin/bash
# Builds Terjiman.app and the .dmg on a Mac, with Python 3.11 from python.org (it runs on macOS 10.9+).
#   bash tools/build_mac.sh arm64    -> dist-arm64/Terjiman-mac-AppleSilicon.dmg   (macOS 11 and newer)
#   bash tools/build_mac.sh x86_64   -> dist-x86_64/Terjiman-mac-Intel.dmg         (macOS 10.15 and newer)
# On an Apple Silicon Mac the Intel build runs under Rosetta. GitHub runs this for every release.
set -euo pipefail
cd "$(dirname "$0")/.."
ARCH="${1:-$(uname -m)}"
PYTHON="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11}"
case "$ARCH" in
  arm64)  NAME=AppleSilicon; MINOS=11.0 ;;
  x86_64) NAME=Intel;        MINOS=10.15 ;;
  *) echo "Give arm64 or x86_64"; exit 1 ;;
esac
run() { arch -"$ARCH" "$@"; }

VENV="venv-$ARCH"
rm -rf "$VENV" "build-$ARCH" "dist-$ARCH"
run "$PYTHON" -m venv "$VENV"
run "$VENV/bin/python" -m pip install --quiet --upgrade pip
run "$VENV/bin/python" -m pip install --quiet -r requirements-mac.txt

echo "== checks"
run "$VENV/bin/python" tools/check_engine.py --offline
run "$VENV/bin/python" tools/check_mac.py

echo "== build"
export MACOSX_DEPLOYMENT_TARGET="$MINOS"
run "$VENV/bin/python" -m PyInstaller terjiman.spec --noconfirm --distpath "dist-$ARCH" --workpath "build-$ARCH"
codesign --force --deep --sign - "dist-$ARCH/Terjiman.app"      # ad-hoc: Apple Silicon only runs signed code
run "$VENV/bin/python" tools/mac_min_version.py "dist-$ARCH/Terjiman.app" "$ARCH" "$MINOS"

echo "== the built app draws its windows (demo answers, no network)"
if ! TERJIMAN_HOME="$PWD/build-$ARCH/home" run "dist-$ARCH/Terjiman.app/Contents/MacOS/Terjiman" \
     --screenshot "$PWD/dist-$ARCH/screenshots"; then
  echo "SCREENSHOTS FAILED"; cat "build-$ARCH/home/terjiman.log" || true; exit 1
fi
ls "dist-$ARCH/screenshots"

echo "== the .dmg: the app and a link to Applications, to drag it there"
STAGE="build-$ARCH/dmg"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "dist-$ARCH/Terjiman.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Terjiman" -srcfolder "$STAGE" -ov -format UDZO "dist-$ARCH/Terjiman-mac-$NAME.dmg"
echo "Built dist-$ARCH/Terjiman-mac-$NAME.dmg"
