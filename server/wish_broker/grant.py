"""The grant: one genie call (the twist, how the client took it, their review), then stars and bill.

Speech for the genie line and the review are separate requests, so no single
request runs long.
"""
import logging
import random
from functools import lru_cache

from . import clients, config, economy, llm, prompts, scoring
from .lines import genie_key, line
from .schemas import GenieOutput, GrantRequest, GrantResult, Scorecard

log = logging.getLogger("wish_broker.grant")


@lru_cache(maxsize=1)
def _adjectives() -> list[str]:
    return config.ADJECTIVES.read_text(encoding="utf-8").split()


def _genie(c, wish: str) -> GenieOutput:
    system = prompts.render("genie", name=c.name, age=c.age, profession=c.profession, persona=c.persona,
                            facts=clients.facts_text(c, kinds=("goal", "care")),
                            genie_tags=", ".join(random.sample(config.GENIE_TAGS, config.GENIE_TAGS_OFFERED)))
    words = ", ".join(random.sample(_adjectives(), config.RANDOM_WORDS_PER_GRANT))
    pick = random.randint(1, config.GENIE_IDEAS)
    user = (f"The wish, exactly as written:\n\"{wish}\"\n\nThese words are random and unrelated: {words}\n\n"
            f"Write {config.GENIE_IDEAS} ideas, then grant idea number {pick}.")
    return llm.structured("genie", config.MODEL_GENIE, system, [{"role": "user", "content": user}], GenieOutput,
                          context={"client": c, "wish": wish})


def run(req: GrantRequest) -> GrantResult:
    c = clients.get(req.client_id)
    wish = " ".join(req.wish.split())
    g = _genie(c, wish) if wish else None       # time ran out with nothing written: no genie call
    if g is None or not g.is_wish:                           # not a wish, or not one the genie will touch: fixed refusal
        return GrantResult(refused=True, genie=line(config.REFUSAL_LINE, genie_key("refused")), scorecard=None,
                           stars=1, bill=economy.bill(1), review=clients.refused_review(c))
    card = Scorecard(goal_met=g.goal_met, feeling=g.feeling, note=g.note)
    s = scoring.stars(card)
    return GrantResult(refused=False, genie=line(g.outcome, ""), scorecard=card,
                       stars=s, bill=economy.bill(s), review=line(g.review, ""))
