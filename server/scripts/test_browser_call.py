"""Browser test of a live call: real Chromium, a fake microphone playing a recorded broker, the real page.

Needs the game running (./dev.sh). Then:
  python scripts/test_browser_call.py "Danny Kowalski"
  python scripts/test_browser_call.py "Danny Kowalski" --say "Where are you proposing, and does she like surprises?"
  python scripts/test_browser_call.py "Kim" --wish "I wish Theo asks Kim out tonight"     # then the wish and the callback

Answers the phone, lets the broker's line play into the call once the client has opened, waits for the client to answer it,
then prints the transcript and notepad and saves a screenshot. Exits non-zero if the client never opens, never answers,
or no note is filed.
"""
import argparse
import hashlib
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from wish_broker import agents, config, voice  # noqa: E402

OUT = config.ROOT / "assets" / "browser-tests"
BROKER_VOICE = "cjVigY5qzO86Huf0OWal"     # a stock voice for the broker
RATE = 16000


LEAD_S = 14      # quiet while the client opens the call


def broker_wav(text: str, silence_s: int = 40) -> Path:
    """The broker's line as a WAV, then a long silence so the client can answer before Chrome loops the file."""
    path = OUT / f"broker-{hashlib.sha256(f'{LEAD_S}:{text}'.encode()).hexdigest()[:10]}.wav"
    if not path.exists():
        pcm = b"".join(voice._elevenlabs().text_to_speech.convert(
            BROKER_VOICE, text=text, model_id="eleven_flash_v2_5", output_format=f"pcm_{RATE}"))
        OUT.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(b"\x00\x00" * RATE * LEAD_S + pcm + b"\x00\x00" * RATE * silence_s)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("--say", default="Hi! Tell me what's going on tonight, where it's happening, and what would ruin it for you.")
    ap.add_argument("--url", default="http://localhost:5173")
    ap.add_argument("--seconds", type=int, default=60, help="how long to stay on the call")
    ap.add_argument("--wish", help="after the call, make this wish and take the client's callback")
    a = ap.parse_args()
    wav = broker_wav(a.say)

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                          f"--use-file-for-fake-audio-capture={wav}", "--autoplay-policy=no-user-gesture-required"])
        page = browser.new_context(permissions=["microphone"], viewport={"width": 1376, "height": 768}).new_page()
        errors = []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        varied = []      # the notes the call sent the client about pet words they've worn out
        page.on("console", lambda m: m.text.startswith("[varied]") and varied.append(m.text))
        page.goto(a.url)
        page.get_by_role("button", name="Open for business").click()
        page.get_by_role("button", name="Turn on the light").click()
        page.get_by_role("button", name="Tonight's clients").click()
        page.get_by_role("button", name=a.client).click()
        page.get_by_role("button", name="Answer the phone").click(timeout=30_000)     # rings once the client is ready
        ok = True
        try:
            page.locator(".call-log .line.client").first.wait_for(timeout=20_000)
            print("Connected: the client spoke")
        except Exception:
            print("FAIL: the client never spoke"); ok = False
        if ok:
            try:      # the client's answer to the broker's line, then until they stop talking
                page.locator(".call-log .line.client").nth(1).wait_for(timeout=a.seconds * 1000)
                page.wait_for_function("() => !/talking/i.test(document.querySelector('.call-head .clock')?.textContent || '')",
                                       timeout=30_000)
                page.wait_for_timeout(1500)
            except Exception:
                print("FAIL: the client never answered the broker"); ok = False
            if not page.locator(".pad .ask, .facts li.known").count():
                print("FAIL: no notepad line filled in"); ok = False
        OUT.mkdir(parents=True, exist_ok=True)
        shot = OUT / "call.png"
        page.screenshot(path=str(shot))
        print("\n=== Transcript ===")
        for line in page.locator(".call-log .line").all_inner_texts():
            print(" ", line)
        print("\n=== Notepad ===")
        for li in page.locator(".pad .ask, .facts li").all_inner_texts():
            print(" ", " ".join(li.split()))
        print("\nStatus:", page.locator(".call-head .clock").inner_text())
        for v in varied:
            print(" ", v)
        if page.get_by_role("button", name="Hang up").count():
            page.get_by_role("button", name="Hang up").click()
        if ok and a.wish:
            ok = wish_and_callback(page, a.wish, a.client)
        if errors:
            print("\nConsole errors:", *errors[:5], sep="\n  ")
        print(f"\nScreenshot: {shot}")
        browser.close()
    sys.exit(0 if ok else 1)


def wish_and_callback(page, wish: str, client: str) -> bool:
    """Start the clock, rub the lamp, seal the wish, dismiss the genie, answer the callback, read the review."""
    page.get_by_role("button", name="Put the phone down").click(timeout=5000) if page.get_by_role("button", name="Put the phone down").count() else None
    page.get_by_role("button", name="Start the clock").click(timeout=10_000)
    page.get_by_role("button", name="Rub the lamp").click(timeout=10_000)
    page.get_by_placeholder("I wish…").fill(wish)
    genie = []      # the browser's own log of the genie: when he filed the grant, spoke, and had been heard in full
    page.on("console", lambda m: m.text.startswith("[genie]") and genie.append(m.text))
    page.get_by_role("button", name="Seal the wish").click()
    page.locator(".contract p.genie").wait_for(timeout=120_000)
    print("\n=== Genie ===\n ", page.locator(".contract p.genie").inner_text())
    for _ in range(200):      # let him finish before the phone is answered, so his voice isn't mixed up with the callback
        if any("heard in full" in g for g in genie):
            break
        page.wait_for_timeout(300)
    for g in genie:
        print(" ", g)
    done = page.get_by_role("button", name="Done")
    if not done.count():
        print("Refused: back to before the wish"); return True
    if not any("heard in full" in g for g in genie):
        print("FAIL: the genie's session didn't end with him heard in full")
    done.click()
    modes = []      # the browser's own log of the callback: when the client started and stopped, and how much audio came
    page.on("console", lambda m: m.text.startswith("[callback]") and modes.append(m.text))
    page.get_by_role("button", name="Answer the phone").click(timeout=60_000)     # rings once the client is ready
    seen, end = [], time.time() + 150      # the call log closes when the review opens, so keep what it showed
    while time.time() < end and not page.locator(".review-text").count():
        seen = page.locator(".call-log .line").all_inner_texts() or seen
        page.wait_for_timeout(300)
    print("\n=== Callback (what the player saw) ===")
    for line in seen:
        print(" ", line)
    ok = heard_in_full(modes)
    check_callback_transcript(client)
    if not page.locator(".review-text").count():
        print("FAIL: no review after the callback")
        return False
    print("\n=== Review ===\n ", page.locator(".review .stars").get_attribute("aria-label"))
    print(" ", page.locator(".review-text").inner_text())
    for li in page.locator(".review .score li").all_inner_texts() + page.locator(".review .ledger tr").all_inner_texts():
        print(" ", " ".join(li.split()))
    page.screenshot(path=str(OUT / "review.png"))
    return ok


def heard_in_full(modes: list[str]) -> bool:
    """The client's own hang-up mustn't cut them off: the browser has to play for as long as the audio it was sent."""
    import re
    for m in modes:
        print(" ", m)
    t = [(m.split()[1], float(re.search(r"audio=([\d.]+)s", m)[1]), float(re.search(r"t=([\d.]+)s", m)[1])) for m in modes]
    start = next((x[2] for x in t if x[0] == "speaking"), None)
    if start is None or t[-1][0] != "disconnected":
        print("FAIL: the client never spoke, or never hung up"); return False
    played, audio = t[-1][2] - start, t[-1][1]
    print(f"  played {played:.1f}s of {audio:.1f}s of audio: {'heard in full' if played >= audio - 0.3 else 'CUT OFF'}")
    return played >= audio - 0.3


def check_callback_transcript(client: str):
    """The server's record of the callback. Its interrupted flag is its own guess at playback and runs behind the browser,
    so it says interrupted even when everything was heard; heard_in_full is the real check."""
    ids = agents.saved_ids()["clients"]
    key = next((k for k in ids if client.lower().startswith(k)), None)
    if not key:
        print("(no saved agent for this client; skipping the transcript check)")
        return True
    for _ in range(20):
        c = agents._http("GET", "/conversations", params={"agent_id": ids[key], "page_size": 1})["conversations"][0]
        d = agents._http("GET", f"/conversations/{c['conversation_id']}")
        if d.get("status") == "done":
            break
        time.sleep(3)
    said = [t for t in d["transcript"] if t["role"] == "agent" and t.get("message")]
    tools = [x.get("tool_name") for t in d["transcript"] for x in t.get("tool_calls") or []]
    cut = any(t.get("interrupted") for t in said)
    print(f"\n=== Server record {c['conversation_id']} ===\n  {(d.get('metadata') or {}).get('call_duration_secs')}s | tools {tools} | "
          f"{len(said)} spoken turn(s) | server flag interrupted={cut}")
    for t in said:
        print("  ends:", t["message"][-100:].replace("\n", " "))


if __name__ == "__main__":
    main()
