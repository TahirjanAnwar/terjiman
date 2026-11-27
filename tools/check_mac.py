"""Mac checks that need no person at the keyboard (GitHub runs them on its Macs before building):
the shortcut can be registered and freed, the frontmost app can be read, the Accessibility check answers, the
shortcut texts become Mac key codes, and HTTPS works (free Google, and Claude with a fake key).

    python3 tools/check_mac.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import engine  # noqa: E402
import mackeys  # noqa: E402
import terjiman  # noqa: E402

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


try:
    import truststore
    truststore.inject_into_ssl()
except Exception as error:  # noqa: BLE001
    print("truststore:", error)

front = mackeys.foreground()
check("the frontmost app can be read", isinstance(front, int), str(front))
check("the Accessibility check answers", mackeys.can_type(prompt=False) in (True, False))
parsed = terjiman.parse_shortcut("Ctrl+Shift+Space")
check("Ctrl+Shift+Space in Qt is Cmd+Shift+Space on a Mac",
      parsed == (mackeys.CMD_KEY | mackeys.SHIFT_KEY, mackeys.KVK_SPACE), str(parsed))
check("a letter without Cmd/Option/Control is refused", terjiman.parse_shortcut("Shift+A") is None)
listener = mackeys.HotkeyListener(lambda: None)
check("the hot-key handler is installed", listener.installed)
check("the shortcut can be registered", listener.set(*parsed))
check("and freed again", listener.set(0, 0))
listener.stop()

try:
    result = engine.GoogleEngine().write(engine.DEMO_SENTENCE, mine="ug", target="en")
    check("free Google over HTTPS", bool(result["versions"][0]["text"]), result["versions"][0]["text"])
except engine.EngineError as error:
    check("free Google over HTTPS", False, f"{error.kind} {error.detail}")
try:
    engine.check_key("terjiman-test-not-a-real-key")
    check("Claude over HTTPS", False, "a fake key was accepted?")
except engine.EngineError as error:
    check("Claude over HTTPS (refuses the fake key)", error.kind == "key_invalid", error.kind)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
