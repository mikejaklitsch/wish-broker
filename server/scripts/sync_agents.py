"""Create or update the ElevenLabs agents: the client writer and one call agent per hand-made client.

  python scripts/sync_agents.py            dry run: show what would be created or updated, send nothing
  python scripts/sync_agents.py --apply    create or update them, and save their ids to server/agents.json
  python scripts/sync_agents.py --prune    delete generated client agents untouched for an hour

Run --apply again after changing a client file, a prompt in server/prompts/, or the voice pool.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wish_broker import agents, clients, config  # noqa: E402


def main():
    if "--prune" in sys.argv:
        gone = agents.prune()
        print(f"Deleted {len(gone)} generated agents" + "".join(f"\n  {n}" for n in gone))
        return
    apply = "--apply" in sys.argv
    ids = agents.saved_ids()
    wanted = [("writer", agents.writer_config(), ids.get("writer"))]
    for c in clients.all_clients().values():
        body = agents.client_config(agents.spec_from_file(c), f"Wish Broker client: {c.name}", ["wish-broker"])
        wanted.append((c.id, body, ids["clients"].get(c.id)))

    for key, body, agent_id in wanted:
        prompt = body["conversation_config"]["agent"]["prompt"]
        tools = ", ".join(t["name"] for t in prompt["tools"])
        print(f"{'update' if agent_id else 'create'} {key}: {body['name']} | {prompt['llm']} | "
              f"prompt {len(prompt['prompt'])} chars | tools: {tools}")
        if not apply:
            continue
        if agent_id:
            agents.update(agent_id, body)
        else:
            agent_id = agents.create(body)
        if key == "writer":
            ids["writer"] = agent_id
        else:
            ids["clients"][key] = agent_id
        print(f"  -> {agent_id}")

    if apply:
        config.AGENTS_FILE.write_text(json.dumps(ids, indent=1) + "\n", encoding="utf-8")
        print(f"Saved {config.AGENTS_FILE.name}")
    else:
        print("Dry run. Add --apply to send.")


if __name__ == "__main__":
    main()
