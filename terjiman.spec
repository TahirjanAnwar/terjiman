# PyInstaller recipe for the built Terjiman: one Terjiman.exe on Windows, Terjiman.app on macOS.
# Nobody needs Python to run these. GitHub builds them for each release (.github/workflows/build.yml).
#
#   Windows:  .venv\Scripts\python.exe -m PyInstaller terjiman.spec --noconfirm     -> dist\Terjiman.exe
#   macOS:    tools/build_mac.sh                                                    -> dist/Terjiman-mac-*.dmg
import platform
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH)
VERSION = re.search(r'^VERSION = "([^"]+)"', (ROOT / "terjiman.py").read_text(encoding="utf-8"), re.M).group(1)
MAC = sys.platform == "darwin"

datas = [(str(ROOT / "locales" / "*.json"), "locales"),
         (str(ROOT / "assets" / "terjiman.png"), "assets"),
         (str(ROOT / "assets" / "terjiman.ico"), "assets")]
# keyring finds its backends at run time, so name the one for this system.
hidden = ["keyring.backends.macOS"] if MAC else ["keyring.backends.Windows"]

other_system = ["winkeys"] if MAC else ["mackeys", "AppKit", "Quartz", "ApplicationServices", "HIServices"]
a = Analysis([str(ROOT / "terjiman.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "unittest", "pydoc_data", *other_system], noarchive=False)
pyz = PYZ(a.pure)

if MAC:
    intel = platform.machine() == "x86_64"
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Terjiman", console=False, upx=False,
              argv_emulation=False)
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Terjiman")
    app = BUNDLE(coll, name="Terjiman.app", icon=str(ROOT / "assets" / "terjiman.png"),
                 bundle_identifier="com.tproduction.terjiman", version=VERSION,
                 info_plist={
                     "CFBundleName": "Terjiman",
                     "CFBundleDisplayName": "Terjiman",
                     "CFBundleShortVersionString": VERSION,
                     "CFBundleVersion": VERSION,
                     "LSUIElement": True,           # lives in the menu bar, no Dock icon
                     "LSMinimumSystemVersion": "10.15" if intel else "11.0",
                     "NSHighResolutionCapable": True,
                     "NSHumanReadableCopyright": "© 2026 TahirjanAnwar, MIT License",
                 })
else:
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    numbers = tuple(int(n) for n in VERSION.split(".")) + (0,)
    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "T-production"),
            StringStruct("FileDescription", "Terjiman: write in Uyghur, send in English"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "Terjiman"),
            StringStruct("LegalCopyright", "© 2026 TahirjanAnwar, MIT License"),
            StringStruct("OriginalFilename", "Terjiman.exe"),
            StringStruct("ProductName", "Terjiman"),
            StringStruct("ProductVersion", VERSION)])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])])])
    version_file = Path(workpath) / "version_info.txt"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(str(info), encoding="utf-8")
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="Terjiman", console=False, upx=False,
              icon=str(ROOT / "assets" / "terjiman.ico"), version=str(version_file))
