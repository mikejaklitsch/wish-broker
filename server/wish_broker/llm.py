"""The only door to the text models. Every text generation call goes through here.

Backends: the Claude API (WB_LLM=anthropic, Sonnet 5.5; the hosted game), the local Claude Code
CLI (WB_LLM=claude, free on a Claude subscription for local play), or OpenAI (WB_LLM=openai). Fake mode (no key, or WB_FAKE=1) returns canned objects from fakes.py, so the
whole game runs and tests pass with no network.
"""
import json
import logging
import subprocess
import tempfile
import time
from typing import TypeVar

from pydantic import BaseModel

from . import config, fakes

log = logging.getLogger("wish_broker.llm")
T = TypeVar("T", bound=BaseModel)

_client = None


def _openai():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.LLM_TIMEOUT_S, max_retries=config.LLM_RETRIES)
    return _client


def structured(purpose: str, model: str, system: str, messages: list[dict], schema: type[T], context: dict | None = None) -> T:
    """Ask the model for an object matching `schema`.

    purpose: short tag for logs and for picking the fake ("genie", ...).
    messages: [{"role": "user"|"assistant", "content": str}, ...]
    context: extra data the fake may use to build a plausible answer.
    """
    if config.LLM_FAKE:
        return fakes.respond(purpose, schema, context or {})
    if config.LLM_BACKEND == "claude":
        return _claude(purpose, system, messages, schema)
    if config.LLM_BACKEND == "anthropic":
        return _anthropic_call(purpose, system, messages, schema)
    start = time.perf_counter()
    resp = _openai().chat.completions.parse(
        model=model,
        messages=[{"role": "system", "content": system}, *messages],
        response_format=schema,
    )
    msg = resp.choices[0].message
    if msg.parsed is None:
        raise RuntimeError(f"{purpose}: model refused or returned no object: {msg.refusal!r}")
    u = resp.usage
    log.info("%s %s %.0fms in=%s out=%s", purpose, model, (time.perf_counter() - start) * 1000,
             getattr(u, "prompt_tokens", "?"), getattr(u, "completion_tokens", "?"))
    return msg.parsed


_anthropic_client = None


def _anthropic_call(purpose: str, system: str, messages: list[dict], schema: type[T]) -> T:
    """One Claude API call that returns a validated `schema` object.
    A safety decline is retried server-side on Anthropic's recommended fallback model."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(timeout=config.LLM_TIMEOUT_S, max_retries=config.LLM_RETRIES)
    start = time.perf_counter()
    resp = _anthropic_client.beta.messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=16000,
        system=system,
        messages=messages,
        output_format=schema,
        output_config={"effort": config.ANTHROPIC_EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        raise RuntimeError(f"{purpose}: model returned no object (stop_reason={resp.stop_reason})")
    u = resp.usage
    log.info("%s %s %.0fms in=%s out=%s", purpose, resp.model, (time.perf_counter() - start) * 1000,
             u.input_tokens, u.output_tokens)
    return resp.parsed_output


def _claude(purpose: str, system: str, messages: list[dict], schema: type[T]) -> T:
    """One headless Claude Code call with no tools, no settings and no memory, run from an empty folder."""
    prompt = "\n\n".join(m["content"] for m in messages)
    cmd = ["claude", "-p", prompt, "--model", config.CLAUDE_MODEL, "--output-format", "json",
           "--system-prompt", system, "--json-schema", json.dumps(schema.model_json_schema()),
           "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "project"]
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as cwd:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=config.LLM_TIMEOUT_S)
    try:
        d = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{purpose}: claude CLI failed: {out.stderr.strip() or out.stdout.strip()}")
    if d.get("is_error") or d.get("structured_output") is None:
        raise RuntimeError(f"{purpose}: claude CLI returned no object: {d.get('result')!r}")
    log.info("%s claude/%s %.0fms", purpose, config.CLAUDE_MODEL, (time.perf_counter() - start) * 1000)
    return schema.model_validate(d["structured_output"])

