"""Test a client's callback: the genie grants a wish, then the client calls the broker back about it (text only).

  python scripts/test_callback.py danny "I wish Danny's proposal to Rachel tonight goes perfectly"
  python scripts/test_callback.py kim "I wish Theo asks Kim out tonight" --repeat 3

Prints the genie's outcome, then each callback in order: the review tool call, what the client says, and whether
they hung up. A clean callback is review, then speech, then the line closing.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wish_broker import agents, clients, grant  # noqa: E402
from wish_broker.schemas import GrantRequest  # noqa: E402


async def callback(agent_id: str, wish: str, outcome: str, call: str = "(no record)") -> list[str]:
    events, t0 = [], time.time()
    async with websockets.connect(agents.signed_url(agent_id)) as ws:
        await ws.send(json.dumps({"type": "conversation_initiation_client_data",
                                  "starting_workflow_node_id": agents.CALLBACK_NODE,
                                  "dynamic_variables": {"wish": wish, "outcome": outcome, "call": call},
                                  "conversation_config_override": {"conversation": {"text_only": True},
                                                                  "agent": {"first_message": ""}}}))
        try:
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 45))
                t = m.get("type")
                if t == "ping":
                    await ws.send(json.dumps({"type": "pong", "event_id": m["ping_event"]["event_id"]}))
                elif t == "agent_response":
                    events.append(f"{time.time() - t0:5.1f}s SAYS: " + m["agent_response_event"]["agent_response"])
                elif t == "client_tool_call":
                    c = m["client_tool_call"]
                    events.append(f"{time.time() - t0:5.1f}s TOOL {c['tool_name']}: {json.dumps(c['parameters'])}")
                    await ws.send(json.dumps({"type": "client_tool_result", "tool_call_id": c["tool_call_id"],
                                              "result": agents.REVIEW_POSTED, "is_error": False}))
                elif t == "agent_tool_response":
                    events.append(f"TOOL {m['agent_tool_response'].get('tool_name')}")
        except websockets.ConnectionClosed:
            events.append(f"{time.time() - t0:5.1f}s (line closed)")
        except asyncio.TimeoutError:
            events.append("(the client never hung up)")
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("wish")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    agent_id = agents.saved_ids()["clients"].get(a.client, a.client)
    spec = agents.spec_from_file(clients.get(a.client)) if a.client in clients.all_clients() else agents.load_spec(agent_id)
    g = grant.run(GrantRequest(client_id=agent_id, wish=a.wish), spec)
    print("GENIE:", g.genie.text, "\n")
    if g.refused:
        return
    for i in range(a.repeat):
        for e in asyncio.run(asyncio.wait_for(callback(agent_id, a.wish, g.genie.text), 120)):
            print(" ", e)
        print()


if __name__ == "__main__":
    main()
