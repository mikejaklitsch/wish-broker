"""The credit guards in voice.py, with a fake ElevenLabs client: nothing here touches the network."""
import contextlib
import threading

import pytest

from wish_broker import config, voice


class FakeResp:
    headers = {"x-character-count": "5", "request-id": "req-1"}
    data = [b"mp3"]


class FakeClient:
    def __init__(self):
        self.calls = 0
        outer = self

        class Raw:
            @contextlib.contextmanager
            def convert(self, voice_id, **kw):
                outer.calls += 1
                yield FakeResp()

        class TTS:
            with_raw_response = Raw()

        self.text_to_speech = TTS()


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Voice on, dry run off, fresh ledger and cache, fake client."""
    fake = FakeClient()
    monkeypatch.setattr(config, "VOICE_FAKE", False)
    monkeypatch.setattr(config, "VOICE_DRY", False)
    monkeypatch.setattr(config, "VOICE_BUDGET", 100)
    monkeypatch.setattr(config, "VOICE_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(voice, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(voice, "_client", fake)
    return fake


def test_same_line_is_requested_once(live):
    a = voice.speak("Hello", "v1", "eleven_v4", "t")
    b = voice.speak("Hello", "v1", "eleven_v4", "t")
    assert a == b and a.exists() and live.calls == 1


def test_dry_run_sends_nothing_and_logs(live, monkeypatch):
    monkeypatch.setattr(config, "VOICE_DRY", True)
    assert voice.speak("Hello", "v1", "eleven_v4", "t") is None
    assert live.calls == 0
    assert '"mode": "dry"' in config.VOICE_LEDGER.read_text()
    assert voice.spent() == 0


def test_budget_refuses_the_request_that_would_pass_it(live):
    voice.speak("x" * 60, "v1", "eleven_v4", "t")           # real: ledger records the billed count (5)
    with pytest.raises(voice.BudgetExceeded):
        voice.speak("y" * 200, "v1", "eleven_v4", "t")
    assert live.calls == 1


def test_simultaneous_requests_for_one_line_make_one_call(live):
    threads = [threading.Thread(target=voice.speak, args=("Same line", "v1", "eleven_v4", "t")) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert live.calls == 1


def test_fake_mode_never_calls(live, monkeypatch):
    monkeypatch.setattr(config, "VOICE_FAKE", True)
    assert voice.speak("Hello", "v1", "eleven_v4", "t") is None and live.calls == 0
