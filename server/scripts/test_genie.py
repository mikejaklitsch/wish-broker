"""Test the live genie: the genie node of a client's agent grants a wish.

  python scripts/test_genie.py danny "I wish Danny's proposal to Rachel tonight goes perfectly"
  python scripts/test_genie.py kim "I wish Theo asks Kim out tonight" --repeat 3
  python scripts/test_genie.py vinny "I wish for more money" --voice      with audio, to time his first words

Prints each grant in order: the grant tool call, then what the genie says. A clean grant is the tool, then the outcome,
with nothing said before the tool.
"""
import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wish_broker import agents, grant  # noqa: E402
from wish_broker.schemas import GrantRequest  # noqa: E402


async def genie(agent_id: str, wish: str, used: list[str], voice: bool) -> tuple[list[str], list[str]]:
    start = grant.start(GrantRequest(client_id=agent_id, wish=wish, used_phrases=used))
    events, phrases, t0, audio, granted, said = [], [], time.monotonic(), 0, None, False
    written = heard = 0      # characters he has written, and characters whose audio has arrived
    events.append(f"       pick {start.variables['pick']} | tags {start.variables['tags']}")
    async with websockets.connect(start.signed_url) as ws:
        init = {"type": "conversation_initiation_client_data", "starting_workflow_node_id": agents.GENIE_NODE,
                "dynamic_variables": start.variables,
                "conversation_config_override": {"agent": {"first_message": ""}}}     # the client's opening is for the call only
        if not voice:
            init["conversation_config_override"]["conversation"] = {"text_only": True}
        await ws.send(json.dumps(init))
        try:
            # He hangs up himself (end_call) once he's told the outcome. Leave early only when he's refused.
            while granted is not False:
                m = json.loads(await asyncio.wait_for(ws.recv(), 40))
                t = m.get("type")
                if t == "ping":
                    await ws.send(json.dumps({"type": "pong", "event_id": m["ping_event"]["event_id"]}))
                elif t == "audio":
                    if not audio:
                        events.append(f"{time.monotonic() - t0:5.1f}s (first audio{'' if granted else ' BEFORE THE GRANT'})")
                    audio += len(base64.b64decode(m["audio_event"]["audio_base_64"]))
                    heard += len((m["audio_event"].get("alignment") or {}).get("chars") or [])
                elif t == "agent_response":
                    text = m["agent_response_event"]["agent_response"]
                    events.append(f"{time.monotonic() - t0:5.1f}s SAYS{'' if granted else ' BEFORE THE GRANT'}: " + text)
                    said, written = said or bool(granted), written + len(text)
                elif t == "client_tool_call":
                    c = m["client_tool_call"]
                    p = c["parameters"]
                    phrases, granted, audio = p.get("phrases") or [], bool(p.get("is_wish")), 0
                    events.append(f"{time.monotonic() - t0:5.1f}s TOOL {c['tool_name']}: is_wish={p.get('is_wish')} | twist on {p.get('twisted_phrase')!r}")
                    events += [f"         open: {o}" for o in p.get("open") or ["(nothing: the wish secures everything)"]]
                    events += [f"         {'>' if i == p.get('chosen_idea') else ' '} {i}" for i in p.get("ideas") or []]
                    events.append(f"         phrases {phrases}")
                    await ws.send(json.dumps({"type": "client_tool_result", "tool_call_id": c["tool_call_id"],
                                              "result": agents.GRANT_NOTED if granted else agents.GRANT_REFUSED, "is_error": False}))
                elif t == "agent_tool_response":
                    events.append(f"{time.monotonic() - t0:5.1f}s TOOL {m['agent_tool_response'].get('tool_name')}")
        except websockets.ConnectionClosed:
            events.append(f"{time.monotonic() - t0:5.1f}s (line closed by the server)")
        except asyncio.TimeoutError:
            events.append("(the genie never hung up)" if said else "(the genie never spoke)")
        if audio:
            events.append(f"       {audio / 32000:.1f}s of audio")
    return events, phrases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client")
    ap.add_argument("wish")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--voice", action="store_true")
    a = ap.parse_args()
    agent_id = agents.saved_ids()["clients"].get(a.client, a.client)
    used = []
    for _ in range(a.repeat):
        events, phrases = asyncio.run(asyncio.wait_for(genie(agent_id, a.wish, used, a.voice), 150))
        used += phrases
        for e in events:
            print(" ", e)
        print()


if __name__ == "__main__":
    main()
