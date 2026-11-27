"""macOS helpers for Terjiman: the system-wide shortcut (Carbon), keystrokes into other apps (Quartz), and which app
is in front (AppKit). The same functions as winkeys.py; a "window" here is an app's process id.

Typing into other apps needs the user's permission once: System Settings → Privacy & Security → Accessibility.
The shortcut itself works without it (Carbon hot keys need no permission).
Needs pyobjc (pyobjc-framework-Cocoa, -Quartz, -ApplicationServices); see requirements-mac.txt.
"""
from __future__ import annotations

import ctypes
import os
import time

import AppKit
import Quartz

try:
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
except ImportError:  # older pyobjc keeps them in HIServices
    from HIServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

# Apps that aren't a place to paste into.
SHELL_APPS = {"com.apple.dock", "com.apple.loginwindow", "com.apple.systemuiserver", "com.apple.notificationcenterui"}


# ---------------------------------------------------------------- apps and focus

def foreground() -> int:
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return int(app.processIdentifier()) if app is not None else 0


def _app(pid: int):
    return AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid) if pid else None


def is_window(pid: int) -> bool:
    app = _app(pid)
    return app is not None and not app.isTerminated()


def window_pid(pid: int) -> int:
    return int(pid or 0)


def is_shell_window(pid: int) -> bool:
    app = _app(pid)
    return app is not None and str(app.bundleIdentifier() or "") in SHELL_APPS


def allow_others_to_focus() -> None:
    """Only Windows needs this (see winkeys.py)."""


def _spin(seconds: float) -> None:
    """Waits while the app's event loop keeps running: macOS reports the app in front through that loop."""
    from PySide6.QtCore import QCoreApplication, QEventLoop
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        time.sleep(0.005)


def focus_own_app() -> None:
    """Terjiman lives in the menu bar (no Dock icon), so it has to bring itself forward before its box can take
    the keyboard."""
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def focus_window(pid: int, timeout: float = 0.8) -> bool:
    """Brings the app with this process id to the front. True when it really is the frontmost app."""
    app = _app(pid)
    if app is None or app.isTerminated():
        return False
    if pid == os.getpid():
        focus_own_app()
    else:
        app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if foreground() == pid:
            return True
        _spin(0.02)
    return foreground() == pid


# ---------------------------------------------------------------- keystrokes

KVK_ANSI_A, KVK_ANSI_C, KVK_ANSI_V, KVK_RETURN, KVK_SPACE = 0, 8, 9, 36, 49
_CMD = Quartz.kCGEventFlagMaskCommand
_MODIFIERS = (Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift | Quartz.kCGEventFlagMaskAlternate
              | Quartz.kCGEventFlagMaskControl)


def can_type(prompt: bool = False) -> bool:
    """True when macOS lets Terjiman send keystrokes to other apps (Accessibility). prompt: let macOS show its own
    message that leads the user to the setting."""
    try:
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: bool(prompt)}))
    except Exception:  # noqa: BLE001
        return False


def _post(code: int, down: bool, flags: int = 0) -> None:
    event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    Quartz.CGEventSetFlags(event, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def combo(code: int, flags: int = 0) -> bool:
    _post(code, True, flags)
    _post(code, False, flags)
    return True


def paste() -> bool:
    return combo(KVK_ANSI_V, _CMD)


def copy() -> bool:
    return combo(KVK_ANSI_C, _CMD)


def enter() -> bool:
    return combo(KVK_RETURN)


def _flags() -> int:
    return int(Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateCombinedSessionState))


def copy_modifier_down() -> bool:
    """Cmd is held (Cmd+C twice reads the copied text)."""
    return bool(_flags() & _CMD)


def modifiers_down() -> bool:
    return bool(_flags() & _MODIFIERS)


def wait_modifiers_up(timeout: float = 1.0) -> bool:
    end = time.monotonic() + timeout
    while modifiers_down():
        if time.monotonic() > end:
            return False
        _spin(0.01)
    return True


# ---------------------------------------------------------------- the system-wide shortcut (Carbon hot key)

CMD_KEY, SHIFT_KEY, OPTION_KEY, CONTROL_KEY = 1 << 8, 1 << 9, 1 << 11, 1 << 12

# Mac virtual key codes of the US layout; key equivalents use these positions on every layout.
_CHARS = {"A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7, "C": 8, "V": 9, "B": 11, "Q": 12,
          "W": 13, "E": 14, "R": 15, "Y": 16, "T": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
          "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "O": 31, "U": 32, "[": 33, "I": 34,
          "P": 35, "L": 37, "J": 38, "'": 39, "K": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "N": 45, "M": 46,
          ".": 47, "`": 50}
_F_KEYS = [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90]
_QT_SPECIAL = {0x01000030 + i: code for i, code in enumerate(_F_KEYS)}      # Qt F1 ... F20
_QT_SPECIAL.update({
    0x01000010: 115, 0x01000011: 119,                     # Home, End
    0x01000016: 116, 0x01000017: 121,                     # PageUp, PageDown
    0x01000012: 123, 0x01000013: 126, 0x01000014: 124, 0x01000015: 125,   # arrows
    0x01000001: 48, 0x01000003: 51, 0x01000007: 117,      # Tab, Backspace, forward Delete
})


def shortcut_to_native(key: int, ctrl: bool, shift: bool, alt: bool, meta: bool) -> tuple[int, int] | None:
    """(Carbon modifiers, Mac key code), or None. Qt on macOS calls Cmd "Control" and the Control key "Meta"."""
    if key in _QT_SPECIAL:
        code = _QT_SPECIAL[key]
    elif key == 0x20:
        code = KVK_SPACE
    elif 0x20 < key < 0x7F and chr(key).upper() in _CHARS:
        code = _CHARS[chr(key).upper()]
    else:
        return None
    mods = (CMD_KEY if ctrl else 0) | (SHIFT_KEY if shift else 0) | (OPTION_KEY if alt else 0) | \
        (CONTROL_KEY if meta else 0)
    if not (mods & (CMD_KEY | OPTION_KEY | CONTROL_KEY)) and code not in _F_KEYS:
        return None                      # Shift+letter alone would stop people typing capitals
    return mods, code


_carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")


class _HotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
_carbon.GetApplicationEventTarget.argtypes = []
_carbon.InstallEventHandler.restype = ctypes.c_int32
_carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_ulong, ctypes.POINTER(_EventTypeSpec),
                                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_carbon.RegisterEventHotKey.restype = ctypes.c_int32
_carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _HotKeyID, ctypes.c_void_p, ctypes.c_uint32,
                                        ctypes.POINTER(ctypes.c_void_p)]
_carbon.UnregisterEventHotKey.restype = ctypes.c_int32
_carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
_carbon.GetEventParameter.restype = ctypes.c_int32
_carbon.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]


def _fourcc(text: str) -> int:
    return int.from_bytes(text.encode("ascii"), "big")


K_EVENT_CLASS_KEYBOARD, K_EVENT_HOT_KEY_PRESSED = _fourcc("keyb"), 5
K_PARAM_DIRECT_OBJECT, TYPE_HOT_KEY_ID = _fourcc("----"), _fourcc("hkid")
SIGNATURE = _fourcc("TJMN")


class HotkeyListener:
    """One system-wide shortcut through Carbon's RegisterEventHotKey. macOS calls callback() on the main thread
    each time it is pressed. Use it from the main thread."""

    def __init__(self, callback):
        self._callback = callback
        self._ref = ctypes.c_void_p()
        self._handler_ref = ctypes.c_void_p()
        self._handler = _HANDLER(self._on_event)       # kept alive: Carbon calls it for as long as the app runs
        spec = _EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOT_KEY_PRESSED)
        self.installed = _carbon.InstallEventHandler(_carbon.GetApplicationEventTarget(), self._handler, 1,
                                                     ctypes.byref(spec), None, ctypes.byref(self._handler_ref)) == 0

    def _on_event(self, call_ref, event, user_data):
        hotkey = _HotKeyID()
        _carbon.GetEventParameter(event, K_PARAM_DIRECT_OBJECT, TYPE_HOT_KEY_ID, None, ctypes.sizeof(hotkey), None,
                                  ctypes.byref(hotkey))
        if hotkey.signature == SIGNATURE and hotkey.id == 1:
            try:
                self._callback()
            except Exception:  # noqa: BLE001 - never let an error escape into Carbon
                pass
        return 0

    def set(self, mods: int, code: int) -> bool:
        """Switches to a new shortcut; (0, 0) means none. False if another app already uses it."""
        self.stop()
        if mods == 0 and code == 0:
            return True
        status = _carbon.RegisterEventHotKey(code, mods, _HotKeyID(SIGNATURE, 1), _carbon.GetApplicationEventTarget(),
                                             0, ctypes.byref(self._ref))
        if status != 0:
            self._ref = ctypes.c_void_p()
            return False
        return True

    def stop(self) -> None:
        if self._ref:
            _carbon.UnregisterEventHotKey(self._ref)
            self._ref = ctypes.c_void_p()
