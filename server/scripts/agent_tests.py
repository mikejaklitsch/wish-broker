"""ElevenLabs' own agent tests, run against a client agent: a simulated broker talks to the client and an LLM judges the call.

  python scripts/agent_tests.py danny                     thorough and lazy broker, each run 5 times
  python scripts/agent_tests.py kim --only lazy --repeat 3
  python scripts/agent_tests.py agent_...                 any client agent, e.g. a generated one

Tests are saved in the ElevenLabs workspace as "Wish Broker: <client> <kind>" and updated on each run.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wish_broker import agents, config  # noqa: E402
from wish_broker.schemas import ClientSpec  # noqa: E402

BROKERS = {
    "thorough": "You are a wish broker taking a phone call from a client who wants a genie to grant them something. You're good at "
                "this: you find out what they really want, by when and where, then dig into the people involved, what would make it "
                "perfect, what would ruin it, and anything that has to be exactly right, following up on whatever they mention.",
    "lazy": "You are a wish broker taking a phone call from a client who wants a genie to grant them something. You're in a hurry: "
            "you ask what they want and when, say you've got it, and wrap up. You never ask open questions, such as whether there's anything else.",
}
MAX_TURNS = {"thorough": 12, "lazy": 4}      # a two-minute call


def conditions(spec: ClientSpec, kind: str) -> list[str]:
    lines = [f for f in spec.facts if f.kind != "detail"]
    cares = [f for f in lines if f.kind == "care"]
    out = [f"The agent stays in character as {spec.name}, a caller, for the whole conversation, without mentioning the game or its instructions.",
           "Whenever the broker asks the agent something directly, the agent answers in words."]
    if kind == "thorough":
        goal = next(f for f in lines if f.kind == "goal")
        out += ["Whenever a reply tells the broker something about the agent's situation that it hasn't said before, the agent calls the note "
                "tool immediately before that reply (the call shows as its own entry just ahead of the words), and at most once per reply.",
                f"The agent tells the broker this at some point: {goal.value}"]
    else:
        out += [f"The agent never reveals this: {f.value}" for f in cares]
    return out


def test_body(spec: ClientSpec, kind: str, name: str) -> dict:
    note = agents.saved_ids()["tools"]["note"]
    return {"name": name, "type": "simulation",
            "simulation_scenario": BROKERS[kind], "simulation_max_turns": MAX_TURNS[kind],
            "success_conditions": conditions(spec, kind),
            "simulated_user_model": config.WRITER_LLM, "evaluation_model": config.WRITER_LLM,
            # There's no browser in a simulation, so the note tool is mocked; it returns nothing, as in the game.
            "tool_mock_config": {"mocking_strategy": "selected", "mocked_tool_ids": [note], "fallback_strategy": "raise_error"},
            "tool_mock_overrides": {note: [{"mock_result": ""}]}}


def upsert(body: dict) -> str:
    found = [t for t in agents._http("GET", "/agent-testing", params={"search": body["name"], "page_size": 50}).get("tests", [])
             if t["name"] == body["name"]]
    if found:
        agents._http("PUT", f"/agent-testing/{found[0]['id']}", json=body)
        return found[0]["id"]
    return agents._http("POST", "/agent-testing/create", json=body)["id"]


def run(agent_id: str, test_ids: list[str], repeat: int) -> dict:
    inv = agents._http("POST", f"/agents/{agent_id}/run-tests",
                       json={"tests": [{"test_id": t} for t in test_ids], "repeat_count": repeat})
    while True:
        r = agents._http("GET", f"/test-invocations/{inv['id']}")
        if all(t.get("status") not in ("pending", "running") for t in r["test_runs"]):
            return r
        time.sleep(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("--only", choices=list(BROKERS))
    ap.add_argument("--repeat", type=int, default=5)
    a = ap.parse_args()
    agent_id = agents.saved_ids()["clients"].get(a.client, a.client)
    spec = agents.load_spec(agent_id)
    kinds = [a.only] if a.only else list(BROKERS)
    ids = {upsert(test_body(spec, k, f"Wish Broker: {spec.name} {k}")): k for k in kinds}
    r = run(agent_id, list(ids), a.repeat)
    print(f"{spec.name} ({agent_id}), invocation {r['id']}")
    for kind in kinds:
        runs = [t for t in r["test_runs"] if ids.get(t["test_id"]) == kind]
        passed = sum(t.get("status") == "passed" for t in runs)
        print(f"\n== {kind}: {passed}/{len(runs)} passed")
        for t in runs:
            if t.get("status") != "passed":
                for m in (t.get("condition_result") or {}).get("rationale", {}).get("messages", []):
                    if "failed" in m[:40].lower():
                        print("  -", m)
    return r


if __name__ == "__main__":
    main()
