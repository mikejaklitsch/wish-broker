# Wish Broker

You broker wishes between clients and a petty genie who grants exactly what was written.

## Run it

```
./dev.sh
```
Then open http://localhost:5173. Ctrl+C stops it.

Keys go in `.env` (copy `.env.example`). With no keys, or `WB_FAKE=1`, every model call returns a canned answer, so the game still plays end to end.

## Layout

| Path | What |
|---|---|
| `server/wish_broker/schemas.py` | Every data shape. Frontend types are generated from it |
| `server/wish_broker/config.py` | Every number: pay table, fee rate, win line, models |
| `server/wish_broker/llm.py`, `voice.py` | The only code that talks to OpenAI and ElevenLabs. Each has a fake mode |
| `server/wish_broker/fakes.py` | Canned answers for fake mode and tests |
| `server/prompts/` | Prompt templates |
| `server/clients/` | One YAML file per client |
| `server/wish_broker/consult.py`, `grant.py`, `review.py` | The call, the wish, the review |
| `server/wish_broker/economy.py`, `scoring.py` | Money and stars. Pure functions |
| `web/src/Desk.tsx`, `lighting.ts` | The painted desk, its clickable objects, and the light blending |
| `web/src/panels.tsx` | Phone list, call, notepad, contract, review |
| `web/src/App.tsx` | Game flow |

## Checks

```
cd server && python3 -m pytest -q        # rules and a full round in fake mode
python3 server/scripts/export_types.py   # after changing schemas.py
cd web && npx tsc --noEmit               # frontend types
```
