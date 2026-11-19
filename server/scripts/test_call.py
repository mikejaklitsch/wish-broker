"""Automated test calls: a test broker agent phones a client agent, both in text mode on ElevenLabs.

  python scripts/test_call.py danny                  thorough broker (default)
  python scripts/test_call.py danny --style lazy     a broker who only asks what they want
  python scripts/test_call.py agent_...              any client agent, e.g. a generated one
  python scripts/test_call.py --new                  write a brand-new client first, then call them

Prints the transcript and every note the client filed, then checks
that no reply carries more than one note, and (thorough) that the pad has at least three lines.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elevenlabs.conversational_ai.conversation import ClientTools, Conversation, ConversationInitiationData  # noqa: E402

from wish_broker import agents, voice  # noqa: E402

STYLES = {
    "thorough": "Be a good broker. Find out what they really want, by when, and where. Then dig: ask about the people "
                "involved, what would make it perfect, what would ruin it, anything they'd hate to happen, and anything "
                "that has to be exactly right. Follow up on whatever they mention. About ten questions in all.",
    "lazy": "Be a lazy broker. Ask what they want and when, then say you've got it and wrap up. "
            "Ask no more than two questions, and don't dig into anything.",
}
MAX_TURNS = 30
SPEECH_CHARS_PER_S = 14      # roughly how fast the client's line plays


def call(agent_id: str, style: str) -> dict:
    el = voice._elevenlabs()
    ids = agents.saved_ids()
    log, notes = [], []
    ended = threading.Event()
    say_to_broker, say_to_client = [], []
    turn = threading.Event()

    tools = ClientTools()
    def note(p):
        notes.append(p); log.append(("NOTE", p["text"]))
    tools.register("note", note)

    speaking_until = [0.0]     # the client's line is still playing until then; replying sooner talks over them

    def client_said(text):
        log.append(("CLIENT", text)); say_to_broker.append(text)
        speaking_until[0] = time.time() + len(text) / SPEECH_CHARS_PER_S
        turn.set()

    def broker_said(text):
        log.append(("BROKER", text)); say_to_client.append(text); turn.set()

    client = Conversation(el, agent_id, requires_auth=True, client_tools=tools, callback_agent_response=client_said,
)
    broker = Conversation(el, ids["test_broker"], requires_auth=True, callback_agent_response=broker_said,
                          callback_disconnect=lambda d: (log.append(("END", "broker hung up")), ended.set(), turn.set()),
                          config=ConversationInitiationData(dynamic_variables={"style": STYLES[style]}))
    broker.start_session()
    client.start_session()
    turns = 0
    try:
        while not ended.is_set() and turns < MAX_TURNS:
            if not turn.wait(60):
                log.append(("END", "nobody spoke for 60s"))
                break
            turn.clear()
            time.sleep(0.5)                      # let a reply that comes in parts finish
            if say_to_broker:
                broker.send_user_message(" ".join(say_to_broker)); say_to_broker.clear(); turns += 1
            if say_to_client and not ended.is_set():
                time.sleep(max(0.0, speaking_until[0] - time.time()))
                if ended.is_set():
                    break
                client.send_user_message(" ".join(say_to_client)); say_to_client.clear(); turns += 1
    finally:
        for c in (client, broker):
            try:
                c.end_session()
            except Exception:
                pass
        tools.stop()
    return {"log": log, "notes": notes, "conversation_id": client._conversation_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client", nargs="?", help="hand-made client id (danny) or an agent id")
    ap.add_argument("--style", choices=list(STYLES), default="thorough")
    ap.add_argument("--new", action="store_true", help="write a new client first")
    a = ap.parse_args()
    if a.new:
        card = agents.new_client()
        agent_id = card.agent_id
        print(f"New client: {card.name}, {card.age}, {card.profession} ({agent_id})")
    else:
        agent_id = agents.saved_ids()["clients"].get(a.client, a.client)
    spec = agents.load_spec(agent_id)
    r = call(agent_id, a.style)

    print(f"\n=== {spec.name}, {a.style} broker ===")
    for who, text in r["log"]:
        print(f"{who:>7}: {text}")
    print("\n=== Notepad ===")
    for n in r["notes"]:
        print(f"  - {n['text']}")
    kinds = [who for who, _ in r["log"]]
    fails = []
    if any(a == b == "NOTE" for a, b in zip(kinds, kinds[1:])):
        fails.append("a reply carried more than one note")
    if a_style_thorough := (a.style == "thorough"):
        if len(r["notes"]) < 3:
            fails.append("a thorough broker should fill at least three lines")
    ok = not fails
    print("\nPASS: one note per reply" if ok else "\nFAIL: " + "; ".join(fails))
    print(f"Conversation {r['conversation_id']}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
