"""HTTP layer. Thin: each route validates, calls one module, returns its result."""
import logging

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles

from . import clients, config, grant
from .lines import genie_key, line
from .schemas import AskRequest, AskResponse, ClientCard, GameConfig, GrantRequest, GrantResult

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")


def _check_code(x_access_code: str = Header("")):
    """The hosted game sets WB_ACCESS_CODE; the page sends the code from its link (?code=...)."""
    if config.ACCESS_CODE and x_access_code.strip().lower() != config.ACCESS_CODE.lower():
        raise HTTPException(401, "Access code needed")


app = FastAPI(title="Wish Broker")
api = APIRouter(prefix="/api", dependencies=[Depends(_check_code)])


def _client(client_id: str):
    try:
        return clients.get(client_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@api.get("/config", response_model=GameConfig)
def get_config():
    return GameConfig(win_karma=config.WIN_KARMA, start_karma=config.START_KARMA,
                      questions_per_call=config.QUESTIONS_PER_CALL, wish_seconds=config.WISH_SECONDS, timeout_penalty=config.TIMEOUT_PENALTY,
                      genie_refused=line(config.REFUSAL_LINE, genie_key("refused")),
                      genie_rubs=[line(t, genie_key(f"rub_{i}")) for i, t in enumerate(config.RUB_LINES, 1)],
                      llm_fake=config.LLM_FAKE, voice_fake=config.VOICE_FAKE)


@api.get("/clients", response_model=list[ClientCard])
def list_clients():
    return [clients.card(c) for c in clients.all_clients().values()]


@api.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    c = _client(req.client_id)
    try:
        return clients.ask(c, req.question_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@api.post("/grant", response_model=GrantResult)
def do_grant(req: GrantRequest):
    _client(req.client_id)
    # a blank wish (time ran out with nothing written) is refused in grant.run
    return grant.run(req)


app.include_router(api)


# Serve the built frontend when it exists (npm run build). In development Vite serves it instead.
# On Vercel this mount is moved to the CDN at build time; the API routes above still win.
_dist = config.ROOT / "web" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
