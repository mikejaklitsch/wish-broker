"""The grant: the genie twists the wish. How the client takes it comes later, on their callback.

In the game the genie is live: the genie node of the client's agent, started by the browser (start). run is the same
grant as one model call, for fake mode and the test scripts; with WB_GENIE_VOICE=1 its outcome is also spoken.
"""
import base64
import logging
import random
from functools import lru_cache

from . import agents, clients, config, llm, prompts, voice
from .lines import genie_key, line
from .schemas import ClientSpec, GenieOutput, GenieStart, GenieTestOutput, GrantRequest, GrantResult, Line

log = logging.getLogger("wish_broker.grant")


@lru_cache(maxsize=1)
def _adjectives() -> list[str]:
    return config.ADJECTIVES.read_text(encoding="utf-8").split()


def _dice(used: list[str]) -> dict[str, str]:
    """What changes from one grant to the next: random words, which idea to grant, voice tags, and phrases not to repeat."""
    used = list(dict.fromkeys(" ".join(p.split())[:80] for p in used if p.strip()))[-config.GENIE_PHRASES_KEPT:]
    return {"words": ", ".join(random.sample(_adjectives(), config.RANDOM_WORDS_PER_GRANT)),
            "pick": str(random.randint(1, config.GENIE_IDEAS)),
            "tags": ", ".join(random.sample(config.GENIE_TAGS, config.GENIE_TAGS_OFFERED)),
            "used": ("Phrases you've already used on this broker tonight. Don't use any of them again, or anything close:\n"
                     + "\n".join(f"- {p}" for p in used)) if used else ""}


def start(req: GrantRequest) -> GenieStart:
    """The live genie: a link to the genie node of the client's agent, and what the browser passes in with the wish.
    He speaks the outcome himself, so nothing is granted here."""
    return GenieStart(signed_url=agents.signed_url(req.client_id), variables={"wish": " ".join(req.wish.split()), **_dice(req.used_phrases)})


def _genie(c, wish: str, used: list[str]) -> GenieOutput:
    d = _dice(used)
    system = prompts.render("genie", name=c.name, age=c.age, profession=c.profession,
                            facts=clients.facts_text(c, kinds=("goal", "care")),
                            write=prompts.render("genie_write", genie_tags=d["tags"]))
    earlier = d["used"] + "\n\n" if d["used"] else ""
    user = (f"The wish, exactly as written:\n\"{wish}\"\n\nThese words are random and unrelated: {d['words']}\n\n{earlier}"
            f"Write {config.GENIE_IDEAS} ideas, then grant idea number {d['pick']}.")
    return llm.structured("genie", config.MODEL_GENIE, system, [{"role": "user", "content": user}], GenieOutput,
                          context={"client": c, "wish": wish})


def run(req: GrantRequest, c: ClientSpec) -> GrantResult:
    wish = " ".join(req.wish.split())
    if wish and config.GENIE_VOICE_TEST:                     # voice check: a 1 to 5 word genie reply, spoken live
        short = llm.structured("genie_test", config.MODEL_GENIE, config.GENIE_TEST_SYSTEM,
                               [{"role": "user", "content": f"The wish: \"{wish}\""}], GenieTestOutput)
        return GrantResult(refused=False, genie=_spoken(short.line))
    g = _genie(c, wish, req.used_phrases) if wish else None       # time ran out with nothing written: no genie call
    if g is None or not g.is_wish:                           # not a wish, or not one the genie will touch: fixed refusal
        return GrantResult(refused=True, genie=line(config.REFUSAL_LINE, genie_key("refused")))
    return GrantResult(refused=False, genie=_spoken(g.outcome), phrases=g.phrases)


def _spoken(text: str) -> Line:
    """The genie's outcome as a Line, with live audio when the genie voice is on (text only otherwise)."""
    shown = line(text, "")
    audio = voice.speak_live(text, config.GENIE_VOICE_ID, config.TTS_MODEL_EXPRESSIVE, "genie/outcome")
    if not audio:     # voice off: text only; voice on but out of credits or failing: a recorded "Nice wish."
        return line(config.GENIE_FALLBACK_LINE, genie_key("nice_wish")).model_copy(update={"text": shown.text}) if config.GENIE_VOICE else shown
    return shown.model_copy(update={"audio": "data:audio/mpeg;base64," + base64.b64encode(audio).decode(),
                                    "seconds": round(len(audio) * 8 / 128_000, 2)})     # 128 kbps constant bitrate
