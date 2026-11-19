"""Turns text into a Line: the words, the recording if one was generated, and its length.

Recordings live in web/public/audio/<key>.mp3, with lengths in server/audio_manifest.json, both written
by scripts/generate_audio.py. Without them the game still runs; lengths are estimated.
"""
import json
import re
from functools import lru_cache

from . import config
from .schemas import Line

_TAG = re.compile(r"\[[^\]]*\]")


def spoken_text(text: str) -> str:
    """Text without audio tags like [sighs], for display."""
    return " ".join(_TAG.sub("", text).split())


@lru_cache(maxsize=1)
def _manifest() -> dict[str, float]:
    p = config.AUDIO_MANIFEST
    return json.loads(p.read_text()) if p.exists() else {}


def line(text: str, key: str) -> Line:
    shown = spoken_text(text)
    seconds = _manifest().get(key)
    if seconds is not None:
        return Line(text=shown, audio=f"/audio/{key}.mp3", seconds=seconds)
    return Line(text=shown, audio=None, seconds=round(0.4 + len(shown) / config.CHARS_PER_SECOND, 1))


# Audio keys, so the generator and the server agree on file names.
def genie_key(line_id: str) -> str:
    return f"genie/{line_id}"
