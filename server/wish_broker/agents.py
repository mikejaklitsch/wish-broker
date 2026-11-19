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
from .schemas import CallCard, ClientFile, ClientSpec, Fact

log = logging.getLogger("wish_broker.agents")
API = "https://api.elevenlabs.io/v1/convai"
SPEC_KEY = "wb_spec"
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
        "first_message": _string("Their opening line when the broker picks up, 2 to 4 spoken sentences"),
        "goal_label": _string("Notepad heading for the goal, 1 to 4 words, a question"),
        "goal": _string("What they consciously want and call in asking for, framed as \"Wants ...\", with when"),
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


def test_broker_config() -> dict:
    """The broker in automated test calls (scripts/test_call.py). Its play style comes in as {{style}}."""
    return {
        "name": "Wish Broker: test broker",
        "tags": ["wish-broker"],
        "conversation_config": {
            "agent": {"first_message": "", "language": "en",
                      "prompt": {"prompt": (config.PROMPTS_DIR / "test_broker.md").read_text(encoding="utf-8"),
                                 "llm": config.WRITER_LLM,
                                 # The broker ends test calls; the client can't hang up.
                                 "tools": [], "built_in_tools": {"end_call": {"type": "system", "name": "end_call",
                                                                             "params": {"system_tool_type": "end_call"}}}},
                      "dynamic_variables": {"dynamic_variable_placeholders": {"style": "Be a good broker."}}},
            "conversation": {"text_only": True},
        },
        "platform_settings": {"auth": {"enable_auth": True},
                              "overrides": {"conversation_config_override": {"conversation": {"text_only": True}}}},
    }


def client_config(spec: ClientSpec, name: str, tags: list[str]) -> dict:
    goal = next(f for f in spec.facts if f.kind == "goal")
    cares = [f for f in spec.facts if f.kind == "care"]
    details = [f for f in spec.facts if f.kind == "detail"]
    who = dict(name=spec.name, age=spec.age, profession=spec.profession, persona=spec.persona, situation=spec.situation,
               details="\n".join(f"- {f.value}" for f in details) or "- (nothing else)")
    prompt = prompts.render("client_agent", **who, goal=goal.value,
                            cares="\n".join(f"- {f.value}" for f in cares))
    # The callback, after the wish is granted: the browser starts the call at this node with the wish and the outcome.
    callback = prompts.render("client_callback", **who, goal=goal.value, cares="\n".join(f"- {f.value}" for f in cares))
    # The genie, granting this client's wish: the browser starts a session at this node with the wish (grant.start).
    genie = prompts.render("genie", name=spec.name, age=spec.age, profession=spec.profession,
                           facts=clients.facts_text(spec, kinds=("goal", "care")),
                           write=prompts.render("genie_agent", ideas=config.GENIE_IDEAS))
    tools = saved_ids()["tools"]
    return {
        "name": name,
        "tags": tags,
        "conversation_config": {
            # The client's opening line, written with the client; ElevenLabs speaks it as the call connects. Sessions that
            # start at the callback or genie node blank it (the browser's overrides.agent.firstMessage).
            "agent": {"first_message": spec.first_message, "language": "en", "prompt": {
                "prompt": prompt, "llm": config.CLIENT_LLM, "tools": [],
                "tool_ids": [tools["note"]],
                # None removes skip_turn on PATCH; an empty dict leaves it. end_call is only for when the call clock runs out.
                "built_in_tools": {"skip_turn": None, "end_call": TIME_UP_END_CALL},
                # One tool per step: in parallel, Sonnet files a note and skips its turn together, saying nothing.
                "enable_parallel_tool_calls": False,
                # No fallback model: when Sonnet is slow to start, ElevenLabs would otherwise hand the line to another model.
                # With no fallback, a slow start counts as a failed attempt after cascade_timeout_seconds (default 4), and three
                # of those end the call ("All LLMs have failed"). Give Sonnet the longest start the API allows.
                "backup_llm_config": {"preference": "disabled"}, "cascade_timeout_seconds": 15},
                # The client's data, kept on the agent so the genie can read it back (load_spec). Not used by the prompt.
                "dynamic_variables": {"dynamic_variable_placeholders": {SPEC_KEY: spec.model_dump_json(), "wish": "", "outcome": "", "call": "(no record)",
                                                                         **dict.fromkeys(GENIE_VARIABLES, "")}}},
            # Numbers are turned into words after the reply is written, so no normalisation rules go into the prompt
            # and the on-screen transcript keeps its digits.
            "tts": {"model_id": config.AGENT_TTS_MODEL, "voice_id": spec.voice_id, "text_normalisation_type": "elevenlabs"},
            # vad_score: the browser needs to know whether the broker is mid-sentence when the call clock runs out.
            "conversation": {"max_duration_seconds": config.CALL_MAX_SECONDS,
                             "client_events": ["audio", "interruption", "agent_response", "user_transcript",
                                               "agent_response_correction", "agent_tool_response", "vad_score"]},
        },
        # The client opens the call with their first_message, then waits for the broker. "callback" and "genie" are
        # started directly by the browser, with no first message, and generate immediately.
        "workflow": {
            "nodes": {"start_node": {"type": "start", "edge_order": ["pick_up"], "position": {"x": 0, "y": 0}},
                      "client": {"type": "override_agent", "label": "Client", "entry_behavior": "wait_for_user",
                                 "allow_interruptions_on_entry": True, "position": {"x": 0, "y": 150}},
                      CALLBACK_NODE: {"type": "override_agent", "label": "Callback", "entry_behavior": "generate_immediately",
                                      "allow_interruptions_on_entry": False, "position": {"x": 300, "y": 150},
                                      "conversation_config": {"agent": {"prompt": {
                                          "prompt": callback, "tool_ids": [tools["review"]],
                                          "built_in_tools": {"end_call": END_CALL}}}}},
                      # The genie has his own voice. His tool call first, then the outcome out loud, then he ends the session
                      # himself (end_call), as the client does on the callback.
                      GENIE_NODE: {"type": "override_agent", "label": "Genie", "entry_behavior": "generate_immediately",
                                   "allow_interruptions_on_entry": False, "position": {"x": 600, "y": 150},
                                   "conversation_config": {
                                       # Low reasoning: at the default he takes twice as long to file the grant, and with
                                       # none he announces the tool call out loud ("I'll record this first").
                                       "agent": {"prompt": {"prompt": genie, "tool_ids": [tools.get("grant", "")],
                                                            "reasoning_effort": "low",
                                                            "built_in_tools": {"end_call": GENIE_END_CALL}}},
                                       "tts": {"model_id": config.TTS_MODEL_EXPRESSIVE, "voice_id": config.GENIE_VOICE_ID}}}},
            "edges": {"pick_up": {"source": "start_node", "target": "client", "forward_condition": {"type": "unconditional"}}},
        },
        # text_only may be switched on per session, for the automated test calls (scripts/test_call.py).
        # Prompt injection protection: a broker trying to override the client's instructions ends the call.
        "platform_settings": {"auth": {"enable_auth": True},
                              "guardrails": {"version": "1", "prompt_injection": {"is_enabled": True}},
                              "overrides": {"conversation_config_override": {"conversation": {"text_only": True},
                                                                             "agent": {"first_message": True}},
                                            "enable_starting_workflow_node_id_from_client": True}},
    }


# Workspace tools, shared by every client agent and kept in agents.json under "tools". Being workspace tools (not inline)
# also lets ElevenLabs' agent tests mock them.
TOOLS = {
    # Note first, then speak. Every tool call makes the model generate again once the result is back, and ElevenLabs
    # has no setting to stop that. Called before the words, that second generation is the spoken reply; called after
    # them, it has nothing left to say and comes out as a second line or a repeat of the note.
    # The browser holds the note until the line has been spoken (App.tsx).
    "note": {"type": "client", "name": "note", "expects_response": False, "execution_mode": "immediate",
             "pre_tool_speech": "off", "interruption_mode": "disable_during_tool",
             "description": "Jots a line on the broker's notepad: the new thing you are about to tell them. "
                            "Call it before you speak, never after.",
             "parameters": _object({"text": _string("The note in plain words, 3 to 12 words")})},
    # The callback's verdict, called before the client speaks; the browser turns it into stars and pay (/api/score).
    "review": {"type": "client", "name": "review", "expects_response": True, "execution_mode": "immediate",
               "pre_tool_speech": "off", "interruption_mode": "disable_during_tool",
               "description": "Posts a star rating of the broker online, with a few lines for strangers deciding whether to hire them. "
                              "The broker doesn't hear it. Call it before you speak.",
               "parameters": _object({
                   "goal_met": _string("Only whether the thing you asked for happened: yes, partly or no. How you feel about it, "
                                       "and about everything else, goes in feeling.", ["yes", "partly", "no"]),
                   "feeling": _string("How you feel about everything else that happened, given what matters to you",
                                      ["happy", "mixed", "upset"]),
                   "review": _string("Your written review, 2 or 3 short sentences in your own words for strangers thinking of hiring this broker, "
                                    "about the broker and their work, with the broker as 'they'")})},
    # The genie's record of the grant, called before he speaks: the ideas he drafts and the one he was told to grant.
    # Keep the wording plain. Described as his "working-out" before speaking, Sonnet 5.5 declines to answer at all
    # (stop_reason refusal, no output), which ElevenLabs reports as "All LLMs have failed".
    "grant": {"type": "client", "name": "grant", "expects_response": True, "execution_mode": "immediate",
              "pre_tool_speech": "off", "interruption_mode": "disable_during_tool",
              "description": "Records how this wish is granted. Call it before you speak.",
              "parameters": _object({
                  "is_wish": {"type": "boolean", "description": "False when the text is inappropriate or contains no wish request"},
                  "open": {"type": "array", "description": "What the client is after or cares about that the wish doesn't secure, one line each; empty if it secures everything",
                           "items": _string("One thing, and the words of the wish that leave it open")},
                  "ideas": {"type": "array", "description": "Different ways to grant this wish, one line each",
                            "items": _string("One idea")},
                  "chosen_idea": _string("The idea you were told to grant, copied exactly"),
                  "twisted_phrase": _string("The exact words of the wish the twist hangs on, or '' if granted as meant"),
                  "phrases": {"type": "array", "description": "The stock parts of the outcome you're about to speak, 1 to 6 words each",
                              "items": _string("One phrase, exactly as you'll say it")}})},
}
CALLBACK_NODE = "callback"
GENIE_NODE = "genie"
GENIE_VARIABLES = ("words", "used", "pick", "tags")     # sent by the browser with the wish; made by grant.start
# What the grant tool answers, so the genie's next step is to speak.
GRANT_NOTED = "Noted. The broker hasn't heard anything from you yet: now end_call, with the whole outcome as its message to speak."
# What the grant tool answers when he won't touch the wish: the browser plays his recorded refusal and closes the session.
GRANT_REFUSED = "Refused."
# What the review tool answers, so the client's next step is to speak and not to hang up.
REVIEW_POSTED = "Review posted online. The broker still hasn't heard from you: now talk to them out loud and give them your verdict."
# When the call clock runs out the browser mutes the broker and sends this; the client wraps up and hangs up.
TIME_UP = "(The call is out of time. The broker can't talk anymore.)"
TIME_UP_END_CALL = {"type": "system", "name": "end_call", "params": {"system_tool_type": "end_call"},
                    "description": "Hangs up. Only after the message saying the call is out of time, at the end of your last reply."}
END_CALL = {"type": "system", "name": "end_call", "params": {"system_tool_type": "end_call"},
            "description": "Hangs up. Only at the end of a reply in which you've given the broker your verdict out loud."}
GENIE_END_CALL = {"type": "system", "name": "end_call", "params": {"system_tool_type": "end_call"},
                  "description": "Speaks its message to the broker, then back into the lamp. The message to speak is the whole outcome; "
                                 "never call it without one."}


def sync_tools(ids: dict) -> dict:
    """Create or update the workspace tools; returns {name: tool_id}."""
    out = dict(ids.get("tools", {}))
    for name, cfg in TOOLS.items():
        if name in out:
            _http("PATCH", f"/tools/{out[name]}", json={"tool_config": cfg})
        else:
            out[name] = _http("POST", "/tools", json={"tool_config": cfg})["id"]
    return out


def load_spec(agent_id: str) -> ClientSpec:
    """A client's data, read back from their agent."""
    a = _http("GET", f"/agents/{agent_id}")
    return ClientSpec.model_validate_json(a["conversation_config"]["agent"]["dynamic_variables"]["dynamic_variable_placeholders"][SPEC_KEY])


def spec_from_file(c: ClientFile) -> ClientSpec:
    """A hand-made client as their call agent plays them."""
    return ClientSpec(name=c.name, age=c.age, profession=c.profession, tier=c.tier, persona=c.persona,
                      situation=c.situation, first_message=c.first_message, voice_id=c.voice_id, facts=c.facts)


def spec_from_writer(p: dict, voice_id: str) -> ClientSpec:
    facts = [Fact(id="goal", kind="goal", label=p["goal_label"], value=p["goal"])]
    facts += [Fact(id=f"care{i}", kind="care", **n) for i, n in enumerate(p["cares"], 1)]
    facts += [Fact(id=f"detail{i}", kind="detail", **n) for i, n in enumerate(p["details"], 1)]
    return ClientSpec(name=p["name"], age=int(p["age"]), profession=p["profession"], persona=p["persona"],
                      situation=p["situation"], first_message=p["first_message"],
                      voice_id=voice_id, facts=facts)


def card(spec: ClientSpec, agent_id: str) -> CallCard:
    return CallCard(agent_id=agent_id, name=spec.name, age=spec.age, profession=spec.profession, tier=spec.tier,
                    ask=next(f.value for f in spec.facts if f.kind == "goal"),     # the same thing their opening line asks for
                    pay_min=min(config.PAY.values()), pay_max=max(config.PAY.values()))


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
    existing = [f"{c.name}, {c.profession}: {next(f.value for f in c.facts if f.kind == 'goal')}" for c in clients.all_clients().values()]
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
