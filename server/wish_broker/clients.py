"""Loads the hand-made client files and checks them."""
from functools import lru_cache

import yaml

from . import config
from .schemas import ClientFile


def validate(c: ClientFile) -> None:
    """Content rules every client file must follow."""
    ids = [f.id for f in c.facts]
    assert len(set(ids)) == len(ids), f"{c.id}: duplicate fact ids"
    assert [f.kind for f in c.facts].count("goal") == 1, f"{c.id}: needs exactly one goal"
    assert any(f.kind == "care" for f in c.facts), f"{c.id}: needs at least one care"


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


def facts_text(c, kinds: tuple[str, ...] = ("goal", "care", "detail")) -> str:
    """A client's facts as a bullet list for prompts."""
    lines = [f"- [{f.id}] ({f.kind.replace('_', ' ')}) {f.value}" for f in c.facts if f.kind in kinds]
    return "\n".join(lines) or "- (none)"
