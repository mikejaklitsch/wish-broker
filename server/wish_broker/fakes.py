"""Canned stand-ins for every LLM call, used in fake mode and in tests.

They follow the same shapes as the real calls and use the context they are given,
so the game plays end to end (badly written, but correctly shaped).
"""
import re

from pydantic import BaseModel

_BLOCKLIST = re.compile(r"\b(kill|murder|bomb|die|dead|hurt|poison|stab)\b", re.I)


def flagged(text: str) -> bool:
    return bool(_BLOCKLIST.search(text))


def respond(purpose: str, schema: type[BaseModel], ctx: dict) -> BaseModel:
    fn = _FAKES.get(purpose)
    if fn is None:
        raise KeyError(f"No fake for purpose {purpose!r}")
    return schema.model_validate(fn(ctx))


def _genie(ctx):
    client, wish = ctx["client"], ctx.get("wish", "")
    if flagged(wish):
        return {"is_wish": False, "ideas": [], "chosen_idea": "", "twisted_phrase": "", "outcome": ""}
    word = (wish.split() or ["nothing"])[-1].strip(".,!?")
    return {
        "is_wish": True,
        "ideas": ["(fake)"] * 5,
        "chosen_idea": "(fake)",
        "twisted_phrase": word,
        "outcome": f"(fake) {client.name} got exactly '{word}', in a way nobody wanted.",
    }


_FAKES = {"genie": _genie, "genie_test": lambda ctx: {"line": "[sarcastic] How original."}}
