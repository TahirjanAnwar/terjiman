r"""Checks the Claude path inside a built Terjiman.exe, for free: a fake key is put in a test entry of Windows
Credential Manager (removed again at the end), the exe reads it, sends a request, and the box must say that the key
isn't valid. That proves the Anthropic SDK, HTTPS and the key store all work in the one-file exe.

    .venv\Scripts\python.exe tools\check_frozen.py [path\to\Terjiman.exe]
"""
import json, os, subprocess, sys, time, hashlib, getpass
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
import keyring
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket
root = Path(__file__).resolve().parents[1]
EXE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "dist" / "Terjiman.exe"
home = (root / "test-output" / "exe-claude" / "home").resolve(); home.mkdir(parents=True, exist_ok=True)
(home / "settings.json").write_text(json.dumps({"shortcut": "Ctrl+Shift+F11", "language": "en", "quality": "fast"}), encoding="utf-8")
SERVICE = "Terjiman-test-fake"
keyring.set_password(SERVICE, "claude-api-key", "terjiman-test-not-a-real-key")
server = "Terjiman-" + hashlib.sha1(f"{getpass.getuser()}|{home}".lower().encode()).hexdigest()[:12]
app = QCoreApplication([])
def cmd(line):
    s = QLocalSocket(); s.connectToServer(server)
    if not s.waitForConnected(300): return None
    s.write((line + "\n").encode()); s.flush(); s.waitForBytesWritten(500); data = b""
    for _ in range(30):
        if s.waitForReadyRead(100): data += bytes(s.readAll())
        if data.endswith(b"\n"): break
    return json.loads(data) if data.strip() else None
env = dict(os.environ, TERJIMAN_HOME=str(home), TERJIMAN_TEST="1", TERJIMAN_KEYRING_SERVICE=SERVICE)
env.pop("TERJIMAN_DEMO", None)
p = subprocess.Popen([str(EXE), "--tray"], env=env, cwd=str(root))
try:
    state = None
    for _ in range(150):
        state = cmd("state")
        if state: break
        time.sleep(0.1)
    print("exe answers:", bool(state), "| key from Credential Manager -> engine:", state and state["quality"])
    cmd("show"); cmd("write Salam, qandaq ehwalingiz?")
    for _ in range(200):
        state = cmd("state")
        if state and state["status"] and "Translating" not in state["status"]: break
        time.sleep(0.1)
    print("status after a Claude request with a fake key:", state and state["status"])
    ok = bool(state) and state["quality"] == "fast" and "isn't valid" in state["status"]
    print("PASS" if ok else "FAIL", "the Claude SDK works inside Terjiman.exe")
finally:
    cmd("quit"); time.sleep(1)
    if p.poll() is None: p.kill()
    keyring.delete_password(SERVICE, "claude-api-key")
    log = home / "terjiman.log"
    print("log:", log.read_text(encoding="utf-8").strip().replace("\n", " | ")[-500:] if log.exists() else "none")
