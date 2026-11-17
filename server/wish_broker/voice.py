"""The only door to ElevenLabs. Every request goes through _guarded(), which protects the credits:

- Cache: each file is named by a hash of what was asked for. The same request is never sent twice.
- Dry run (WB_VOICE_DRY=1, the default): nothing is sent; the ledger records what would have been.
- Budget: real spending is totalled from the ledger; a request that could pass WB_VOICE_BUDGET is refused.
- One at a time per request: simultaneous identical requests wait for the first one.

The ledger (server/voice_ledger.jsonl) has one line per request: real, dry or cached.
"""
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger("wish_broker.voice")

CACHE_DIR = config.AUDIO_DIR / "cache"
SFX_DIR = config.AUDIO_DIR / "sfx"
SFX_MODEL = "eleven_text_to_sound_v3"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_ledger_guard = threading.Lock()
_client = None


class BudgetExceeded(RuntimeError):
    pass


def credits_for(chars: int, model: str) -> float:
    """Speech credits: one per character, half for Flash models."""
    return chars * (0.5 if "flash" in model else 1.0)


def spent() -> float:
    """Credits actually spent, from the ledger."""
    if not config.VOICE_LEDGER.exists():
        return 0.0
    total = 0.0
    for row in config.VOICE_LEDGER.read_text(encoding="utf-8").splitlines():
        r = json.loads(row)
        if r["mode"] == "real":
            total += r["credits"]
    return total


def _record(**row) -> None:
    row["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with _ledger_guard, config.VOICE_LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _elevenlabs():
    global _client
    if _client is None:
        from elevenlabs import ElevenLabs
        _client = ElevenLabs()          # reads ELEVENLABS_API_KEY from the environment
    return _client


def _guarded(path: Path, purpose: str, estimate: float,
             make: Callable[[], tuple[bytes, float, str | None]]) -> Path | None:
    """Return path if it exists; otherwise, unless dry or over budget, call make() -> (audio, credits, request_id)."""
    with _lock(path.name):
        if path.exists():
            _record(mode="cached", purpose=purpose, credits=0, file=path.name)
            return path
        if config.VOICE_DRY:
            _record(mode="dry", purpose=purpose, credits=estimate, file=path.name)
            return None
        if spent() + estimate > config.VOICE_BUDGET:
            raise BudgetExceeded(f"{purpose}: about {estimate:.0f} credits would pass the budget of "
                                 f"{config.VOICE_BUDGET} ({spent():.0f} spent). Raise WB_VOICE_BUDGET to allow it.")
        audio, credits, request_id = make()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        _record(mode="real", purpose=purpose, credits=credits, file=path.name, request_id=request_id)
        log.info("elevenlabs %s credits=%s", purpose, credits)
        return path


def _key(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12]


def speak(text: str, voice_id: str, model: str, purpose: str) -> Path | None:
    """Path of an MP3 for the text, or None in dry run or when voice is off.

    purpose: short tag for the ledger, e.g. "clients/gordon/q_why" or "genie/outcome".
    """
    if config.VOICE_FAKE or not voice_id:
        return None
    estimate = credits_for(len(text), model)

    def make():
        with _elevenlabs().text_to_speech.with_raw_response.convert(
                voice_id, text=text, model_id=model, output_format="mp3_44100_128") as resp:
            audio = b"".join(resp.data)
        billed = resp.headers.get("x-character-count")
        return audio, credits_for(int(billed), model) if billed else estimate, resp.headers.get("request-id")

    return _guarded(CACHE_DIR / f"{_key(model, voice_id, text)}.mp3", purpose, estimate, make)


def _used() -> int:
    return _elevenlabs().user.subscription.get().character_count


def _measured(before: int, fallback: float) -> float:
    """Credits used since `before`. The account's figure lags a few seconds, so poll for up to 30s."""
    for _ in range(15):
        now = _used()
        if now != before:
            return float(now - before)
        time.sleep(2)
    log.warning("usage didn't change within 30s; recording the estimate")
    return fallback


def sound_credits(seconds: float | None) -> float:
    """Measured 2026-11-17: 100 per sound, including a 5-second loop with its length set.
    The docs say 40 per second when the length is set, so that stays the estimate for longer sounds."""
    return 40.0 * seconds if seconds and seconds > 5 else 100.0


def sound(name: str, prompt: str, loop: bool = False, seconds: float | None = None,
          influence: float = 0.75) -> Path | None:
    """Path of a generated sound effect, or None in dry run. A changed prompt makes a new file."""
    if config.VOICE_FAKE:
        return None
    estimate = sound_credits(seconds)

    def make():
        audio = b"".join(_elevenlabs().text_to_sound_effects.convert(
            text=prompt, model_id=SFX_MODEL, loop=loop, duration_seconds=seconds, prompt_influence=influence,
            output_format="mp3_44100_128"))
        return audio, estimate, None

    return _guarded(SFX_DIR / f"{name}-{_key(SFX_MODEL, prompt, loop, seconds, influence)}.mp3",
                    f"sfx/{name}", estimate, make)


DESIGN_MODEL = "eleven_ttv_v3"
DESIGN_DIR = config.ROOT / "assets" / "voice-design"


def design(name: str, description: str, text: str, guidance: float | None = None) -> Path | None:
    """Voice Design: three candidate voices reading `text`. Saves <name>-<key>-<n>.mp3 for each,
    plus a .json with their generated_voice_ids (needed to save the chosen one). Returns the .json path.
    Charged by the length of `text`; the real cost is read from the account afterwards."""
    if config.VOICE_FAKE:
        return None
    estimate = 3.0 * len(text)        # budget check only; assumes all three previews are charged
    path = DESIGN_DIR / f"{name}-{_key(DESIGN_MODEL, description, text, guidance)}.json"

    def make():
        before = _used()
        extra = {"guidance_scale": guidance} if guidance is not None else {}
        r = _elevenlabs().text_to_voice.design(voice_description=description, text=text, model_id=DESIGN_MODEL,
                                               output_format="mp3_44100_128", **extra)
        import base64
        ids = []
        for n, p in enumerate(r.previews, 1):
            path.with_name(f"{path.stem}-{n}.mp3").write_bytes(base64.b64decode(p.audio_base_64))
            ids.append(p.generated_voice_id)
        info = {"description": description, "text": text, "model": DESIGN_MODEL, "guidance": guidance,
                "generated_voice_ids": ids}
        return json.dumps(info, indent=1).encode(), _measured(before, estimate), None

    DESIGN_DIR.mkdir(parents=True, exist_ok=True)
    return _guarded(path, f"design/{name}", estimate, make)


MUSIC_MODEL = "music_v2_5"
MUSIC_ESTIMATE = 600        # budget check only; the real cost is read from the account afterwards


def music(name: str, prompt: str, seconds: int) -> Path | None:
    """Path of a generated instrumental track, or None in dry run."""
    if config.VOICE_FAKE:
        return None

    def make():
        before = _used()
        audio = b"".join(_elevenlabs().music.compose(
            prompt=prompt, music_length_ms=seconds * 1000, model_id=MUSIC_MODEL, force_instrumental=True))
        return audio, _measured(before, MUSIC_ESTIMATE), None

    return _guarded(SFX_DIR / f"{name}-{_key(MUSIC_MODEL, prompt, seconds)}.mp3",
                    f"music/{name}", MUSIC_ESTIMATE, make)


def speak_live(text: str, voice_id: str, model: str, purpose: str) -> bytes | None:
    """MP3 bytes for a line generated on the spot (the genie's outcome), or None when voice is off, in dry run,
    when the account can't cover it, or when anything goes wrong.
    No cache or ledger: the hosted server can't keep files, so the account's own balance is the guard."""
    if config.VOICE_FAKE or not config.GENIE_VOICE or not voice_id:
        return None
    estimate = credits_for(len(text), model)
    if config.VOICE_DRY:
        log.info("elevenlabs dry %s: would spend about %.0f credits", purpose, estimate)
        return None
    try:
        sub = _elevenlabs().user.subscription.get()
        left = sub.character_limit - sub.character_count
        if left < estimate:
            log.warning("elevenlabs %s skipped: %d credits left, %.0f needed", purpose, left, estimate)
            return None
        audio = b"".join(_elevenlabs().text_to_speech.convert(
            voice_id, text=text, model_id=model, output_format="mp3_44100_128"))
        log.info("elevenlabs %s about %.0f credits, %d left before", purpose, estimate, left)
        return audio
    except Exception as e:      # a voice failure must never break the wish
        log.warning("elevenlabs %s failed: %s", purpose, e)
        return None
