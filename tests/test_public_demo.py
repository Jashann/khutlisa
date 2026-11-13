"""Public demonstration mode, the model budget, health and readiness, and who a request came from."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from khutlisa import clients, invented_holder as inv, llm, public_demo
from khutlisa.server import create_app
from test_claims import AS_PAYER, PAYER_KEY, PNG
from test_demonstration import MARISOL
from test_totals import searchable_register

REAL_ASK = llm.ask            # taken before the test fixtures replace it
SAMPLE = b"\x89PNG\r\n\x1a\n" + b"sample document that ships with the product " * 20
SOUND = b"\x00\x00\x00\x20ftypM4A " + b"demonstration sound " * 40
CLAIMANT = {"name": "Marisol Elena Tolmedo Peralmonte", "address": "Calle Fresno 214, Guadalajara", "country": "MX",
            "email": "marisol@example.com", "relationship": "self"}


def app_for(tmp_path, public=True, db=None, clock=None, **more):
    web = tmp_path / "web"
    (web / "samples").mkdir(parents=True, exist_ok=True)
    (web / "demo").mkdir(exist_ok=True)
    (web / "samples" / "mx_passport_id.png").write_bytes(SAMPLE)
    (web / "demo" / "marisol_history_es.m4a").write_bytes(SOUND)
    (web / "index.html").write_text("<html></html>")
    extra = {"clock": clock} if clock else {}
    return create_app(db_path=db or tmp_path / "no-register.duckdb", totals_path=tmp_path / "t.json", web_dist=web,
                      claims_dir=tmp_path / "claims", demonstration=True, payer_key=PAYER_KEY, public_demo_mode=public,
                      outreach_today=lambda: date(2026, 11, 13), **extra, **more)


@pytest.fixture
def demo(tmp_path):
    app = app_for(tmp_path, db=searchable_register(tmp_path / "registers.duckdb"))
    with TestClient(app) as client:
        yield client


def record(client, source):
    found = client.post("/api/search", json={"given_names": ["Odalys", "Marisol"], "family_names": ["Quillfeather", "Tolmedo"]}).json()
    return next(m for m in found["matches"] if m["source"] == source)


# ---- the budget --------------------------------------------------------------------------------------------------

def test_the_daily_budget_counts_calls_and_starts_again_at_midnight_utc():
    now = [86400.0 * 20000 + 10]
    budget = public_demo.DailyBudget(2, clock=lambda: now[0])
    budget.take()
    budget.take()
    assert budget.left() == 0
    with pytest.raises(public_demo.BudgetUsed) as refused:
        budget.take()
    assert refused.value.for_screen and "budget of language model calls" in str(refused.value) and isinstance(refused.value, llm.ModelUnavailable)
    now[0] += 86400
    assert budget.left() == 2
    budget.take()
    assert budget.left() == 1


def test_every_model_call_passes_the_gate_and_a_used_budget_stops_the_call_before_it_is_made(monkeypatch):
    made = []
    monkeypatch.setattr(llm, "ask", REAL_ASK)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(llm, "_ask_api", lambda prompt, files, model, timeout: made.append(prompt) or '{"ok": true}')
    budget = public_demo.DailyBudget(2)
    monkeypatch.setattr(llm, "gate", budget.take)
    assert llm.ask_json("one") == {"ok": True} and llm.ask("two") == '{"ok": true}'
    with pytest.raises(public_demo.BudgetUsed):
        llm.ask("three")
    assert len(made) == 2
    monkeypatch.setattr(llm, "gate", None)
    assert llm.ask("four") and len(made) == 3


def test_a_used_budget_is_said_in_plain_words_on_the_screen(tmp_path, monkeypatch):
    app = app_for(tmp_path)
    monkeypatch.setattr(llm, "recorded", None)      # with no recorded answers, the invented file's mapping asks the model
    monkeypatch.setattr(llm, "ask", REAL_ASK)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(llm, "_ask_api", lambda *a: pytest.fail("the budget is used: no call may be made"))
    app.state.model_budget.calls = 0
    with TestClient(app) as client:
        refused = client.post("/api/intake/text", json={"text": "Me llamo Marisol."})
        assert refused.status_code == 503 and refused.json()["detail"] == public_demo.BUDGET_USED
        mode = client.get("/api/mode").json()
        assert mode["model"]["calls_left_today"] == 0
        # the holder's list still works: the columns are read in code, and the screen says why
        view = client.post("/api/holder/list/invented", headers=AS_PAYER).json()
        assert view["list"]["proposal"]["by"] == "code" and view["list"]["proposal"]["model_note"] == public_demo.BUDGET_USED


def test_outside_the_public_demonstration_there_is_no_budget_and_no_gate(tmp_path):
    app = app_for(tmp_path, public=False)
    assert app.state.model_budget is None and llm.gate is None
    with TestClient(app) as client:
        mode = client.get("/api/mode").json()
        assert mode == {**mode, "public_demo": False, "notice": "", "holder_key": None}


# ---- what the public demonstration keeps and what it closes ------------------------------------------------------------

def test_the_mode_says_what_it_is_and_hands_out_the_holders_key_only_in_the_public_demonstration(demo):
    mode = demo.get("/api/mode").json()
    assert mode["public_demo"] is True and mode["holder_key"] == PAYER_KEY and "do not enter real personal details" in mode["notice"]
    assert mode["model"]["calls_left_today"] == 150 and mode["register_loaded"] is True


def test_the_real_search_and_the_holders_screens_stay(demo):
    found = demo.post("/api/search", json={"given_names": ["Odalys"], "family_names": ["Quillfeather"]}).json()
    assert found["searched"]["register_loaded"] is True and found["matches"][0]["source"] == "TEST"
    assert demo.get("/api/demonstration").json()["records"] == 8
    assert demo.get("/api/holders").status_code in (200, 503) and demo.get("/api/countries").status_code == 200


def test_a_claim_can_be_opened_only_on_a_demonstration_record(demo):
    real = demo.post("/api/claims", json={"record_id": record(demo, "TEST")["record_id"], "claimant": CLAIMANT})
    assert real.status_code == 403 and real.json()["detail"] == public_demo.ONLY_DEMO_CLAIMS
    made = demo.post("/api/claims", json={"record_id": record(demo, "DEMO")["record_id"], "claimant": CLAIMANT, "history": MARISOL})
    assert made.status_code == 201 and made.json()["sample"] is True
    assert demo.post("/api/claims", json={"record_id": "k" + "0" * 23, "claimant": CLAIMANT}).status_code == 404
    assert demo.post("/api/claims", content=b"not json", headers={"Content-Type": "application/json"}).status_code == 422


def test_only_the_sample_documents_are_accepted_and_arbitrary_uploads_are_refused(demo):
    claim = demo.post("/api/claims", json={"record_id": record(demo, "DEMO")["record_id"], "claimant": CLAIMANT}).json()
    other = demo.post(f"/api/claims/{claim['id']}/documents", data={"kind": "id"}, files={"file": ("mine.png", PNG, "image/png")})
    assert other.status_code == 403 and other.json()["detail"] == public_demo.ONLY_SAMPLE_DOCUMENTS
    sample = demo.post(f"/api/claims/{claim['id']}/documents", data={"kind": "id"}, files={"file": ("mx_passport_id.png", SAMPLE, "image/png")})
    assert sample.status_code == 201 and len(sample.json()["documents"]) == 1


def test_only_the_demonstration_sound_is_transcribed(demo):
    mine = demo.post("/api/intake/audio", files={"file": ("recording", b"RIFF" + b"\x01" * 500, "audio/wav")})
    assert mine.status_code == 403 and mine.json()["detail"] == public_demo.ONLY_SAMPLE_VOICE
    assert demo.post("/api/intake/heard", files={"file": ("recording", b"\x02" * 500, "audio/webm")}).status_code == 403
    # the demonstration sound passes the gate; with no speech engine in the tests the route itself answers
    theirs = demo.post("/api/intake/heard", files={"file": ("recording", SOUND, "audio/mp4")})
    assert theirs.status_code == 503 and "tests do not run the speech engine" in theirs.json()["detail"]


def test_only_the_invented_holder_file_can_be_loaded(demo):
    real = b"Name,Amount,Pay Date,Country\nIna Vell,12.00,2025-01-02,MX\nBo Lark,13.00,2025-01-03,MX\n"
    refused = demo.post("/api/holder/list", headers=AS_PAYER, files={"file": ("ours.csv", real, "text/csv")})
    assert refused.status_code == 403 and "only the invented holder file" in refused.json()["detail"]
    marked = f"{inv.FIRST_LINE}\n".encode() + real          # the mark alone is not enough: it must be the invented file itself
    assert demo.post("/api/holder/list", headers=AS_PAYER, files={"file": ("ours.csv", marked, "text/csv")}).status_code == 403
    table = inv.rows()
    for data, name in ((inv.as_csv(table), inv.file_name()), (inv.as_excel(table), inv.file_name("excel"))):
        assert demo.post("/api/holder/list", headers=AS_PAYER, files={"file": (name, data, "application/octet-stream")}).status_code == 200
    assert demo.post("/api/holder/list/invented", headers=AS_PAYER).json()["demo_only"] is True


def test_a_visitor_cannot_start_or_approve_a_payment_on_anything_but_a_demonstration_claim(demo, tmp_path):
    store = demo.app.state.claims
    real = store.create({"record_id": "k-real", "source": "US-CA", "owner": "O··· Q···", "owner_is_organisation": False, "amount": 50.0,
                         "currency": "USD", "holder_name": "A BANK", "property_type": "", "owner_city": "", "owner_region": "",
                         "owner_country": "US"}, CLAIMANT, None, {"source": "US-CA", "record_id": "1"})
    for path in (f"/api/claims/{real['id']}/payout/plan", f"/api/claims/{real['id']}/payout/confirm", f"/api/claims/{real['id']}/payout/resume",
                 f"/api/payer/claims/{real['id']}/approve"):
        refused = demo.post(path, headers=AS_PAYER, json={"plan_id": "p" * 10})
        assert refused.status_code == 403 and refused.json()["detail"] == public_demo.ONLY_DEMO_PAYMENTS, path
    shown = demo.post("/api/claims", json={"record_id": record(demo, "DEMO")["record_id"], "claimant": CLAIMANT}).json()
    # a demonstration claim reaches the route itself, which answers by its own rules (no approval yet)
    assert demo.post(f"/api/claims/{shown['id']}/payout/plan", json={}).status_code == 409
    assert demo.post(f"/api/payer/claims/{shown['id']}/approve", headers=AS_PAYER).status_code in (200, 409)
    assert demo.get(f"/api/claims/{real['id']}/payout").status_code == 200       # reading is not starting


def test_everything_is_counted_per_client_in_the_public_demonstration(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setenv("KHUTLISA_REQUESTS_PER_MINUTE", "5")
    monkeypatch.setenv("KHUTLISA_REQUESTS_PER_HOUR", "8")
    with TestClient(app_for(tmp_path, clock=lambda: now[0])) as client:
        assert [client.get("/api/countries").status_code for _ in range(6)] == [200] * 5 + [429]
        slow = client.get("/api/mode")
        assert slow.status_code == 429 and "Too many requests" in slow.json()["detail"] and int(slow.headers["retry-after"]) >= 1
        assert client.get("/api/health").status_code == 200 and client.get("/").status_code == 200       # never counted
        now[0] += 61
        assert [client.get("/api/countries").status_code for _ in range(4)] == [200] * 3 + [429]         # the hour's limit


def test_without_the_mode_nothing_is_closed(tmp_path):
    with TestClient(app_for(tmp_path, public=False, db=searchable_register(tmp_path / "registers.duckdb"))) as client:
        real = client.post("/api/claims", json={"record_id": record(client, "TEST")["record_id"], "claimant": CLAIMANT})
        assert real.status_code == 201
        added = client.post(f"/api/claims/{real.json()['id']}/documents", data={"kind": "id"}, files={"file": ("mine.png", PNG, "image/png")})
        assert added.status_code == 201
        ours = b"Name,Amount,Pay Date,Country\nIna Vell,12.00,2025-01-02,MX\nBo Lark,13.00,2025-01-03,MX\n"
        assert client.post("/api/holder/list", headers=AS_PAYER, files={"file": ("ours.csv", ours, "text/csv")}).status_code == 200


# ---- health and readiness ------------------------------------------------------------------------------------------

def test_health_answers_at_once_and_readiness_waits_for_californias_file(tmp_path):
    with TestClient(app_for(tmp_path, public=False)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        waiting = client.get("/api/ready")
        body = waiting.json()
        assert waiting.status_code == 503 and body["ready"] is False and body["register"]["loaded"] is False
        assert "demonstration records only" in body["register"]["note"] and body["web"] is True and body["holder_key_set"] is True
        (tmp_path / "build_progress.json").write_text(json.dumps({"stage": "loading", "file": "01_From_x.zip", "rows": 5}))
        assert client.get("/api/ready").json()["register"]["building"] == {"stage": "loading", "file": "01_From_x.zip", "rows": 5}
    with TestClient(app_for(tmp_path, public=False, db=searchable_register(tmp_path / "registers.duckdb"))) as client:
        ready = client.get("/api/ready")
        assert ready.status_code == 200 and ready.json()["ready"] is True and ready.json()["register"]["building"] is None
        shown = json.dumps(ready.json())
        assert PAYER_KEY not in shown and "airwallex_keys" in shown and ready.json()["airwallex_keys"] is False


def test_the_model_status_never_shows_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    status = public_demo.model_status()
    assert status["available"] is True and "sk-secret-value" not in json.dumps(status)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(public_demo.shutil, "which", lambda name: None)
    assert public_demo.model_status()["available"] is False and "ANTHROPIC_API_KEY is not set" in public_demo.model_status()["note"]


# ---- who a request came from -------------------------------------------------------------------------------------------

class Request:
    def __init__(self, host, headers=None):
        self.client = type("C", (), {"host": host})()
        self.headers = headers or {}


def test_by_default_a_forwarding_header_is_never_believed():
    assert clients.keys(Request("10.0.0.5"), trusted=False) == ["10.0.0.5"]
    assert clients.keys(Request("10.0.0.5", {"x-forwarded-for": "1.2.3.4"}), trusted=False) == [clients.SHARED, "10.0.0.5"]
    assert clients.address(Request("10.0.0.5", {"x-real-ip": "1.2.3.4"}), trusted=False) == "10.0.0.5"


def test_behind_our_own_proxy_the_caller_is_the_address_the_proxy_appended(monkeypatch):
    assert clients.keys(Request("172.18.0.3", {"x-forwarded-for": "9.9.9.9, 203.0.113.7"}), trusted=True) == ["203.0.113.7"]
    assert clients.keys(Request("172.18.0.3"), trusted=True) == ["172.18.0.3"]
    monkeypatch.setenv("KHUTLISA_TRUSTED_PROXY", "1")
    assert clients.address(Request("172.18.0.3", {"x-forwarded-for": "203.0.113.7"})) == "203.0.113.7"
    monkeypatch.delenv("KHUTLISA_TRUSTED_PROXY")
    assert clients.address(Request("172.18.0.3", {"x-forwarded-for": "203.0.113.7"})) == "172.18.0.3"
