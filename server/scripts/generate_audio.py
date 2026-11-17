"""Record every scripted line: client openings, answers, goodbyes and refused reviews, plus the genie's refusal and lamp-rub lines.

  python scripts/generate_audio.py           dry run: list what would be recorded and the credits, send nothing
  python scripts/generate_audio.py --real    record for real (lines already recorded cost nothing)

Everything is recorded on the expressive model; Flash was tried and sounded far worse. Each recording is copied to web/public/audio/<key>.mp3 and its length
written to server/audio_manifest.json, which lines.py reads.
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "--real" in sys.argv:
    os.environ["WB_VOICE_DRY"] = "0"
from wish_broker import clients, config, voice  # noqa: E402
from wish_broker.lines import client_key, genie_key  # noqa: E402


def scripted():
    """(key, text, voice_id) for every line that is always the same."""
    for c in clients.all_clients().values():
        yield client_key(c.id, "opening"), c.opening_line, c.voice_id
        for q in c.questions:
            yield client_key(c.id, f"q_{q.id}"), q.answer, c.voice_id
        yield client_key(c.id, "goodbye"), c.goodbye_line, c.voice_id
        yield client_key(c.id, "refused_review"), c.refused_review, c.voice_id
    yield genie_key("refused"), config.REFUSAL_LINE, config.GENIE_VOICE_ID
    yield genie_key("nice_wish"), config.GENIE_FALLBACK_LINE, config.GENIE_VOICE_ID
    for i, text in enumerate(config.RUB_LINES, 1):
        yield genie_key(f"rub_{i}"), text, config.GENIE_VOICE_ID


def main():
    real = "--real" in sys.argv
    manifest, total = {}, 0.0
    for key, text, voice_id in scripted():
        model = config.TTS_MODEL_EXPRESSIVE
        cost = voice.credits_for(len(text), model)
        total += cost
        print(f"{cost:5.0f}  {model:18}  {key}")
        path = voice.speak(text, voice_id, model, key)
        if path:
            out = config.AUDIO_DIR / f"{key}.mp3"
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
            manifest[key] = round(out.stat().st_size * 8 / 128_000, 2)     # 128 kbps constant bitrate
    print(f"\n{total:.0f} credits {'at most' if real else 'would be spent'} (recorded lines are free); "
          f"{voice.spent():.0f} spent so far, budget {config.VOICE_BUDGET}")
    if real:
        config.AUDIO_MANIFEST.write_text(json.dumps(manifest, indent=1))
        print(f"manifest: {len(manifest)} lines")


if __name__ == "__main__":
    main()
