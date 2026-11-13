"""The public demonstration's recorded model answers: every demonstration input has one, the two readings of each
document agree, and a call that is not recorded is refused in plain words on a copy with no live model."""
import json

import pytest
from fastapi.testclient import TestClient

from khutlisa import documents, estates, llm, notices, payouts, public_demo, reading, recorded
from test_public_demo import app_for

REAL_ASK = llm.ask            # taken before the test fixtures replace it


@pytest.fixture
def replay_only(monkeypatch):
    """The real llm.ask with the recorded answers and no live model at all: no key and no claude program."""
    held = recorded.RecordedAnswers.load()
    monkeypatch.setattr(llm, "ask", REAL_ASK)
    monkeypatch.setattr(llm, "recorded", held)
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    monkeypatch.setattr(llm, "_ask_api", lambda *a: pytest.fail("a recorded call must not reach the model"))
    monkeypatch.setattr(llm, "gate", lambda: pytest.fail("a recorded call must not count against the budget"))
    return held


def test_every_model_call_of_the_demonstration_journeys_has_a_recorded_answer(replay_only):
    steps = recorded.journeys(replay_only.heard)
    assert len(steps) >= 50
    for label, call in steps:
        before = replay_only.missed
        out = call()
        assert replay_only.missed == before, f"no recorded answer for: {label}"
        if isinstance(out, dict) and "status" in out:
            assert out["status"] == "read", f"{label}: {out}"
    assert replay_only.used >= 56          # 8 intake, 2 estate family, 2 holder file, 22 + 22 readings


def test_the_two_recorded_readings_of_every_sample_document_agree(replay_only):
    samples = recorded._samples()
    from khutlisa import demo
    for person in demo.people():
        for doc in person["documents"]:
            got = reading.read_twice(samples / doc["file"], doc["kind"])
            assert got["status"] == "read" and got["agreement"]["status"] == "agree", (doc["file"], got.get("agreement"))
    estate = json.loads((recorded.ROOT / "src" / "khutlisa" / "demonstration_estate.json").read_text(encoding="utf-8"))
    for doc in estate["estate_documents"] + [d for h in estate["heirs"] for d in h["documents"]]:
        got = estates.read_civil_record_twice(samples / doc["file"], doc["kind"])
        assert got["status"] == "read" and got["extra_agreement"]["status"] == "agree", doc["file"]


def test_the_recorded_answers_hold_only_invented_inputs_and_no_key():
    data = json.loads(recorded.ANSWERS_FILE.read_text(encoding="utf-8"))
    text = json.dumps(data)
    assert "sk-ant" not in text and "ANTHROPIC_API_KEY" not in text
    for key, entry in data["answers"].items():
        assert len(key) == 64 and 1 <= len(entry["answers"]) <= 2
        for answer in entry["answers"]:
            llm._extract_json(answer)          # every recorded answer parses


def test_a_call_that_was_not_recorded_is_refused_in_plain_words_with_no_live_model(replay_only):
    with pytest.raises(llm.NotRecorded) as refused:
        llm.ask("A question nobody recorded.")
    assert refused.value.for_screen and "recorded in advance" in str(refused.value)
    assert documents.read_document(recorded._samples() / "mx_passport_id.png", "other")["problem"] == llm.NOT_RECORDED


def test_the_public_copy_replays_a_recorded_intake_and_refuses_other_words(tmp_path, monkeypatch):
    app = app_for(tmp_path)
    assert llm.recorded is not None and len(llm.recorded) > 0
    monkeypatch.setattr(llm, "ask", REAL_ASK)
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    monkeypatch.setattr(public_demo.shutil, "which", lambda name: None)
    from khutlisa import demo
    amihan = next(p for p in demo.people() if p["key"] == "amihan")
    with TestClient(app) as client:
        left = client.get("/api/mode").json()["model"]["calls_left_today"]
        heard = client.post("/api/intake/text", json={"text": amihan["words"]})
        assert heard.status_code == 200 and "Villareal" in heard.json()["history"]["family_names"]
        assert client.get("/api/mode").json()["model"]["calls_left_today"] == left      # not counted
        other = client.post("/api/intake/text", json={"text": "My own words, never recorded."})
        assert other.status_code == 503 and other.json()["detail"] == llm.NOT_RECORDED
        ready = client.get("/api/ready").json()["model"]
        assert ready["available"] and "recorded in advance" in ready["through"]


def test_the_public_copy_words_payments_with_the_fixed_sentences_and_keeps_metal_off(tmp_path):
    facts = {"arrived": "90.00", "difference": "10.00", "approved": "100.00"}
    said = public_demo.fixed_wording("short_deposit", facts, None)
    assert said == {"text": payouts.fixed_explanation("short_deposit", facts, None), "worded_by": "fixed sentence"}
    with TestClient(app_for(tmp_path)) as client:
        metal = client.get("/api/metal").json()
        assert metal["available"] is False and metal["problem"] == public_demo.METAL_OFF


def test_every_notice_language_is_shipped_so_the_public_copy_never_asks_the_model_for_one():
    held = notices.Translations(use_model=False)
    for code in notices.LANGUAGES:
        assert held.get(code) is not None, code


def test_the_public_copy_transcribes_each_demonstration_sound_once(tmp_path, monkeypatch):
    from khutlisa import speech
    from test_public_demo import SOUND
    made = []
    monkeypatch.setattr(speech, "transcribe", lambda path: made.append(path) or {"text": "Me llamo Marisol.", "language": "es"})
    with TestClient(app_for(tmp_path)) as client:
        for _ in range(3):
            heard = client.post("/api/intake/heard", files={"file": ("marisol_history_es.m4a", SOUND, "audio/mp4")})
            assert heard.status_code == 200 and heard.json()["transcript"] == "Me llamo Marisol."
    assert len(made) == 1
