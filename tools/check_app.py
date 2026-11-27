"""Real-window test of Terjiman with the demo translator (no network, no API key, no cost).

It starts a test copy of Terjiman (own settings folder, test shortcut Ctrl+Shift+F11) and a Notepad window, then
works them with real keystrokes: shortcut -> type Uyghur -> Enter pastes and sends version 1; shortcut -> type
English -> a click pastes version 2; select all + Ctrl+C twice -> the copied text is shown translated. It checks
Notepad's text, the clipboard being put back, and saves pictures of the box.

It waits until nobody has touched the keyboard or mouse for a few seconds, and stops at once if the window it is
about to type into isn't in front, so keystrokes never land in another program. It puts back the clipboard text.

    .venv\\Scripts\\python.exe tools\\check_app.py [OUT_DIR]
"""
from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine  # noqa: E402
import winkeys  # noqa: E402

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtNetwork import QLocalSocket  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "test-output" / "app").resolve()
HOME = OUT / "home"
SERVER = "Terjiman-" + hashlib.sha1(f"{getpass.getuser()}|{HOME}".lower().encode()).hexdigest()[:12]
VK_F11, VK_A, VK_C = 0x7A, 0x41, 0x43
ENGLISH = "i has send you the video yesterday"

user32, kernel32 = winkeys.user32, winkeys.kernel32
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = ctypes.c_ssize_t
EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [EnumProc, wintypes.LPARAM]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GetTickCount.restype = wintypes.DWORD
WM_GETTEXT, WM_GETTEXTLENGTH, CF_UNICODETEXT = 0x000D, 0x000E, 13

results: list[tuple[str, bool, str]] = []


class Stop(Exception):
    pass


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    return ok


# ---------------------------------------------------------------- helpers

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    user32.GetLastInputInfo(ctypes.byref(info))
    return (kernel32.GetTickCount() - info.dwTime) / 1000


def wait_until_idle(seconds: float = 4, limit: float = 120) -> None:
    end = time.time() + limit
    while idle_seconds() < seconds:
        if time.time() > end:
            raise Stop("the keyboard or mouse kept being used; try again later")
        time.sleep(0.5)


def get_clipboard() -> str:
    for _ in range(40):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard(text: str) -> None:
    data = text.encode("utf-16-le") + b"\0\0"
    handle = kernel32.GlobalAlloc(0x0002, len(data))
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    for _ in range(40):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_UNICODETEXT, handle)
    finally:
        user32.CloseClipboard()


def windows_of(pid: int) -> list[int]:
    found = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(EnumProc(visit), 0)
    return found


def notepad_text(hwnd: int) -> str:
    edit = user32.FindWindowExW(hwnd, None, "Edit", None)
    length = user32.SendMessageW(edit, WM_GETTEXTLENGTH, 0, 0)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(edit, WM_GETTEXT, length + 1, ctypes.cast(buffer, ctypes.c_void_p).value)
    return buffer.value


def describe(hwnd: int) -> str:
    title = ctypes.create_unicode_buffer(200)
    user32.GetWindowTextW(hwnd, title, 200)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return f"{winkeys.window_class(hwnd)} '{title.value[:40]}' pid {pid.value}"


def must_be_front(hwnd: int, what: str) -> None:
    front = winkeys.foreground()
    if front != hwnd:
        raise Stop(f"{what} isn't in front, so no keys were sent (in front: {describe(front)}, "
                   f"idle {idle_seconds():.1f} s)")


def server_for(home: Path) -> str:
    return "Terjiman-" + hashlib.sha1(f"{getpass.getuser()}|{home}".lower().encode()).hexdigest()[:12]


def command(line: str, timeout_ms: int = 3000, server: str = SERVER):
    socket = QLocalSocket()
    socket.connectToServer(server)
    if not socket.waitForConnected(timeout_ms):
        raise ConnectionError("the test copy of Terjiman doesn't answer")
    socket.write((line + "\n").encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    data, end = b"", time.time() + timeout_ms / 1000
    while not data.endswith(b"\n") and time.time() < end:
        if socket.waitForReadyRead(100):
            data += bytes(socket.readAll())
    socket.disconnectFromServer()
    return json.loads(data.decode("utf-8")) if data.strip() else None


def wait_for(test, timeout: float, what: str):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = command("state")
            if last and test(last):
                return last
        except ConnectionError:
            pass
        time.sleep(0.1)
    raise Stop(f"timed out waiting for: {what} (last state: {json.dumps(last, ensure_ascii=False)[:300]})")


def press_shortcut(front: int, what: str) -> None:
    must_be_front(front, what)
    winkeys.combo(VK_F11, winkeys.VK_CONTROL, winkeys.VK_SHIFT)


# ---------------------------------------------------------------- the test

def first_start(python: Path) -> None:
    """A normal start (not --tray, real engine) without an API key: the box opens at once and asks for the key."""
    home = OUT / "first-start"
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps({"shortcut": "Ctrl+Shift+F11", "language": "ug"}),
                                        encoding="utf-8")
    env = dict(os.environ, TERJIMAN_HOME=str(home), TERJIMAN_TEST="1",
               TERJIMAN_KEYRING_SERVICE="Terjiman-test-no-key")
    env.pop("TERJIMAN_DEMO", None)
    server = server_for(home)
    started = time.time()
    process = subprocess.Popen([str(python), str(ROOT / "terjiman.py")], env=env, cwd=str(ROOT))
    state = None
    try:
        while time.time() - started < 15 and not (state and state["visible"]):
            try:
                state = command("state", server=server)
            except ConnectionError:
                time.sleep(0.1)
        check("a normal start opens the box within 3 s", bool(state and state["visible"])
              and time.time() - started < 3, f"{time.time() - started:.1f} s")
        check("without an API key the box asks for one", bool(state and state["banner"]))
        if state:
            command(f"grab {OUT / 'first-start.png'}", server=server)
    finally:
        try:
            command("quit", server=server)
        except ConnectionError:
            pass
        try:
            process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()
    log = (home / "terjiman.log").read_text(encoding="utf-8") if (home / "terjiman.log").exists() else ""
    check("no errors when starting normally", "Traceback" not in log, log[-200:] if "Traceback" in log else "")


def main() -> int:
    app = QCoreApplication(sys.argv)  # noqa: F841 - QLocalSocket needs it
    try:
        command("state", timeout_ms=500, server=server_for(ROOT))
        real_running = True
    except ConnectionError:
        real_running = False
    if real_running:
        # The real Terjiman watches the clipboard too: the Ctrl+C-twice step would make it translate the test
        # text with Claude, which costs money and changes where its box pastes.
        print("The real Terjiman is running. Quit it first (tray icon -> Quit), then run this test again.")
        return 2
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "settings.json").write_text(json.dumps({"shortcut": "Ctrl+Shift+F11", "language": "en"}),
                                        encoding="utf-8")
    env = dict(os.environ, TERJIMAN_HOME=str(HOME), TERJIMAN_DEMO="1", TERJIMAN_TEST="1",
               TERJIMAN_KEYRING_SERVICE="Terjiman-test")
    python = ROOT / ".venv" / "Scripts" / "pythonw.exe"

    first_start(python)
    print("Waiting until the keyboard and mouse are idle...", flush=True)
    wait_until_idle()
    original_window = winkeys.foreground()
    original_clipboard = get_clipboard()
    terjiman = subprocess.Popen([str(python), str(ROOT / "terjiman.py"), "--tray"], env=env, cwd=str(ROOT))
    notepad = None
    try:
        try:
            wait_for(lambda s: s is not None, 40, "Terjiman to start")
        except Stop:
            alive = terjiman.poll() is None
            log = HOME / "terjiman.log"
            raise Stop(f"Terjiman didn't answer (process {'running' if alive else f'ended {terjiman.returncode}'}, "
                       f"log: {log.read_text(encoding='utf-8')[-300:] if log.exists() else 'none'})")
        notepad = subprocess.Popen(["notepad.exe"])
        end = time.time() + 10
        pad = 0
        while time.time() < end and not pad:
            pad = next(iter(windows_of(notepad.pid)), 0)
            time.sleep(0.1)
        if not pad:
            raise Stop("Notepad didn't open")
        time.sleep(0.5)
        if not winkeys.focus_window(pad, 2.0):
            raise Stop("couldn't bring Notepad to the front")

        # A: shortcut, type Uyghur, Enter pastes and sends version 1, the clipboard comes back
        set_clipboard("TERJIMAN-TEST-MARKER")
        press_shortcut(pad, "Notepad")
        state = wait_for(lambda s: s["visible"] and s["foreground"] == s["box"], 5, "the box to open in front")
        box = state["box"]
        check("shortcut opens the box in front", True)
        check("box remembers Notepad as the target", state["target"] == pad)
        must_be_front(box, "the Terjiman box")
        winkeys.type_text(engine.DEMO_SENTENCE)
        state = wait_for(lambda s: s["text"] == engine.DEMO_SENTENCE and s["result"], 10, "the translation")
        check("typing Uyghur gives three versions", len(state["result"]["versions"]) == 3)
        command(f"grab {OUT / 'real-typed.png'}")
        first = state["result"]["versions"][0]["text"]
        must_be_front(box, "the Terjiman box")
        winkeys.enter()
        time.sleep(1.0)
        text = notepad_text(pad)
        check("Enter pastes version 1 into Notepad and presses Enter", text == first + "\r\n", repr(text))
        check("the box hides after sending", not command("state")["visible"])
        time.sleep(1.2)
        check("the clipboard is put back after pasting", get_clipboard() == "TERJIMAN-TEST-MARKER",
              repr(get_clipboard()[:40]))

        # B: English gets corrected; a click pastes version 2 without sending
        press_shortcut(pad, "Notepad")
        wait_for(lambda s: s["visible"] and s["foreground"] == s["box"], 5, "the box to open again")
        must_be_front(box, "the Terjiman box")
        winkeys.type_text(ENGLISH)
        state = wait_for(lambda s: s["text"] == ENGLISH and s["result"], 10, "the correction")
        check("English text is corrected", state["result"]["mode"] == "correct")
        second = state["result"]["versions"][1]["text"]
        command("click 1")
        time.sleep(1.0)
        text = notepad_text(pad)
        check("a click pastes version 2 without sending", text == first + "\r\n" + second, repr(text[-80:]))

        # C: select all, Ctrl+C twice -> the copied text is read in Uyghur
        time.sleep(3.2)              # Terjiman ignores the clipboard for 3 s after its own pasting
        must_be_front(pad, "Notepad")
        winkeys.combo(VK_A, winkeys.VK_CONTROL)
        time.sleep(0.2)
        must_be_front(pad, "Notepad")
        winkeys.send([winkeys._key(winkeys.VK_CONTROL), winkeys._key(VK_C), winkeys._key(VK_C, True)])
        time.sleep(0.18)
        winkeys.send([winkeys._key(VK_C), winkeys._key(VK_C, True)])
        time.sleep(0.25)
        winkeys.send([winkeys._key(winkeys.VK_CONTROL, True)])
        state = wait_for(lambda s: s["visible"] and s["read"] == engine.DEMO_READ, 6, "the copied text to be read")
        check("Ctrl+C twice shows the copied text translated", True)
        check("the reply goes back to Notepad", state["target"] == pad)
        check("the copied message is kept as reply context",
              state["received"].replace("\r\n", "\n") == first + "\n" + second, repr(state["received"][-60:]))
        command(f"grab {OUT / 'real-read.png'}")

        # D: the shortcut closes the box again; Esc closes it too
        must_be_front(box, "the Terjiman box")
        press_shortcut(box, "the Terjiman box")
        wait_for(lambda s: not s["visible"], 3, "the shortcut to close the box")
        check("the shortcut closes the box when it is in front", True)
        if not winkeys.focus_window(pad, 2.0):
            raise Stop("couldn't bring Notepad back to the front")
        press_shortcut(pad, "Notepad")
        wait_for(lambda s: s["visible"] and s["foreground"] == s["box"], 5, "the box to open")
        must_be_front(box, "the Terjiman box")
        winkeys.combo(winkeys.VK_ESCAPE)
        wait_for(lambda s: not s["visible"], 3, "Esc to close the box")
        check("Esc closes the box", True)
    except Stop as stop:
        check("test run", False, str(stop))
    finally:
        try:
            command("quit")
        except Exception:  # noqa: BLE001
            pass
        try:
            terjiman.wait(5)
        except subprocess.TimeoutExpired:
            terjiman.kill()
        if notepad:
            notepad.kill()
        set_clipboard(original_clipboard)
        if original_window:
            winkeys.focus_window(original_window, 1.0)

    log = HOME / "terjiman.log"
    problems = [line for line in log.read_text(encoding="utf-8").splitlines()
                if "Traceback" in line or "Error" in line] if log.exists() else []
    check("no errors in Terjiman's log", not problems, "; ".join(problems[:3]))
    failed = [name for name, ok, _ in results if not ok]
    print()
    print("ALL PASSED" if not failed else f"{len(failed)} FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
