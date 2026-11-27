"""Windows helpers for Terjiman: the system-wide shortcut, window focus, and keystrokes into other programs.

Everything here talks to user32 through ctypes, so no extra packages are needed.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP = 0x8000
PM_NOREMOVE = 0x0000
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK, VK_TAB, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU = 0x08, 0x09, 0x0D, 0x10, 0x11, 0x12
VK_ESCAPE, VK_SPACE, VK_LWIN, VK_RWIN = 0x1B, 0x20, 0x5B, 0x5C
SW_RESTORE = 9
ASFW_ANY = 0xFFFFFFFF

# The taskbar, the desktop and the Start menu: pasting "into" these makes no sense.
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "NotifyIconOverflowWindow",
                 "TopLevelWindowForOverflowXamlIsland", "Windows.UI.Core.CoreWindow"}

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


# ---------------------------------------------------------------- windows and focus

def foreground() -> int:
    return user32.GetForegroundWindow() or 0


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def is_shell_window(hwnd: int) -> bool:
    return window_class(hwnd) in SHELL_CLASSES


def top_level(hwnd: int) -> int:
    return user32.GetAncestor(hwnd, 2) or hwnd if hwnd else 0   # GA_ROOT


def allow_others_to_focus() -> None:
    """Lets the running Terjiman bring its window forward when a second copy is started."""
    user32.AllowSetForegroundWindow(ASFW_ANY)


def focus_window(hwnd: int, timeout: float = 0.6) -> bool:
    """Brings hwnd to the front with the keyboard focus. True when it really is the foreground window."""
    if not is_window(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if not user32.SetForegroundWindow(hwnd):
        # Windows only lets the foreground program hand over the focus. Borrowing its input queue for a moment
        # counts as that, and is what most launchers do.
        current = foreground()
        theirs = user32.GetWindowThreadProcessId(current, None) if current else 0
        mine = kernel32.GetCurrentThreadId()
        attached = bool(theirs and theirs != mine and user32.AttachThreadInput(mine, theirs, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(mine, theirs, False)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if foreground() == hwnd:
            return True
        time.sleep(0.01)
    return foreground() == hwnd


# ---------------------------------------------------------------- keystrokes

def _key(vk: int, up: bool = False) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return event


def _char(code_unit: int, up: bool = False) -> INPUT:
    event = INPUT(type=INPUT_KEYBOARD)
    event.u.ki = KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
    return event


def send(events: list[INPUT]) -> bool:
    if not events:
        return True
    array = (INPUT * len(events))(*events)
    return user32.SendInput(len(events), array, ctypes.sizeof(INPUT)) == len(events)


def combo(vk: int, *modifiers: int) -> bool:
    """Presses modifier(s) + key, like a person would."""
    return send([_key(m) for m in modifiers] + [_key(vk), _key(vk, True)] + [_key(m, True) for m in reversed(modifiers)])


def paste() -> bool:
    return combo(ord("V"), VK_CONTROL)


def copy() -> bool:
    return combo(ord("C"), VK_CONTROL)


def enter() -> bool:
    return combo(VK_RETURN)


def type_text(text: str) -> bool:
    """Types any text (Uyghur too), one UTF-16 unit at a time. Used by the tests."""
    units = text.encode("utf-16-le")
    events = []
    for i in range(0, len(units), 2):
        unit = int.from_bytes(units[i:i + 2], "little")
        events += [_char(unit), _char(unit, True)]
    return send(events)


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def ctrl_down() -> bool:
    return key_down(VK_CONTROL)


def modifiers_down() -> bool:
    return any(key_down(vk) for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))


def wait_modifiers_up(timeout: float = 1.0) -> bool:
    """Waits until Shift, Ctrl, Alt and Win are released, so a pasted Ctrl+V doesn't become Ctrl+Shift+V."""
    end = time.monotonic() + timeout
    while modifiers_down():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True


# ---------------------------------------------------------------- the system-wide shortcut

# Qt key codes for keys that aren't printable characters, and their Windows virtual-key codes.
_QT_SPECIAL = {
    0x01000030 + i: 0x70 + i for i in range(24)          # F1 ... F24
}
_QT_SPECIAL.update({
    0x01000006: 0x2D, 0x01000007: 0x2E,                   # Insert, Delete
    0x01000010: 0x24, 0x01000011: 0x23,                   # Home, End
    0x01000016: 0x21, 0x01000017: 0x22,                   # PageUp, PageDown
    0x01000012: 0x25, 0x01000013: 0x26, 0x01000014: 0x27, 0x01000015: 0x28,   # arrows
    0x01000008: 0x13, 0x01000026: 0x91, 0x01000009: 0x2C,  # Pause, ScrollLock, Print
    0x01000001: VK_TAB, 0x01000003: VK_BACK,
})
_NO_MODIFIER_OK = {0x70 + i for i in range(24)} | {0x13, 0x91}   # F-keys, Pause and Scroll Lock may stand alone


def shortcut_to_windows(key: int, ctrl: bool, shift: bool, alt: bool, win: bool) -> tuple[int, int] | None:
    """(modifiers, virtual key) for RegisterHotKey, or None if the key can't be a shortcut."""
    if key in _QT_SPECIAL:
        vk = _QT_SPECIAL[key]
    elif key == 0x20:
        vk = VK_SPACE
    elif 0x41 <= key <= 0x5A or 0x30 <= key <= 0x39:      # A-Z and 0-9 are the same in Qt and Windows
        vk = key
    elif 0x21 <= key <= 0xFFFF:
        scan = user32.VkKeyScanW(chr(key))                # punctuation: depends on the keyboard layout
        if scan == -1:
            return None
        vk = scan & 0xFF
    else:
        return None
    mods = (MOD_CONTROL if ctrl else 0) | (MOD_SHIFT if shift else 0) | (MOD_ALT if alt else 0) | (MOD_WIN if win else 0)
    if not (mods & (MOD_CONTROL | MOD_ALT | MOD_WIN)) and vk not in _NO_MODIFIER_OK:
        return None                                       # Shift+letter alone would stop people typing capitals
    return mods, vk


class HotkeyListener(threading.Thread):
    """Owns the system-wide shortcut. RegisterHotKey belongs to a thread, so this thread runs its own message loop
    and calls callback() (on this thread) each time the shortcut is pressed."""

    _SET = WM_APP + 1

    def __init__(self, callback):
        super().__init__(name="terjiman-hotkey", daemon=True)
        self._callback = callback
        self._ready = threading.Event()
        self._answered = threading.Event()
        self._wanted = (0, 0)
        self._result = False
        self._thread_id = 0
        self.start()
        self._ready.wait(3)

    def run(self):
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)   # makes the message queue
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        registered = False
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam == 1:
                try:
                    self._callback()
                except Exception:   # noqa: BLE001 - never let the shortcut thread die
                    pass
            elif msg.message == self._SET:
                if registered:
                    user32.UnregisterHotKey(None, 1)
                    registered = False
                mods, vk = self._wanted
                if vk:
                    registered = bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
                self._result = registered or not vk
                self._answered.set()
        if registered:
            user32.UnregisterHotKey(None, 1)

    def set(self, mods: int, vk: int) -> bool:
        """Switches to a new shortcut (vk 0 = none). False if another program already uses it."""
        self._answered.clear()
        self._wanted = (mods, vk)
        user32.PostThreadMessageW(self._thread_id, self._SET, 0, 0)
        return self._answered.wait(3) and self._result

    def stop(self):
        user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self.join(2)
