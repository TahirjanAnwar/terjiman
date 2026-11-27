"""Checks Terjiman's settings window and messages: saving a new shortcut, quality, languages and options, refusing a
shortcut without Ctrl/Alt, every error message in every language, no missing translations, and the update check.
Demo mode with a scratch settings folder, so nothing real is touched.

    .venv\\Scripts\\python.exe tools\\check_settings.py [OUT_DIR]
"""
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "test-output" / "settings").resolve()
HOME = OUT / "home"
HOME.mkdir(parents=True, exist_ok=True)
(HOME / "settings.json").write_text(json.dumps({"shortcut": "Ctrl+Shift+F11", "language": "en"}), encoding="utf-8")
os.environ.update(TERJIMAN_HOME=str(HOME), TERJIMAN_DEMO="1", TERJIMAN_TEST="1",
                  TERJIMAN_KEYRING_SERVICE="Terjiman-test")
sys.path.insert(0, str(ROOT))

import engine  # noqa: E402
import terjiman  # noqa: E402
import winkeys  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        failures.append(name)


QApplication.setStyle("Fusion")
app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
app.setStyleSheet(terjiman.STYLE)
t = terjiman.Terjiman(app, tray_only=True)

# ---- translations: every English text exists in the other four languages, with the same {placeholders}
english = t.locales["en"]


def placeholders(text: str) -> list[str]:
    return sorted(re.findall(r"\{(\w+)\}", text))


for code in terjiman.LANGUAGE_ORDER:
    locale = t.locales.get(code, {})
    missing = [k for k in english if k not in locale]
    wrong = [k for k in english if k in locale and placeholders(english[k]) != placeholders(locale[k])]
    check(f"{code}: all {len(english)} texts translated", not missing, ", ".join(missing[:5]))
    check(f"{code}: placeholders match English", not wrong, ", ".join(wrong[:5]))

# ---- error messages in every language
kinds = ["key_invalid", "key_denied", "no_credit", "rate_limited", "no_connection", "timeout", "server", "refused",
         "bad_answer", "bad_request", "not_found", "generic", "something_new"]
bad = []
for code in terjiman.LANGUAGE_ORDER:
    t.apply_language(code)
    for kind in kinds:
        text = t.error_text(engine.EngineError(kind, "detail"))
        if text.startswith("err_") or "{" in text:
            bad.append(f"{code}/{kind}")
check("every error has a message in every language", not bad, ", ".join(bad[:5]))
t.apply_language("en")
t._write_failed(t._write_job, engine.EngineError("no_credit"))
check("a credit error shows the message and the Settings banner",
      "credit" in t.box.status.text() and not t.box.banner.isHidden())


# ---- the settings window
def drive():
    dialog = t._settings_dialog
    if dialog is None:
        return QTimer.singleShot(100, drive)
    dialog.shortcut.setKeySequence(QKeySequence.fromString("A", QKeySequence.SequenceFormat.PortableText))
    dialog._save()
    check("a shortcut without Ctrl/Alt is refused", dialog.isVisible() and "Ctrl" in dialog.message.text(),
          dialog.message.text())
    dialog.shortcut.setKeySequence(QKeySequence.fromString("Ctrl+Shift+F10", QKeySequence.SequenceFormat.PortableText))
    dialog.fast.setChecked(True)
    dialog.target.setCurrentIndex(dialog.target.findData("nl"))
    dialog.ui_language.setCurrentIndex(dialog.ui_language.findData("tr"))
    dialog.copy_twice.setChecked(False)
    dialog.grab().save(str(OUT / "settings-filled.png"))
    dialog._save()


QTimer.singleShot(300, drive)
t.open_settings()          # returns when the window closes
s = t.settings
check("settings are saved", (s.get("shortcut"), s.get("quality"), s.get("target"), s.get("copy_twice"), t.lang)
      == ("Ctrl+Shift+F10", "fast", "nl", False, "tr"),
      str((s.get("shortcut"), s.get("quality"), s.get("target"), s.get("copy_twice"), t.lang)))
saved = json.loads((HOME / "settings.json").read_text(encoding="utf-8"))
check("settings.json is written", saved.get("shortcut") == "Ctrl+Shift+F10" and saved.get("language") == "tr")
mods, vk = terjiman.parse_shortcut("Ctrl+Shift+F10")
free = winkeys.user32.RegisterHotKey(None, 77, mods, vk)
if free:
    winkeys.user32.UnregisterHotKey(None, 77)
check("the new shortcut is active", not free)
mods, vk = terjiman.parse_shortcut("Ctrl+Shift+F11")
free = winkeys.user32.RegisterHotKey(None, 78, mods, vk)
if free:
    winkeys.user32.UnregisterHotKey(None, 78)
check("the old shortcut is released", bool(free))
check("the placeholder follows the new languages", "Engels" not in t.box.input.placeholderText()
      and "Felemenkçe" in t.box.input.placeholderText(), t.box.input.placeholderText())

# ---- the update check answers (whether or not this folder is a git copy yet)
messages = []
t._message = lambda text, warning=False: messages.append(text)
t._check_updates(quiet=False)
for _ in range(20):
    app.processEvents()
check("the update check gives an answer", bool(messages), messages[0][:80] if messages else "")

t.quit()
print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
