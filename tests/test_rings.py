"""The ring detector on claim files made here: each signal alone, the honest look-alikes, the graph, the points,
the threshold, the image hash, and the generator with the measurement. Nothing here touches the network."""
import base64
import importlib.util
import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageEnhance

from khutlisa import claims as cl
from khutlisa import rings

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_ring_claims", ROOT / "scripts" / "make_ring_claims.py")
maker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maker)

_n = iter(range(1, 10**6))
# People who share no word and are no variants of each other.
PEOPLE = ["Ana Reyes", "Bela Cruz", "Caloy Lim", "Dina Uy", "Efren Sy", "Gina Go", "Hilda Ko", "Ismael Tan",
          "Jovita Ong", "Karding Yap", "Lorna Chua", "Manolo Dy"]


def bank(number="1234567890", name=None, country="PH"):
    name = name or f"Holder Number{next(_n)}"
    return {"currency": "PHP", "hash": f"h{number}{name}",
            "beneficiary": {"beneficiary": {"bank_details": {"account_number": number, "account_name": name,
                                                             "bank_country_code": country}}}}


def claim(name="Ana Reyes", *, email=None, address=None, country="PH", account=None, holder="Acme Payroll",
          minute=None, docs=(), network=None, agent=None, state=cl.PROOF_READY, phone=None, heirs=None, record=None):
    """One claim file with just the parts the detector reads. Every part is unique unless it is given."""
    n = next(_n)
    claimant = {"name": name, "country": country, "relationship": "self",
                "email": email or f"person{n}@post{n}.example", "address": address or f"{n} Unique Street, Town{n} 1000"}
    if phone:
        claimant["phone"] = phone
    made = {"id": f"{n:016x}", "state": state, "created_at": f"2026-10-{1 + n % 27:02d}T{n % 24:02d}:00:00+00:00",
            "record": {"holder_name": holder, "amount": 100.0 + n, "currency": "USD", "source": "TEST",
                       "record_id": record or f"R{n}"},
            "property": {"source": "TEST", "record_id": record or f"R{n}"}, "claimant": claimant,
            "payee": account, "documents": list(docs), "history": [],
            "origin": {"network": network or f"net{n}", "agent": agent or f"agent{n}"}}
    if minute is not None:
        made["created_at"] = f"2026-11-01T10:{minute:02d}:00+00:00"
    if heirs is not None:
        made["estate"] = {"heirs": heirs}
    return made


def doc(sha, kind="id", disagreed=()):
    return {"id": sha[:6], "kind": kind, "sha256": sha, "stored_as": f"{sha[:6]}.jpg", "content_type": "image/jpeg",
            "reading": {"status": "read", "agreement": {"status": "disagree" if disagreed else "agree",
                                                        "disagreed": list(disagreed)}}}


def signals(a, b, *others, hashes=None):
    found = rings.analyse([a, b, *others], hashes or {})
    return set(found["edges"].get(tuple(sorted((a["id"], b["id"]))), {}))


def groups(*claims, hashes=None):
    return rings.analyse(list(claims), hashes or {})["groups"]


# ---- each signal alone, and the honest situation beside it -----------------------------------------------------

def test_the_same_bank_account_for_different_claimants_is_a_signal_and_holds_by_itself():
    a, b = claim("Ana Reyes", account=bank("5550001111")), claim("Bela Cruz", account=bank("5550001111"))
    assert signals(a, b) == {"account"}
    (group,) = groups(a, b)
    assert group["flagged"] and group["points"] == 60 and group["shared"][0]["element"] == "account ending 1111"
    assert signals(claim(account=bank("5550001111")), claim("Bela Cruz", account=bank("5550002222"))) == set()
    # the same number at a bank in another country is another account
    assert signals(claim(account=bank("5550001111", country="PH")), claim("Bela Cruz", account=bank("5550001111", country="MX"))) == set()


def test_one_person_with_two_properties_and_one_account_is_not_a_ring():
    shared = dict(email="ana@post.example", address="14 Mango Avenue, Cebu City 6000", account=bank("5550001111"),
                  network="home", agent="phone", docs=[doc("a" * 64)])
    a, b = claim("Ana Luz Reyes", **shared), claim("Reyes Ana Luz", **shared)
    assert signals(a, b) == set() and groups(a, b) == []
    # the same name in another country, or with nothing else in common, is another person
    other = claim("Ana Luz Reyes", country="MX", account=bank("5550001111"))
    assert "account" in signals(a, other)
    # a fourth property under the one name is past what one person is given without a look
    many = [claim("Ana Luz Reyes", **shared) for _ in range(4)]
    assert groups(*many)[0]["flagged"]


def test_an_heirs_account_and_contact_belong_to_the_estate_claim_and_heirs_of_one_estate_are_not_compared():
    heirs = [{"id": "h1", "name": "Bela Cruz", "email": "bela@post.example", "payee": bank("7770001111", "Bela Cruz")},
             {"id": "h2", "name": "Caloy Cruz", "email": "bela@post.example", "payee": bank("7770001111", "Bela Cruz")},
             {"id": "h3", "name": "Dina Cruz", "payee": None}]
    estate = claim("Ana Reyes", heirs=heirs)
    assert groups(estate) == []                                   # two heirs of one estate sharing an account
    other = claim("Efren Lim", account=bank("7770001111", "Bela Cruz"))
    assert signals(estate, other) == {"account"}
    third = claim("Gina Uy", email="Bela@post.example")
    assert signals(estate, third) == {"email"}


def test_accounts_in_one_holders_name_are_a_weak_signal_that_links_nothing():
    a = claim("Jose Garcia Cruz", country="PH", account=bank("111122223333", "Jose Garcia"))
    b = claim("Jose Garcia Cruz", country="MX", account=bank("444455556666", "Jose Garcia", "MX"))
    assert signals(a, b) == {"account_name"}                      # two honest people with one common name
    assert groups(a, b) == []


def test_the_same_document_file_in_two_claims_is_a_signal_and_a_pdf_is_compared_by_file_only():
    a, b = claim("Ana Reyes", docs=[doc("a" * 64)]), claim("Bela Cruz", docs=[doc("a" * 64)])
    assert signals(a, b) == {"document"} and groups(a, b)[0]["flagged"]
    pdf = {**doc("b" * 64, "proof_of_address"), "content_type": "application/pdf"}
    assert signals(claim("Ana Reyes", docs=[pdf]), claim("Bela Cruz", docs=[dict(pdf)])) == {"document"}
    assert signals(claim(docs=[doc("c" * 64)]), claim("Bela Cruz", docs=[doc("d" * 64)])) == set()


def test_contacts_reused_by_unrelated_claimants_are_signals_and_emails_are_normalised():
    assert rings.email_key(" Ana.Reyes+claims@GMail.com ") == rings.email_key("anareyes@googlemail.com") == "anareyes@gmail.com"
    assert rings.email_key("ana.reyes@post.example") != rings.email_key("anareyes@post.example")     # dots matter elsewhere
    assert rings.email_key("ana+x@post.example") == "ana@post.example" and rings.email_key("not an email") == ""
    a, b = claim("Ana Reyes", email="ana.reyes+one@gmail.com"), claim("Bela Cruz", email="AnaReyes@gmail.com")
    assert signals(a, b) == {"email"}
    (group,) = groups(a, b)
    assert not group["flagged"] and group["points"] == 30          # linked and shown, not held
    assert signals(claim(phone="+63 917 555 0101"), claim("Bela Cruz", phone="0917-555-0101")) == {"phone"}
    same_street = ("14 Mango Avenue, Lahug, Cebu City 6000", "14 mango ave lahug cebu city 6000")
    assert signals(claim("Ana Reyes", address=same_street[0]), claim("Bela Cruz", address=same_street[1])) == {"address"}
    assert groups(claim("Ana Reyes", address=same_street[0]), claim("Bela Cruz", address=same_street[1])) == []
    assert signals(claim(address="14 Mango Avenue, Cebu City"), claim("Bela Cruz", address="15 Mango Avenue, Cebu City")) == set()


def test_a_married_couple_at_one_address_is_a_household_and_not_a_ring():
    home = dict(address="27 Sampaguita Lane, Lahug, Cebu City 6000", network="home")
    bill = doc("e" * 64, "proof_of_address")
    a = claim("Ana Dalisanto", email="ana@family.example", docs=[bill, doc("1" * 64)], **home)
    b = claim("Berto Dalisanto", email="ana@family.example", docs=[bill, doc("2" * 64)], agent=a["origin"]["agent"], **home)
    assert signals(a, b) == set() and groups(a, b) == []          # address, network, device, email and the shared bill
    # what a household does not explain still counts: one bank account, or one identity document
    assert signals({**a, "payee": bank("5550001111")}, {**b, "payee": bank("5550001111")}) == {"account"}
    assert signals({**a, "documents": [doc("9" * 64)]}, {**b, "documents": [doc("9" * 64)]}) == {"document"}
    # strangers at one address are not a household, and an address alone links nothing
    c = claim("Carlos Montoyasa", address=home["address"])
    assert signals(a, c) == {"address"} and groups(a, c) == []


def test_a_shared_network_or_device_never_links_claims():
    a, b = claim("Ana Reyes", network="cafe"), claim("Bela Cruz", network="cafe")
    assert signals(a, b) == {"network"} and groups(a, b) == []
    c, d = claim("Ana Reyes", network="centre", agent="tablet"), claim("Bela Cruz", network="centre", agent="tablet")
    assert signals(c, d) == {"device"} and groups(c, d) == []
    # a network behind more claims than NETWORK_CROWD is shared by too many people to mean anything
    crowd = [claim(PEOPLE[i], network="proxy") for i in range(rings.NETWORK_CROWD + 1)]
    assert rings.analyse(crowd, {})["edges"] == {}


def test_a_burst_for_one_holder_is_a_signal_only_inside_the_window_and_only_from_four_claims():
    burst = [claim(PEOPLE[i], holder="Big Payroll", minute=5 * i) for i in range(4)]
    found = rings.analyse(burst, {})
    assert all(set(s) == {"burst"} for s in found["edges"].values()) and len(found["edges"]) == 6
    assert found["groups"] == []                                   # a burst alone holds nothing
    three = [claim(PEOPLE[i], holder="Big Payroll", minute=5 * i) for i in range(3)]
    assert rings.analyse(three, {})["edges"] == {}
    slow = [claim(PEOPLE[i], holder="Big Payroll", minute=15 * i) for i in range(4)]     # 45 minutes
    assert rings.analyse(slow, {})["edges"] == {}
    mixed = [claim(PEOPLE[i], holder=f"Holder {i}", minute=i) for i in range(4)]
    assert rings.analyse(mixed, {})["edges"] == {}


def test_a_field_that_disagrees_in_three_claims_is_a_pattern_and_in_two_it_is_not():
    def with_doubt(name, field="expiry date", kind="id"):
        return claim(name, docs=[doc(f"{next(_n):064x}", kind, [field])])
    two = [with_doubt("Ana Reyes"), with_doubt("Bela Cruz")]
    assert rings.analyse(two, {})["edges"] == {}
    three = two + [with_doubt("Caloy Lim")]
    found = rings.analyse(three, {})
    assert len(found["edges"]) == 3 and all(set(s) == {"reading_pattern"} for s in found["edges"].values())
    assert found["groups"] == []
    # another field, or the same field on another kind of document, is another pattern
    other = [with_doubt("Ana Reyes"), with_doubt("Bela Cruz"), with_doubt("Caloy Lim", "name"), with_doubt("Dina Uy", kind="payslip")]
    assert rings.analyse(other, {})["edges"] == {}


@pytest.mark.parametrize("a, b, variant", [
    ("Corazon Villaluz", "Corason Villaluz", True),          # one letter
    ("Corazon Villaluz", "Corazon Vilaluz", True),           # a doubled letter dropped
    ("Corazon Villaluz", "Corazon B Villaluz", True),        # an added initial
    ("Corazon Villaluz", "Corason Vilaluz", True),           # both words, one letter each
    ("Mario Dela Rama", "Maria Dela Rama", True),            # siblings look the same, which is why it is not enough alone
    ("Corazon Villaluz", "Villaluz Corazon", False),         # the same name in another order
    ("Corazon Villaluz", "Corazon Villaluz", False),         # identical: two honest people can share a common name
    ("Maria Santos", "Jose Santos", False),                  # a shared family name only
    ("Maria Santos", "Maria Reyes", False),                  # a shared given name only
    ("Teodoro Balmaceda", "Teodoro Balmaceda Ruiz", False),  # a further family name is another name
    ("Ana Lim", "Ana Sim", True),                            # ANA is shared, LIM and SIM are one letter apart
    ("Jo Uy", "Jo Ty", False),                               # nothing of three letters is shared
])
def test_name_variants_are_near_identical_names_that_are_not_identical(a, b, variant):
    assert rings.name_variant(a, b) is variant and rings.name_variant(b, a) is variant


def test_a_name_variant_alone_links_nothing_and_with_a_shared_network_it_links_without_holding():
    a, b = claim("Mario Delamora"), claim("Maria Delamora")
    assert signals(a, b) == {"name_variant"} and groups(a, b) == []
    a, b = claim("Mario Delamora", network="family"), claim("Maria Delamora", network="family")
    (group,) = groups(a, b)
    assert group["points"] == 35 and not group["flagged"]
    # two claims on one property are rivals for it, which the property queue handles; they are not variants here
    assert signals(claim("Mario Delamora", record="R-one"), claim("Maria Delamora", record="R-one")) == set()


# ---- the graph, the points and the threshold -------------------------------------------------------------------

def test_every_point_is_named_and_the_rating_is_their_sum():
    values = {kind: points for kind, (points, _, _) in rings.POINTS.items()}
    assert values == {"account": 60, "document": 60, "image": 50, "email": 30, "phone": 30, "name_variant": 25,
                      "device": 20, "account_name": 15, "reading_pattern": 15, "network": 10, "address": 10, "burst": 10}
    assert (rings.LINK_AT, rings.FLAG_AT) == (30, 60) and rings.SIZE_POINTS == ((5, 20, "five or more claims are linked"),
                                                                              (3, 10, "three or more claims are linked"))
    ring = [claim(n, email=f"c.villaluz+{i}@gmail.com", network="one", agent="one", holder="Camino", minute=3 * i)
            for i, n in enumerate(["Corazon Villaluz", "Corason Villaluz", "Corazon Vilaluz", "Corazon B Villaluz"])]
    (group,) = groups(*ring)
    table = {row["kind"]: row["points"] for row in group["table"]}
    assert table == {"email": 30, "name_variant": 25, "device": 20, "burst": 10, "size": 10}
    assert group["points"] == sum(table.values()) == 95 and group["flagged"]
    assert all(row["words"] and row["claims"] for row in group["table"])
    assert {e["kind"] for e in group["shared"]} == {"email", "name_variant", "device", "burst"}
    assert group["shared"][0]["claims"] == sorted(c["id"] for c in ring) and group["shared"][0]["element"] == "c···@gmail.com"
    for edge in group["edges"]:
        assert edge["points"] == sum(s["points"] for s in edge["signals"])


def test_weak_signals_never_reach_the_line_whatever_their_sum():
    # the same network and device, the same address (no shared name, so not a household), a burst, accounts in one name
    weak = [claim(PEOPLE[i], address="1 Shared Yard, Old Town 1000", network="one", agent="one",
                  holder="Big Payroll", minute=i, account=bank(f"90000000{i}", "Sam Holder"),
                  docs=[doc(f"{i}" * 64, "id", ["expiry date"])]) for i in range(5)]
    found = rings.analyse(weak, {})
    pair = next(iter(found["edges"].values()))
    assert set(pair) == {"address", "device", "burst", "account_name", "reading_pattern"}
    assert sum(s["points"] for s in pair.values()) == 70 >= rings.FLAG_AT       # more than the line, and still
    assert found["groups"] == []                                                # nothing links, so nothing is held


def test_the_threshold_between_linked_and_held():
    email = dict(email="shared@post.example")
    assert not groups(claim("Ana Reyes", **email), claim("Bela Cruz", **email))[0]["flagged"]                        # 30
    both = groups(claim("Ana Reyes", **email, network="n", agent="a"), claim("Bela Cruz", **email, network="n", agent="a"))
    assert both[0]["points"] == 50 and not both[0]["flagged"]                                                         # 30 + 20
    three = groups(*[claim(PEOPLE[i], **email, network="n", agent="a") for i in range(3)])
    assert three[0]["points"] == 60 and three[0]["flagged"]                                                           # 30 + 20 + 10
    phone = groups(claim("Ana Reyes", **email, phone="09175550101"), claim("Bela Cruz", **email, phone="09175550101"))
    assert phone[0]["points"] == 60 and phone[0]["flagged"]                                                           # 30 + 30


def test_groups_are_the_connected_parts_and_an_honest_claim_on_a_shared_network_is_not_pulled_in():
    a, b = claim("Ana Reyes", account=bank("5550001111")), claim("Bela Cruz", account=bank("5550001111"), network="cafe")
    c = claim("Caloy Lim", account=bank("5550001111"), email="caloy@post.example")
    d = claim("Dina Uy", email="caloy@post.example")                      # reaches the ring through one email
    bystander = claim("Efren Sy", network="cafe")                         # shares only a network with a ring member
    unrelated = [claim("Gina Go", email="x@post.example"), claim("Hilda Ko", email="x@post.example")]
    found = rings.analyse([a, b, c, d, bystander, *unrelated], {})
    by_members = {tuple(sorted(g["members"])): g for g in found["groups"]}
    ring = by_members[tuple(sorted(x["id"] for x in (a, b, c, d)))]
    assert ring["flagged"] and bystander["id"] not in found["by_claim"]
    assert not by_members[tuple(sorted(x["id"] for x in unrelated))]["flagged"]
    assert found["groups"][0] is ring                                     # the strongest group comes first
    assert found["by_claim"][d["id"]]["links"] and found["by_claim"][d["id"]]["group"] == ring["id"]


# ---- the image hash ----------------------------------------------------------------------------------------------

def card_bytes(person, face, rng, photographed=False):
    return maker.capture(maker.identity_card(person, face), rng, photographed)


def card_hash(tmp_path, data):
    path = tmp_path / f"{next(_n)}.jpg"
    path.write_bytes(data)
    return rings.image_hash(path)


def test_the_image_hash_follows_a_lightly_edited_copy_and_tells_two_people_apart(tmp_path):
    for seed in (1, 2, 3):
        rng = random.Random(seed)
        make = maker.Maker(tmp_path / f"people{seed}", seed)
        base, other = make.person("PH"), make.person("PH")
        original = card_hash(tmp_path, card_bytes(base, base["face"], rng))
        # saved again at another size, brightness and quality: every tile is the same
        again = card_hash(tmp_path, card_bytes(base, base["face"], rng))
        assert rings.tiles_apart(original, again) <= 2
        # the same picture with another name on it: a few tiles
        edited = card_hash(tmp_path, card_bytes({**base, "name": other["name"]}, base["face"], rng))
        assert rings.tiles_apart(original, edited) <= rings.NEAR_IMAGE_TILES
        # another person's card from the same template, and the same card photographed on a table
        assert rings.tiles_apart(original, card_hash(tmp_path, card_bytes(other, other["face"], rng))) > rings.NEAR_IMAGE_TILES
        assert rings.tiles_apart(original, card_hash(tmp_path, card_bytes(base, base["face"], rng, True))) > rings.NEAR_IMAGE_TILES
        # a different kind of document altogether
        bill = card_hash(tmp_path, maker.capture(maker.utility_bill(base, rng), rng, False))
        assert rings.tiles_apart(original, bill) > 40


def test_the_image_hash_survives_a_brighter_png_copy_and_gives_none_for_what_is_not_a_picture(tmp_path):
    make = maker.Maker(tmp_path / "people", 5)
    person = make.person("MX")
    card = maker.identity_card(person, person["face"])
    card.save(tmp_path / "card.png")
    ImageEnhance.Brightness(card).enhance(1.04).resize((700, 441), Image.LANCZOS).save(tmp_path / "copy.png")
    a, b = rings.image_hash(tmp_path / "card.png"), rings.image_hash(tmp_path / "copy.png")
    assert a != b and rings.tiles_apart(a, b) == 0
    (tmp_path / "file.pdf").write_bytes(b"%PDF-1.4\n" + b"0" * 64)
    assert rings.image_hash(tmp_path / "file.pdf") is None and rings.image_hash(tmp_path / "missing.jpg") is None
    assert rings.tiles_apart(a, "not a hash") == rings.TILES


def test_tiles_apart_agrees_with_a_plain_count_on_random_pictures():
    """`tiles_apart` stops early and looks at brightness first. On random pictures it must give the same count as
    the definition written out plainly."""
    rng = random.Random(11)
    size = (rings.TILES_ACROSS * rings.TILE, rings.TILES_DOWN * rings.TILE)

    def as_hash(image):
        return base64.b64encode(image.tobytes()).decode()

    def plain(a, b):
        a, b = base64.b64decode(a), base64.b64decode(b)
        count = 0
        for ty in range(rings.TILES_DOWN):
            for tx in range(rings.TILES_ACROSS):
                at = [y * size[0] + x for y in range(ty * 8, ty * 8 + 8) for x in range(tx * 8, tx * 8 + 8)]
                ma, mb = sum(a[i] for i in at) / 64, sum(b[i] for i in at) / 64
                pattern = sum(abs((a[i] - ma) - (b[i] - mb)) for i in at)
                count += abs(ma - mb) > rings.TILE_MEAN_APART or pattern > rings.TILE_PATTERN_APART * 64
        return count

    for _ in range(25):
        first = Image.new("L", size)
        first.putdata([rng.randint(0, 255) for _ in range(size[0] * size[1])])
        second = first.copy()
        for _ in range(rng.randint(0, 12)):                       # change a few random tiles, by a random amount
            tx, ty = rng.randrange(rings.TILES_ACROSS), rng.randrange(rings.TILES_DOWN)
            patch = Image.new("L", (8, 8))
            patch.putdata([rng.randint(0, 255) if rng.random() < 0.5 else first.getpixel((tx * 8 + i % 8, ty * 8 + i // 8))
                           for i in range(64)])
            second.paste(patch, (tx * 8, ty * 8))
        a, b = as_hash(first), as_hash(second)
        assert rings.tiles_apart(a, b) == plain(a, b)
        assert rings.tiles_apart(a, a) == 0
        assert (rings.tiles_apart(a, b, stop_after=3) > 3) == (plain(a, b) > 3)


def test_near_identical_pictures_are_a_signal_for_identity_documents_only(tmp_path):
    rng = random.Random(4)
    make = maker.Maker(tmp_path / "people", 4)
    base, second, third = make.person("PH"), make.person("PH"), make.person("PH")
    files = [card_bytes({**base, "name": p["name"]}, base["face"], rng) for p in (base, second, third)]
    shas = [cl.sha256(f) for f in files]
    hashes = {sha: card_hash(tmp_path, data) for sha, data in zip(shas, files)}
    a, b, c = (claim(p["name"], docs=[doc(sha)]) for p, sha in zip((base, second, third), shas))
    assert signals(a, b, hashes=hashes) == {"image"}
    (pair,) = groups(a, b, hashes=hashes)
    assert pair["points"] == 50 and not pair["flagged"]            # two near-identical pictures alone are not held
    (three,) = groups(a, b, c, hashes=hashes)
    assert three["points"] == 60 and three["flagged"]              # a third claim on the same picture is
    assert groups(a, {**b, "origin": a["origin"]}, hashes=hashes)[0]["flagged"]        # and so is one more signal: 50 + 20
    # bills from one template differ in a few words by nature: they are compared as files, never as pictures
    as_bills = [claim(p["name"], docs=[doc(sha, "proof_of_address")]) for p, sha in zip((base, second), shas)]
    assert signals(*as_bills, hashes=hashes) == set()


def test_the_image_hash_is_worked_out_once_per_file_and_kept_beside_the_claims(tmp_path, monkeypatch):
    store = cl.ClaimStore(tmp_path / "claims")
    detector = rings.Rings(store)
    make = maker.Maker(tmp_path / "people", 9)
    person = make.person("PH")
    made = make.claim(person, maker.START, docs=[make.identity(person), make.bill(person)])
    store.save({**made})                      # the maker wrote into its own folder; copy the claim and its files
    (store.files(made["id"])).mkdir(parents=True)
    for d in made["documents"]:
        (store.files(made["id"]) / d["stored_as"]).write_bytes((make.store.files(made["id"]) / d["stored_as"]).read_bytes())
    calls = []
    real = rings.image_hash
    monkeypatch.setattr(rings, "image_hash", lambda path: calls.append(path) or real(path))
    first = detector.hashes_for(store.all())
    assert len(calls) == 2 and all(first[d["sha256"]] for d in made["documents"])
    detector.hashes_for(store.all())
    assert len(calls) == 2                                         # nothing is hashed twice
    assert set(json.loads(detector.hashes_path.read_text())) == {d["sha256"] for d in made["documents"]}
    assert rings.Rings(store).hashes_for(store.all()) == first and len(calls) == 2     # a new process reads the file


# ---- masking -------------------------------------------------------------------------------------------------------

def test_shared_elements_are_masked():
    assert rings.mask_account("0020 1007 7777 7777 71") == "account ending 7771"
    assert rings.mask_email("maria.santos@example.org") == "m···@example.org"
    assert rings.mask_phone("+63 917 555 0142") == "phone ending 42"
    assert rings.mask_address("14 Mango Avenue, Lahug, Cebu City 6000") == "an address starting 14 Man···"
    assert rings.mask_person("Rafael Montoya Cruz") == "Rafael M. C." and rings.mask_person("") == "A claimant"


# ---- the generator and the measurement -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp("rings") / "claims"
    truth = maker.generate(folder, seed=3, honest=40)
    return folder, truth, maker.measure(folder)


def test_the_generator_writes_invented_claims_with_three_rings_and_the_same_set_for_the_same_seed(generated, tmp_path):
    folder, truth, _ = generated
    claims = cl.ClaimStore(folder).all()
    assert len(claims) == 53 and len(truth["honest"]) == 40
    assert {name: len(ids) for name, ids in truth["rings"].items()} == {"mule_account": 5, "forged_identity": 4,
                                                                         "name_variant_burst": 4}
    assert set(truth["look_alikes"]) == {"same_person_two_properties", "married_couple", "same_name_other_country",
                                         "same_hour_same_holder", "family_home_network", "helpers_device",
                                         "relative_files_for_three", "siblings_one_letter_apart"}
    assert all(c["record"]["source"] == "DEMO" and c["record"]["owner"].endswith("···") for c in claims)
    for c in claims:
        for d in c["documents"]:
            stored = folder / c["id"] / d["stored_as"]
            assert stored.is_file() and cl.sha256(stored.read_bytes()) == d["sha256"]
            assert d["reading"]["marked_sample"] is True
    again = maker.generate(tmp_path / "again", seed=3, honest=40)
    assert again == truth
    assert maker.generate(tmp_path / "other", seed=4, honest=40) != truth
    # it refuses to empty a folder it did not make
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "notes.txt").write_text("keep")
    with pytest.raises(SystemExit):
        maker.generate(tmp_path / "mine", seed=3)


def test_the_detector_on_the_generated_set_holds_the_rings_and_says_which_honest_claims_it_held(generated):
    folder, truth, result = generated
    # The one honest case that is held: a daughter who opened three relatives' claims with her own email address on
    # her own laptop. One of the three had been paid already, so two are held. Every other look-alike passes.
    assert result["honest_claims"] == 40 and result["honest_claims_held"] == 2
    assert set(result["honest_held_kinds"]) == {"relative_files_for_three"} and result["honest_claims_in_a_held_group"] == 3
    assert result["ring_claims"] == 13 and result["rings_flagged"] == 3
    # one ring claim was paid before the second claim of its ring existed, and one forged card was photographed
    # again, which the picture comparison cannot follow: the measurement says so and does not hide it
    assert result["ring_claims_paid_before"] == 1 and result["ring_claims_caught"] == 11 and result["ring_claims_missed"] == 1
    assert result["hard_cases"] == {"forged_card_photographed_again": "clear"}
    per = result["per_ring"]
    assert per["mule_account"]["held_before_payment"] == 4 and "account" in per["mule_account"]["signals"]
    assert per["forged_identity"]["held_before_payment"] == 3 and "image" in per["forged_identity"]["signals"]
    assert per["name_variant_burst"]["held_before_payment"] == 4
    assert {"email", "name_variant", "device", "burst"} <= set(per["name_variant_burst"]["signals"])
    assert per["mule_account"]["flagged_when_claim_number_arrived"] == 2
    assert json.loads((folder / "ring_measurement.json").read_text())["ring_claims_caught"] == 11
    # the detector was given the folder and nothing else: the ground truth is not among its inputs
    claims = cl.ClaimStore(folder).all()
    held = {c["id"] for c in claims if (c.get("risk") or {}).get("status") in rings.BLOCKED}
    assert held <= {i for ids in truth["rings"].values() for i in ids} | set(truth["look_alikes"]["relative_files_for_three"])
    paid = next(c for c in claims if c["id"] == truth["paid_before_the_ring_showed"][0])
    event = paid["risk"]["events"][-1]
    assert paid["risk"]["status"] == "paid_before" and event["amount"] == f"{paid['record']['amount']:.2f}" and event["at"]
