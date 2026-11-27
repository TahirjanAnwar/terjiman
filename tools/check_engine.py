"""Checks Terjiman's translator without spending money:

- the prompts are complete for every language pair,
- an answer streamed in random pieces (also split by a fallback switch) is read correctly,
- the demo engine works end to end,
- the Anthropic SDK accepts every option the real engine sends: a request with a fake key must come back as
  "key not valid" (HTTP 401), not as a programming error.

    .venv\\Scripts\\python.exe tools\\check_engine.py [--offline]
"""
import json
import random
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


# ---- prompts
for mine in engine.LANGUAGE_NAMES:
    for target in engine.LANGUAGE_NAMES:
        prompt = engine.write_system_prompt(mine, target)
        read = engine.read_system_prompt(mine, target)
        if "{" in prompt.replace("{text}", "") or "{" in read:
            check(f"prompt {mine}->{target}", False, "unfilled placeholder")
check("prompts filled for all 25 language pairs", True)
ug = engine.write_system_prompt("ug", "en")
check("Uyghur prompt asks for Arabic script", "Uyghur Arabic script" in ug)
message = engine.write_user_message("سالام", "Hello, how are you?")
check("reply context goes before the text", message.index("<received>") < message.index("<text>"))

# ---- streaming in pieces
raw = json.dumps(engine.DEMO_ANSWER, ensure_ascii=False)
random.seed(7)
for trial in range(200):
    cuts = sorted(random.sample(range(1, len(raw)), random.randint(1, 40)))
    pieces = [raw[a:b] for a, b in zip([0] + cuts, cuts + [len(raw)])]
    parts, last_count = [[]], 0
    for piece in pieces:
        parts[0].append(piece)
        partial = engine.parse_partial(parts)
        if partial is not None:
            if len(partial["versions"]) < last_count:
                check("versions never disappear while streaming", False, f"trial {trial}")
                break
            last_count = len(partial["versions"])
    final = engine.parse_final(parts)
    if not final or [v["text"] for v in final["versions"]] != [v["text"] for v in engine.DEMO_ANSWER["versions"]]:
        check("final answer after random pieces", False, f"trial {trial}")
        break
else:
    check("200 random streams read correctly", True)

half = len(raw) // 2
final = engine.parse_final([[raw[:half]], [raw[half:]]])
check("answer continued after a fallback switch", bool(final) and len(final["versions"]) == 3)
final = engine.parse_final([['{"mode": "translate", "vers'], [raw]])
check("answer restarted after a fallback switch", bool(final) and len(final["versions"]) == 3)
partial = engine.parse_partial([['{"mode": "translate", "versions": [{"style": "natural", "text": "My Eng']])
check("a half-written version shows while streaming", bool(partial) and partial["versions"][0]["text"] == "My Eng"
      and not partial["versions"][0]["complete"])
check("an empty or broken answer is refused", engine.parse_final([["{\"mode\": \"translate\""]]) is None)

# ---- demo engine
demo = engine.DemoEngine(delay=0)
seen = []
result = demo.write(engine.DEMO_SENTENCE, mine="ug", target="en", quality="best", on_partial=seen.append)
check("demo engine streams and finishes", bool(seen) and result["versions"][0]["text"].startswith("My English"))
check("demo English text gets corrected", demo.write("i has a apple", mine="ug", target="en",
                                                     quality="best")["mode"] == "correct")
check("demo cancel stops", demo.write(engine.DEMO_SENTENCE, mine="ug", target="en", quality="best",
                                      cancelled=lambda: True) is None)

# ---- the SDK accepts our requests (needs the internet; a fake key is refused for free)
if "--offline" not in sys.argv:
    fake = "sk-ant-api03-terjiman-test-not-a-real-key"
    real = engine.Engine(fake)
    for quality in ("best", "fast"):
        try:
            real.write("سالام", mine="ug", target="en", quality=quality)
            check(f"write request ({quality})", False, "a fake key was accepted?")
        except engine.EngineError as error:
            check(f"write request ({quality}) reaches Claude and is refused for the fake key", error.kind == "key_invalid",
                  error.kind)
        except TypeError as error:
            check(f"write request ({quality})", False, f"SDK rejected an option: {error}")
    try:
        real.read("Hello", mine="ug", target="en", quality="best")
    except engine.EngineError as error:
        check("read request reaches Claude", error.kind == "key_invalid", error.kind)
    try:
        engine.check_key(fake)
        check("key check", False, "a fake key was accepted?")
    except engine.EngineError as error:
        check("key check says the fake key is not valid", error.kind == "key_invalid", error.kind)

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: {', '.join(failures)}")
sys.exit(1 if failures else 0)
