"""The demonstration records live apart from the register, and every search runs over both in one pass."""
import json

from fastapi.testclient import TestClient

from khutlisa import demo, packet
from khutlisa import claims as cl
from khutlisa.server import NOTABLE_PATH, create_app, mask_name, shown_as_organisation
from test_claims import AS_PAYER, PAYER_KEY
from test_totals import searchable_register

MARISOL = {"given_names": ["Marisol", "Elena"], "family_names": ["Tolmedo", "Peralmonte"],
           "places": [{"city": "Salinas", "region": "CA"}], "employers": ["Empacadora Valle Sereno"],
           "current_country": "MX"}
WITH_ADDRESS = {**MARISOL, "places": [{"city": "Salinas", "region": "CA", "postcode": "93905",
                                       "street": "618 Camino Lunamar, apartamento 3"}],
                "employers": ["Empacadora Valle Sereno", "Punta Clara Water and Light"]}
# What her answer adds that the search counts on: the postcode, beside the holder she named at the start.
WITH_POSTCODE = {**MARISOL, "places": [{"city": "Salinas", "region": "CA", "postcode": "93905"}]}


def client(tmp_path, db=None, **more):
    return TestClient(create_app(db_path=db or tmp_path / "no-register.duckdb", totals_path=tmp_path / "t.json",
                                 web_dist=tmp_path / "no-web", claims_dir=tmp_path / "claims", demonstration=True,
                                 payer_key=PAYER_KEY, **more), headers=AS_PAYER)


def test_one_search_runs_over_the_register_and_the_demonstration_records(tmp_path):
    with client(tmp_path, searchable_register(tmp_path / "registers.duckdb")) as c:
        info = c.get("/api/register").json()
        assert info == {"owner_records": 2, "records": 2, "sample": False, "loaded": True,
                        "demonstration_records": len(demo.records())}
        both = c.post("/api/search", json={"given_names": ["Odalys", "Marisol"],
                                           "family_names": ["Quillfeather", "Tolmedo"]}).json()
        assert both["searched"] == {"register_loaded": True, "owner_records": 2,
                                    "demonstration_records": len(demo.records())}
        assert {m["source"] for m in both["matches"]} == {"TEST", "DEMO"}
        # A demonstration owner is an invented person and is still masked like any private owner.
        for m in both["matches"]:
            assert m["owner"] == mask_name(m["owner"]) and "street" not in json.dumps(m).lower()


def test_the_follow_up_answer_lifts_the_wages_record_from_possible_to_strong(tmp_path):
    with client(tmp_path) as c:
        before = {m["amount"]: m for m in c.post("/api/search", json=MARISOL).json()["matches"]}
        after = {m["amount"]: m for m in c.post("/api/search", json=WITH_ADDRESS).json()["matches"]}
        assert before[2316.4]["strength"] == "possible" and after[2316.4]["strength"] == "strong"
        assert after[2316.4]["score"] > before[2316.4]["score"]
        tie = "what makes this a strong match: the holder they named together with the postcode they gave"
        assert tie in after[2316.4]["reasons"] and tie not in before[2316.4]["reasons"]
        assert not any("address" in reason for reason in after[2316.4]["reasons"])     # the street is not evidence
        assert after[640.25]["strength"] == "possible"       # the record at an address she never gave stays possible


def test_the_server_starts_without_the_register_database_and_says_so(tmp_path):
    with client(tmp_path) as c:
        info = c.get("/api/register").json()
        assert info["loaded"] is False and info["owner_records"] == 0 and info["demonstration_records"] > 0
        found = c.post("/api/search", json=MARISOL).json()
        assert found["searched"]["register_loaded"] is False and found["searched"]["owner_records"] == 0
        assert found["matches"] and all(m["source"] == "DEMO" for m in found["matches"])
        refused = c.get("/api/organisations", params={"q": "university"})
        assert refused.status_code == 503 and "not loaded" in refused.json()["detail"]
        assert c.get("/api/organisations/notable").status_code == 200     # read from the file earlier


def test_without_demonstration_records_nothing_of_them_is_served(tmp_path):
    with TestClient(create_app(db_path=searchable_register(tmp_path / "registers.duckdb"), totals_path=tmp_path / "t.json",
                               web_dist=tmp_path / "no-web")) as c:
        assert c.get("/api/demonstration").json() == {"people": [], "records": 0}
        assert c.post("/api/search", json=MARISOL).json()["matches"] == []
    with TestClient(create_app(db_path=tmp_path / "none.duckdb", totals_path=tmp_path / "t.json",
                               web_dist=tmp_path / "no-web")) as c:
        assert c.post("/api/search", json=MARISOL).status_code == 503


def test_a_claim_on_a_demonstration_record_is_marked_and_its_packet_says_so(tmp_path):
    with client(tmp_path) as c:
        person = next(p for p in c.get("/api/demonstration").json()["people"] if p["key"] == "marisol")
        match = next(m for m in c.post("/api/search", json=WITH_ADDRESS).json()["matches"] if m["amount"] == 2316.4)
        made = c.post("/api/claims", json={"record_id": match["record_id"], "claimant": person["claimant"],
                                           "history": WITH_ADDRESS})
        assert made.status_code == 201 and made.json()["sample"] is True
        assert made.json()["match"]["strength"] == "strong"
        stored = json.loads((tmp_path / "claims" / f"{made.json()['id']}.json").read_text())
        text = packet.build(stored, cl.checklist(stored), compress=False).decode("latin-1")
        assert "DEMONSTRATION RECORD, NOT A REAL PROPERTY" in text and "Demonstration record number" in text
        assert c.get("/api/payer/queue").json()["claims"][0]["sample"] is True


def test_every_demonstration_person_can_be_filled_in_and_paid_in_her_own_currency():
    people = {p["key"]: p for p in demo.people()}
    assert people["marisol"]["bank"]["currency"] == "MXN" and people["marisol"]["claimant"]["country"] == "MX"
    assert people["amihan"]["bank"]["currency"] == "PHP" and people["amihan"]["claimant"]["country"] == "PH"
    assert people["marisol"]["audio"] and people["amihan"]["audio"] is None     # no Tagalog voice: typed, and labelled
    ids = {r["record_id"] for r in demo.records()}
    for p in people.values():
        assert p["main_record"] in ids and p["documents"][0]["order"] == "first"
        assert f"{p['bank']['first_name']} {p['bank']['last_name']}".split()[0] in p["claimant"]["name"]


def test_the_prepared_examples_are_organisations_only_and_add_up():
    made = json.loads(NOTABLE_PATH.read_text())
    assert made["count"] == len(made["examples"]) >= 30
    assert round(sum(e["amount"] for e in made["examples"]), 2) == made["total"]
    for e in made["examples"]:
        assert shown_as_organisation(e["owner"]), e["owner"]
        assert e["amount"] > 0 and e["holder"] and e["category"] in made["categories"]
    assert sum(1 for e in made["examples"] if e["opening"]) == 3


def test_the_holder_she_named_and_the_postcode_alone_lift_the_wages_record(tmp_path):
    """Her first account names her employer and no postcode; the postcode in her answer is what makes it strong."""
    with client(tmp_path) as c:
        before = {m["amount"]: m for m in c.post("/api/search", json=MARISOL).json()["matches"]}
        after = {m["amount"]: m for m in c.post("/api/search", json=WITH_POSTCODE).json()["matches"]}
        assert set(before) == {2316.4, 95.0, 640.25} and all(m["strength"] == "possible" for m in before.values())
        assert after[2316.4]["strength"] == "strong" and after[2316.4]["score"] > before[2316.4]["score"]
        assert after[640.25]["strength"] == "possible"


def test_the_spoken_account_carries_what_her_records_need_and_the_answer_carries_the_rest():
    marisol = next(p for p in demo.people() if p["key"] == "marisol")
    main = next(r for r in demo.records() if r["record_id"] == marisol["main_record"])
    need = demo.spoken_requirements(marisol)
    for word in ("MARISOL", "ELENA", "TOLMEDO", "PERALMONTE", "SALINAS", "2008", "2015", *main["holder_name"].split()):
        assert word in need["words"], word
    for word in ("618", "CAMINO", "LUNAMAR", "93905", "PUNTA", "CLARA"):
        assert word in need["answer"], word
    assert demo.missing_words(marisol["words"], need["words"]) == []
    assert demo.missing_words(marisol["answer"], need["answer"]) == []
    # The first account gives no postcode and no street: those come only with the answer.
    assert set(demo.missing_words(marisol["words"], need["answer"])) >= {"618", "CAMINO", "LUNAMAR", "93905"}
    amihan = next(p for p in demo.people() if p["key"] == "amihan")
    assert demo.spoken_requirements(amihan) == {}          # her account is typed; nothing is spoken


def test_what_the_recogniser_heard_is_checked_word_by_word():
    need = ["TOLMEDO", "2015", "93905", "PUNTA", "CLARA", "WATER", "LIGHT"]
    heard = "me llamo Marisol Tolmedo, hasta 2015. Código Postal 93905. Con punta clara water and light."
    assert demo.missing_words(heard, need) == []          # case, accents and punctuation do not matter
    assert demo.missing_words("Marisol Tolmedo, hasta 20-15, código postal 93 905", need[:3]) == ["2015", "93905"]
    assert demo.missing_words("", need[:1]) == ["TOLMEDO"]


def test_the_voice_is_labelled_as_synthetic_and_the_words_as_heard_or_prepared():
    people = {p["key"]: p for p in demo.people()}
    heard, prepared = people["marisol"]["spoken_note"], people["marisol"]["prepared_note"]
    for note in (heard, prepared):
        assert "synthetic voice (Paulina, which comes with macOS)" in note and "prepared account" in note
        assert "real person's voice" in note and "\u2014" not in note and "\u2013" not in note
    assert "what the speech recogniser on this machine heard" in heard
    assert "prepared text" in prepared and "not transcribed" in prepared and "heard" not in prepared
    assert people["amihan"]["spoken_note"] is None and people["amihan"]["prepared_note"] is None


def test_the_sound_files_on_disk_were_heard_with_every_required_word():
    """scripts/make_demo_audio.py writes what the recogniser heard beside the sound. The check here is that the
    files on disk belong to the words in demonstration.json; the recogniser itself is not run by the tests."""
    made = json.loads((demo.FILE.parents[2] / "web" / "public" / "demo" / "heard.json").read_text())
    marisol = next(p for p in demo.people() if p["key"] == "marisol")
    need = demo.spoken_requirements(marisol)
    for key, file_key in (("words", "audio"), ("answer", "answer_audio")):
        entry = made[marisol[file_key].rsplit("/", 1)[-1]]
        assert entry["prepared"] == marisol[key]
        assert demo.missing_words(entry["heard"], need[key]) == [] and entry["seconds"] > 5


def test_the_page_is_told_whether_this_server_can_transcribe(tmp_path, monkeypatch):
    from khutlisa import speech
    with client(tmp_path) as c:
        monkeypatch.setattr(speech, "engine", lambda: None)
        assert c.get("/api/demonstration").json()["speech_ready"] is False
        monkeypatch.setattr(speech, "engine", lambda: "whisper.cpp")
        assert c.get("/api/demonstration").json()["speech_ready"] is True
