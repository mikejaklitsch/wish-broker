"""Live call agents on ElevenLabs: the writer that invents clients, and one call agent per client.

The writer runs as a text-only conversation from the server; its create_client tool call is the structured output.
A client's agent config is the only copy of their secrets, so the server stays stateless.
Agent ids for the writer and the hand-made clients live in agents.json, written by scripts/sync_agents.py.
"""
import json
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import httpx
import yaml

from . import clients, config, prompts, voice
from .schemas import CallCard, ClientFile, ClientSpec, Fact, NoteSlot

log = logging.getLogger("wish_broker.agents")
API = "https://api.elevenlabs.io/v1/convai"
AGE_BANDS = {"young": (20, 34), "middle-aged": (35, 60), "old": (62, 82)}     # from the voice pool's descriptions


def _http(method: str, path: str, **kw) -> dict:
    r = httpx.request(method, API + path, headers={"xi-api-key": config.ELEVENLABS_API_KEY}, timeout=30, **kw)
    if r.is_error:
        raise RuntimeError(f"ElevenLabs {method} {path}: {r.status_code} {r.text}")
    return r.json() if r.content else {}


@lru_cache(maxsize=1)
def voice_pool() -> dict[str, dict]:
    return {v["key"]: v for v in yaml.safe_load(config.VOICE_POOL.read_text(encoding="utf-8"))}


@lru_cache(maxsize=1)
def _words() -> list[str]:
    return config.ADJECTIVES.read_text(encoding="utf-8").split()


def saved_ids() -> dict:
    """{"writer": agent_id, "clients": {client_id: agent_id}}"""
    if not config.AGENTS_FILE.exists():
        return {"writer": None, "clients": {}}
    return json.loads(config.AGENTS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- agent configs (pure)
def _string(description: str, enum: list[str] | None = None) -> dict:
    return {"type": "string", "description": description, **({"enum": enum} if enum else {})}


def _object(properties: dict, description: str = "") -> dict:
    return {"type": "object", "description": description, "properties": properties, "required": list(properties)}


def writer_config() -> dict:
    note = _object({"label": _string("Notepad heading, 1 to 4 words, a question"),
                    "value": _string("One plain sentence")})
    params = _object({
        "name": _string("First and last name"),
        "age": {"type": "integer", "description": "18 to 80"},
        "profession": _string("Their job"),
        "persona": _string("How they talk, two or three sentences"),
        "situation": _string("Background paragraph the voice actor improvises from"),
        "opening_line": _string("First thing they say when the broker picks up"),
        "goal_label": _string("Notepad heading for the goal, 1 to 4 words, a question"),
        "goal": _string("What they're really after, with when and where"),
        "cares": {"type": "array", "description": "2 or 3 things a careless wish could trample", "items": note},
        "details": {"type": "array", "description": "2 or 3 true facts that don't matter", "items": note},
    }, "The new client")
    return {
        "name": "Wish Broker: client writer",
        "tags": ["wish-broker"],
        "conversation_config": {
            "agent": {"first_message": "", "language": "en", "prompt": {
                "prompt": prompts.render("writer"), "llm": config.WRITER_LLM, "temperature": 1.0,
                "tools": [{"type": "client", "name": "create_client", "description": "Save the new client",
                           "expects_response": True, "parameters": params}]}},
            "conversation": {"text_only": True},
        },
        "platform_settings": {"auth": {"enable_auth": True},
                              "overrides": {"conversation_config_override": {"conversation": {"text_only": True}}}},
    }


def client_config(spec: ClientSpec, name: str, tags: list[str]) -> dict:
    goal = next(f for f in spec.facts if f.kind == "goal")
    cares = [f for f in spec.facts if f.kind == "care"]
    details = [f for f in spec.facts if f.kind == "detail"]
    prompt = prompts.render(
        "client_agent", name=spec.name, age=spec.age, profession=spec.profession, persona=spec.persona,
        situation=spec.situation, goal=f"[{goal.id}] {goal.value}",
        cares="\n".join(f"- [{f.id}] {f.value}" for f in cares),
        details="\n".join(f"- {f.value}" for f in details) or "- (nothing else)")
    note = {"type": "client", "name": "note", "expects_response": False,
            "description": "Fill in a line on the broker's notepad, right after you've told them your goal or something you care about",
            "parameters": _object({"fact_id": _string("Which line", enum=[goal.id] + [f.id for f in cares]),
                                   "text": _string("The note in plain words, 3 to 15 words")})}
    end_call = {"type": "system", "name": "end_call", "description": "Hang up", "params": {"system_tool_type": "end_call"}}
    return {
        "name": name,
        "tags": tags,
        "conversation_config": {
            "agent": {"first_message": spec.opening_line, "language": "en", "prompt": {
                "prompt": prompt, "llm": config.CLIENT_LLM, "tools": [note, end_call]}},
            "tts": {"model_id": config.AGENT_TTS_MODEL, "voice_id": spec.voice_id},
            "conversation": {"max_duration_seconds": config.CALL_MAX_SECONDS},
        },
        "platform_settings": {"auth": {"enable_auth": True}},
    }


def spec_from_file(c: ClientFile) -> ClientSpec:
    """A hand-made client as an agent plays them. Their scripted answers become background to draw on."""
    said = "\n".join(f"- {q.answer}" for q in c.questions)
    return ClientSpec(name=c.name, age=c.age, profession=c.profession, tier=c.tier, persona=c.persona,
                      situation=f"Things you've said about it, in your own words:\n{said}",
                      opening_line=c.opening_line, voice_id=c.voice_id, facts=c.facts)


def spec_from_writer(p: dict, voice_id: str) -> ClientSpec:
    facts = [Fact(id="goal", kind="goal", label=p["goal_label"], value=p["goal"])]
    facts += [Fact(id=f"care{i}", kind="care", **n) for i, n in enumerate(p["cares"], 1)]
    facts += [Fact(id=f"detail{i}", kind="detail", **n) for i, n in enumerate(p["details"], 1)]
    return ClientSpec(name=p["name"], age=int(p["age"]), profession=p["profession"], persona=p["persona"],
                      situation=p["situation"], opening_line=p["opening_line"],
                      voice_id=voice_id, facts=facts)


def card(spec: ClientSpec, agent_id: str) -> CallCard:
    return CallCard(agent_id=agent_id, name=spec.name, age=spec.age, profession=spec.profession, tier=spec.tier,
                    pay_min=min(config.PAY.values()), pay_max=max(config.PAY.values()),
                    notes=[NoteSlot(id=f.id, label=f.label) for f in spec.facts if f.kind != "detail"])


# ---------------------------------------------------------------- ElevenLabs calls
def create(body: dict) -> str:
    return _http("POST", "/agents/create", json=body)["agent_id"]


def update(agent_id: str, body: dict) -> None:
    _http("PATCH", f"/agents/{agent_id}", json=body)


def delete(agent_id: str) -> None:
    _http("DELETE", f"/agents/{agent_id}")


def signed_url(agent_id: str) -> str:
    return voice._elevenlabs().conversational_ai.conversations.get_signed_url(agent_id=agent_id).signed_url


def write_client() -> ClientSpec:
    """One new client from the writer agent, through a text-only conversation run here on the server.
    The voice is picked first, at random, and the writer builds the person to fit it."""
    from elevenlabs.conversational_ai.conversation import ClientTools, Conversation

    writer = saved_ids().get("writer")
    if not writer:
        raise RuntimeError("No writer agent. Run scripts/sync_agents.py --apply first.")
    got: dict = {}
    done = threading.Event()

    def create_client(params: dict) -> str:
        got.update({k: v for k, v in params.items() if k != "tool_call_id"})
        done.set()
        return "Saved."

    tools = ClientTools()
    tools.register("create_client", create_client)
    conv = Conversation(voice._elevenlabs(), writer, requires_auth=True, client_tools=tools)
    existing = [f"{c.name}, {c.profession}: {c.opening_line}" for c in clients.all_clients().values()]
    words = ", ".join(random.sample(_words(), 12))
    v = random.choice(list(voice_pool().values()))
    band = next((r for word, r in AGE_BANDS.items() if word in v["about"]), (22, 75))
    request = (f"Write a new client whose voice is: {v['about']}. They are {random.randint(*band)}.\n\nClients who already exist:\n" + "\n".join(f"- {e}" for e in existing)
               + f"\n\nRandom words: {words}")
    start = time.perf_counter()
    conv.start_session()
    try:
        for _ in range(100):                     # wait for the session to open; the SDK has no callback for it
            if conv._conversation_id:
                break
            time.sleep(0.1)
        conv.send_user_message(request)
        if not done.wait(config.WRITER_TIMEOUT_S):
            raise RuntimeError("The writer agent didn't create a client in time")
        time.sleep(0.3)                          # let the tool's reply go out before closing
    finally:
        conv.end_session()
        tools.stop()
    log.info("writer %.0fms: %s", (time.perf_counter() - start) * 1000, got.get("name"))
    return spec_from_writer(got, v["id"])


def new_client() -> CallCard:
    """Write a client, give them a call agent, and return what the browser may see."""
    spec = write_client()
    agent_id = create(client_config(spec, f"Wish Broker generated: {spec.name}", ["wish-broker", config.GENERATED_TAG]))
    try:                    # clear out old clients nobody called; a failure here must not lose the new one
        prune()
    except Exception as e:
        log.warning("prune failed: %s", e)
    return card(spec, agent_id)


def keep_alive(agent_ids: list[str]) -> None:
    """Refresh the agents' last-updated time so prune() leaves them alone. An open game sends its clients every so often.
    The update itself changes nothing (auth is already on), so it is safe on any agent."""
    def touch(agent_id: str):
        _http("PATCH", f"/agents/{agent_id}", json={"platform_settings": {"auth": {"enable_auth": True}}})
    with ThreadPoolExecutor(8) as pool:      # each takes a few seconds; send them together
        list(pool.map(touch, agent_ids))


def prune() -> list[str]:
    """Delete generated client agents not touched for GENERATED_MAX_AGE_HOURS. Returns their names."""
    cutoff = time.time() - config.GENERATED_MAX_AGE_HOURS * 3600
    gone = []
    for a in _http("GET", "/agents", params={"tags": config.GENERATED_TAG, "page_size": 100})["agents"]:
        if config.GENERATED_TAG in a["tags"] and a["updated_at_unix_secs"] < cutoff:
            delete(a["agent_id"])
            gone.append(a["name"])
    return gone
