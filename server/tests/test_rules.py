from wish_broker import config, economy, scoring
from wish_broker.schemas import Scorecard


def test_pay_scales_with_stars_and_clamps():
    assert economy.pay(5) == 40
    assert economy.pay(1) == 8
    assert economy.pay(9) == config.PAY[5]


def test_bill_and_floor():
    assert economy.bill(3).pay == 24
    assert economy.apply(3, -10) == 0


def _card(goal, feeling):
    return Scorecard(goal_met=goal, feeling=feeling, note="")


def test_stars_from_reaction_table():
    assert scoring.stars(_card("yes", "happy")) == 5
    assert scoring.stars(_card("yes", "upset")) == 3       # got it, hated the cost
    assert scoring.stars(_card("partly", "mixed")) == 3
    assert scoring.stars(_card("no", "happy")) == 2
    assert scoring.stars(_card("no", "upset")) == 1
    assert scoring.stars(None) == 1
