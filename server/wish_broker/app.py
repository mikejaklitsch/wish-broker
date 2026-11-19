"""HTTP layer. Thin: each route validates, calls one module, returns its result."""
import logging

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

from . import agents, clients, config, economy, grant, scoring
from .lines import genie_key, line
from .schemas import CallCard, GameConfig, GenieStart, GrantRequest, GrantResult, KeepAlive, Scorecard, ScoreResult, SignedUrl

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")


def _check_code(x_access_code: str = Header("")):
    """The hosted game sets WB_ACCESS_CODE; the page sends the code from its link (?code=...)."""
    if config.ACCESS_CODE and x_access_code.strip().lower() != config.ACCESS_CODE.lower():
        raise HTTPException(401, "Access code needed")


app = FastAPI(title="Wish Broker")
api = APIRouter(prefix="/api", dependencies=[Depends(_check_code)])


@api.get("/config", response_model=GameConfig)
def get_config():
    return GameConfig(win_karma=config.WIN_KARMA, start_karma=config.START_KARMA,
                      wish_seconds=config.WISH_SECONDS, call_seconds=config.CALL_SECONDS, timeout_penalty=config.TIMEOUT_PENALTY,
                      genie_refused=line(config.REFUSAL_LINE, genie_key("refused")),
                      genie_rubs=[line(t, genie_key(f"rub_{i}")) for i, t in enumerate(config.RUB_LINES, 1)],
                      llm_fake=config.LLM_FAKE, voice_fake=config.VOICE_FAKE,
                      keep_alive_minutes=config.KEEP_ALIVE_MINUTES)


@api.get("/clients", response_model=list[CallCard])
def list_clients():
    """The hand-made clients, each with their call agent (scripts/sync_agents.py)."""
    synced = agents.saved_ids()["clients"]
    return [agents.card(agents.spec_from_file(c), synced[c.id]) for c in clients.all_clients().values() if c.id in synced]


@api.post("/clients/generate", response_model=CallCard)
def generate_client():
    """A brand-new client, written by the writer agent, with their own call agent."""
    if config.VOICE_FAKE:
        raise HTTPException(503, "Live clients need ELEVENLABS_API_KEY")
    return agents.new_client()


@api.post("/clients/keep-alive")
def keep_alive(req: KeepAlive):
    """An open game's generated clients, so the hourly cleanup doesn't delete them."""
    if not config.VOICE_FAKE:
        agents.keep_alive(req.agent_ids)
    return {"ok": True}


@api.get("/agent/{agent_id}/signed-url", response_model=SignedUrl)
def agent_signed_url(agent_id: str):
    """A one-time link for the browser to start a call with this agent."""
    if config.VOICE_FAKE:
        raise HTTPException(503, "Live calls need ELEVENLABS_API_KEY")
    return SignedUrl(signed_url=agents.signed_url(agent_id))


@api.post("/genie", response_model=GenieStart)
def start_genie(req: GrantRequest):
    """The live genie for this wish; client_id is the client's agent id."""
    if config.VOICE_FAKE:
        raise HTTPException(503, "The live genie needs ELEVENLABS_API_KEY")
    return grant.start(req)


@api.post("/grant", response_model=GrantResult)
def do_grant(req: GrantRequest):
    """client_id is the client's agent id, or a hand-made client's id."""
    return grant.run(req, _spec(req.client_id))


@api.post("/score", response_model=ScoreResult)
def score(card: Scorecard):
    """Stars and pay for the client's review, from their callback."""
    s = scoring.stars(card)
    return ScoreResult(stars=s, bill=economy.bill(s))


def _spec(client_id: str):
    for cid, agent_id in agents.saved_ids()["clients"].items():
        if client_id in (cid, agent_id) and cid in clients.all_clients():
            return agents.spec_from_file(clients.get(cid))
    if config.VOICE_FAKE or not client_id.startswith("agent_"):
        raise HTTPException(404, f"Unknown client {client_id!r}")
    return agents.load_spec(client_id)


app.include_router(api)


# Serve the built frontend when it exists (npm run build). In development Vite serves it instead.
# On Vercel this mount is moved to the CDN at build time; the API routes above still win.
_dist = config.ROOT / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
