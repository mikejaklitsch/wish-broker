"""Every tunable number and setting in one place. Nothing else hard-codes these."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]          # wish-broker/
SERVER = ROOT / "server"
PROMPTS_DIR = SERVER / "prompts"
CLIENTS_DIR = SERVER / "clients"
ADJECTIVES = SERVER / "adjectives.txt"      # random words sent with each grant for variety
AUDIO_DIR = ROOT / "web" / "public" / "audio"     # generated recordings; served at /audio
AUDIO_MANIFEST = SERVER / "audio_manifest.json"    # line key -> seconds; kept with the server, since Vercel moves web/public to its CDN

load_dotenv(ROOT / ".env.local")                # ElevenLabs key, written by `elevenlabs onboard`
load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
FORCE_FAKE = os.getenv("WB_FAKE", "0").strip() == "1"
ACCESS_CODE = os.getenv("WB_ACCESS_CODE", "").strip()    # set on the hosted game; empty = no code needed
# Who writes the text: "anthropic" (the Claude API, needs ANTHROPIC_API_KEY; the hosted game),
# "claude" (the local Claude Code CLI on your subscription; local play only, free),
# or "openai" (needs OPENAI_API_KEY).
LLM_BACKEND = os.getenv("WB_LLM", "anthropic").strip()

# Fake mode per service: on when forced, or when that service has no key.
LLM_FAKE = FORCE_FAKE or {"openai": not OPENAI_API_KEY, "anthropic": not ANTHROPIC_API_KEY}.get(LLM_BACKEND, False)
VOICE_FAKE = FORCE_FAKE or not ELEVENLABS_API_KEY

# ---- ElevenLabs credit guards (see voice.py) ----
VOICE_DRY = os.getenv("WB_VOICE_DRY", "1").strip() != "0"     # on unless set to 0: log requests, send nothing
VOICE_BUDGET = int(os.getenv("WB_VOICE_BUDGET", "1000"))       # hard cap on real credits spent, from the ledger
VOICE_LEDGER = SERVER / "voice_ledger.jsonl"

# ---- Models (decide after evals) ----
MODEL_GENIE = "gpt-4.1"
CLAUDE_MODEL = "sonnet"     # used for every call when WB_LLM=claude
ANTHROPIC_MODEL = "claude-sonnet-5-5"     # used for every call when WB_LLM=anthropic
ANTHROPIC_EFFORT = "low"     # low | medium | high. Measured 2026-11-17: low 6s, medium 16s, same quality
LLM_TIMEOUT_S = 45
LLM_RETRIES = 2

# ---- Economy ----
# Karma paid by the review's stars, up to 40 per client
PAY = {1: 8, 2: 16, 3: 24, 4: 32, 5: 40}
RANDOM_WORDS_PER_GRANT = 30
# Voice tags the genie may use, a random few per grant so he doesn't fall into one pattern
GENIE_TAGS = ["[laughs]", "[mischievously]", "[sarcastic]", "[condescending]", "[booming]", "[savoring it]"]
GENIE_TAGS_OFFERED = 3
GENIE_IDEAS = 5           # the genie drafts this many ways to grant; the server picks one at random
WIN_KARMA = 100
START_KARMA = 0

# ---- Call and wish ----
QUESTIONS_PER_CALL = 3       # questions the broker may ask each client
WISH_SECONDS = 90            # time to write the wish once the kitchen timer is started
CHARS_PER_SECOND = 14        # estimate for lines that have no recording yet

# ---- Voices ----
GENIE_VOICE_ID = os.getenv("WB_GENIE_VOICE_ID", "8rzM3OwnFmoZ34no0ZL4")    # "British Genie", made in Voice Design
TTS_MODEL_EXPRESSIVE = "eleven_v4"            # genie lines and reviews
TTS_MODEL_CHEAP = "eleven_flash_v2_5"         # half the credits, but sounds far worse; unused

# ---- The genie's one recorded line: refusing something that isn't a wish ----
# Audio tags in [brackets] shape the delivery and are hidden on screen.
REFUSAL_LINE = "[sighs] That isn't a wish I'll grant. Come back when you have a proper one."
