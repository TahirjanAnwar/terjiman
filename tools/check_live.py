"""A real test with Claude, using the API key saved in Terjiman. It costs about 1-2 US cents.

One Uyghur message is translated with Claude Opus 5.5 (Best) and with Claude Haiku 5.5 (Fast and cheap), and one
English message is read into Uyghur with Haiku. It prints the versions with their meanings, how long Claude took
(until the first words showed and in total), and what each request cost. The key itself is never printed.

    .venv\\Scripts\\python.exe tools\\check_live.py [--wait MINUTES]

--wait: first wait (up to that many minutes) until a key is saved in Terjiman's settings.
"""
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine  # noqa: E402

# US$ per million tokens: input, output, cache read (cache writes cost 1.25 x input)
PRICES = {"best": (4.00, 20.00, 0.20), "fast": (0.10, 0.50, 0.01)}
MESSAGE = "ياخشىمۇسىز! توي فىلىمىڭىز تەييار بولدى. ئەتە ئەۋەتىپ بېرىمەن، كۆرۈپ باقسىڭىز بولىدۇ."
RECEIVED = "Hi! Thank you so much, we can't wait to see it. Could you also send us the raw photos?"
CYRILLIC = re.compile("[Ѐ-ӿ]")


def saved_key() -> str:
    import keyring
    return keyring.get_password("Terjiman", "claude-api-key") or ""


def cost(quality: str, usage) -> float:
    price_in, price_out, price_cached = PRICES[quality]
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (usage.input_tokens * price_in + written * price_in * 1.25 + read * price_cached
            + usage.output_tokens * price_out) / 1e6


def tokens(usage) -> str:
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cached = f" (+{written} written to / {read} read from the cache)" if written or read else ""
    return f"{usage.input_tokens} in{cached} / {usage.output_tokens} out tokens"


def mixed_letters(text: str) -> str:
    return "  <- Cyrillic letters in Uyghur!" if CYRILLIC.search(text) else ""


def main() -> int:
    if "--wait" in sys.argv:
        minutes = float(sys.argv[sys.argv.index("--wait") + 1])
        end = time.time() + minutes * 60
        while not saved_key():
            if time.time() > end:
                print(f"No key was saved in Terjiman within {minutes:.0f} minutes.")
                return 2
            time.sleep(3)
        print("A key was saved in Terjiman.")
    key = saved_key()
    if not key:
        print("No key is saved in Terjiman yet (Settings -> paste the key -> Save).")
        return 2
    try:
        engine.check_key(key)
        print("Key check: the key works.\n")
    except engine.EngineError as error:
        print(f"Key check failed: {error.kind} {error.detail}")
        return 1

    worker = engine.Engine(key)
    total_cost = 0.0
    failed = False
    for quality in ("best", "fast"):
        started = time.time()
        first = []

        def partial(result, started=started, first=first):
            if not first and result["versions"]:
                first.append(time.time() - started)

        name = engine.MODELS[quality]
        try:
            result = worker.write(MESSAGE, mine="ug", target="en", quality=quality, on_partial=partial)
        except engine.EngineError as error:
            print(f"{name}: FAILED - {error.kind} {error.detail}\n")
            failed = True
            continue
        took = time.time() - started
        usage = worker.last_usage
        price = cost(quality, usage)
        total_cost += price
        print(f"{name}  (first words after {first[0] if first else took:.1f} s, done after {took:.1f} s, "
              f"{tokens(usage)}, ${price:.4f})")
        print(f"  mode: {result['mode']}")
        for version in result["versions"]:
            print(f"  [{version['style']}] {version['text']}")
            print(f"      ✓ {version['meaning']}{mixed_letters(version['meaning'])}")
        if result["note"]:
            print(f"  note: {result['note']}{mixed_letters(result['note'])}")
        print()

    started = time.time()
    try:
        answer = worker.read(RECEIVED, mine="ug", target="en", quality="fast")
        price = cost("fast", worker.last_usage)
        total_cost += price
        print(f"Reading with {engine.MODELS['fast']} ({time.time() - started:.1f} s, ${price:.4f}):")
        print(f"  {RECEIVED}\n  -> {answer}{mixed_letters(answer)}\n")
    except engine.EngineError as error:
        print(f"Reading: FAILED - {error.kind} {error.detail}\n")
        failed = True

    print(f"Total cost of this test: ${total_cost:.4f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
