"""The intake addresses: typed or spoken words in, a searchable history out. The model and the speech engine are
replaced; nothing here calls either."""
import json

import pytest
from fastapi.testclient import TestClient

from khutlisa import intake, llm, speech
from khutlisa.server import create_app
from test_claims import make_register

ANSWER = {
    "language": "Tagalog",
    "english": "I am Maria Luz Santos. My surname was Villanueva before I married. I worked at Kaiser in Daly City.",
    "given_names": ["Maria", "Luz"], "family_names": ["Santos", "Villanueva", "santos"],
    "places": [{"city": "Daly City", "region": "CA", "postcode": "94015", "country": "US", "street": "",
                "from_year": 2009, "to_year": "2018", "what": "worked"},
               {"city": "Los Angeles", "region": "CA", "postcode": "", "country": "US", "from_year": None,
                "to_year": None, "what": "lived"},
               {"city": "", "region": "", "postcode": ""}, "not a place"],
    "employers": ["KAISER FOUNDATION HOSPITALS", "WELLS FARGO BANK"], "current_country": "ph",
    "follow_up": "Ano ang postcode ninyo sa Los Angeles?", "follow_up_english": "What was your postcode in Los Angeles?",
}


@pytest.fixture
def api(tmp_path):
    db = make_register(tmp_path)
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "totals.json", web_dist=tmp_path / "no-web")) as c:
        yield c


def model_says(monkeypatch, answer=ANSWER):
    seen = []

    def ask(prompt, **kw):
        seen.append(prompt)
        return json.dumps(answer)

    monkeypatch.setattr(llm, "ask", ask)
    return seen


def test_typed_words_return_the_translation_the_history_and_the_question_in_both_languages(api, monkeypatch):
    seen = model_says(monkeypatch)
    r = api.post("/api/intake/text", json={"text": "  Ako si Maria Luz Santos.  "})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["transcript"] == "Ako si Maria Luz Santos." and out["language"] == "Tagalog"
    assert out["english"].startswith("I am Maria Luz Santos")
    assert out["follow_up"].startswith("Ano ang") and out["follow_up_english"].startswith("What was")
    history = out["history"]
    assert history["family_names"] == ["Santos", "Villanueva"]          # the repeated name is dropped
    assert history["employers"] == ["KAISER FOUNDATION HOSPITALS", "WELLS FARGO BANK"]
    assert history["current_country"] == "PH" and len(history["places"]) == 2
    assert history["places"][0]["from_year"] == 2009 and history["places"][0]["to_year"] == 2018
    assert "Ako si Maria Luz Santos." in seen[0]


def test_a_married_name_history_from_the_intake_reaches_the_search_with_every_family_name_and_employer(api, monkeypatch):
    model_says(monkeypatch)
    history = api.post("/api/intake/text", json={"text": "Ako si Maria"}).json()["history"]
    found = api.post("/api/search", json=history)
    assert found.status_code == 200, found.text
    by_id = {api.app.state.record_ids.find(m["record_id"])[1]: m for m in found.json()["matches"]}
    assert "P1" in by_id and "P4" in by_id          # one record under each family name
    assert any("which they named" in r for r in by_id["P1"]["reasons"])       # the employer was used
    assert any("which they named" in r for r in by_id["P4"]["reasons"])       # so was the bank


def test_answering_the_follow_up_sends_the_earlier_words_with_the_answer(api, monkeypatch):
    seen = model_says(monkeypatch)
    out = api.post("/api/intake/text", json={"text": "90011 po.", "earlier": "Ako si Maria Luz Santos.",
                                             "question": "Ano ang postcode ninyo sa Los Angeles?"}).json()
    assert out["transcript"] == "90011 po."
    for part in ("Ako si Maria Luz Santos.", "Ano ang postcode ninyo sa Los Angeles?", "They answered: 90011 po."):
        assert part in seen[0] and part in out["full_transcript"]


def test_audio_is_transcribed_then_understood_and_the_recording_is_not_kept(api, monkeypatch, tmp_path):
    model_says(monkeypatch)
    paths = []

    def heard(path):
        paths.append(path)
        assert path.read_bytes() == b"RIFF" + b"\x00" * 400
        return {"text": "Ako si Maria Luz Santos.", "language": "tl"}

    monkeypatch.setattr(speech, "transcribe", heard)
    r = api.post("/api/intake/audio", files={"file": ("words.webm", b"RIFF" + b"\x00" * 400, "audio/webm")},
                 data={"earlier": "", "question": ""})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["transcript"] == "Ako si Maria Luz Santos." and out["heard_language"] == "Tagalog"
    assert out["history"]["family_names"] == ["Santos", "Villanueva"] and "transcribe" in out["seconds"]
    assert not paths[0].exists()


def test_hearing_alone_returns_the_words_without_the_model_and_keeps_nothing(api, monkeypatch):
    """The spoken example shows what the recogniser heard while the sound is still playing, so the words can be
    asked for on their own. The model is not called: in the tests it refuses, and this still answers."""
    paths = []

    def heard(path):
        paths.append(path)
        return {"text": "Me llamo Marisol Elena Tolmedo Peralmonte.", "language": "es"}

    monkeypatch.setattr(speech, "transcribe", heard)
    r = api.post("/api/intake/heard", files={"file": ("marisol.m4a", b"\x00" * 500, "audio/mp4")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["transcript"] == "Me llamo Marisol Elena Tolmedo Peralmonte." and out["heard_language"] == "Spanish"
    assert out["seconds"] >= 0 and "history" not in out and not paths[0].exists()


def test_hearing_alone_says_plainly_when_this_server_cannot_transcribe(api, monkeypatch):
    r = api.post("/api/intake/heard", files={"file": ("a.m4a", b"\x00" * 500)})     # no speech engine in the tests
    assert r.status_code == 503       # the page then shows the prepared text and says it was not transcribed
    assert api.post("/api/intake/heard", files={"file": ("a.m4a", b"tiny")}).status_code == 422
    monkeypatch.setattr(speech, "transcribe", lambda path: {"text": " ", "language": "es"})
    assert api.post("/api/intake/heard", files={"file": ("a.m4a", b"\x00" * 500)}).status_code == 422


def test_intake_problems_are_said_plainly(api, monkeypatch):
    assert api.post("/api/intake/text", json={"text": "   "}).status_code == 422
    assert api.post("/api/intake/text", json={"text": "x" * 5000}).status_code == 422
    r = api.post("/api/intake/text", json={"text": "Ako si Maria"})          # no model in the tests
    assert r.status_code == 503 and "fill in the form" in r.json()["detail"]
    assert api.post("/api/intake/audio", files={"file": ("a.webm", b"tiny")}).status_code == 422
    r = api.post("/api/intake/audio", files={"file": ("a.webm", b"\x00" * 500)})   # no speech engine in the tests
    assert r.status_code == 503
    monkeypatch.setattr(speech, "transcribe", lambda path: {"text": " ", "language": "en"})
    r = api.post("/api/intake/audio", files={"file": ("a.webm", b"\x00" * 500)})
    assert r.status_code == 422 and "No words" in r.json()["detail"]
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: "this is not JSON")
    assert api.post("/api/intake/text", json={"text": "Ako si Maria"}).status_code == 502


def test_the_sample_sentence_is_tagalog_and_served(api):
    out = api.get("/api/intake/sample").json()
    assert out["language"] == "Tagalog" and out["text"] == intake.SAMPLE_TAGALOG and "Amihan" in out["text"]


def test_clean_history_drops_what_the_search_would_refuse():
    out = intake.clean_history({"given_names": "Luz", "family_names": [None, 7, "x" * 300, " De la Cruz "],
                                "places": "nowhere", "employers": [{"a": 1}], "current_country": "Philippines"})
    assert out["given_names"] == ["Luz"] and out["family_names"] == ["x" * 120, "De la Cruz"]
    assert out["places"] == [] and out["employers"] == [] and out["current_country"] == ""


def test_speech_reports_plainly_when_nothing_can_transcribe(monkeypatch, tmp_path):
    monkeypatch.undo()                                    # the real function, with no engine to find
    monkeypatch.setattr(speech, "engine", lambda: None)
    with pytest.raises(speech.SpeechUnavailable) as err:
        speech.transcribe(tmp_path / "nothing.wav")
    assert "type your history" in str(err.value)
    assert speech.language_name("tl") == "Tagalog" and speech.language_name("xx") == "xx"
