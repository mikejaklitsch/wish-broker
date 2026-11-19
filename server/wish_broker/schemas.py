"""Single source of truth for every data shape.

The frontend's TypeScript types are generated from these (scripts/export_types.py),
so a shape is never written twice. Change it here, then regenerate.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Tier = Literal["$", "$$", "$$$"]
FactKind = Literal["goal", "care", "detail"]
GoalMet = Literal["yes", "partly", "no"]
Feeling = Literal["happy", "mixed", "upset"]


# ---------------------------------------------------------------- client files
class Fact(BaseModel):
    """Something true about a client. The goal and cares are lines on the notepad, filled in when the client says them.
    goal: what the client consciously wants. care: a requirement they haven't realized matters.
    detail: true but irrelevant. The goal and cares decide how the client feels about the result."""
    id: str
    kind: FactKind
    label: str = Field(description="A short heading for this fact, for the client file and test reports")
    value: str = Field(description="What gets written in once revealed")


class ClientFile(BaseModel):
    """Hand-authored client. Server-only: holds the secrets."""
    id: str
    name: str
    age: int
    profession: str
    tier: Tier
    persona: str = Field(description="How they talk")
    voice_description: str = Field(description="Prompt for Voice Design")
    situation: str = Field(description="Background the call agent improvises from")
    first_message: str = Field(description="Their opening line when the broker picks up")
    facts: list[Fact]
    voice_id: str = ""


class Line(BaseModel):
    """Something said out loud: the text, its recording if generated, and how long it takes."""
    text: str
    audio: Optional[str] = Field(description="URL of the recording, or null when not generated yet")
    seconds: float


# ---------------------------------------------------------------- live call agents
class ClientSpec(BaseModel):
    """A client as their call agent plays them: written by the writer agent, or built from a client file.
    Server-only: holds the secrets. Once the agent exists, its config is the only copy."""
    name: str
    age: int
    profession: str
    tier: Tier = "$"
    persona: str
    situation: str = Field(description="Background the agent improvises from")
    first_message: str = Field(default="", description="Their opening line when the broker picks up, spoken as written")
    voice_id: str
    facts: list[Fact] = Field(description="One goal, the cares, and the details")


class CallCard(BaseModel):
    """What the browser may see about a client before a live call."""
    agent_id: str
    name: str
    age: int
    profession: str
    tier: Tier
    ask: str = Field(description="What they called to ask for, for the top of the notepad")
    pay_min: int
    pay_max: int


class SignedUrl(BaseModel):
    signed_url: str


class KeepAlive(BaseModel):
    agent_ids: list[str] = Field(description="Generated clients still on an open game's list")


class GameConfig(BaseModel):
    """Rules the browser needs. Served by the API so numbers live only in config.py."""
    win_karma: int
    start_karma: int
    wish_seconds: int
    call_seconds: int
    timeout_penalty: int
    genie_refused: Line = Field(description="The genie's refusal, also said when the wish clock runs out with nothing written")
    genie_rubs: list[Line] = Field(description="The genie's lines when the lamp is rubbed; one is played at random")
    llm_fake: bool
    voice_fake: bool
    keep_alive_minutes: int = Field(description="How often to send the generated clients on the list to /clients/keep-alive")


# ---------------------------------------------------------------- grant
class GrantRequest(BaseModel):
    client_id: str
    wish: str
    used_phrases: list[str] = Field(default_factory=list, description="The genie's stock phrases from earlier outcomes this session, so he doesn't repeat himself")


class GrantResult(BaseModel):
    refused: bool = Field(description="Not a wish the genie will grant; nothing happens and the broker can wish again")
    genie: Line = Field(description="What the genie says: what happened to the client, or the recorded refusal")
    phrases: list[str] = Field(default_factory=list, description="The genie's stock phrases in this outcome; send them back as used_phrases")


class GenieStart(BaseModel):
    """What the browser needs to start the live genie on a wish."""
    signed_url: str
    variables: dict[str, str] = Field(description="Passed to the session as dynamic variables")


# ---------------------------------------------------------------- the callback
class Scorecard(BaseModel):
    """How the client took the result, from their review on the callback. Stars come from these two answers through a fixed table."""
    goal_met: GoalMet
    feeling: Feeling = Field(description="How the client feels about everything else that happened, given what they care about")


class Bill(BaseModel):
    pay: int


class ScoreResult(BaseModel):
    stars: int
    bill: Bill


# ---------------------------------------------------------------- LLM output shapes
class GenieOutput(BaseModel):
    is_wish: bool = Field(description="False when the text is inappropriate or contains no wish request; nothing else is then used")
    open: list[str] = Field(default_factory=list, description="What the client is after or cares about that the wish doesn't secure, one line each")
    ideas: list[str] = Field(description="Five different ways to grant this wish, one line each")
    chosen_idea: str = Field(description="The idea you were told to grant, copied exactly")
    twisted_phrase: str = Field(description="The exact words of the wish the twist hangs on, or '' if granted as meant")
    outcome: str
    phrases: list[str] = Field(default_factory=list, description="The stock parts of the outcome, word for word, 1 to 6 words each")


class GenieTestOutput(BaseModel):
    line: str = Field(description="The genie's reply to the wish, 1 to 5 words, optionally opening with one audio tag")


# Models exported to the frontend.
API_MODELS = [
    GameConfig, Line, GrantRequest, GrantResult, GenieStart, Scorecard, Bill, ScoreResult, CallCard, SignedUrl, KeepAlive,
]
