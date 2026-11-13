"""What the browser walk-through found: the payer's view must speak to the payer, sample records must be labelled
as samples everywhere, and nothing on a screen may carry an internal state name."""
import json
import re

import duckdb
import pytest
from fastapi.testclient import TestClient

from khutlisa import claims as cl, packet
from khutlisa.names import normalise, phonetic
from khutlisa.server import create_app
from test_claims import AS_PAYER, CLAIMANT, PAYER_KEY, give_bank
from test_server import ref
from test_proof import add, api, app, fake_model, open_claim   # noqa: F401  (api and app are fixtures)

TO_THE_CLAIMANT = re.compile(r"\b(you|your)\b", re.I)
STATE_NAME = re.compile(r"\b(FOUND|PROOF_NEEDED|PROOF_READY|PACKET_READY|FILED|APPROVED|PAYING|REJECTED|PAYMENT_HELD)\b")


def payer_words(row: dict) -> str:
    """Every sentence the payer view shows for one claim."""
    file = row["proof_file"]
    lines = file["reasons"] + [file["summary"], (file["record_link"] or {}).get("text", "")]
    for q in file["requirements"]:
        lines += [q["title"]] + q["facts"] + q["problems"]
    return "\n".join(lines + row["proof"]["missing"] + [row["last_event"]["note"]])


def test_the_payer_view_speaks_to_the_payer_and_the_claimant_view_to_the_claimant(api, app):
    claim = open_claim(api)
    row = api.get("/api/payer/queue").json()["claims"][0]
    assert not TO_THE_CLAIMANT.search(payer_words(row)), payer_words(row)      # nothing added yet: all missing
    assert "The claimant's photo identification" in payer_words(row)
    add(api, app, claim["id"], "id", "oldpassport")
    add(api, app, claim["id"], "proof_of_address", "payslip")                  # the old address, not the current one
    add(api, app, claim["id"], "tax_number", "w8ben")
    row = api.get("/api/payer/queue").json()["claims"][0]
    words = payer_words(row)
    assert not TO_THE_CLAIMANT.search(words), words
    assert "the claimant's name, Maria Luz Santos" in words and "is not the claimant's current address" in words
    assert "the claimant added" in words and row["proof_file"]["ready"] is False
    refused = api.post(f"/api/payer/claims/{claim['id']}/approve")
    assert refused.status_code == 409 and not TO_THE_CLAIMANT.search(json.dumps(refused.json()))
    # The claimant still reads the same facts in the second person.
    mine = json.dumps(api.get(f"/api/claims/{claim['id']}").json()["proof"])
    assert "the name you gave, Maria Luz Santos" in mine and "is not the current address you gave" in mine


def test_a_proven_requirement_names_only_the_documents_that_prove_it(api, app):
    claim = open_claim(api)
    add(api, app, claim["id"], "id", "oldpassport")     # expired, so it does not settle the identification
    add(api, app, claim["id"], "id", "passport")
    row = api.get("/api/payer/queue").json()["claims"][0]
    photo = next(q for q in row["proof_file"]["requirements"] if q["key"] == "photo_id")
    assert photo["status"] == "satisfied" and photo["files"] == ["passport.png"] and photo["problems"] == []
    assert row["claimant_country_name"] == "Philippines"


def test_no_internal_state_name_reaches_a_sentence(api, app):
    claim = open_claim(api)
    for kind, word in (("id", "passport"), ("tax_number", "w8ben"), ("proof_of_address", "homebill")):
        add(api, app, claim["id"], kind, word)
    give_bank(api, claim["id"])
    assert api.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 200
    notes = [e["note"] for e in api.get(f"/api/claims/{claim['id']}").json()["history"]]
    assert notes and not any(STATE_NAME.search(n) for n in notes), notes


def test_approval_without_document_reading_does_not_print_a_state_name(tmp_path):
    from test_claims import make_register
    db = make_register(tmp_path)
    with TestClient(create_app(db_path=db, totals_path=tmp_path / "t.json", web_dist=tmp_path / "no-web",
                               payer_key=PAYER_KEY), headers=AS_PAYER) as c:
        claim = c.post("/api/claims", json={"record_id": ref(c, "P1"), "claimant": CLAIMANT}).json()
        give_bank(c, claim["id"])
        assert c.post(f"/api/payer/claims/{claim['id']}/approve").status_code == 200
        notes = [e["note"] for e in c.get(f"/api/claims/{claim['id']}").json()["history"]]
        assert not any(STATE_NAME.search(n) for n in notes), notes


# ---- the sample register ---------------------------------------------------------------------------------------

def sample_register(folder):
    db = folder / "sample.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""create table records (source varchar, record_id varchar, owner_name varchar, owner_norm varchar,
        owner_street varchar, owner_city varchar, owner_region varchar, owner_postcode varchar, owner_country varchar,
        amount double, currency varchar, holder_name varchar, holder_city varchar, holder_region varchar,
        property_type varchar, phon_first varchar, phon_last varchar)""")
    norm = normalise("DALISAY AMIHAN")
    con.execute("insert into records values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ["SAMPLE", "SAMPLE-0001", "DALISAY AMIHAN", norm, "1420 LARKMOOR STREET", "DALY CITY", "CA", "94015",
                 "US", 1840.55, "USD", "BAYVIEW MERCY HOSPITAL", "", "", "MS01: WAGES, PAYROLL, SALARIES",
                 phonetic("DALISAY"), phonetic("AMIHAN")])
    con.close()
    return db


def test_the_register_address_says_whether_it_is_the_sample_register(tmp_path, api):
    assert api.get("/api/register").json()["sample"] is False        # the tests' usual register is not marked SAMPLE
    with TestClient(create_app(db_path=sample_register(tmp_path), totals_path=tmp_path / "t.json",
                               web_dist=tmp_path / "no-web")) as c:
        assert c.get("/api/register").json() == {"owner_records": 1, "records": 1, "sample": True}


def test_a_claim_on_a_sample_record_is_labelled_as_a_sample_on_every_surface(tmp_path):
    with TestClient(create_app(db_path=sample_register(tmp_path), totals_path=tmp_path / "t.json",
                               web_dist=tmp_path / "no-web", payer_key=PAYER_KEY), headers=AS_PAYER) as c:
        made = c.post("/api/claims", json={"record_id": ref(c, "SAMPLE-0001"), "claimant": CLAIMANT})
        assert made.status_code == 201 and made.json()["sample"] is True
        assert c.get("/api/payer/queue").json()["claims"][0]["sample"] is True
        stored = c.app.state.claims.load(made.json()["id"])
        text = packet.build(stored, cl.checklist(stored), compress=False).decode("latin-1")
        assert "SAMPLE RECORD, NOT A REAL PROPERTY" in text and "Sample record number" in text
        assert "No such property exists" in text
        assert "California property number" not in text and "held by the California State Controller" not in text


def test_a_claim_on_a_real_record_is_not_labelled_as_a_sample(api):
    claim = open_claim(api)
    assert claim["sample"] is False
    stored = api.app.state.claims.load(claim["id"])
    text = packet.build(stored, cl.checklist(stored), compress=False).decode("latin-1")
    assert "SAMPLE RECORD" not in text and "California property number" in text


def test_the_packet_banner_fits_the_page_even_with_the_demonstration_words():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from khutlisa import packet

    long = (packet.BANNER + "; demonstration record, not a real property").upper()
    assert stringWidth(long, "Helvetica-Bold", 9.5) > A4[0] - 16 * mm          # at the old size it ran off both edges
    size = packet.banner_size(long, A4[0])
    assert stringWidth(long, "Helvetica-Bold", size) <= A4[0] - 16 * mm and size >= 7
    assert packet.banner_size(packet.BANNER.upper(), A4[0]) == 9.5              # a banner that fits keeps its size


def test_the_sample_taxpayer_letter_prints_one_name_only():
    """A letter that prints a second name ("formerly known as") is a fair thing for a reader to question, and on
    some readings it was questioned, which held the demonstration proof back. The sample letter is in one name."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "make_sample_documents.py"
    spec = importlib.util.spec_from_file_location("make_sample_documents_for_names", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for person in (module.AMIHAN, module.MARISOL):
        printed = module.tax_letter_rows(person)
        assert [label for label, _ in printed] == ["Name on file", "Notice"]
        assert printed[0][1] == person["now"]["name"]
