"""Shared by the estate tests: an invented family on the made-up register, a stand-in model that "reads" each
made-up document, and a fake Airwallex that also pays in pounds and yen. Nothing here touches the network."""
import json
import threading

import httpx
from fastapi.testclient import TestClient

from khutlisa import airwallex as awx
from khutlisa import llm
from khutlisa.server import create_app
from test_airwallex import FakeAirwallex, make_client
from test_claims import AS_PAYER, PAYER_KEY, make_register
from test_proof import PNG, passport
from test_server import MARIA, ref

HEIR_CLAIMANT = {"name": "Pedro Santos Reyes", "address": "Calle Fresno 12, Guadalajara 44160", "country": "MX",
                 "email": "pedro@example.org", "relationship": "heir"}
OWNER = "Maria Luz Santos"                 # the owner on row P1 of the made-up register is SANTOS MARIA L
PEDRO, ANA, TOMAS, ELENA, NAOMI = ("Pedro Santos Reyes", "Ana Santos", "Tomas Santos", "Elena Santos",
                                   "Naomi Santos Kato")

FAMILY = {
    "language": "Spanish", "english": "My wife Maria Luz Santos died on 2 March 2024 in Daly City.",
    "decedent": {"name": OWNER, "died_on": "2024-03-02", "domicile_country": "US", "domicile_state": "CA"},
    "disposition": "intestate", "property": "separate", "has_spouse": True,
    "spouse": {"name": PEDRO, "alive": True, "country": "MX"},
    "children": [{"name": ANA, "alive": True, "country": "PH"}, {"name": TOMAS, "alive": True, "country": "GB"},
                 {"name": ELENA, "alive": False, "children_known": True,
                  "children": [{"name": NAOMI, "alive": True, "country": "JP"}]}],
    "children_known": True, "follow_up_key": "", "follow_up": "", "follow_up_english": "",
}
SPOUSE, CHILD_A, CHILD_T, GRAND = "s1", "c1", "c2", "c3.1"

BANKS = {
    SPOUSE: {"currency": "MXN", "first_name": "Pedro", "last_name": "Santos Reyes", "account_number": "002010077777777771",
             "street_address": "Calle Fresno 12", "city": "Guadalajara", "postcode": "44160", "state": "MX-JAL"},
    CHILD_A: {"currency": "PHP", "first_name": "Ana", "last_name": "Santos", "account_number": "1234567890",
              "swift_code": "BOPIPHMM", "street_address": "14 Mango Avenue", "city": "Cebu City", "postcode": "6000"},
    CHILD_T: {"currency": "GBP", "first_name": "Tomas", "last_name": "Santos", "account_number": "55779911",
              "sort_code": "20-00-00", "street_address": "12 Example Lane", "city": "Leeds", "postcode": "LS1 4AP"},
    GRAND: {"currency": "JPY", "first_name": "Naomi", "last_name": "Santos Kato", "account_number": "1234567",
            "bank_code": "0005", "branch_code": "001", "account_type": "Savings",
            "street_address": "1-2-3 Example Cho", "city": "Osaka", "postcode": "530-0001"},
}


def civil(kind, people, **more):
    names = [p[0] for p in people]
    return {"document_type": kind, "names": names, "holder_name": names[0], "issuer": "Civil Registry of Cebu City",
            "issuing_authority": "Civil Registry of Cebu City", "issue_date": "2024-03-20",
            "people": [{"name": n, "role": r} for n, r in people], **more}


SEEN = {
    "death_owner": civil("death certificate", [(OWNER, "subject"), (PEDRO, "spouse"), ("R. Cruz", "official")],
                         date_of_death="2024-03-02"),
    "marriage": civil("marriage certificate", [(PEDRO, "spouse"), (OWNER, "spouse")]),
    "birth_ana": civil("birth certificate", [(ANA, "subject"), (OWNER, "mother"), (PEDRO, "father")]),
    "birth_tomas": civil("birth certificate", [(TOMAS, "subject"), (OWNER, "mother"), (PEDRO, "father")]),
    "birth_elena": civil("birth certificate", [(ELENA, "subject"), (OWNER, "mother"), (PEDRO, "father")]),
    "death_elena": civil("death certificate", [(ELENA, "subject")], date_of_death="2019-06-11"),
    "birth_naomi": civil("birth certificate", [(NAOMI, "subject"), (ELENA, "mother"), ("Kenji Kato", "father")]),
    "id_pedro": passport("SANTOS REYES", "PEDRO", country="Mexico", state="MEX",
                         authority="Secretaria de Relaciones Exteriores"),
    "id_ana": passport("SANTOS", "ANA"),
    "id_tomas": passport("SANTOS", "TOMAS", country="United Kingdom", state="GBR", authority="HM Passport Office"),
    "id_naomi": passport("SANTOS KATO", "NAOMI", country="Japan", state="JPN", authority="Ministry of Foreign Affairs"),
}
DOCS = {"estate": [("death_certificate", "death_owner")],
        SPOUSE: [("name_change", "marriage"), ("id", "id_pedro")],
        CHILD_A: [("birth_certificate", "birth_ana"), ("id", "id_ana")],
        CHILD_T: [("birth_certificate", "birth_tomas"), ("id", "id_tomas")],
        GRAND: [("birth_certificate", "birth_elena"), ("death_certificate", "death_elena"),
                ("birth_certificate", "birth_naomi"), ("id", "id_naomi")]}


def fake_model(monkeypatch, family=None, seen=None):
    """`llm.ask` answers the family prompt with `family` and a document prompt with what `seen` holds for the
    word stored after the file's first bytes. A list in `seen` gives each of the two readings its own answer."""
    table = dict(SEEN if seen is None else seen)
    state = {"family": family or FAMILY, "calls": [], "lock": threading.Lock()}

    def ask(prompt, files=None, **kw):
        if not files:
            state["calls"].append(prompt)
            return json.dumps(state["family"])
        with state["lock"]:
            state["calls"].append(files[0])
            nth = sum(1 for f in state["calls"] if f == files[0]) - 1
        got = table[open(files[0], "rb").read()[len(PNG):].decode()]
        return json.dumps(got[nth % len(got)] if isinstance(got, list) else got)

    monkeypatch.setattr(llm, "ask", ask)
    return state, table


class EstateAirwallex(FakeAirwallex):
    """The fake sandbox with the two extra corridors. Pounds are quoted the other way round (GBPUSD), as on the
    live sandbox, and yen have no decimals."""

    def __init__(self):
        super().__init__()
        self.rates.update({"GBP": 1.33, "JPY": 158.9})
        self.incoming_fee_rate, self.payout_fee_usd = 0.003, 5.0
        self.refuse_beneficiary_named: str | None = None      # /beneficiaries/create answers 500 for this name

    def _buy(self, currency, sell):
        got = sell / self.rates[currency] if currency == "GBP" else sell * self.rates[currency]
        return round(got) if currency == "JPY" else round(got, 2)

    def route(self, method, path, body, params):
        if path == "/api/v1/fx/quotes/create" and body["buy_currency"] in ("GBP", "JPY"):
            cur = body["buy_currency"]
            real, self.rates[cur] = self.rates[cur], self.rates[cur]
            response = super().route(method, path, body, params)
            quote = self.quotes[response.json()["quote_id"]]
            quote.update(buy_amount=self._buy(cur, body["sell_amount"]),
                         currency_pair="GBPUSD" if cur == "GBP" else "USDJPY")
            return httpx.Response(201, json=quote)
        if path == "/api/v1/fx/conversions/create" and body["buy_currency"] in ("GBP", "JPY"):
            response = super().route(method, path, body, params)
            if response.status_code == 201:
                conv = self.conversions[-1]
                cur, wrong = conv["buy_currency"], conv["buy_amount"]
                conv["buy_amount"] = self._buy(cur, conv["sell_amount"])
                self.balance[cur] = round(self.balance[cur] - wrong + conv["buy_amount"], 2)
                self.ledger[-1]["amount"] = self.ledger[-1]["net"] = conv["buy_amount"]
                return httpx.Response(201, json=conv)
            return response
        if path == "/api/v1/beneficiary_api_schemas/generate" and body["account_currency"] in ("GBP", "JPY"):
            fields = [("beneficiary.bank_details.account_name", None), ("beneficiary.bank_details.account_number", r"^[0-9]{7,8}$"),
                      ("beneficiary.bank_details.account_routing_value1", r"^[0-9]{4,6}$"), ("beneficiary.address.postcode", None)]
            return httpx.Response(200, json={"condition": body, "fields": [
                {"path": p, "required": True, "rule": {"type": "string", "pattern": pat}} for p, pat in fields]})
        if path == "/api/v1/beneficiaries/create" and self.refuse_beneficiary_named and \
                body["beneficiary"]["bank_details"]["account_name"] == self.refuse_beneficiary_named:
            return httpx.Response(500, json={"code": "internal_error", "message": "try later"})
        if path == "/api/v1/fx/rates/current" and params.get("buy_currency") == "GBP":
            return httpx.Response(200, json={"buy_currency": "GBP", "sell_currency": "USD", "currency_pair": "GBPUSD",
                                             "rate": self.rates["GBP"]})
        if path == "/api/v1/transfers/create" and body["transfer_currency"] == "JPY":
            response = super().route(method, path, body, params)
            if response.status_code == 201:       # yen have no decimals: the fee and what is received are whole
                t = self.transfers[response.json()["id"]]
                fee = round(t["fee_amount"])
                t.update(fee_amount=fee, amount_beneficiary_receives=round(t["source_amount"] - fee))
                return httpx.Response(201, json=t)
            return response
        return super().route(method, path, body, params)


class EstateWorld:
    def __init__(self, folder, monkeypatch, family=None, seen=None):
        self.folder = folder
        self.db = make_register(folder)
        self.fake = EstateAirwallex()
        self.model, self.seen = fake_model(monkeypatch, family, seen)
        self.app = self.make_app()

    def factory(self):
        client = make_client(self.fake)
        return client, awx.SandboxSimulator(client)

    def make_app(self):
        return create_app(db_path=self.db, totals_path=self.folder / "totals.json", web_dist=self.folder / "no-web",
                          airwallex_factory=self.factory, payout_pause=0.0, payer_key=PAYER_KEY, watch_seconds=0,
                          read_documents=True)

    def client(self):
        return TestClient(self.app, headers=AS_PAYER)


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def open_estate(api, record="P1", words="Mi esposa murio."):
    claim = ok(api.post("/api/claims", json={"record_id": ref(api, record), "claimant": HEIR_CLAIMANT,
                                             "history": MARIA}), 201)
    ok(api.post(f"/api/claims/{claim['id']}/estate"))
    return ok(api.post(f"/api/claims/{claim['id']}/estate/intake", json={"text": words}))


def add_doc(api, claim_id, kind, word):
    got = ok(api.post(f"/api/claims/{claim_id}/estate/documents", data={"kind": kind},
                      files={"file": (f"{word}.png", PNG + word.encode())}), 201)
    api.app.state.estate_reading.join()
    return ok(api.get(f"/api/claims/{claim_id}/estate"))


def prove(api, claim_id, who=(SPOUSE, CHILD_A, CHILD_T, GRAND), banks=BANKS):
    """Everything the named heirs need: the owner's death certificate, each heir's chain and identification,
    their statement and their own bank account."""
    for kind, word in DOCS["estate"]:
        add_doc(api, claim_id, kind, word)
    for heir in who:
        for kind, word in DOCS[heir]:
            add_doc(api, claim_id, kind, word)
        ok(api.put(f"/api/claims/{claim_id}/estate/heirs/{heir}", json={"declared": True, "email": f"{heir.replace('.', '')}@example.org"}))
        ok(api.put(f"/api/claims/{claim_id}/estate/heirs/{heir}/payee", json=banks[heir]))
    return ok(api.get(f"/api/claims/{claim_id}/estate"))


def approve(api, claim_id, **body):
    return api.post(f"/api/payer/estates/{claim_id}/approve", json=body)


def settle(api, claim_id, fail_heir=None):
    """The family asks for the plan and agrees to it; the settlement then runs to rest."""
    planned = ok(api.post(f"/api/claims/{claim_id}/estate/settlement/plan", json={"fail_heir": fail_heir}))
    plan = planned["settlement"]["plan"] or planned["settlement"]["rounds"][-1].get("plan")
    ok(api.post(f"/api/claims/{claim_id}/estate/settlement/confirm", json={"plan_id": plan["id"]}))
    api.app.state.estates.join(claim_id)
    return ok(api.get(f"/api/claims/{claim_id}/estate"))
