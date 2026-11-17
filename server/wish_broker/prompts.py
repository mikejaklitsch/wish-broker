"""Prompt templates live as files in server/prompts/. This is the one loader.

Templates use $name placeholders (string.Template), so braces in prompt text are safe.
"""
from functools import lru_cache
from string import Template

from . import config


@lru_cache(maxsize=None)
def _template(template: str) -> Template:
    return Template((config.PROMPTS_DIR / f"{template}.md").read_text(encoding="utf-8"))


def render(template: str, /, **values) -> str:
    """Fill a template. A missing placeholder raises, so typos fail loudly."""
    return _template(template).substitute(**{k: str(v) for k, v in values.items()})
