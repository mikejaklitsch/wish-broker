"""Pure functions for money. No I/O."""
from . import config
from .schemas import Bill


def pay(stars: int) -> int:
    return config.PAY[max(1, min(5, stars))]


def bill(stars: int) -> Bill:
    return Bill(pay=pay(stars))


def apply(karma: int, delta: int) -> int:
    """Karma floors at 0."""
    return max(0, karma + delta)
