"""The grant: one genie call (the twist, how the client took it, their review), then stars and bill.

With WB_GENIE_VOICE=1 the genie's outcome is also spoken, sent back inside the result as an MP3 data URL.
"""
import base64
import logging
import random
from functools import lru_cache

from . import clients, config, economy, llm, prompts, scoring, voice
from .lines import genie_key, line
from .schemas import GenieOutput, GenieTestOutput, GrantRequest, GrantResult, Line, Scorecard

log = logging.getLogger("wish_broker.grant")


@lru_cache(maxsize=1)
def _adjectives() -> list[str]:
    return config.ADJECTIVES.read_text(encoding="utf-8").split()


def _genie(c, wish: str, used: list[str]) -> GenieOutput:
    system = prompts.render("genie", name=c.name, age=c.age, profession=c.profession, persona=c.persona,
                            facts=clients.facts_text(c, kinds=("goal", "care")),
                            genie_tags=", ".join(random.sample(config.GENIE_TAGS, config.GENIE_TAGS_OFFERED)))
    words = ", ".join(random.sample(_adjectives(), config.RANDOM_WORDS_PER_GRANT))
    pick = random.randint(1, config.GENIE_IDEAS)
    used = list(dict.fromkeys(" ".join(p.split())[:80] for p in used if p.strip()))[-config.GENIE_PHRASES_KEPT:]
    earlier = ("Phrases you've already used on this broker tonight. Don't use any of them again, or anything close:\n"
               + "\n".join(f"- {p}" for p in used) + "\n\n") if used else ""
    user = (f"The wish, exactly as written:\n\"{wish}\"\n\nThese words are random and unrelated: {words}\n\n{earlier}"
            f"Write {config.GENIE_IDEAS} ideas, then grant idea number {pick}.")
    return llm.structured("genie", config.MODEL_GENIE, system, [{"role": "user", "content": user}], GenieOutput,
                          context={"client": c, "wish": wish})


def run(req: GrantRequest) -> GrantResult:
    c = clients.get(req.client_id)
    wish = " ".join(req.wish.split())
    if wish and config.GENIE_VOICE_TEST:                     # voice check: a 1 to 5 word genie reply, spoken live
        short = llm.structured("genie_test", config.MODEL_GENIE, config.GENIE_TEST_SYSTEM,
                               [{"role": "user", "content": f"The wish: \"{wish}\""}], GenieTestOutput)
        return GrantResult(refused=False, genie=_spoken(short.line), stars=3, bill=economy.bill(3),
                           scorecard=Scorecard(goal_met="partly", feeling="mixed", note="Test wish."),
                           review=line(config.GENIE_TEST_REVIEW, ""))
    g = _genie(c, wish, req.used_phrases) if wish else None       # time ran out with nothing written: no genie call
    if g is None or not g.is_wish:                           # not a wish, or not one the genie will touch: fixed refusal
        return GrantResult(refused=True, genie=line(config.REFUSAL_LINE, genie_key("refused")), scorecard=None,
                           stars=1, bill=economy.bill(1), review=clients.refused_review(c))
    card = Scorecard(goal_met=g.goal_met, feeling=g.feeling, note=g.note)
    s = scoring.stars(card)
    return GrantResult(refused=False, genie=_spoken(g.outcome), scorecard=card,
                       stars=s, bill=economy.bill(s), review=line(g.review, ""), phrases=g.phrases)


def _spoken(text: str) -> Line:
    """The genie's outcome as a Line, with live audio when the genie voice is on (text only otherwise)."""
    shown = line(text, "")
    audio = voice.speak_live(text, config.GENIE_VOICE_ID, config.TTS_MODEL_EXPRESSIVE, "genie/outcome")
    if not audio:     # voice off: text only; voice on but out of credits or failing: a recorded "Nice wish."
        return line(config.GENIE_FALLBACK_LINE, genie_key("nice_wish")).model_copy(update={"text": shown.text}) if config.GENIE_VOICE else shown
    return shown.model_copy(update={"audio": "data:audio/mpeg;base64," + base64.b64encode(audio).decode(),
                                    "seconds": round(len(audio) * 8 / 128_000, 2)})     # 128 kbps constant bitrate
