from fastapi.testclient import TestClient

from wish_broker import clients, config, grant
from wish_broker.app import app

api = TestClient(app)


def test_client_files_load_and_validate():
    assert clients.all_clients()            # validate() runs on load and raises on bad content


def test_cards_hide_answers_and_facts():
    body = str(api.get("/api/clients").json())
    for c in clients.all_clients().values():
        for f in c.facts:
            assert f.value not in body
        for q in c.questions:
            assert q.answer not in body
        assert c.refused_review not in body


def test_full_round_in_fake_mode():
    cfg = api.get("/api/config").json()
    assert cfg["llm_fake"] and cfg["voice_fake"] and cfg["questions_per_call"] > 0
    card = api.get("/api/clients").json()[0]
    assert "[" not in card["opening"]["text"]          # audio tags hidden on screen

    for q in card["questions"]:
        r = api.post("/api/ask", json={"client_id": card["id"], "question_id": q["id"]}).json()
        assert r["answer"]["text"] and r["answer"]["seconds"] > 0 and len(r["revealed"]) == 1

    g = api.post("/api/grant", json={"client_id": card["id"], "wish": "I wish Vinny would win the lottery tonight"}).json()
    assert not g["refused"] and 1 <= g["stars"] <= 5
    assert g["genie"]["text"] and g["review"]["text"]
    assert g["bill"]["pay"] == config.PAY[g["stars"]]


def test_non_wish_gets_the_fixed_refusal_and_one_star():
    g = api.post("/api/grant", json={"client_id": "vinny", "wish": "I wish Lisa's husband would die"}).json()
    assert g["refused"] and g["stars"] == 1


def test_unknown_client_or_question_is_404():
    assert api.post("/api/grant", json={"client_id": "nobody", "wish": "x"}).status_code == 404
    assert api.post("/api/ask", json={"client_id": "vinny", "question_id": "nope"}).status_code == 404


def test_unreachable_question_is_rejected():
    import pytest
    c = clients.get("vinny").model_copy(deep=True)
    c.questions[0].requires = [c.questions[1].reveals]
    c.questions[1].requires = [c.questions[0].reveals]      # a loop: neither can ever be asked
    with pytest.raises(AssertionError, match="never be unlocked"):
        clients.validate(c)


def test_blank_wish_is_refused_without_asking_the_genie(monkeypatch):
    monkeypatch.setattr(grant, "_genie", lambda *a: (_ for _ in ()).throw(AssertionError("genie called")))
    g = api.post("/api/grant", json={"client_id": "danny", "wish": "   "}).json()
    assert g["refused"] and g["stars"] == 1
