"""Stars come from how the client took the result, through a fixed table. Pure function."""
from .schemas import Scorecard

# Did they get what they were after, and how do they feel about everything else?
STARS = {
    "yes":    {"happy": 5, "mixed": 4, "upset": 3},
    "partly": {"happy": 3, "mixed": 3, "upset": 2},
    "no":     {"happy": 2, "mixed": 1, "upset": 1},
}


def stars(card: Scorecard) -> int:
    return STARS[card.goal_met][card.feeling]
