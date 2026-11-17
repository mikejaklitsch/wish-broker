"""Loads hand-authored client files, checks them, and decides what the browser may see."""
from functools import lru_cache

import yaml

from . import config
from .lines import client_key, line
from .schemas import AskResponse, ClientCard, ClientFile, Fact, FactLabel, QuestionLabel, RevealedFact


def validate(c: ClientFile) -> None:
    """Content rules every client file must follow."""
    ids = [f.id for f in c.facts]
    assert len(set(ids)) == len(ids), f"{c.id}: duplicate fact ids"
    assert [f.kind for f in c.facts].count("goal") == 1, f"{c.id}: needs exactly one goal"
    assert any(f.kind == "care" for f in c.facts), f"{c.id}: needs at least one care"
    revealed = [q.reveals for q in c.questions]
    assert sorted(revealed) == sorted(ids), f"{c.id}: each fact must be revealed by exactly one question"
    # Every question must be reachable: walk the unlocks from the questions that need nothing.
    known: set[str] = set()
    open_qs = list(c.questions)
    while True:
        ready = [q for q in open_qs if set(q.requires) <= known]
        if not ready:
            break
        known |= {q.reveals for q in ready}
        open_qs = [q for q in open_qs if q not in ready]
    assert not open_qs, f"{c.id}: questions can never be unlocked: {[q.id for q in open_qs]}"


@lru_cache(maxsize=1)
def all_clients() -> dict[str, ClientFile]:
    out = {}
    for path in sorted(config.CLIENTS_DIR.glob("*.yaml")):
        c = ClientFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        validate(c)
        if c.id in out:
            raise ValueError(f"Duplicate client id {c.id!r} in {path.name}")
        out[c.id] = c
    return out


def get(client_id: str) -> ClientFile:
    try:
        return all_clients()[client_id]
    except KeyError:
        raise KeyError(f"Unknown client {client_id!r}") from None


def card(c: ClientFile) -> ClientCard:
    return ClientCard(
        id=c.id, name=c.name, profession=c.profession, tier=c.tier,
        pay_min=min(config.PAY.values()), pay_max=max(config.PAY.values()),
        opening=line(c.opening_line, client_key(c.id, "opening")),
        goodbye=line(c.goodbye_line, client_key(c.id, "goodbye")),
        facts=[FactLabel(id=f.id, label=f.label, requires=next(q.requires for q in c.questions if q.reveals == f.id)) for f in c.facts],
        questions=[QuestionLabel(id=q.id, text=q.text, requires=q.requires) for q in c.questions],
    )


def fact(c: ClientFile, fact_id: str) -> Fact:
    for f in c.facts:
        if f.id == fact_id:
            return f
    raise KeyError(f"Client {c.id!r} has no fact {fact_id!r}")


def ask(c: ClientFile, question_id: str) -> AskResponse:
    q = next((q for q in c.questions if q.id == question_id), None)
    if q is None:
        raise KeyError(f"Client {c.id!r} has no question {question_id!r}")
    f = fact(c, q.reveals)
    return AskResponse(answer=line(q.answer, client_key(c.id, f"q_{q.id}")), revealed=[RevealedFact(id=f.id, value=f.value)])


def refused_review(c: ClientFile):
    return line(c.refused_review, client_key(c.id, "refused_review"))


def facts_text(c: ClientFile, kinds: tuple[str, ...] = ("goal", "care", "detail")) -> str:
    """Facts as a bullet list for prompts."""
    lines = [f"- [{f.id}] ({f.kind.replace('_', ' ')}) {f.value}" for f in c.facts if f.kind in kinds]
    return "\n".join(lines) or "- (none)"
