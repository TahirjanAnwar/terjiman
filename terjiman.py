"""Terjiman - write in Uyghur, send in English.

Press the shortcut (Ctrl+Shift+Space) in any program and a small box opens. Write in your own language: Claude
offers three English versions (natural, polite, short), each with its meaning back in your language so you can
check it. Click one to paste it into the program you came from, or press Enter to paste the first one and send it.
Write English instead and Terjiman corrects it. Select an English message and press Ctrl+C twice to read it in
your language.

It runs on Windows and macOS: as the built Terjiman.exe / Terjiman.app from the GitHub release, or from a git copy
with  .venv\\Scripts\\pythonw.exe terjiman.py [--tray]  (Windows; setup.cmd builds the small Terjiman.exe launcher).
Test helpers: --screenshot DIR (pictures of the window in every language), TERJIMAN_DEMO=1 (canned answers,
no network), TERJIMAN_HOME=DIR (settings and log in another folder), TERJIMAN_TEST=1 (test commands).
"""
from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
from pathlib import Path

APP_NAME = "Terjiman"
APP_ID = "TProduction.Terjiman"
VERSION = "1.2.0"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))          # the built Terjiman.exe / Terjiman.app
# Where the program is (a git copy: the code folder; a built app: the folder of the .exe or the .app's MacOS folder),
# and where its texts and pictures are (inside the build when frozen).
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RESOURCES = Path(getattr(sys, "_MEIPASS", APP_DIR))
RELEASES_PAGE = "https://github.com/TahirjanAnwar/terjiman/releases/latest"
RELEASES_API = "https://api.github.com/repos/TahirjanAnwar/terjiman/releases/latest"


def default_home() -> Path:
    """Settings and log: next to the code in a git copy (as before), otherwise in the user's own app-data folder."""
    if not FROZEN:
        return APP_DIR
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME


HOME = Path(os.environ["TERJIMAN_HOME"]).resolve() if os.environ.get("TERJIMAN_HOME") else default_home()
SETTINGS_PATH = HOME / "settings.json"
LOG_PATH = HOME / "terjiman.log"
ICON_PATH = RESOURCES / "assets" / ("terjiman.ico" if IS_WINDOWS else "terjiman.png")
KEYRING_SERVICE = os.environ.get("TERJIMAN_KEYRING_SERVICE") or APP_NAME
KEYRING_USER = "claude-api-key"
DEMO = os.environ.get("TERJIMAN_DEMO") == "1"
TEST = os.environ.get("TERJIMAN_TEST") == "1"
KEY_PAGE = "https://platform.claude.com/settings/keys"
SERVER_NAME = "Terjiman-" + hashlib.sha1(f"{getpass.getuser()}|{HOME}".lower().encode()).hexdigest()[:12]

from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QTimer, QUrl, Qt, Signal, qInstallMessageHandler
from PySide6.QtGui import (QColor, QCursor, QDesktopServices, QFont, QFontDatabase, QGuiApplication, QIcon,
                           QKeySequence, QPalette, QTextOption)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout,
                               QKeySequenceEdit, QLabel, QLayout, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QScrollArea, QSystemTrayIcon, QToolButton, QVBoxLayout,
                               QWidget)

import engine

if IS_MAC:
    import mackeys as keys     # Carbon shortcut, Quartz keystrokes, AppKit apps
else:
    import winkeys as keys     # RegisterHotKey, SendInput, Win32 windows

LANGUAGE_ORDER = ["en", "ug", "tr", "ar", "nl"]
RTL_LANGUAGES = {"ug", "ar"}
UYGHUR_FONTS = ["UKIJ Tuz Tom", "ALKATIP Basma Tom", "Microsoft Uighur"]
UYGHUR_LETTERS = re.compile("[\u06d5\u06c6\u06c7\u06c8\u06cb\u06d0\u06ad\u06be]")   # letters only Uyghur uses
DEFAULTS = {"language": "ug", "quality": "best", "target": "en", "mine": "ug", "shortcut": "Ctrl+Shift+Space",
            "copy_twice": True, "box_pos": None}
BOX_WIDTH = 560
TYPING_PAUSE_MS = 900        # translate when the writer stops typing for this long
GOOGLE_PAUSE_MS = 500        # Google answers in well under a second and costs nothing, so it can ask sooner
UPDATE_CHECK_HOURS = 6
COPY_TWICE_WINDOW = (0.06, 0.8)   # seconds between the two Ctrl+C presses
UI_FAMILY = "Segoe UI" if IS_WINDOWS else ""
SIZE_SCALE = 1.3 if IS_MAC else 1.0   # macOS counts 72 points per inch, Windows 96: the same text looks smaller there


# ---------------------------------------------------------------- logging

def log(text: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")
    except OSError:
        pass
    if sys.stderr:
        print(text, file=sys.stderr)


def start_log() -> None:
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 512_000:
            LOG_PATH.unlink()
    except OSError:
        pass
    log(f"{APP_NAME} {VERSION} starting{' (demo)' if DEMO else ''}")
    qInstallMessageHandler(lambda mode, context, message: log(f"Qt: {message}"))
    sys.excepthook = lambda kind, value, tb: log("".join(traceback.format_exception(kind, value, tb)))


# ---------------------------------------------------------------- settings, key, start-up

class Settings:
    """settings.json next to the app. Writes are bundled, so moving the window doesn't hammer the disk."""

    def __init__(self, path: Path):
        self.path = path
        self.data = dict(DEFAULTS)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.save_now)

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value) -> None:
        if self.data.get(key) != value:
            self.data[key] = value
            self._timer.start()

    def save_now(self) -> None:
        self._timer.stop()
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as error:
            log(f"settings not saved: {error}")


def load_key() -> str:
    """The Claude API key lives in Windows Credential Manager, never in a file next to the app."""
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception as error:  # noqa: BLE001
        log(f"reading the API key failed: {error}")
        return ""


def store_key(key: str) -> bool:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        return True
    except Exception as error:  # noqa: BLE001
        log(f"saving the API key failed: {error}")
        return False


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.tproduction.terjiman.plist"
CAN_AUTOSTART = not os.environ.get("TERJIMAN_HOME")      # test copies never touch the start-up list


def launch_command(*extra: str) -> list[str]:
    if FROZEN:
        return [sys.executable, *extra]           # Terjiman.exe, or Terjiman.app/Contents/MacOS/Terjiman
    exe = APP_DIR / "Terjiman.exe"
    if IS_WINDOWS and exe.exists():
        return [str(exe), *extra]
    python = Path(sys.executable)
    if IS_WINDOWS:
        python = python.with_name("pythonw.exe")
    return [str(python), str(APP_DIR / "terjiman.py"), *extra]


def autostart_enabled() -> bool:
    if IS_MAC:
        return LAUNCH_AGENT.exists()
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on: bool) -> None:
    if IS_MAC:          # a LaunchAgent: macOS starts Terjiman (in the menu bar) when the user logs in
        if on:
            import plistlib
            LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
            LAUNCH_AGENT.write_bytes(plistlib.dumps({"Label": "com.tproduction.terjiman",
                                                     "ProgramArguments": launch_command("--tray"),
                                                     "RunAtLoad": True}))
        elif LAUNCH_AGENT.exists():
            LAUNCH_AGENT.unlink()
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(launch_command("--tray")))
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------- languages and fonts

def load_locales() -> dict[str, dict]:
    locales = {}
    for file in sorted((RESOURCES / "locales").glob("*.json")):
        try:
            locales[file.stem] = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log(f"locale {file.name} not loaded: {error}")
    locales.setdefault("en", {"_language_name": "English"})
    return locales


def is_rtl(text: str) -> bool:
    """True when the first letter with a direction is right-to-left (Uyghur, Arabic)."""
    for ch in text or "":
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return True
        if kind == "L":
            return False
    return False


class Fonts:
    def __init__(self):
        families = set(QFontDatabase.families())
        self.uyghur = next((f for f in UYGHUR_FONTS if f in families), "")
        # Microsoft Uighur draws its letters small; Voice Clone and T-Player enlarge it the same way.
        self.scale = 1.45 if self.uyghur == "Microsoft Uighur" else 1.0

    def text(self, text: str, size: float) -> QFont:
        size *= SIZE_SCALE
        if self.uyghur and UYGHUR_LETTERS.search(text or ""):
            font = QFont(self.uyghur)
            font.setPointSizeF(size * self.scale)
        else:
            # Windows: Segoe UI. macOS: the system font; for Uyghur without a Uyghur font, macOS picks one itself.
            font = QFont(UI_FAMILY) if UI_FAMILY else QFont()
            font.setPointSizeF(size)
        return font

    def ui(self, lang: str, size: float = 10.0) -> QFont:
        return self.text("ە" if lang == "ug" else "", size)


def show_text(label: QLabel, text: str, fonts: Fonts, size: float) -> None:
    """Puts text in a label with the right font and direction for its language, and hides the label if empty."""
    label.setText(text)
    label.setFont(fonts.text(text, size))
    rtl = is_rtl(text)
    label.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
    side = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
    label.setAlignment(side | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)
    label.setVisible(bool(text))


def plain_label(name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)    # people's messages are never read as HTML
    label.setWordWrap(wrap)
    if name:
        label.setObjectName(name)
    return label


def restyle(widget: QWidget, **properties) -> None:
    for name, value in properties.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def parse_shortcut(text: str) -> tuple[int, int] | None:
    sequence = QKeySequence.fromString(text or "", QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1:
        return None
    combination = sequence[0]
    key = combination.key()
    key = key.value if hasattr(key, "value") else int(key)
    mods = combination.keyboardModifiers()
    km = Qt.KeyboardModifier
    # On macOS Qt calls Cmd "Control" and Control "Meta"; keys.shortcut_to_native knows that.
    return keys.shortcut_to_native(key, bool(mods & km.ControlModifier), bool(mods & km.ShiftModifier),
                                   bool(mods & km.AltModifier), bool(mods & km.MetaModifier))


def shortcut_label(text: str) -> str:
    return QKeySequence.fromString(text or "", QKeySequence.SequenceFormat.PortableText).toString(
        QKeySequence.SequenceFormat.NativeText)


# ---------------------------------------------------------------- updates from GitHub (the same way as T-Player)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / r"Microsoft.NET\Framework64\v4.0.30319\csc.exe"
LAUNCHER_SOURCES = {"launcher/TerjimanLauncher.cs", "assets/terjiman.ico"}


def run_quiet(args, timeout: int = 120, env=None) -> tuple[int, str, str]:
    """Runs a program without flashing a console window. Returns (exit code, output, errors)."""
    try:
        done = subprocess.run([str(a) for a in args], cwd=str(APP_DIR), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, env=env, creationflags=NO_WINDOW)
        return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except OSError as error:
        return 127, "", str(error)


def git(*args, timeout: int = 60) -> tuple[int, str, str]:
    exe = shutil.which("git")
    if not exe:
        return 127, "", "git not found"
    return run_quiet([exe, *args], timeout=timeout,
                     env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never"))


def short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= 300 else text[:297] + "..."


GIT_COPY = not FROZEN and (APP_DIR / ".git").exists()      # a git clone updates with git pull
WINDOWS_ASSET = "Terjiman.exe"                               # what a built app downloads from the release


def version_text() -> str:
    """"1.0.0 (e210a79 · 2026-11-27)" in a git copy, otherwise just the version."""
    code, out, _ = git("log", "-1", "--format=%h · %cs") if GIT_COPY else (1, "", "")
    return f"{VERSION} ({out})" if code == 0 and out else VERSION


def version_tuple(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:3])


def latest_release() -> dict:
    """The newest release on GitHub (tag_name, html_url, body, assets). Raises OSError or ValueError."""
    import urllib.request
    request = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                            "User-Agent": f"Terjiman/{VERSION}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def install_exe_update(url: str) -> str:
    """Downloads the new Terjiman.exe next to this one and swaps them: a running exe can be renamed, not
    overwritten. Returns an error text, or "" when it worked."""
    import urllib.request
    current = Path(sys.executable)
    new = current.with_name(current.stem + ".new" + current.suffix)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": f"Terjiman/{VERSION}"})
        with urllib.request.urlopen(request, timeout=300) as response, new.open("wb") as out:
            shutil.copyfileobj(response, out)
        if new.stat().st_size < 5_000_000:
            raise OSError("the download is incomplete")
        old = current.with_name(f"{current.stem}.old-{int(time.time())}{current.suffix}")
        current.rename(old)
        try:
            new.rename(current)
        except OSError:
            old.rename(current)
            raise
        return ""
    except OSError as error:
        try:
            new.unlink()
        except OSError:
            pass
        return short(str(error))


def rebuild_launcher() -> str:
    """Builds Terjiman.exe again. Returns an error text, or "" when it worked. The running exe is renamed,
    not overwritten, because Windows keeps it locked."""
    staging = APP_DIR / "build-new"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.mkdir()
        code, out, err = run_quiet([CSC, "/nologo", "/optimize+", "/target:winexe", r"/win32icon:assets\terjiman.ico",
                                    "/reference:System.Windows.Forms.dll", f"/out:{staging / 'Terjiman.exe'}",
                                    r"launcher\TerjimanLauncher.cs"])
        if code != 0:
            return short(out or err)
        target = APP_DIR / "Terjiman.exe"
        if target.exists():
            target.rename(target.with_name(f"Terjiman.old-{int(time.time())}.exe"))
        (staging / "Terjiman.exe").rename(target)
        return ""
    except OSError as error:
        return short(str(error))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def remove_old_builds() -> None:
    """Deletes what an update renamed away. A built exe may sit in Downloads, so only its own old copies."""
    if FROZEN:
        exe = Path(sys.executable)
        folder, pattern = exe.parent, f"{exe.stem}.old-*{exe.suffix}"
    else:
        folder, pattern = APP_DIR, "*.old-*"
    for old in folder.glob(pattern):
        try:
            old.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- the box

STYLE = """
QWidget#box, QDialog { background: #1b1c22; }
QLabel { color: #f4f4f7; }
QLabel#muted, QLabel#hint, QLabel#num, QLabel#status { color: #8a8d99; }
QLabel#status[error="true"] { color: #ff8a80; }
QLabel#tag { color: #66c2ff; }
QLabel#meaning { color: #8fd19e; }
QLabel#note { color: #d6d8df; background: #24252d; border-radius: 8px; padding: 6px 9px; }
QPlainTextEdit#input { background: #141519; color: #f4f4f7; border: 1px solid #30313a; border-radius: 9px;
                       padding: 6px 8px; selection-background-color: #0099ff; }
QPlainTextEdit#input:focus { border-color: #0099ff; }
QFrame#card { background: #22232a; border: 1px solid #30313a; border-radius: 10px; }
QFrame#card[ready="true"]:hover { border-color: #0099ff; background: #262832; }
QFrame#banner { background: #0d3a5c; border-radius: 9px; }
QFrame#readPanel { background: #24252d; border-radius: 9px; }
QScrollArea { background: transparent; border: none; }
QToolButton { color: #c9cbd3; background: transparent; border: none; padding: 3px 8px; border-radius: 6px; }
QToolButton:hover { background: #30313a; color: #ffffff; }
QToolButton#update[ready="true"] { background: #0099ff; color: #ffffff; padding: 3px 10px; }
QToolButton#update[ready="true"]:hover { background: #1aa3ff; }
QPushButton { background: #24252d; color: #f4f4f7; border: 1px solid #3a3b45; border-radius: 6px; padding: 5px 14px; }
QPushButton:hover { border-color: #0099ff; }
QPushButton:disabled { color: #6d707b; }
QPushButton#primary { background: #0099ff; border-color: #0099ff; color: #ffffff; }
"""


def apply_palette(app: QApplication) -> None:
    """Dark colours for menus, dialogs and message boxes (the same as T-Player)."""
    role, group = QPalette.ColorRole, QPalette.ColorGroup
    colours = {role.Window: "#1b1c22", role.WindowText: "#f4f4f7", role.Base: "#141519",
               role.AlternateBase: "#22232a", role.ToolTipBase: "#24252d", role.ToolTipText: "#f4f4f7",
               role.Text: "#f4f4f7", role.Button: "#24252d", role.ButtonText: "#f4f4f7", role.BrightText: "#ffffff",
               role.Highlight: "#0099ff", role.HighlightedText: "#ffffff", role.Light: "#3a3b45",
               role.Midlight: "#30313a", role.Mid: "#2a2b33", role.Dark: "#101114", role.Shadow: "#000000",
               role.PlaceholderText: "#8a8d99", role.Link: "#66c2ff"}
    palette = QPalette()
    for r, colour in colours.items():
        palette.setColor(r, QColor(colour))
    for r in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(group.Disabled, r, QColor("#6d707b"))
    app.setPalette(palette)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p("{" + text + "}"), ctypes.byref(self))


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("value", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


def set_taskbar_identity(widget: QWidget) -> None:
    """Shows a window on the taskbar as Terjiman, with Terjiman's icon (not as Python with Python's icon), and makes
    pinning it pin Terjiman.exe. The same as T-Player does."""
    icon = sys.executable if FROZEN else ICON_PATH        # the built exe carries the icon itself (stays put)
    values = ((5, APP_ID), (2, subprocess.list2cmdline(launch_command())), (4, APP_NAME), (3, f"{icon},0"))
    shell32 = ctypes.windll.shell32         # 5 ID, 2 RelaunchCommand, 4 RelaunchDisplayName, 3 RelaunchIcon
    shell32.SHGetPropertyStoreForWindow.argtypes = [ctypes.c_void_p, ctypes.POINTER(_GUID),
                                                    ctypes.POINTER(ctypes.c_void_p)]
    store = ctypes.c_void_p()
    if shell32.SHGetPropertyStoreForWindow(int(widget.winId()), _GUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"),
                                           ctypes.byref(store)) != 0 or not store:
        return
    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
                                   ctypes.POINTER(_PROPVARIANT))(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    fmtid = _GUID("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")   # System.AppUserModel.*
    try:
        for pid, text in values:
            variant = _PROPVARIANT()
            variant.vt = 31  # VT_LPWSTR
            variant.value = text
            set_value(store, ctypes.byref(_PROPERTYKEY(fmtid, pid)), ctypes.byref(variant))
        commit(store)
    finally:
        release(store)


def windows_touches(widget: QWidget) -> None:
    """Dark title bar and taskbar identity for a window that shows on the taskbar (cosmetic, never fatal)."""
    if not IS_WINDOWS:
        return
    for step in (set_dark_title_bar, set_taskbar_identity):
        try:
            step(widget)
        except Exception as error:  # noqa: BLE001
            log(f"{step.__name__} failed: {error}")


def set_dark_title_bar(widget: QWidget) -> None:
    on = ctypes.c_int(1)
    for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Windows 10 builds)
        try:
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(widget.winId())), attribute,
                                                          ctypes.byref(on), ctypes.sizeof(on)) == 0:
                return
        except OSError:
            return


class InputBox(QPlainTextEdit):
    """Enter sends, Shift+Enter makes a new line, Ctrl+1/2/3 pastes that version, Esc closes the box."""
    sendRequested = Signal()
    escapePressed = Signal()
    pickRequested = Signal(int)

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key.Key_Return.value, Qt.Key.Key_Enter.value) and not mods & Qt.KeyboardModifier.ShiftModifier:
            self.sendRequested.emit()
            return
        if key == Qt.Key.Key_Escape.value:
            self.escapePressed.emit()
            return
        if mods & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_1.value <= key <= Qt.Key.Key_3.value:
            self.pickRequested.emit(key - Qt.Key.Key_1.value)
            return
        super().keyPressEvent(event)


class Card(QFrame):
    """One suggested version: its style, the text to send, and its meaning in the writer's language."""
    clicked = Signal(int)

    def __init__(self, index: int, fonts: Fonts):
        super().__init__()
        self.index = index
        self.fonts = fonts
        self.ready = False
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(3)
        top = QHBoxLayout()
        self.tag = plain_label("tag", wrap=False)
        self.num = plain_label("num", wrap=False)
        self.num.setText(str(index + 1))
        top.addWidget(self.tag)
        top.addStretch(1)
        top.addWidget(self.num)
        layout.addLayout(top)
        self.english = plain_label("english")
        self.meaning = plain_label("meaning")
        layout.addWidget(self.english)
        layout.addWidget(self.meaning)
        for label in (self.tag, self.num, self.english, self.meaning):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_content(self, tag: str, text: str, meaning: str, ready: bool, small: QFont) -> None:
        self.tag.setText(tag)
        self.tag.setFont(small)
        self.num.setFont(small)
        show_text(self.english, text, self.fonts, 12.0)
        show_text(self.meaning, ("✓  " + meaning) if meaning else "", self.fonts, 9.5)
        if ready != self.ready:
            self.ready = ready
            restyle(self, ready=ready)
        self.setCursor(Qt.CursorShape.PointingHandCursor if ready else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self.ready and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(event)


class Box(QWidget):
    """The small always-on-top window that the shortcut opens."""

    def __init__(self, owner: "Terjiman"):
        # No resize border: fit() sizes the box to its content (minimum/maximum sizes would fight it).
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.MSWindowsFixedSizeDialogHint)
        self.owner = owner
        self.fonts = owner.fonts
        self.setObjectName("box")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if IS_MAC:     # macOS hides tool windows when you click into another app; Terjiman's box stays, as on Windows
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.resize(BOX_WIDTH, 200)
        self.setWindowIcon(owner.icon)
        self._input_rtl = None
        self._input_uyghur = None
        self._dark = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(9)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)   # fit() sets the height itself

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(12, 8, 8, 8)
        self.banner_text = plain_label()
        self.banner_button = QPushButton()
        self.banner_button.setObjectName("primary")
        row.addWidget(self.banner_text, 1)
        row.addWidget(self.banner_button)
        root.addWidget(self.banner)
        self.banner.hide()

        self.read_panel = QFrame()
        self.read_panel.setObjectName("readPanel")
        panel = QVBoxLayout(self.read_panel)
        panel.setContentsMargins(12, 6, 6, 10)
        panel.setSpacing(2)
        head = QHBoxLayout()
        self.read_title = plain_label("muted", wrap=False)
        self.read_close = QToolButton()
        self.read_close.setText("✕")
        head.addWidget(self.read_title)
        head.addStretch(1)
        head.addWidget(self.read_close)
        self.read_body = plain_label()
        self.read_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel.addLayout(head)
        panel.addWidget(self.read_body)
        root.addWidget(self.read_panel)
        self.read_panel.hide()

        self.input = InputBox()
        self.input.setObjectName("input")
        self.input.setTabChangesFocus(True)
        self.input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input.textChanged.connect(self._input_changed)
        root.addWidget(self.input)

        self.status = plain_label("status")
        self.status.hide()
        root.addWidget(self.status)

        self.results = QWidget()
        results = QVBoxLayout(self.results)
        results.setContentsMargins(0, 0, 0, 0)
        results.setSpacing(8)
        self.mode_label = plain_label("muted", wrap=False)
        results.addWidget(self.mode_label)
        self.cards = [Card(i, self.fonts) for i in range(3)]
        for card in self.cards:
            results.addWidget(card)
            card.hide()
        self.note = plain_label("note")
        results.addWidget(self.note)
        self.mode_label.hide()
        self.note.hide()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.results)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll)

        foot = QHBoxLayout()
        foot.setSpacing(2)
        self.hint = plain_label("hint", wrap=False)
        self.read_button = QToolButton()
        self.update_button = QToolButton()        # "⟳"; blue "⟳ Update" / "⟳ Restart" when there is one
        self.update_button.setObjectName("update")
        self.update_button.setText("⟳")
        self.settings_button = QToolButton()
        self.settings_button.setText("⚙")
        foot.addWidget(self.hint, 1)
        foot.addWidget(self.read_button)
        foot.addWidget(self.update_button)
        foot.addWidget(self.settings_button)
        root.addLayout(foot)
        self._update_state = None

    # ---- texts
    def retranslate(self) -> None:
        o = self.owner
        self.setWindowTitle(o.t("app_title"))
        self.input.setPlaceholderText(o.t("placeholder", mine=o.language_name(o.settings.get("mine")),
                                          target=o.language_name(o.settings.get("target"))))
        small = o.small_font()
        self.hint.setText(o.t("hint_keys"))
        self.hint.setFont(small)
        self.read_button.setText(o.t("read_copied"))
        self.read_button.setFont(small)
        self.settings_button.setToolTip(o.t("settings"))
        self.read_title.setText(o.t("they_wrote"))
        self.read_title.setFont(small)
        self.mode_label.setFont(small)
        self.banner_text.setText(o.t("free_mode"))
        self.banner_button.setText(o.t("settings"))
        self.set_update_state(self._update_state)
        self._input_rtl = None
        self._input_changed(emit=False)

    def text(self) -> str:
        return self.input.toPlainText()

    def set_text(self, text: str) -> None:
        self.input.setPlainText(text)
        cursor = self.input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input.setTextCursor(cursor)

    def _input_changed(self, emit: bool = True) -> None:
        text = self.text()
        rtl = is_rtl(text) if text.strip() else QGuiApplication.layoutDirection() == Qt.LayoutDirection.RightToLeft
        uyghur = bool(UYGHUR_LETTERS.search(text)) or (not text.strip() and self.owner.lang == "ug")
        if rtl != self._input_rtl or uyghur != self._input_uyghur:
            self._input_rtl, self._input_uyghur = rtl, uyghur
            option = self.input.document().defaultTextOption()
            option.setTextDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            side = Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft
            option.setAlignment(side | Qt.AlignmentFlag.AlignAbsolute)
            self.input.document().setDefaultTextOption(option)
            self.input.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            self.input.setFont(self.fonts.text("ە" if uyghur else "", 12.0))
        self.fit()
        if emit:
            self.owner.text_changed(text)

    # ---- what the owner shows
    def show_status(self, text: str, error: bool = False) -> None:
        restyle(self.status, error=error)
        show_text(self.status, text, self.fonts, 9.5)
        self.fit()

    def show_banner(self, on: bool) -> None:
        self.banner.setVisible(on)
        self.fit()

    def set_update_state(self, state: str | None) -> None:
        """None: a quiet "⟳" that checks GitHub. "available" / "restart": a blue button that says so."""
        self._update_state = state
        o = self.owner
        labels = {"available": o.t("update_ready"), "restart": o.t("upd_restart")}
        self.update_button.setText("⟳  " + labels[state] if state in labels else "⟳")
        self.update_button.setFont(o.small_font() if state in labels else QFont())
        self.update_button.setToolTip(o.t("upd_restart_needed") if state == "restart" else o.t("check_updates"))
        restyle(self.update_button, ready=state in labels)

    def show_read(self, text: str, error: bool = False) -> None:
        self.read_panel.show()
        show_text(self.read_body, text, self.fonts, 11.0)
        self.read_body.setStyleSheet("color: #ff8a80;" if error else "")
        self.fit()

    def hide_read(self) -> None:
        self.read_panel.hide()
        self.read_body.clear()
        self.fit()

    def show_result(self, data: dict | None, final: bool) -> None:
        o = self.owner
        data = data or {}
        versions = data.get("versions") or []
        mode = data.get("mode") or ""
        target = o.language_name(o.settings.get("target"))
        mode_text = o.t(f"mode_{mode}", target=target) if mode and versions else ""
        self.mode_label.setText(mode_text)
        self.mode_label.setVisible(bool(mode_text))
        small = o.small_font()
        for i, card in enumerate(self.cards):
            if i < len(versions):
                version = versions[i]
                style = version.get("style") or ""
                tag = o.t(f"style_{style}") if style else ""
                card.set_content(tag, version["text"], version.get("meaning", ""), final, small)
                card.show()
            else:
                card.hide()
        # Google sends English back as it was typed: say why there is no correction.
        note = data.get("note") or (o.t("google_no_grammar") if mode == "same" else "")
        show_text(self.note, note if final else "", self.fonts, 9.5)
        self.fit()

    def clear_result(self) -> None:
        self.show_result(None, False)

    # ---- size and place
    def fit(self) -> None:
        """Grows or shrinks the box to its content, keeping it on the screen."""
        lines = max(2, min(6, int(self.input.document().size().height())))
        frame = self.input.height() - self.input.viewport().height() if self.input.isVisible() else 16
        doc_margin = self.input.document().documentMargin() * 2
        self.input.setFixedHeight(int(lines * self.input.fontMetrics().lineSpacing() + doc_margin + max(frame, 12)))

        width = BOX_WIDTH - 28
        content = self.results.layout()
        needed = content.totalHeightForWidth(width) if content.hasHeightForWidth() else content.totalSizeHint().height()
        any_result = any(not card.isHidden() for card in self.cards) or not self.note.isHidden()
        self.scroll.setVisible(any_result)
        self.scroll.setFixedHeight(max(0, needed))
        area = self._screen_area()
        limit = int(area.height() * 0.88)
        layout = self.layout()
        total = layout.totalHeightForWidth(BOX_WIDTH) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        if total > limit and any_result:
            self.scroll.setFixedHeight(max(120, needed - (total - limit)))
            total = layout.totalHeightForWidth(BOX_WIDTH) if layout.hasHeightForWidth() else layout.totalSizeHint().height()
        self.resize(BOX_WIDTH, min(total, limit))
        if self.isVisible():
            self._keep_on_screen()

    def _screen_area(self):
        screen = self.screen() if self.isVisible() else QGuiApplication.screenAt(QCursor.pos())
        return (screen or QGuiApplication.primaryScreen()).availableGeometry()

    def _keep_on_screen(self) -> None:
        area = self._screen_area()
        frame = self.frameGeometry()
        x, y = frame.x(), frame.y()
        if frame.bottom() > area.bottom():
            y = area.bottom() - frame.height()
        if y < area.top():
            y = area.top()
        if frame.right() > area.right():
            x = area.right() - frame.width()
        if x < area.left():
            x = area.left()
        if (x, y) != (frame.x(), frame.y()):
            self.move(self.pos() + QPoint(x - frame.x(), y - frame.y()))

    def place(self) -> None:
        saved = self.owner.settings.get("box_pos") or {}
        try:
            point = QPoint(int(saved["x"]), int(saved["y"]))
            if not any(s.availableGeometry().contains(point) for s in QGuiApplication.screens()):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            point = QPoint(area.center().x() - self.width() // 2, area.bottom() - self.height() - 120)
        self.move(point)

    def hasHeightForWidth(self):
        # fit() sets the height. Otherwise Qt grows the window to the layout's minimum height, which it measures
        # at a narrow width where wrapped text is taller (about 20 px too much).
        return False

    # ---- window events
    def showEvent(self, event):
        super().showEvent(event)
        if not self._dark:
            self._dark = True
            if IS_WINDOWS:
                set_dark_title_bar(self)
        QTimer.singleShot(0, self.fit)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.owner.box_hidden()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible() and not self.owner.screenshotting:
            self.owner.settings.set("box_pos", {"x": self.x(), "y": self.y()})

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self.isVisible():
            # The writer clicked into another program: paste into that one from now on.
            QTimer.singleShot(60, self.owner.note_foreground)

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key.Key_Escape.value:
            self.hide()
            return
        if mods & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_1.value <= key <= Qt.Key.Key_3.value:
            self.owner.pick(key - Qt.Key.Key_1.value)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()      # the close button only hides the box; Quit is in the tray menu
        self.hide()


# ---------------------------------------------------------------- settings window

class SettingsDialog(QDialog):
    def __init__(self, owner: "Terjiman"):
        super().__init__(None, Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowCloseButtonHint)
        self.owner = owner
        t = owner.t
        self.setWindowTitle(t("settings_title"))
        self.setWindowIcon(owner.icon)
        self.setMinimumWidth(600)

        form = QFormLayout()
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("key_placeholder_saved") if owner.key else t("key_placeholder_new"))
        self.key_check = QPushButton(t("key_check"))
        self.key_get = QPushButton(t("key_get") + " ↗")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.key_check)
        key_row.addWidget(self.key_get)
        self.key_note = plain_label("muted")
        self.key_note.setText(t("key_where"))
        key_box = QVBoxLayout()
        key_box.addLayout(key_row)
        key_box.addWidget(self.key_note)
        form.addRow(t("key_label"), key_box)

        self.best = QRadioButton(t("quality_best"))
        self.fast = QRadioButton(t("quality_fast"))
        self.google = QRadioButton(t("quality_free"))
        chosen = owner.settings.get("quality")
        {"fast": self.fast, "google": self.google}.get(chosen, self.best).setChecked(True)
        quality = QVBoxLayout()
        quality.addWidget(self.best)
        quality.addWidget(self.fast)
        quality.addWidget(self.google)
        form.addRow(t("quality_label"), quality)

        self.target = self._language_box(owner.settings.get("target"))
        self.mine = self._language_box(owner.settings.get("mine"))
        form.addRow(t("target_label"), self.target)
        form.addRow(t("mine_label"), self.mine)

        self.shortcut = QKeySequenceEdit(QKeySequence.fromString(owner.settings.get("shortcut"),
                                                                 QKeySequence.SequenceFormat.PortableText))
        if hasattr(self.shortcut, "setMaximumSequenceLength"):     # Qt 6.5+; the Mac build uses Qt 6.4
            self.shortcut.setMaximumSequenceLength(1)
        if hasattr(self.shortcut, "setClearButtonEnabled"):
            self.shortcut.setClearButtonEnabled(True)
        form.addRow(t("shortcut_label"), self.shortcut)

        self.copy_twice = QCheckBox(t("copy_twice"))
        self.copy_twice.setChecked(bool(owner.settings.get("copy_twice")))
        self.autostart = QCheckBox(t("autostart"))
        self.autostart.setChecked(CAN_AUTOSTART and autostart_enabled())
        self.autostart.setEnabled(CAN_AUTOSTART)
        form.addRow("", self.copy_twice)
        form.addRow("", self.autostart)

        self.ui_language = QComboBox()
        for code in LANGUAGE_ORDER:
            if code in owner.locales:
                self.ui_language.addItem(owner.locales[code].get("_language_name", code), code)
        self.ui_language.setCurrentIndex(max(0, self.ui_language.findData(owner.lang)))
        form.addRow(t("ui_language"), self.ui_language)

        self.version = plain_label("muted", wrap=False)
        self.version.setText(t("upd_version", version=owner.version))
        self.updates = QPushButton(t("check_updates"))
        version_row = QHBoxLayout()
        version_row.addWidget(self.version, 1)
        version_row.addWidget(self.updates)
        form.addRow("", version_row)

        self.message = plain_label()
        self.message.hide()
        save = QPushButton(t("save"))
        save.setObjectName("primary")
        save.setDefault(True)
        cancel = QPushButton(t("cancel"))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)
        root.addLayout(form)
        root.addWidget(self.message)
        root.addLayout(buttons)

        self.key_check.clicked.connect(self._check_key)
        self.key_get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(KEY_PAGE)))
        self.updates.clicked.connect(lambda: owner.check_updates(quiet=False))
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)

    def _language_box(self, current: str) -> QComboBox:
        box = QComboBox()
        for code in LANGUAGE_ORDER:
            box.addItem(self.owner.language_name(code), code)
        box.setCurrentIndex(max(0, box.findData(current)))
        return box

    def showEvent(self, event):
        super().showEvent(event)
        windows_touches(self)

    def say(self, text: str, error: bool = False) -> None:
        self.message.setStyleSheet("color: #ff8a80;" if error else "color: #8fd19e;")
        show_text(self.message, text, self.owner.fonts, 9.5)

    def _check_key(self) -> None:
        key = self.key.text().strip() or self.owner.key
        if not key:
            self.say(self.owner.t("key_missing"), error=True)
            return
        self.say(self.owner.t("key_checking"))
        self.key_check.setEnabled(False)

        def work():
            problem = None
            if not DEMO:
                try:
                    engine.check_key(key)
                except engine.EngineError as error:
                    problem = error
            self.owner.later(lambda: self._key_checked(problem))

        threading.Thread(target=work, daemon=True).start()

    def _key_checked(self, problem) -> None:
        try:
            self.key_check.setEnabled(True)
            if problem is None:
                self.say(self.owner.t("key_ok"))
            else:
                self.say(self.owner.error_text(problem), error=True)
        except RuntimeError:
            pass   # the window was closed meanwhile

    def _save(self) -> None:
        o = self.owner
        text = self.shortcut.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if not parse_shortcut(text):
            self.say(o.t("shortcut_invalid"), error=True)
            return
        if not o.try_shortcut(text):
            self.say(o.t("shortcut_taken"), error=True)
            return
        key = self.key.text().strip()
        if key and not o.set_key(key):
            self.say(o.t("err_generic", detail="Windows Credential Manager"), error=True)
            return
        o.settings.set("quality", "google" if self.google.isChecked() else "fast" if self.fast.isChecked() else "best")
        o.settings.set("target", self.target.currentData())
        o.settings.set("mine", self.mine.currentData())
        o.settings.set("copy_twice", self.copy_twice.isChecked())
        if CAN_AUTOSTART and self.autostart.isChecked() != autostart_enabled():
            try:
                set_autostart(self.autostart.isChecked())
            except OSError as error:
                log(f"start-up entry not changed: {error}")
        o.settings.save_now()
        self.accept()
        o.settings_saved(self.ui_language.currentData())


# ---------------------------------------------------------------- the app

class Terjiman(QObject):
    hotkeyPressed = Signal(object)     # the window that was in front (an HWND)
    writePartial = Signal(int, object)
    writeDone = Signal(int, object)
    writeFailed = Signal(int, object)
    readText = Signal(int, str)
    readDone = Signal(int, str)
    readFailed = Signal(int, object)
    _relay = Signal(object)

    def __init__(self, app: QApplication, tray_only: bool = False, screenshots: Path | None = None):
        super().__init__()
        self.app = app
        self.settings = Settings(SETTINGS_PATH)
        self.locales = load_locales()
        self.lang = self.settings.get("language") if self.settings.get("language") in self.locales else "en"
        self.strings: dict = {}
        self.fonts = Fonts()
        self.icon = QIcon(str(ICON_PATH))
        self.version = version_text()
        self.key = "" if DEMO else load_key()
        self._engine = None
        self._engine_key = None
        self._google = None
        self._engine_lock = threading.Lock()
        self._target = 0                 # the window to paste into
        self._received = ""              # the message being replied to (after Ctrl+C twice)
        self._write_job = 0
        self._write_cancel: threading.Event | None = None
        self._running_key = None
        self._cache: dict = {}
        self._shown_key = None
        self._pending_send = False
        self._read_job = 0
        self._read_cancel: threading.Event | None = None
        self._last_copy = (0.0, "")
        self._ignore_clipboard_until = 0.0
        self._settings_dialog: SettingsDialog | None = None
        self._update_busy = False
        self._update_waiting = None
        self._update_state: str | None = None      # None, "available" (on GitHub) or "restart" (already on disk)
        self._started_head = ""
        self.screenshotting = False

        self._relay.connect(lambda job: job(), Qt.ConnectionType.QueuedConnection)
        self.hotkeyPressed.connect(self.on_hotkey)
        self.writePartial.connect(self._write_partial)
        self.writeDone.connect(self._write_done)
        self.writeFailed.connect(self._write_failed)
        self.readText.connect(self._read_text)
        self.readDone.connect(self._read_done)
        self.readFailed.connect(self._read_failed)

        self.box = Box(self)
        self.box.input.sendRequested.connect(self.send_first)
        self.box.input.escapePressed.connect(self.box.hide)
        self.box.input.pickRequested.connect(self.pick)
        for card in self.box.cards:
            card.clicked.connect(self.pick)
        self.box.banner_button.clicked.connect(self.open_settings)
        self.box.settings_button.clicked.connect(self.open_settings)
        self.box.update_button.clicked.connect(self.update_clicked)
        self.box.read_button.clicked.connect(lambda: self.read_copied(QGuiApplication.clipboard().text(), None))
        self.box.read_close.clicked.connect(self.close_read)

        self._pause = QTimer(self)
        self._pause.setSingleShot(True)
        self._pause.setInterval(TYPING_PAUSE_MS)
        self._pause.timeout.connect(lambda: self.request_write(self.box.text()))

        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.messageClicked.connect(self._tray_message_clicked)
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.apply_language(self.lang)
        self.server = QLocalServer(self)
        self.hotkeys = None
        if screenshots:
            QTimer.singleShot(0, lambda: self.take_screenshots(screenshots))
            return

        if not DEMO:
            threading.Thread(target=engine.warm_up, name="load-anthropic-sdk", daemon=True).start()
        threading.Thread(target=self._remember_version, name="git-version", daemon=True).start()
        QLocalServer.removeServer(SERVER_NAME)
        if not self.server.listen(SERVER_NAME):
            log(f"single-instance server not started: {self.server.errorString()}")
        self.server.newConnection.connect(self._on_connection)
        self.hotkeys = keys.HotkeyListener(lambda: self.hotkeyPressed.emit(keys.foreground()))
        shortcut_ok = self.register_shortcut()
        QGuiApplication.clipboard().dataChanged.connect(self._clipboard_changed)
        self.tray.show()
        remove_old_builds()
        if not tray_only:
            self.open_box(0)
            if not shortcut_ok:
                self.box.show_status(self.t("shortcut_taken"), error=True)
            self.tray.showMessage(APP_NAME, self.t("tray_running", key=shortcut_label(self.settings.get("shortcut"))),
                                  self.icon, 6000)
        if not (DEMO or TEST):
            QTimer.singleShot(5000, lambda: self.check_updates(quiet=True))
            # Terjiman can stay in the tray for weeks, so it looks again now and then.
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(UPDATE_CHECK_HOURS * 3600 * 1000)
            self._update_timer.timeout.connect(lambda: self.check_updates(quiet=True))
            self._update_timer.start()

    # ---- helpers
    def later(self, job) -> None:
        """Runs job() on the window thread. Widgets must never be touched from a background thread."""
        self._relay.emit(job)

    def t(self, name: str, /, **args) -> str:
        """The text called name in the app's language, with {placeholders} filled in (one is even called {key})."""
        text = self.strings.get(name) or self.locales.get("en", {}).get(name) or name
        for placeholder, value in args.items():
            text = text.replace("{" + placeholder + "}", str(value))
        if IS_MAC:
            text = text.replace("Ctrl+", "⌘")        # Mac keyboards copy and paste with Cmd: ⌘C, ⌘V
        return text

    def language_name(self, code: str) -> str:
        return self.t(f"lang_{code}")

    def small_font(self) -> QFont:
        return self.fonts.ui(self.lang, 9.0)

    def quality(self) -> str:
        """best, fast or google. Without a Claude key Terjiman uses the free Google Translate, so it works for
        everyone straight away."""
        chosen = self.settings.get("quality")
        if chosen == "google" or not (DEMO or self.key):
            return "google"
        return chosen if chosen in ("best", "fast") else "best"

    def free_by_default(self) -> bool:
        """True when Google is used only because there is no Claude key (then the box says how to get better)."""
        return self.settings.get("quality") != "google" and not (DEMO or self.key)

    def engine_for(self, key: str, quality: str):
        """The translator to use. Called from the worker threads: the first Claude call may wait for the Anthropic
        SDK to finish loading, and the window must not wait with it."""
        with self._engine_lock:
            if DEMO:
                if self._engine is None:
                    self._engine = engine.DemoEngine()
                return self._engine
            if quality == "google":
                if self._google is None:
                    self._google = engine.GoogleEngine()
                return self._google
            if self._engine is None or self._engine_key != key:
                self._engine = engine.Engine(key)
                self._engine_key = key
            return self._engine

    def set_key(self, key: str) -> bool:
        if DEMO:
            self.key = key
            return True
        if not store_key(key):
            return False
        self.key = key
        self._cache.clear()
        return True

    def error_text(self, error: engine.EngineError) -> str:
        key = f"err_{error.kind}"
        return self.t(key if key in self.locales.get("en", {}) else "err_generic", detail=error.detail or error.kind)

    def apply_language(self, code: str) -> None:
        self.lang = code if code in self.locales else "en"
        self.strings = {**self.locales.get("en", {}), **self.locales.get(self.lang, {})}
        rtl = self.lang in RTL_LANGUAGES
        self.app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
        self.app.setFont(self.fonts.ui(self.lang))
        self.box.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
        self.box.retranslate()
        self._build_menu()
        if self._shown_key in self._cache:
            self.box.show_result(self._cache[self._shown_key], True)

    def _build_menu(self) -> None:
        self.menu.clear()
        self.menu.setLayoutDirection(self.app.layoutDirection())
        key = shortcut_label(self.settings.get("shortcut"))
        self.menu.addAction(f"{self.t('tray_open')}  ({key})", lambda: self.open_box(0))
        self.menu.addAction(self.t("settings"), self.open_settings)
        self.menu.addAction(self.t("check_updates"), lambda: self.check_updates(quiet=False))
        self.menu.addSeparator()
        self.menu.addAction(self.t("tray_quit"), self.quit)

    def _tray_clicked(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.box.isVisible():
                self.box.hide()
            else:
                self.open_box(0)

    def quit(self) -> None:
        self.settings.save_now()
        if self.hotkeys:
            self.hotkeys.stop()
        self.tray.hide()
        self.app.quit()

    # ---- the shortcut
    def register_shortcut(self) -> bool:
        parsed = parse_shortcut(self.settings.get("shortcut")) or parse_shortcut(DEFAULTS["shortcut"])
        ok = bool(self.hotkeys) and self.hotkeys.set(*parsed)
        if not ok:
            log(f"shortcut {self.settings.get('shortcut')} not registered (used by another program?)")
        return ok

    def try_shortcut(self, text: str) -> bool:
        parsed = parse_shortcut(text)
        if not parsed or not self.hotkeys or not self.hotkeys.set(*parsed):
            return False
        self.settings.set("shortcut", text)
        return True

    def on_hotkey(self, window: int) -> None:
        if self.box.isVisible() and self._is_own(window):
            self.box.hide()          # the same shortcut closes the box again
        else:
            self.open_box(window)

    def _is_own(self, window: int) -> bool:
        """window: a window handle on Windows, an app's process id on macOS."""
        return bool(window) and keys.window_pid(window) == os.getpid()

    def _usable_target(self, window: int) -> bool:
        return bool(window) and keys.is_window(window) and not self._is_own(window) \
            and not keys.is_shell_window(window)

    def note_foreground(self) -> None:
        window = keys.foreground()
        if self._usable_target(window):
            self._target = window

    # ---- the box
    def open_box(self, target: int) -> None:
        if target and self._usable_target(target):
            self._target = target
        elif not self.box.isVisible():
            self._target = 0           # opened from the tray: no program to paste into
        first = not self.box.isVisible()
        self.box.show_banner(self.free_by_default())
        if first:
            self.box.place()
        self.box.show()
        self.box.raise_()
        self.box.activateWindow()
        if IS_WINDOWS:
            keys.focus_window(int(self.box.winId()), 0.3)
        else:
            keys.focus_own_app()          # a menu-bar app has to bring itself forward before its window can
        self.box.input.setFocus()
        if first and self.box.text().strip():
            self.text_changed(self.box.text())

    def box_hidden(self) -> None:
        self._pause.stop()
        self._cancel_write()
        self._pending_send = False

    def text_changed(self, text: str) -> None:
        if self.screenshotting:
            return
        self._pending_send = False
        if not text.strip():
            self._pause.stop()
            self._cancel_write()
            self._shown_key = None
            self.box.clear_result()
            self.box.show_status("")
            return
        key = self._cache_key(text)
        if key in self._cache:
            self._pause.stop()
            self._show_final(key)
            return
        self._pause.setInterval(GOOGLE_PAUSE_MS if self.quality() == "google" else TYPING_PAUSE_MS)
        self._pause.start()

    def _cache_key(self, text: str) -> tuple:
        s = self.settings
        return (text.strip(), s.get("mine"), s.get("target"), self.quality(), self._received)

    def _show_final(self, key) -> None:
        self._shown_key = key
        self.box.show_status("")
        self.box.show_result(self._cache[key], True)

    def _cancel_write(self) -> None:
        if self._write_cancel:
            self._write_cancel.set()
        self._write_cancel = None
        self._running_key = None

    def request_write(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        key = self._cache_key(text)
        if key in self._cache:
            self._show_final(key)
            return
        if self._running_key == key:
            return
        self._cancel_write()
        self._write_job += 1
        job = self._write_job
        cancel = threading.Event()
        self._write_cancel, self._running_key = cancel, key
        self.box.show_status(self.t("sending" if self._pending_send else "translating"))
        api_key = self.key
        s = self.settings
        mine, target, quality, received = s.get("mine"), s.get("target"), self.quality(), self._received

        def work():
            try:
                worker = self.engine_for(api_key, quality)
                result = worker.write(text, mine=mine, target=target, quality=quality, received=received,
                                      on_partial=lambda partial: self.writePartial.emit(job, partial),
                                      cancelled=cancel.is_set)
                if result is not None:
                    self.writeDone.emit(job, (key, result))
            except engine.EngineError as error:
                self.writeFailed.emit(job, error)
            except Exception as error:  # noqa: BLE001
                log("translation failed:\n" + traceback.format_exc())
                self.writeFailed.emit(job, engine.EngineError("generic", str(error)))

        threading.Thread(target=work, daemon=True).start()

    def _write_partial(self, job: int, partial) -> None:
        if job == self._write_job and self._running_key:
            self.box.show_result(partial, False)

    def _write_done(self, job: int, payload) -> None:
        key, result = payload
        self._cache[key] = result
        if job != self._write_job:
            return
        self._running_key = None
        self._write_cancel = None
        if key == self._cache_key(self.box.text()):
            self._show_final(key)
            if self._pending_send and result["versions"]:
                self._pending_send = False
                self.deliver(result["versions"][0]["text"], send=True)

    def _write_failed(self, job: int, error) -> None:
        if job != self._write_job:
            return
        self._running_key = None
        self._write_cancel = None
        self._pending_send = False
        log(f"translation error: {error}")
        self.box.show_status(self.error_text(error), error=True)

    def send_first(self) -> None:
        """Enter: paste the first version and press Enter in the other program."""
        text = self.box.text().strip()
        if not text:
            return
        key = self._cache_key(text)
        if key in self._cache:
            self.deliver(self._cache[key]["versions"][0]["text"], send=True)
            return
        self._pending_send = True
        self._pause.stop()
        if self._running_key == key:
            self.box.show_status(self.t("sending"))
        else:
            self.request_write(text)

    def pick(self, index: int) -> None:
        """A click on a version (or Ctrl+1/2/3): paste it without sending."""
        result = self._cache.get(self._cache_key(self.box.text()))
        if result and 0 <= index < len(result["versions"]):
            self.deliver(result["versions"][index]["text"], send=False)

    # ---- pasting into the other program
    def deliver(self, text: str, send: bool) -> None:
        clipboard = QGuiApplication.clipboard()
        saved = self._snapshot_clipboard()
        self._ignore_clipboard_until = time.monotonic() + 3.0
        clipboard.setText(text)
        target = self._target
        if not self._usable_target(target):
            self.box.show_status(self.t("copied_only"))
            return
        self.box.hide()
        QTimer.singleShot(40, lambda: self._paste_into(target, text, send, saved))

    def _paste_into(self, target: int, text: str, send: bool, saved) -> None:
        def failed():
            self.open_box(0)
            self._target = target
            self.box.show_status(self.t("err_paste"), error=True)

        if IS_MAC and not keys.can_type(prompt=True):
            # macOS lets an app type into other apps only after the user allows it (Accessibility).
            self.open_box(0)
            self._target = target
            self.box.show_status(self.t("mac_accessibility"), error=True)
            return
        if not keys.focus_window(target):
            log("paste: the other window didn't come to the front")
            return failed()
        keys.wait_modifiers_up(0.8)
        if keys.foreground() != target:      # never type into a window the writer didn't choose
            return failed()
        keys.paste()
        if send:
            QTimer.singleShot(150, lambda: keys.foreground() == target and keys.enter())
        QTimer.singleShot(1500, lambda: self._restore_clipboard(saved, text))
        self._received = ""
        self._shown_key = None
        self.box.hide_read()
        self.box.set_text("")
        self.box.show_status("")

    def _snapshot_clipboard(self):
        """Keeps what was copied before (text, links, a picture), to put it back after pasting. Only these common
        kinds: asking a program like Excel for all its formats can take seconds."""
        data = QGuiApplication.clipboard().mimeData()
        if data is None:
            return None
        copy = QMimeData()
        try:
            if data.hasText():
                copy.setText(data.text())
            if data.hasHtml():
                copy.setHtml(data.html())
            if data.hasUrls():
                copy.setUrls(data.urls())
            if data.hasImage():
                copy.setImageData(data.imageData())
        except Exception as error:  # noqa: BLE001
            log(f"clipboard not saved: {error}")
        return copy

    def _restore_clipboard(self, saved, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard.text() != text:
            return              # something else was copied meanwhile: leave it
        self._ignore_clipboard_until = time.monotonic() + 1.0
        if saved is not None and saved.formats():
            clipboard.setMimeData(saved)
        else:
            clipboard.clear()

    # ---- reading a copied message (Ctrl+C twice, or the button)
    def _clipboard_changed(self) -> None:
        now = time.monotonic()
        if now < self._ignore_clipboard_until or not self.settings.get("copy_twice"):
            return
        text = QGuiApplication.clipboard().text()
        last_time, last_text = self._last_copy
        self._last_copy = (now, text)
        low, high = COPY_TWICE_WINDOW
        if text.strip() and text == last_text and low < now - last_time < high and keys.copy_modifier_down():
            window = keys.foreground()
            if not self._is_own(window):
                self._last_copy = (0.0, "")
                self.read_copied(text, window)

    def read_copied(self, text: str, window: int | None) -> None:
        if window:
            self.open_box(window)
        elif not self.box.isVisible():
            self.open_box(0)
        text = (text or "").strip()
        if not text:
            self.box.show_read(self.t("nothing_copied"), error=True)
            return
        if self._read_cancel:
            self._read_cancel.set()
        self._read_job += 1
        job = self._read_job
        cancel = threading.Event()
        self._read_cancel = cancel
        self._received = text
        self.box.show_read(self.t("reading"))
        api_key = self.key
        s = self.settings
        mine, target, quality = s.get("mine"), s.get("target"), self.quality()

        def work():
            try:
                worker = self.engine_for(api_key, quality)
                answer = worker.read(text, mine=mine, target=target, quality=quality,
                                     on_text=lambda so_far: self.readText.emit(job, so_far), cancelled=cancel.is_set)
                if answer is not None:
                    self.readDone.emit(job, answer)
            except engine.EngineError as error:
                self.readFailed.emit(job, error)
            except Exception as error:  # noqa: BLE001
                log("reading failed:\n" + traceback.format_exc())
                self.readFailed.emit(job, engine.EngineError("generic", str(error)))

        threading.Thread(target=work, daemon=True).start()
        if self.box.text().strip():
            self.text_changed(self.box.text())     # the reply now has a message to fit

    def _read_text(self, job: int, text: str) -> None:
        if job == self._read_job and text.strip():
            self.box.show_read(text)

    def _read_done(self, job: int, text: str) -> None:
        if job == self._read_job:
            self._read_cancel = None
            self.box.show_read(text)

    def _read_failed(self, job: int, error) -> None:
        if job == self._read_job:
            self._read_cancel = None
            log(f"reading error: {error}")
            self.box.show_read(self.error_text(error), error=True)

    def close_read(self) -> None:
        if self._read_cancel:
            self._read_cancel.set()
        self._read_cancel = None
        self._received = ""
        self.box.hide_read()
        if self.box.text().strip():
            self.text_changed(self.box.text())

    # ---- settings
    def open_settings(self) -> None:
        if self._settings_dialog:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        if self.hotkeys:
            self.hotkeys.set(0, 0)         # free the shortcut, so the shortcut field can record it
        dialog = SettingsDialog(self)
        self._settings_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._settings_dialog = None
            self.register_shortcut()

    def settings_saved(self, language: str) -> None:
        self._cache.clear()
        self._shown_key = None
        self.apply_language(language)
        self.settings.set("language", self.lang)
        self.settings.save_now()
        self.box.show_banner(self.free_by_default())
        if self.box.isVisible() and self.box.text().strip():
            self.request_write(self.box.text())

    # ---- updates: the button in the box, Settings and the tray menu all come here
    def _remember_version(self) -> None:
        """The git commit this copy started with: when the files on disk are newer, a restart finishes updating."""
        code, head, _ = git("rev-parse", "HEAD") if GIT_COPY else (1, "", "")
        self._started_head = head if code == 0 else ""

    def update_clicked(self) -> None:
        if self._update_state == "available":
            self._ask_install()
        elif self._update_state == "restart":
            self._ask_restart()
        else:
            self.check_updates(quiet=False)

    def _set_update_state(self, state: str | None) -> None:
        self._update_state = state
        self.box.set_update_state(state)

    def check_updates(self, quiet: bool = False) -> None:
        if self._update_busy:
            return
        self._update_busy = True
        threading.Thread(target=self._check_updates, args=(quiet,), daemon=True).start()

    def _check_updates(self, quiet: bool) -> None:
        try:
            if FROZEN:
                return self._check_release(quiet)
            if not shutil.which("git"):
                problem = ("upd_no_git", {})
            elif not GIT_COPY:
                problem = ("upd_not_repo", {})
            else:
                code, _, err = git("fetch", "--quiet", "origin", timeout=120)
                count = "0"
                if code == 0:
                    code, count, err = git("rev-list", "--count", "HEAD..@{u}")
                if code == 0:
                    n = int(count or "0")
                    if n == 0:
                        _, head, _ = git("rev-parse", "HEAD")
                        if self._started_head and head and head != self._started_head:
                            self.later(lambda: self._restart_needed(quiet))
                        elif not quiet:
                            self.later(lambda: self._message(self.t("upd_latest")))
                        return
                    _, changes, _ = git("log", "--format=%s", "HEAD..@{u}")
                    lines = changes.splitlines()[:12]
                    self.later(lambda: self._updates_found(n, lines, quiet))
                    return
                problem = ("upd_fetch_failed", {"error": short(err)})
            if not quiet:
                self.later(lambda: self._message(self.t(problem[0], **problem[1]), warning=True))
        finally:
            self._update_busy = False

    def _check_release(self, quiet: bool) -> None:
        """The built Terjiman.exe / Terjiman.app: is there a newer release on GitHub?"""
        try:
            release = latest_release()
        except (OSError, ValueError) as error:
            if not quiet:
                self.later(lambda: self._message(self.t("upd_fetch_failed", error=short(str(error))), warning=True))
            return
        tag = str(release.get("tag_name") or "")
        if version_tuple(tag) > version_tuple(VERSION):
            notes = [line.strip(" -*•\t") for line in str(release.get("body") or "").splitlines() if line.strip()]
            self._release = release
            self.later(lambda: self._updates_found(1, [tag] + notes[:10], quiet))
        elif not quiet:
            self.later(lambda: self._message(self.t("upd_latest")))

    def _updates_found(self, count: int, changes: list[str], quiet: bool) -> None:
        self._update_waiting = (count, changes)
        self._set_update_state("available")
        if quiet:
            self.tray.showMessage(APP_NAME, self.t("upd_notify"), self.icon, 10000)
        else:
            self._ask_install()

    def _restart_needed(self, quiet: bool) -> None:
        """A newer version is already on disk (installed by git pull, or by setup): only a restart is missing."""
        self._set_update_state("restart")
        if not quiet:
            self._ask_restart()

    def _ask_restart(self) -> None:
        box = self._message_box(self.t("upd_restart_needed"))
        restart = box.addButton(self.t("upd_restart"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.t("upd_later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is restart:
            self.restart()

    def _tray_message_clicked(self) -> None:
        if self._update_waiting:
            self._ask_install()

    def _ask_install(self) -> None:
        count, changes = self._update_waiting or (0, [])
        box = self._message_box(self.t("upd_available", count=count) + "\n\n" + "\n".join("•  " + c for c in changes))
        install = box.addButton(self.t("upd_install"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(self.t("upd_later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is install:
            self.tray.showMessage(APP_NAME, self.t("upd_installing"), self.icon, 4000)
            threading.Thread(target=self._install_update, daemon=True).start()

    def _install_update(self) -> None:
        if FROZEN:
            return self._install_release()
        _, old, _ = git("rev-parse", "HEAD")
        code, out, err = git("pull", "--ff-only", timeout=300)
        if code != 0:
            return self.later(lambda: self._message(self.t("upd_pull_failed", error=short(err or out)), warning=True))
        _, new, _ = git("rev-parse", "HEAD")
        changed = set(git("diff", "--name-only", old, new)[1].splitlines()) if old and new else set()
        if "requirements.txt" in changed:
            python = Path(sys.executable).with_name("python.exe")
            code, out, err = run_quiet([python if python.exists() else sys.executable, "-m", "pip", "install",
                                        "-r", "requirements.txt"], timeout=1800)
            if code != 0:
                return self.later(lambda: self._message(self.t("upd_pip_failed", error=short(err or out)),
                                                        warning=True))
        if changed & LAUNCHER_SOURCES:
            error = rebuild_launcher()
            if error:
                return self.later(lambda: self._message(self.t("upd_build_failed", error=error), warning=True))
        log(f"updated {old[:7]} -> {new[:7]} ({len(changed)} files)")
        self.later(self.restart)

    def _install_release(self) -> None:
        """Windows: download the new Terjiman.exe, swap it in and restart. macOS (or when the exe's folder can't be
        written): open the download page, because a running .app can't replace itself."""
        release = getattr(self, "_release", None) or {}
        if IS_WINDOWS:
            asset = next((a for a in release.get("assets") or [] if a.get("name") == WINDOWS_ASSET), None)
            if asset:
                error = install_exe_update(asset.get("browser_download_url", ""))
                if not error:
                    log(f"updated to {release.get('tag_name')}")
                    return self.later(self.restart)
                log(f"update download failed: {error}")
        page = str(release.get("html_url") or RELEASES_PAGE)
        self.later(lambda: (QDesktopServices.openUrl(QUrl(page)), self._message(self.t("upd_download_page"))))

    def restart(self) -> None:
        self.tray.showMessage(APP_NAME, self.t("upd_restarting"), self.icon, 3000)
        self.settings.save_now()
        if self.hotkeys:
            self.hotkeys.stop()
        self.server.close()
        # Started from the box: the new copy opens the box again. Otherwise it waits quietly in the tray.
        subprocess.Popen(launch_command(*([] if self.box.isVisible() else ["--tray"])), cwd=str(APP_DIR))
        QTimer.singleShot(300, self.app.quit)

    def _message_box(self, text: str, warning: bool = False) -> QMessageBox:
        box = QMessageBox(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information, APP_NAME, text)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setWindowIcon(self.icon)
        windows_touches(box)
        return box

    def _message(self, text: str, warning: bool = False) -> None:
        self._message_box(text, warning).exec()

    # ---- the second copy, and test commands
    def _on_connection(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._on_command(s))
            socket.disconnected.connect(socket.deleteLater)

    def _on_command(self, socket: QLocalSocket) -> None:
        while socket.canReadLine():
            line = bytes(socket.readLine()).decode("utf-8", "replace").strip()
            try:
                reply = self._command(line)
            except Exception as error:  # noqa: BLE001
                reply = {"error": str(error)}
            if reply is not None:
                socket.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                socket.flush()

    def _command(self, line: str):
        name, _, arg = line.partition(" ")
        if name == "show":
            self.open_box(0)
            return None
        if not TEST:
            return None
        if name == "state":
            result = self._cache.get(self._cache_key(self.box.text()))
            return {"visible": self.box.isVisible(), "box": int(self.box.winId()), "text": self.box.text(),
                    "target": self._target, "foreground": keys.foreground(), "status": self.box.status.text(),
                    "status_visible": not self.box.status.isHidden(), "result": result,
                    "read": self.box.read_body.text() if not self.box.read_panel.isHidden() else None,
                    "received": self._received, "banner": not self.box.banner.isHidden(),
                    "height": self.box.height(), "quality": self.quality(), "update": self._update_state}
        if name == "click":
            self.box.cards[int(arg)].clicked.emit(int(arg))
            return {"ok": True}
        if name == "write":
            self.box.set_text(arg)
            return {"ok": True}
        if name == "grab":
            self.box.grab().save(arg)
            return {"ok": True}
        if name == "quit":
            QTimer.singleShot(50, self.quit)
            return {"ok": True}
        return {"error": f"unknown command {name}"}

    # ---- pictures for the README and for checking the layout
    def take_screenshots(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.screenshotting = True
        english = "i has send you the video yesterday, did you saw it"
        samples = [("translate", engine.DEMO_SENTENCE, engine.DEMO_READ, "best", None),
                   ("correct", english, "", "best", None),
                   ("google", engine.DEMO_SENTENCE, "", "google", "available"),
                   ("google-english", english, "", "google", "restart")]
        for code in [c for c in LANGUAGE_ORDER if c in self.locales]:
            self.apply_language(code)
            for name, text, received, quality, update in samples:
                self.box.set_text(text)
                if received:
                    self.box.show_read(received)
                else:
                    self.box.hide_read()
                self.box.show_banner(quality == "google")     # how a new user without a Claude key sees it
                self.box.set_update_state(update)
                self.box.show_status("")
                self.box.show_result(engine.demo_answer(text, quality), True)
                self.box.move(40, 40)
                self.box.show()
                for _ in range(3):
                    self.app.processEvents()
                    self.box.fit()
                self.box.grab().save(str(folder / f"box-{name}-{code}.png"))
            dialog = SettingsDialog(self)
            dialog.move(60, 60)
            dialog.show()
            for _ in range(3):
                self.app.processEvents()
            dialog.grab().save(str(folder / f"settings-{code}.png"))
            dialog.close()
        self.box.hide()
        log(f"screenshots saved in {folder}")
        self.app.quit()


# ---------------------------------------------------------------- start

def another_copy_running(tray_only: bool) -> bool:
    """If Terjiman already runs, asks it to open its box (unless this is the start-up copy) and returns True."""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(500):
        return False
    if not tray_only:
        keys.allow_others_to_focus()
        socket.write(b"show\n")
        socket.flush()
        socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def main() -> int:
    global DEMO
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass
    args = sys.argv[1:]
    screenshots = None
    if "--screenshot" in args:
        index = args.index("--screenshot")
        screenshots = Path(args[index + 1] if index + 1 < len(args) else "screenshots").resolve()
        DEMO = True          # pictures use the canned answers, never the network
    tray_only = "--tray" in args
    HOME.mkdir(parents=True, exist_ok=True)
    start_log()
    try:
        import truststore     # HTTPS checks use the system's certificates (a built Mac app has no others)
        truststore.inject_into_ssl()
    except Exception as error:  # noqa: BLE001
        log(f"system certificates not used: {error}")
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("T-production")
    QApplication.setApplicationVersion(VERSION)
    QApplication.setStyle("Fusion")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not screenshots and another_copy_running(tray_only):
        return 0
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    apply_palette(app)
    app.setStyleSheet(STYLE)
    terjiman = Terjiman(app, tray_only=tray_only, screenshots=screenshots)
    app.aboutToQuit.connect(lambda: log("closed"))
    code = app.exec()
    del terjiman
    return code


if __name__ == "__main__":
    sys.exit(main())
