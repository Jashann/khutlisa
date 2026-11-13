"""Makes a set of demonstration claims with three planted rings, and measures the ring detector on it.

    .venv/bin/python scripts/make_ring_claims.py                 # data/ring_demo/claims, seed 7, then the measurement
    .venv/bin/python scripts/make_ring_claims.py --seed 11 --out /some/folder
    .venv/bin/python scripts/make_ring_claims.py --measure-only  # measure the set that is already there

Every person, owner, holder, address, account and document here is invented, and every generated image carries
the word SAMPLE. Nothing is read from a register. The claims are written straight into a claims folder in the
shape the server keeps them (claims.py), so the server can be started on the folder:

    KHUTLISA_CLAIMS=data/ring_demo/claims KHUTLISA_PAYER_KEY=demo KHUTLISA_READ_DOCUMENTS=0 \\
        .venv/bin/python -m uvicorn khutlisa.server:app --port 8031

The honest claims are made to look like rings where honest people do: one person with two properties and one
account, married couples at one address, two unrelated people with the same common name in different countries,
several claims for one large holder in the same hour from different networks, a family on one home network, a
helper's device used by unrelated people, a daughter who opens claims for three relatives with her own email
address on her own laptop, and siblings whose names are a letter apart. Nothing in the honest set was chosen so
that the detector passes it: the daughter's three claims are held, and the measurement counts them as wrongly held.

The three rings:
  mule_account         five claimants with different contacts, all paid into one bank account. The first was
                       paid before the second claim existed and the second already has an approval.
  forged_identity      one picture of an identity card used in four claims with the name changed. Three are
                       edited copies of the file; the fourth was printed and photographed again.
  name_variant_burst   four claims in a few minutes for one holder, under names a letter or two apart, with one
                       mailbox written four ways and one device.

`ground_truth.json` (which claims belong to which ring) is written beside the claims. Only the measurement reads
it. The detector never does.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from khutlisa import claims as cl  # noqa: E402
from khutlisa import documents, rings  # noqa: E402

FONTS = ROOT / "src" / "khutlisa" / "fonts"
_FONTS: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}
DEFAULT_OUT = ROOT / "data" / "ring_demo" / "claims"
START = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)      # the first day of the made-up queue
RINGS = ("mule_account", "forged_identity", "name_variant_burst")

# Invented people. The pools are ordinary given names and made-up or common family names; no combination is
# taken from any register.
GIVEN = {"PH": ["Amihan", "Isagani", "Liwayway", "Efren", "Corazon", "Benigno", "Rosalinda", "Crisanto", "Marilou",
                "Teodoro", "Ligaya", "Honorio", "Perla", "Danilo", "Imelda", "Rogelio", "Luzviminda", "Arnel",
                "Milagros", "Wilfredo", "Estrella", "Renato", "Flordeliza", "Mariano"],
         "MX": ["Marisol", "Ximena", "Hortensia", "Amado", "Dolores", "Leobardo", "Graciela", "Fausto", "Yolanda",
                "Rigoberto", "Esperanza", "Octavio", "Refugio", "Anselmo", "Guadalupe", "Evaristo", "Lourdes",
                "Baltazar", "Consuelo", "Fidel", "Araceli", "Wenceslao", "Remedios", "Eusebio"]}
FAMILY = {"PH": ["Dalisanto", "Lacsamante", "Buenviado", "Macaraeno", "Dimasupil", "Villaluzon", "Magbanuan",
                 "Tolentares", "Sumulongco", "Panganiro", "Katigbayan", "Alimurang", "Bacolodan", "Caluyangco",
                 "Malabanos", "Gatdulano", "Pamintuyan", "Quiambaoro", "Sinagtalan", "Tanglawin", "Ulandayan",
                 "Zabalacan", "Hilarion", "Lumbreras"],
          "MX": ["Tolmedo", "Peralmonte", "Zavalerra", "Quimbayo", "Portillano", "Balmacedo", "Montoyasa",
                 "Villanuez", "Arrecife", "Camposeco", "Delamora", "Escalonte", "Fuenmayor", "Galindero",
                 "Huertaza", "Izquierro", "Jaramilo", "Landaverde", "Mirelesco", "Navarrosa", "Oyarzabal",
                 "Pedrazo", "Robledano", "Santibaro"]}
CITIES = {"PH": [("Cebu City", "6000"), ("Davao City", "8000"), ("Iloilo City", "5000"), ("Baguio", "2600"),
                 ("Tacloban", "6500"), ("Zamboanga City", "7000")],
          "MX": [("Puebla", "72000"), ("Oaxaca", "68000"), ("Morelia", "58000"), ("Merida", "97000"),
                 ("Zacatecas", "98000"), ("Tepic", "63000")]}
STREETS = ["Sampaguita", "Narra", "Acacia", "Mabini", "Rizal", "Jacaranda", "Nogal", "Reforma", "Hidalgo", "Laurel",
           "Bonifacio", "Molave", "Girasol", "Cedro", "Alondra", "Magnolia"]
MAIL = ["mailhaven.example", "correo.example", "postbox.example", "sulat.example", "buzon.example"]
HOLDERS = ["Valle Sereno Packing Company", "Bayview Mercy Hospital", "Golden Coast Power and Water",
           "Pacific Crest Staffing", "Harborline Credit Union", "Sierra Vista Growers", "Redwood Mutual Insurance"]
LARGE_HOLDER = "Coastline Payroll Services"
BURST_HOLDER = "Camino Alto Staffing Group"
KINDS_OF_PROPERTY = ["MS01: WAGES, PAYROLL, SALARIES", "AC01: CHECKING ACCOUNTS", "IN01: INDIVIDUAL POLICY BENEFITS",
                     "UT01: UTILITY DEPOSITS", "CK13: VENDOR CHECKS"]
COUNTRY_WORDS = {"PH": "SAMPLE REPUBLIC OF THE NORTH ISLANDS", "MX": "SAMPLE FEDERATION OF THE HIGH VALLEY"}
BANDS = {"PH": "#1f4e79", "MX": "#1d6b4f"}
UTILITIES = [("Tanglaw Power Cooperative", "#7a3b12"), ("Agua Clara Municipal Water", "#1c5d7a"),
             ("Lakbay Telecom", "#5a2d7a"), ("Red Sierra Gas", "#7a1c2e")]
BANK_CODE = {"PH": ("PHP", "BOPIPHMM"), "MX": ("MXN", None)}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if (size, bold) not in _FONTS:
        _FONTS[(size, bold)] = ImageFont.truetype(str(FONTS / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")), size)
    return _FONTS[(size, bold)]


_MARKS: dict[tuple[int, int], Image.Image] = {}


def stamp(image: Image.Image) -> Image.Image:
    """The word SAMPLE across the picture and a line at the foot saying it is invented."""
    width, height = image.size
    if (width, height) not in _MARKS:
        layer = Image.new("RGBA", (width * 2, height * 2), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((width, height), "SAMPLE", font=font(170, True), fill=(179, 38, 30, 60), anchor="mm")
        layer = layer.rotate(22, resample=Image.BICUBIC)
        left, top = (layer.width - width) // 2, (layer.height - height) // 2
        _MARKS[(width, height)] = layer.crop((left, top, left + width, top + height))
    image = Image.alpha_composite(image.convert("RGBA"), _MARKS[(width, height)]).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, height - 40, width, height], fill="#fdecea")
    draw.text((width // 2, height - 20), "SAMPLE DOCUMENT. The person is invented. Not a real record.",
              font=font(18, True), fill="#b3261e", anchor="mm")
    return image


def identity_card(person: dict, face_seed: int) -> Image.Image:
    """A sample identity card in a layout of our own. The portrait is a drawn outline, never a photograph, and
    is decided by `face_seed` alone, so a card can be drawn again with another name and the same face."""
    face = random.Random(face_seed)
    width, height = 1000, 630
    image = Image.new("RGB", (width, height), "#f7f4ec")
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, width, 96], fill=BANDS[person["country"]])
    d.text((36, 18), COUNTRY_WORDS[person["country"]], font=font(30, True), fill="white")
    d.text((36, 58), "National identity card. SAMPLE layout, not a real document.", font=font(20), fill="#dfe8f2")
    skin = face.choice(["#c69c7b", "#a8795a", "#d9b596", "#8f6247", "#e0c2a2"])
    hair = face.choice(["#1c1c1c", "#3b2a1e", "#5a4632", "#777777", "#2b2b3a"])
    d.rounded_rectangle([36, 130, 300, 470], radius=10, outline="#8a8f99", width=3,
                        fill=face.choice(["#dfe5ee", "#e8e1d3", "#d5e3da", "#e6dbe6", "#cfd8e6"]))
    cx, top, r = 168 + face.randint(-14, 14), 190 + face.randint(-16, 16), face.randint(52, 70)
    d.pieslice([cx - r - 50, top + 2 * r - 10, cx + r + 50, top + 2 * r + 330], 180, 360,
               fill=face.choice(["#34506b", "#6b3434", "#3f5f45", "#555555", "#70583a"]))
    d.ellipse([cx - r, top, cx + r, top + 2 * r + 14], fill=skin)
    style = face.randint(0, 2)
    if style == 0:
        d.pieslice([cx - r - 6, top - 18, cx + r + 6, top + r + 30], 180, 360, fill=hair)
    elif style == 1:
        d.ellipse([cx - r - 16, top - 22, cx + r + 16, top + r], fill=hair)
        d.rectangle([cx - r - 16, top + 20, cx - r + 4, top + 2 * r + 40], fill=hair)
        d.rectangle([cx + r - 4, top + 20, cx + r + 16, top + 2 * r + 40], fill=hair)
    else:
        d.chord([cx - r, top - 6, cx + r, top + r], 180, 360, fill=hair)
    y = 132
    for label, value in [("Name", person["name"].upper()), ("Date of birth", person["born"]),
                         ("Card number", person["card_number"]), ("Date of issue", person["issued"]),
                         ("Date of expiry", person["expires"]), ("City", person["city"])]:
        d.text((340, y), label, font=font(19), fill="#6a7180")
        d.text((340, y + 22), value, font=font(27, True), fill="#1b2230")
        y += 62
    d.line([36, 500, width - 36, 500], fill="#b9bfca", width=2)
    d.text((36, 512), "Signature", font=font(18), fill="#6a7180")
    words = person["name"].split()
    d.text((150, 506), f"{words[0]} {words[-1][0]}.", font=font(28), fill="#27303f")
    return stamp(image)


def utility_bill(person: dict, rng: random.Random) -> Image.Image:
    """A sample bill from an invented utility, as proof of address."""
    name, colour = rng.choice(UTILITIES)
    width, height = 900, 1100
    image = Image.new("RGB", (width, height), "#ffffff")
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, width, 120], fill=colour)
    d.text((40, 30), name, font=font(40, True), fill="white")
    d.text((40, 84), "SAMPLE statement of account", font=font(20), fill="#f0e8e0")
    d.text((40, 160), person["name"], font=font(28, True), fill="#1b2230")
    d.text((40, 200), person["address"], font=font(22), fill="#1b2230")
    d.text((40, 260), f"Account {rng.randint(10**7, 10**8 - 1)}", font=font(22), fill="#6a7180")
    d.text((width - 40, 160), f"Statement date {person['bill_date']}", font=font(22), fill="#1b2230", anchor="ra")
    y, total = 340, 0.0
    for line in ("Previous balance", "Payment received", "Current charges", "Service fee", "Taxes"):
        amount = round(rng.uniform(40, 2400), 2)
        total += amount
        d.text((40, y), line, font=font(24), fill="#1b2230")
        d.text((width - 40, y), f"{amount:,.2f}", font=font(24), fill="#1b2230", anchor="ra")
        d.line([40, y + 42, width - 40, y + 42], fill="#d0d4db", width=1)
        y += 62
    d.text((40, y + 20), "Amount due", font=font(30, True), fill="#1b2230")
    d.text((width - 40, y + 20), f"{total:,.2f}", font=font(30, True), fill="#1b2230", anchor="ra")
    return stamp(image)


def capture(image: Image.Image, rng: random.Random, photographed: bool) -> bytes:
    """The picture as an upload: a flat scan, or a photograph on a table (a margin, a slight turn), then a new
    brightness, a new size and a JPEG quality of its own."""
    if photographed:
        pad = rng.randint(20, 70)
        table = Image.new("RGB", (image.width + 2 * pad, image.height + 2 * pad),
                          rng.choice(["#5b4a3a", "#2e2e33", "#7a7468", "#3d4a44"]))
        table.paste(image, (pad + rng.randint(-12, 12), pad + rng.randint(-12, 12)))
        image = table.rotate(rng.uniform(-2.5, 2.5), resample=Image.BICUBIC)
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.93, 1.05))
    scale = rng.uniform(0.8, 1.0)
    image = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=rng.randint(68, 92))
    return out.getvalue()


class Maker:
    """Writes claims into one folder. Everything random comes from one seeded generator."""

    def __init__(self, out: Path, seed: int):
        self.out = Path(out)
        self.rng = random.Random(seed)
        self.store = cl.ClaimStore(self.out)
        self.used_names: set[str] = set()
        self.used_numbers: set[str] = set()
        self.counter = 0
        self.truth = {"seed": seed, "rings": {name: [] for name in RINGS}, "honest": [], "look_alikes": {},
                      "paid_before_the_ring_showed": [], "hard_cases": {}}

    # ---- invented people and things ----

    def token(self, n: int) -> str:
        return f"{self.rng.getrandbits(n * 4):0{n}x}"

    def person(self, country: str | None = None, name: str | None = None) -> dict:
        rng = self.rng
        country = country or rng.choice(["PH", "PH", "MX"])
        while name is None or name in self.used_names:
            name = f"{rng.choice(GIVEN[country])} {rng.choice(GIVEN[country]) + ' ' if rng.random() < 0.25 else ''}" \
                   f"{rng.choice(FAMILY[country])}"
            name = " ".join(name.split())
            if len(set(name.split())) < len(name.split()):
                name = None
        self.used_names.add(name)
        city, postcode = rng.choice(CITIES[country])
        words = name.lower().split()
        return {"name": name, "country": country, "city": city,
                "address": f"{rng.randint(2, 980)} {rng.choice(STREETS)} Street, {city} {postcode}",
                "email": f"{words[0]}.{words[-1]}{rng.randint(11, 98)}@{rng.choice(MAIL)}",
                "born": f"19{rng.randint(52, 99)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "card_number": f"S{rng.randint(10**8, 10**9 - 1)}",
                "issued": f"20{rng.randint(19, 24)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "expires": f"20{rng.randint(28, 34)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                "bill_date": f"2026-{rng.randint(6, 8):02d}-{rng.randint(1, 28):02d}",
                "face": rng.getrandbits(32), "network": self.token(16), "agent": self.token(16)}

    def account(self, person: dict, account_name: str | None = None) -> dict:
        """A bank account in the person's own name, in the shape the server stores (claims.set_payee)."""
        from khutlisa import airwallex as awx
        currency, swift = BANK_CODE[person["country"]]
        while True:
            if currency == "MXN":
                first = "002" + "".join(str(self.rng.randint(0, 9)) for _ in range(14))
                number = first + str(awx.clabe_check_digit(first))
            else:
                number = "".join(str(self.rng.randint(0, 9)) for _ in range(self.rng.randint(10, 12)))
            if number not in self.used_numbers:
                self.used_numbers.add(number)
                break
        words = (account_name or person["name"]).split()
        street = person["address"].split(",")[0]
        beneficiary = awx.local_beneficiary(currency, words[0], words[-1], number, swift_code=swift,
                                            street_address=street, city=person["city"])
        return {"currency": currency, "beneficiary": beneficiary, "checked_by": "Khutlisa's own checks (demonstration)"}

    def document(self, kind: str, data: bytes, person: dict, disagree: str | None = None) -> dict:
        """A stored document and what its two readings saw, in the shape the server keeps (documents.py): each
        reading goes through `clean_reading` and the two are put together by `combine_readings`, which is what
        works out the agreement. `disagree` names a field the second reading saw differently."""
        city, postcode = person["address"].rsplit(", ", 1)[-1].rsplit(" ", 1)
        first = {"document_type": "national identity card" if kind == "id" else "utility bill", "names": [person["name"]],
                 "holder_name": person["name"], "legible": True, "marked_sample": True, "signs_of_editing": False,
                 "concerns": [{"kind": "sample_mark", "text": "The document is marked SAMPLE."}],
                 "summary": "A sample document for a demonstration claim."}
        if kind == "id":
            first.update(issue_date=person["issued"], expiry_date=person["expires"], date_of_birth=person["born"],
                         presents_as_government_photo_id=True, photo_present=True,
                         issuing_country=COUNTRY_WORDS[person["country"]].title(), issuing_authority="Sample Civil Registry",
                         dates=[{"label": "date of expiry", "value": person["expires"]}], identifiers_present=["card number"])
        else:
            first.update(issue_date=person["bill_date"], issuer="a sample utility",
                         dates=[{"label": "statement date", "value": person["bill_date"]}],
                         addresses=[{"street": person["address"].split(",")[0], "city": city, "postcode": postcode,
                                     "country": person["country"], "whose": "person"}])
        second = dict(first)
        if disagree == "expiry date":
            year = first["expiry_date"][:4]
            second["expiry_date"] = str(int(year) + 1) + first["expiry_date"][4:]
        elif disagree == "name":
            second["holder_name"] = person["name"].split()[0]
        reading = documents.combine_readings(documents.clean_reading(first), documents.clean_reading(second))
        assert reading["agreement"]["disagreed"] == ([disagree] if disagree else []), reading["agreement"]
        return {"kind": kind, "kind_label": documents.KINDS[kind], "data": data, "reading": reading,
                "filename": "identity-card.jpg" if kind == "id" else "bill.jpg"}

    def identity(self, person: dict, photographed: bool | None = None, disagree: str | None = None) -> dict:
        if photographed is None:
            photographed = self.rng.random() < 0.7        # most people photograph their card; some scan it flat
        return self.document("id", capture(identity_card(person, person["face"]), self.rng, photographed), person, disagree)

    def bill(self, person: dict) -> dict:
        return self.document("proof_of_address", capture(utility_bill(person, self.rng), self.rng, self.rng.random() < 0.5), person)

    # ---- one claim ----

    def claim(self, person: dict, when: datetime, *, holder: str | None = None, state: str = cl.PROOF_READY,
              docs: list[dict] | None = None, payee: dict | None = None, amount: float | None = None,
              network: str | None = None, agent: str | None = None) -> dict:
        rng = self.rng
        self.counter += 1
        claim_id = self.token(16)
        stamp_ = lambda minutes=0: (when + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        amount = amount if amount is not None else round(rng.choice([rng.uniform(60, 900), rng.uniform(900, 6000),
                                                                    rng.uniform(300, 2500)]), 2)
        record_id = f"demo-ring-{self.counter:04d}"
        record = {"record_id": record_id, "source": "DEMO",
                  "owner": " ".join(w[0].upper() + "···" for w in person["name"].split()), "owner_is_organisation": False,
                  "amount": amount, "currency": "USD", "holder_name": holder or rng.choice(HOLDERS),
                  "property_type": rng.choice(KINDS_OF_PROPERTY), "owner_city": rng.choice(["Salinas", "Daly City", "Fresno", "Oxnard", "Stockton"]),
                  "owner_region": "CA", "owner_country": "US"}
        claim = {"id": claim_id, "created_at": stamp_(), "opened": int(when.timestamp() * 1e9), "state": cl.FOUND,
                 "record": record, "property": {"source": "DEMO", "record_id": record_id},
                 "claimant": {"name": person["name"], "address": person["address"], "country": person["country"],
                              "email": person["email"], "relationship": "self"},
                 "match": None, "documents": [], "history": [], "payee": None, "approval": None, "past_approvals": [],
                 "rejection_reason": None, "address_given": [],
                 "origin": {"network": network or person["network"], "agent": agent or person["agent"], "at": stamp_()}}
        note = lambda state_, text, minutes: claim["history"].append({"state": state_, "at": stamp_(minutes), "note": text})
        note(cl.FOUND, "The record was chosen from the search and a claim was opened.", 0)
        note(cl.PROOF_NEEDED, "2 documents are needed before the packet is complete.", 0)
        claim["state"] = cl.PROOF_NEEDED
        if state == cl.PROOF_NEEDED:
            docs = (docs or [])[:1]
        folder = self.store.files(claim_id)
        for n, doc in enumerate(docs or []):
            folder.mkdir(parents=True, exist_ok=True)
            doc_id = self.token(12)
            (folder / f"{doc_id}.jpg").write_bytes(doc["data"])
            claim["documents"].append({"id": doc_id, "kind": doc["kind"], "kind_label": doc["kind_label"],
                                       "filename": doc["filename"], "stored_as": f"{doc_id}.jpg", "content_type": "image/jpeg",
                                       "size": len(doc["data"]), "sha256": hashlib.sha256(doc["data"]).hexdigest(),
                                       "uploaded_at": stamp_(4 + n), "reading": doc["reading"], "read_at": stamp_(5 + n)})
            note(cl.PROOF_NEEDED, f"A document was added: {doc['kind_label'].lower()}.", 4 + n)
        if state != cl.PROOF_NEEDED:
            payee = payee or self.account(person)
            claim["payee"] = {**payee, "hash": cl.digest({"currency": payee["currency"], "beneficiary": payee["beneficiary"]}),
                              "set_at": stamp_(9)}
            note(cl.PROOF_NEEDED, "The claimant gave the bank account to be paid into.", 9)
            note(cl.PROOF_READY, "Every required document is attached.", 10)
            claim["state"] = cl.PROOF_READY
        if state in (cl.APPROVED, cl.PAYING, cl.PAID):
            covered = cl.terms(claim, None, None)
            at = stamp_(60 * 26)
            claim["approval"] = {"at": at, "terms": covered, "terms_hash": cl.digest(covered), "from_state": cl.PROOF_READY,
                                 "replaces_earlier_approval": False, "deadline_at": None, "fee_rule": None}
            note(cl.APPROVED, f"The holder approved the claim for {covered['amount']} USD to the bank account on file.", 60 * 26)
            claim["state"] = cl.APPROVED
        if state == cl.PAID:
            note(cl.PAYING, "The claimant agreed to the payout plan and the payment started.", 60 * 30)
            note(cl.PAID, "The money arrived in the claimant's bank account.", 60 * 31)
            claim["state"] = cl.PAID
        self.store.save(claim)
        return claim

    def day(self, first: int, last: int) -> datetime:
        return START + timedelta(days=self.rng.randint(first, last), minutes=self.rng.randint(0, 9 * 60))

    def honest_state(self) -> str:
        return self.rng.choices([cl.PROOF_READY, cl.APPROVED, cl.PAID, cl.PROOF_NEEDED], [50, 15, 20, 15])[0]

    def honest(self, kind: str, claim: dict) -> dict:
        self.truth["honest"].append(claim["id"])
        if kind != "single":
            self.truth["look_alikes"].setdefault(kind, []).append(claim["id"])
        return claim

    # ---- the honest claims, with the look-alikes ----

    def honest_set(self, total: int) -> None:
        rng = self.rng
        # one person, two properties, one bank account, the same documents
        for _ in range(3):
            p = self.person()
            docs, account = [self.identity(p), self.bill(p)], self.account(p)
            first = self.day(0, 50)
            for n in range(2):
                self.honest("same_person_two_properties", self.claim(p, first + timedelta(days=n * rng.randint(0, 6), minutes=11 * n),
                                                                     docs=docs, payee=account, state=self.honest_state()))
        # married couples: one address, one email domain, one home network; the first couple sends the same bill
        for n in range(2):
            country = rng.choice(["PH", "MX"])
            a = self.person(country)
            b = self.person(country, name=f"{rng.choice([g for g in GIVEN[country] if g not in a['name']])} {a['name'].split()[-1]}")
            domain = a["email"].split("@")[1]
            b.update(address=a["address"], city=a["city"], network=a["network"],
                     email=f"{b['name'].split()[0].lower()}{rng.randint(11, 98)}@{domain}")
            bill = self.bill(a)
            when = self.day(0, 55)
            self.honest("married_couple", self.claim(a, when, docs=[self.identity(a), bill], state=self.honest_state()))
            self.honest("married_couple", self.claim(b, when + timedelta(minutes=rng.randint(20, 300)),
                                                     docs=[self.identity(b), bill if n == 0 else self.bill(b)], state=self.honest_state()))
        # two unrelated people with the same common name, in different countries
        for common in ("Maria Santos Reyes", "Jose Garcia Cruz"):
            for country in ("PH", "MX"):
                self.used_names.discard(common)
                p = self.person(country, name=common)
                self.honest("same_name_other_country", self.claim(p, self.day(0, 55), docs=[self.identity(p), self.bill(p)],
                                                                  state=self.honest_state()))
        # five claims for one large holder inside the same hour, from different networks
        hour = self.day(5, 50)
        for _ in range(5):
            p = self.person()
            self.honest("same_hour_same_holder", self.claim(p, hour + timedelta(minutes=rng.randint(0, 45)), holder=LARGE_HOLDER,
                                                            docs=[self.identity(p), self.bill(p)], state=cl.PROOF_READY))
        # a family on one home network: two at one typed address, a grown child who typed another
        country = rng.choice(["PH", "MX"])
        parent = self.person(country)
        when = self.day(0, 55)
        for n in range(3):
            p = parent if n == 0 else self.person(country, name=f"{rng.choice([g for g in GIVEN[country] if g not in parent['name']])} {parent['name'].split()[-1]}")
            if n == 1:
                p.update(address=parent["address"], city=parent["city"])
            p["network"] = parent["network"]
            self.honest("family_home_network", self.claim(p, when + timedelta(minutes=40 * n), docs=[self.identity(p), self.bill(p)],
                                                          state=self.honest_state()))
        # a helper at a community centre: three unrelated people open their claims on her device
        helper = self.person()
        when = self.day(0, 55)
        for n in range(3):
            p = self.person()
            self.honest("helpers_device", self.claim(p, when + timedelta(days=n, minutes=rng.randint(0, 200)), network=helper["network"],
                                                     agent=helper["agent"], docs=[self.identity(p), self.bill(p)], state=self.honest_state()))
        # a daughter opens claims for three older relatives and neighbours on her own laptop, with her own email
        # address, because they have none. Each claim is in its owner's name, at their address, into their account.
        daughter = self.person()
        when = self.day(0, 55)
        for n in range(3):
            p = self.person()
            p.update(email=daughter["email"])
            self.honest("relative_files_for_three", self.claim(p, when + timedelta(days=n, minutes=rng.randint(0, 200)),
                                                               network=daughter["network"], agent=daughter["agent"],
                                                               docs=[self.identity(p), self.bill(p)], state=self.honest_state()))
        # two siblings whose given names are one letter apart, on the family's network, at different addresses
        country = rng.choice(["PH", "MX"])
        a = self.person(country, name=f"{'Mario' if country == 'MX' else 'Danilo'} {rng.choice(FAMILY[country])}")
        b = self.person(country, name=f"{'Maria' if country == 'MX' else 'Danila'} {a['name'].split()[-1]}")
        b["network"] = a["network"]
        when = self.day(0, 55)
        for p in (a, b):
            self.honest("siblings_one_letter_apart", self.claim(p, when + timedelta(days=rng.randint(0, 3)),
                                                                docs=[self.identity(p), self.bill(p)], state=self.honest_state()))
        # everyone else: unrelated people. A few of their cards were read with a disagreement, as blurred cards are.
        singles = max(total - len(self.truth["honest"]), 0)
        blurred = {0: "expiry date", 1: "expiry date", 2: "expiry date", 3: "name", 4: "name"}
        for n in range(singles):
            p = self.person()
            self.honest("single", self.claim(p, self.day(0, 58), docs=[self.identity(p, disagree=blurred.get(n)), self.bill(p)],
                                             state=self.honest_state()))

    # ---- the rings ----

    def ring(self, name: str, claim: dict) -> dict:
        self.truth["rings"][name].append(claim["id"])
        return claim

    def mule_ring(self) -> None:
        """Five claimants, five owners, one bank account. Each claimant's name contains the account holder's
        name, which is what the server asks of an account. The first was paid before the second existed."""
        rng = self.rng
        country = rng.choice(["PH", "MX"])
        mule = self.person(country)
        account = self.account(mule)
        given, family = mule["name"].split()[0], mule["name"].split()[-1]
        extra = [f for f in FAMILY[country] if f != family]
        names = [mule["name"], f"{given} {family} {rng.choice(extra)}", f"{given} {rng.choice('ABCDEFGJLMNPRST')} {family}",
                 f"{rng.choice([g for g in GIVEN[country] if g != given])} {given} {family}", f"{given} {family} {rng.choice(extra)}"]
        when = self.day(2, 6)
        for n, name in enumerate(names):
            self.used_names.discard(name)
            p = mule if n == 0 else self.person(country, name=name)
            state = cl.PAID if n == 0 else cl.APPROVED if n == 1 else cl.PROOF_READY
            claim = self.ring("mule_account", self.claim(p, when, docs=[self.identity(p, photographed=True), self.bill(p)],
                                                         payee=account, state=state))
            if n == 0:
                self.truth["paid_before_the_ring_showed"].append(claim["id"])
            when += timedelta(days=rng.randint(4, 9), minutes=rng.randint(0, 300))

    def forged_ring(self) -> None:
        """One identity card picture, four names. Three copies are the same file with the name changed and saved
        again. The fourth was printed and photographed again, which no comparison of pictures can follow."""
        rng = self.rng
        country = rng.choice(["PH", "MX"])
        base = self.person(country)
        when = self.day(8, 30)
        for n in range(4):
            p = self.person(country)
            card = {**base, "name": p["name"]}                 # the card's face, numbers and dates never change
            data = capture(identity_card(card, base["face"]), rng, photographed=(n == 3))
            read_as = {**p, "born": base["born"], "issued": base["issued"], "expires": base["expires"]}
            doc = self.document("id", data, read_as, disagree="expiry date" if n != 1 else None)
            claim = self.ring("forged_identity", self.claim(p, when, docs=[doc, self.bill(p)],
                                                            state=cl.APPROVED if n == 0 else cl.PROOF_READY))
            if n == 3:
                self.truth["hard_cases"]["forged_card_photographed_again"] = claim["id"]
            when += timedelta(days=rng.randint(1, 6), minutes=rng.randint(0, 300))

    def variant_ring(self) -> None:
        """Four claims in a few minutes for one holder, under names a letter or two apart, with one mailbox
        written four ways and one device."""
        rng = self.rng
        country = rng.choice(["PH", "MX"])
        base = self.person(country)
        given, family = base["name"].split()[0], base["name"].split()[-1]

        def nudge(word: str) -> str:
            at = rng.randint(1, len(word) - 2)
            return rng.choice([word[:at] + word[at + 1:], word[:at] + word[at] + word[at:],
                               word[:at] + rng.choice("aeiou") + word[at + 1:]])
        names = [f"{given} {family}"]
        while len(names) < 4:
            name = rng.choice([f"{nudge(given)} {family}", f"{given} {nudge(family)}", f"{given} {rng.choice('ABDEGLMR')} {family}"])
            if name not in names and rings.name_key(name) not in {rings.name_key(n) for n in names}:
                names.append(name)
        local = f"{given}{family}{rng.randint(11, 98)}".lower()
        mailboxes = [f"{local}@gmail.com", f"{local[:3]}.{local[3:]}@gmail.com", f"{local}+claims@gmail.com",
                     f"{local[:5]}.{local[5:]}+b@googlemail.com"]
        when = self.day(20, 50)
        for n, name in enumerate(names):
            self.used_names.discard(name)
            p = self.person(country, name=name)
            p.update(email=mailboxes[n], network=base["network"], agent=base["agent"])
            self.ring("name_variant_burst", self.claim(p, when, holder=BURST_HOLDER, docs=[self.identity(p), self.bill(p)],
                                                       state=cl.PROOF_READY))
            when += timedelta(minutes=rng.randint(2, 7))


def generate(out: Path | str, seed: int = 7, honest: int = 60) -> dict:
    """Writes the claims and `ground_truth.json` into `out` (emptied first) and returns the ground truth."""
    out = Path(out)
    if out.exists():
        if any(out.iterdir()) and not (out / "ground_truth.json").exists():
            raise SystemExit(f"{out} holds something this script did not make. Choose an empty folder.")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    maker = Maker(out, seed)
    maker.honest_set(honest)
    maker.mule_ring()
    maker.forged_ring()
    maker.variant_ring()
    (out / "ground_truth.json").write_text(json.dumps(maker.truth, indent=2, sort_keys=True))
    return maker.truth


# ---- the measurement -----------------------------------------------------------------------------------------

def measure(folder: Path | str, write: bool = True) -> dict:
    """Runs the detector over the claims in `folder` and compares what it holds with the ground truth there.
    The detector is given the claims folder and nothing else."""
    folder = Path(folder)
    store = cl.ClaimStore(folder)
    detector = rings.Rings(store)
    found = detector.sync()
    claims = {c["id"]: c for c in store.all()}
    truth = json.loads((folder / "ground_truth.json").read_text())        # read only after the detector has run
    status = {i: (c.get("risk") or {}).get("status") or rings.CLEAR for i, c in claims.items()}
    group_of = {i: g for g in found["groups"] for i in g["members"]}
    ordered = sorted(claims.values(), key=lambda c: (c["created_at"], c["id"]))
    per_ring = {}
    for name, members in truth["rings"].items():
        groups = {group_of[i]["id"]: group_of[i] for i in members if i in group_of}
        # replay the queue in the order the claims were opened: at which of the ring's claims was it first flagged?
        flagged_at = None
        mine = [c for c in ordered if c["id"] in members]
        for n, last in enumerate(mine, start=1):
            so_far = [c for c in ordered if (c["created_at"], c["id"]) <= (last["created_at"], last["id"])]
            partly = rings.analyse(so_far, detector.hashes_for(so_far))
            if any(g["flagged"] and set(g["members"]) & set(members) for g in partly["groups"]):
                flagged_at = n
                break
        per_ring[name] = {
            "claims": len(members),
            "held_before_payment": sum(1 for i in members if status[i] in rings.BLOCKED),
            "paid_before_the_ring_showed": sum(1 for i in members if status[i] == rings.PAID_BEFORE),
            "missed": sum(1 for i in members if status[i] not in rings.BLOCKED + (rings.PAID_BEFORE,)),
            "signals": sorted({row["kind"] for g in groups.values() if g["flagged"] for row in g["table"]}),
            "points": max((g["points"] for g in groups.values()), default=0),
            "flagged_when_claim_number_arrived": flagged_at,
        }
    honest = truth["honest"]
    wrongly = [i for i in honest if status[i] in rings.BLOCKED]
    kind_of = {i: kind for kind, ids in truth["look_alikes"].items() for i in ids}
    ring_ids = [i for members in truth["rings"].values() for i in members]
    result = {
        "seed": truth["seed"], "claims": len(claims), "measured_at": cl.now(),
        "ring_claims": len(ring_ids),
        "ring_claims_caught": sum(1 for i in ring_ids if status[i] in rings.BLOCKED),
        "ring_claims_paid_before": sum(1 for i in ring_ids if status[i] == rings.PAID_BEFORE),
        "ring_claims_missed": sum(1 for i in ring_ids if status[i] not in rings.BLOCKED + (rings.PAID_BEFORE,)),
        "rings": len(truth["rings"]), "rings_flagged": sum(1 for r in per_ring.values() if r["signals"]),
        "honest_claims": len(honest), "honest_claims_held": len(wrongly),
        "honest_held_kinds": sorted(kind_of.get(i, "single") for i in wrongly),
        "honest_claims_in_a_held_group": sum(1 for i in honest if i in group_of and group_of[i]["flagged"]),
        "honest_linked_below_the_line": sum(1 for i in honest if i in group_of and not group_of[i]["flagged"]),
        "per_ring": per_ring,
        "hard_cases": {k: status.get(v) for k, v in truth.get("hard_cases", {}).items()},
    }
    if write:
        (folder / "ring_measurement.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def in_words(result: dict) -> str:
    lines = [f"Seed {result['seed']}: {result['claims']} claims.",
             f"  Ring claims held before payment: {result['ring_claims_caught']} of {result['ring_claims']}"
             f" ({result['ring_claims_paid_before']} had been paid before the ring showed, {result['ring_claims_missed']} missed).",
             f"  Honest claims wrongly held: {result['honest_claims_held']} of {result['honest_claims']}"
             + (f" ({', '.join(sorted(set(result['honest_held_kinds'])))}; {result['honest_claims_in_a_held_group']} honest claims"
                f" are in a held group, counting any already paid)." if result["honest_held_kinds"] else "."),
             f"  Honest claims linked but not held: {result['honest_linked_below_the_line']}."]
    for name, ring in result["per_ring"].items():
        lines.append(f"  {name}: {ring['held_before_payment']} of {ring['claims']} held, {ring['paid_before_the_ring_showed']} paid before, "
                     f"{ring['missed']} missed; {ring['points']} points from {', '.join(ring['signals']) or 'nothing'}; "
                     f"flagged when its claim number {ring['flagged_when_claim_number_arrived']} arrived.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--honest", type=int, default=60)
    parser.add_argument("--other-seeds", type=int, nargs="*", default=[11, 23, 42])
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    if not args.measure_only:
        generate(args.out, args.seed, args.honest)
        print(f"Wrote the demonstration claims to {args.out}. Every person in them is invented.")
    print(in_words(measure(args.out)))
    for seed in [] if args.measure_only else args.other_seeds:
        with tempfile.TemporaryDirectory() as tmp:
            generate(Path(tmp) / "claims", seed, args.honest)
            print(in_words(measure(Path(tmp) / "claims", write=False)))


if __name__ == "__main__":
    main()
