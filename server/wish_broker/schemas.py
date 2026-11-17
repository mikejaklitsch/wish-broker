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
    """One line on the notepad, filled in when its question is asked.
    goal: what the client is really after. care: something they'd be happy or upset about.
    detail: true but irrelevant. The goal and cares decide how the client feels about the result."""
    id: str
    kind: FactKind
    label: str = Field(description="Shown next to the '?' before it is revealed, e.g. 'Who is the cake for?'")
    value: str = Field(description="What gets written in once revealed")


class Question(BaseModel):
    """A scripted question the broker can ask, with the client's recorded answer."""
    id: str
    text: str = Field(description="What the broker asks")
    answer: str = Field(description="What the client says back (may include audio tags like [sighs])")
    reveals: str = Field(description="The fact this answer puts on the notepad. Every answer reveals one; only the goal and cares affect the score")
    requires: list[str] = Field(default_factory=list, description="Fact ids that must be on the notepad before this question can be asked")


class ClientFile(BaseModel):
    """Hand-authored client. Server-only: holds the secrets."""
    id: str
    name: str
    age: int
    profession: str
    tier: Tier
    persona: str = Field(description="How they talk; used to write lines and design the voice")
    voice_description: str = Field(description="Prompt for Voice Design")
    opening_line: str
    goodbye_line: str = Field(description="Said when the call timer runs out")
    facts: list[Fact]
    questions: list[Question]
    refused_review: str = Field(description="Their review when the genie refuses to grant anything")
    voice_id: str = ""


class Line(BaseModel):
    """Something said out loud: the text, its recording if generated, and how long it takes."""
    text: str
    audio: Optional[str] = Field(description="URL of the recording, or null when not generated yet")
    seconds: float


class FactLabel(BaseModel):
    id: str
    label: str
    requires: list[str] = Field(description="Same gate as the question that reveals it; the line stays off the notepad until then")


class QuestionLabel(BaseModel):
    id: str
    text: str
    requires: list[str]


class ClientCard(BaseModel):
    """What the browser may see about a client before the call: name, job and pay only. Everything else comes from the call."""
    id: str
    name: str
    profession: str
    tier: Tier
    pay_min: int
    pay_max: int
    opening: Line
    goodbye: Line
    facts: list[FactLabel]
    questions: list[QuestionLabel]


class GameConfig(BaseModel):
    """Rules the browser needs. Served by the API so numbers live only in config.py."""
    win_karma: int
    start_karma: int
    questions_per_call: int
    wish_seconds: int
    llm_fake: bool
    voice_fake: bool


# ---------------------------------------------------------------- the call
class AskRequest(BaseModel):
    client_id: str
    question_id: str


class RevealedFact(BaseModel):
    id: str
    value: str


class AskResponse(BaseModel):
    answer: Line
    revealed: list[RevealedFact]


# ---------------------------------------------------------------- grant
class GrantRequest(BaseModel):
    client_id: str
    wish: str


class Scorecard(BaseModel):
    """How the client took the result. Stars come from these two answers through a fixed table."""
    goal_met: GoalMet
    feeling: Feeling = Field(description="How the client feels about everything else that happened, given what they care about")
    note: str = Field(description="One plain sentence on both")


class Bill(BaseModel):
    pay: int


class GrantResult(BaseModel):
    refused: bool
    genie: Line = Field(description="What the genie says: what happened to the client, or the recorded refusal")
    scorecard: Optional[Scorecard]
    stars: int
    bill: Bill
    review: Line = Field(description="The client's review of the broker, in their voice, about what happened")


# ---------------------------------------------------------------- LLM output shapes
class GenieOutput(BaseModel):
    is_wish: bool = Field(description="False when the text is inappropriate or contains no wish request; nothing else is then used")
    ideas: list[str] = Field(description="Five different ways to grant this wish, one line each")
    chosen_idea: str = Field(description="The idea you were told to grant, copied exactly")
    twisted_phrase: str = Field(description="The exact words of the wish the twist hangs on, or '' if granted as meant")
    outcome: str
    goal_met: GoalMet
    feeling: Feeling
    note: str
    review: str


# Models exported to the frontend.
API_MODELS = [
    GameConfig, ClientCard, Line, FactLabel, QuestionLabel, AskRequest, AskResponse, RevealedFact,
    GrantRequest, GrantResult, Scorecard, Bill,
]
