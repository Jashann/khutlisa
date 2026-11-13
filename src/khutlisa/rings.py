"""Rings: organised false claims, caught by looking across the whole queue.

One claim on its own can look sound. A ring shows only when claims are put side by side: one bank account that
receives for several claimants, one picture of an identity document used again with small edits, one contact
behind several names. Everything here is comparison and arithmetic over the claim files. No language model is
involved.

How it works, in order:

1. Each pair of claims is compared on the signals in POINTS. A signal between two claims is an edge, and it
   carries the shared element (masked) and a fixed number of points.
2. Two claims are linked when the points between them reach LINK_AT and at least one of the signals is a linking
   signal (LINKING). The weak signals (a shared network, a shared device, a burst, an address, an account name,
   a pattern in the readings) never link two claims by themselves.
3. Linked claims form groups (connected groups of the graph).
4. A group's rating is a plain sum: each signal found between any two of its claims counts once, at its fixed
   value, plus fixed points for the size of the group. A group is flagged when the sum reaches FLAG_AT.
5. Every claim in a flagged group is held: no approval and no payment, until a person at the holder releases it
   with a reason.

Two honest situations are taken out before any signal counts (see `same_person` and `household`): one person with
up to SAME_PERSON_MAX properties, and members of one family at one address.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from . import claims as cl
from . import documents
from .names import normalise, tokens

# ---- the points: every one is named and has a fixed value ----------------------------------------------------

# kind: (points, the words for the points table, the short word on the graph)
POINTS: dict[str, tuple[int, str, str]] = {
    "account": (60, "the same bank account receives for different claimants", "bank account"),
    "document": (60, "the same document file is used in different claims", "same file"),
    "image": (50, "a near-identical picture of an identity document is used in different claims", "near-identical picture"),
    "email": (30, "the same email address is used by different claimants", "email"),
    "phone": (30, "the same phone number is used by different claimants", "phone"),
    "name_variant": (25, "claimant names that are one or two letters apart claim different properties", "name variants"),
    "device": (20, "the claims were opened from the same network with the same browser", "device"),
    "account_name": (15, "accounts in the same holder's name receive for different claimants", "account name"),
    "reading_pattern": (15, "the same field of the same kind of document disagrees between its two readings", "readings disagree"),
    "network": (10, "the claims were opened from the same network", "network"),
    "address": (10, "the same typed address is used by different claimants", "address"),
    "burst": (10, "many claims for one holder were opened in a short time", "burst"),
}
SIZE_POINTS = ((5, 20, "five or more claims are linked"), (3, 10, "three or more claims are linked"))
# The signals that can link two claims. The others only add to a group that something else has already linked.
LINKING = frozenset({"account", "document", "image", "email", "phone", "name_variant"})
LINK_AT = 30      # points between two claims at which they are linked
FLAG_AT = 60      # points of a group at which every claim in it is held

SAME_PERSON_MAX = 3        # one person may have this many properties before the claims count as separate again
NEAR_IMAGE_TILES = 8       # of 96: two images that differ in this many tiles or fewer are near-identical
BURST_MINUTES = 30
BURST_CLAIMS = 4           # this many claims on different properties of one holder inside the window
PATTERN_CLAIMS = 3         # the same field must disagree in this many claims before it is a pattern
NETWORK_CROWD = 10         # a network behind more claims than this is shared by too many people to mean anything
MONEY_GONE = (cl.PAYING, cl.PAID)

RULE = (f"Two claims are linked when the signals between them add up to {LINK_AT} points or more and one of them "
        "is a bank account, a document, an email, a phone number or a name variant. A group of linked claims is "
        f"held when its points add up to {FLAG_AT} or more. Each signal counts once in a group, at a fixed value. "
        "A shared network, a shared device, a burst, an address, an account name or a pattern in the readings "
        "never links claims and never holds a claim alone.")
FIXED_RULE = ("A fixed rule, not yours to switch off: linked claims are held before any money moves. Only a person "
              "releases one, with a reason.")
HELD_FOR_CLAIMANT = ("No money can move on this claim for now. A safety check at the holder has paused it, and a "
                     "person there has to release it. Nothing is needed from you at this moment.")

_STREET_WORDS = {"STREET": "ST", "AVENUE": "AVE", "AVENIDA": "AV", "ROAD": "RD", "BOULEVARD": "BLVD", "DRIVE": "DR",
                 "LANE": "LN", "APARTMENT": "APT", "CALLE": "C", "NUMBER": "NO", "BARANGAY": "BRGY"}
_GMAIL = {"gmail.com", "googlemail.com"}


def _money(amount, currency: str = "USD") -> str:
    value = Decimal(str(amount or 0))
    return f"${value:,.2f}" if currency == "USD" else f"{value:,.2f} {currency}"


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ---- normalising and masking ---------------------------------------------------------------------------------

def email_key(email: str) -> str:
    """The address two spellings of one mailbox share: lower case; a plus-tag ("ana+two@") is dropped for every
    provider; dots in the part before the @ are dropped for Gmail only, where they do not matter."""
    email = (email or "").strip().lower()
    if email.count("@") != 1:
        return ""
    local, domain = email.split("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}" if local and domain else ""


def phone_key(phone: str) -> str:
    """The last ten digits, so a number with and without its country code is the same number."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 7 else ""


def address_key(address: str) -> str:
    """A typed address without case, accents, punctuation or word order, and with the common street words in
    one spelling. Two addresses are the same only when every remaining word is the same."""
    words = [_STREET_WORDS.get(w, w) for w in normalise(address).split()]
    return " ".join(sorted(words)) if len(words) >= 3 else ""


def account_key(bank: dict) -> str:
    """One bank account: the bank's country and the account number without spaces."""
    number = re.sub(r"[^0-9A-Z]", "", str(bank.get("account_number") or "").upper())
    return f"{(bank.get('bank_country_code') or '').upper()}:{number}" if len(number) >= 4 else ""


def name_key(name: str) -> tuple[str, ...]:
    return tuple(sorted(tokens(name)))


def mask_account(number: str) -> str:
    return "account ending " + re.sub(r"[^0-9A-Za-z]", "", number or "")[-4:]


def mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}···@{domain}"


def mask_phone(phone: str) -> str:
    return "phone ending " + re.sub(r"\D", "", phone or "")[-2:]


def mask_address(address: str) -> str:
    return "an address starting " + " ".join((address or "").split())[:6].strip() + "···"


def mask_person(name: str) -> str:
    """"Rafael M. C." for "Rafael Montoya Cruz": enough to tell the nodes of a graph apart."""
    words = (name or "").split()
    return " ".join([words[0]] + [w[0].upper() + "." for w in words[1:]]) if words else "A claimant"


# ---- the perceptual hash of an image -------------------------------------------------------------------------
#
# One whole-image hash of 64 or 256 bits cannot tell "one picture with a word changed" from "two people's cards
# printed from one template": measured on sample cards, both sit about as many bits apart. So the picture is
# hashed tile by tile. The image is made grey, stretched to full contrast and shrunk to 96 by 64 points, which is
# 12 by 8 tiles of 8 by 8 points. Two tiles are the same when their brightness and their pattern both agree
# within a fixed tolerance. The distance between two images is the number of tiles that differ, from 0 to 96 (a
# Hamming distance over tiles). Saving a picture again, scaling it or brightening it leaves every tile the same;
# changing a name changes the few tiles the name sits in; another person's card differs in the name, the photo,
# the numbers and the dates.

TILES_ACROSS, TILES_DOWN, TILE = 12, 8, 8
TILES = TILES_ACROSS * TILES_DOWN
TILE_MEAN_APART = 24       # grey levels (of 255) between the brightness of two tiles before they differ
TILE_PATTERN_APART = 8     # mean grey levels between the patterns of two tiles before they differ


def image_hash(path: Path | str) -> str | None:
    """The tile hash of an image file, as text (the 96 by 64 grey points in base 64). None for a file Pillow
    cannot open: a PDF, a format it does not know, a damaged file. Those are compared by their SHA-256 only."""
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as image:
            grey = ImageOps.autocontrast(image.convert("L"), cutoff=1)
            small = grey.resize((TILES_ACROSS * TILE, TILES_DOWN * TILE), Image.LANCZOS)
            return base64.b64encode(small.tobytes()).decode()
    except Exception:
        return None


@lru_cache(maxsize=4096)
def _tiles(hashed: str) -> tuple[tuple[float, ...], tuple[tuple[float, ...], ...]]:
    """(the mean of each tile, each tile's points with its mean taken away)."""
    raw = base64.b64decode(hashed)
    width = TILES_ACROSS * TILE
    means, patterns = [], []
    for ty in range(TILES_DOWN):
        for tx in range(TILES_ACROSS):
            points = [raw[y * width + x] for y in range(ty * TILE, ty * TILE + TILE)
                      for x in range(tx * TILE, tx * TILE + TILE)]
            mean = sum(points) / len(points)
            means.append(mean)
            patterns.append(tuple(p - mean for p in points))
    return tuple(means), tuple(patterns)


def tiles_apart(a: str, b: str, stop_after: int = TILES) -> int:
    """How many of the 96 tiles differ between two tile hashes. Counting stops once it passes `stop_after`,
    because two different pictures differ almost everywhere and need not be counted to the end."""
    try:
        (means_a, patterns_a), (means_b, patterns_b) = _tiles(a), _tiles(b)
    except Exception:
        return TILES
    if len(means_a) != TILES or len(means_b) != TILES:
        return TILES
    differ = [abs(x - y) > TILE_MEAN_APART for x, y in zip(means_a, means_b)]
    count = sum(differ)
    limit = TILE_PATTERN_APART * TILE * TILE
    for n in range(TILES):
        if count > stop_after:
            break
        if not differ[n] and sum(abs(x - y) for x, y in zip(patterns_a[n], patterns_b[n])) > limit:
            count += 1
    return count


# ---- names ---------------------------------------------------------------------------------------------------

def _close(a: str, b: str) -> bool:
    """Two words that are one letter apart, or two letters when both are seven letters or longer."""
    allowed = 2 if min(len(a), len(b)) >= 7 else 1
    return abs(len(a) - len(b)) <= allowed and 0 < Levenshtein.distance(a, b) <= allowed


def name_variant(a: str, b: str) -> bool:
    """True when two full names are near-identical and not identical.

    The words are compared in any order after `names.tokens`. Words both names carry are set aside. What is left
    must be: one word on each side that is one letter apart (two letters for words of seven letters or more); or
    two words on each side, each one letter apart from its partner; or nothing on one side and a single initial
    on the other. At least one word of three letters or more must be the same in both. Identical names are not
    variants: two honest people can carry the same common name. A shared surname alone is not a variant either,
    because the given names then differ by more than a letter."""
    left, right = list(tokens(a)), list(tokens(b))
    if len(left) < 2 or len(right) < 2:
        return False
    shared = []
    for word in list(left):
        if word in right:
            left.remove(word)
            right.remove(word)
            shared.append(word)
    if not left and not right:
        return False
    if not any(len(w) >= 3 for w in shared) and not (len(left) == len(right) == 2):
        return False
    if len(left) == 1 and len(right) == 1:
        return _close(left[0], right[0])
    if len(left) == 2 and len(right) == 2:
        return ((_close(left[0], right[0]) and _close(left[1], right[1]))
                or (_close(left[0], right[1]) and _close(left[1], right[0])))
    rest = left or right
    return not (left and right) and len(rest) == 1 and len(rest[0]) == 1


# ---- what is read from one claim -----------------------------------------------------------------------------

def _bank(payee: dict | None) -> dict | None:
    try:
        bank = payee["beneficiary"]["beneficiary"]["bank_details"]
    except (KeyError, TypeError):
        return None
    return bank if isinstance(bank, dict) else None


def features(claim: dict, hashes: dict[str, str | None]) -> dict:
    """Everything the comparison needs from one claim, already normalised. An estate claim's heirs add their
    bank accounts and their contacts to the claim they belong to."""
    claimant = claim.get("claimant") or {}
    record = claim.get("record") or {}
    heirs = [h for h in ((claim.get("estate") or {}).get("heirs") or []) if isinstance(h, dict)]
    emails, phones, accounts, account_names = {}, {}, {}, {}
    for person in [claimant] + heirs:
        if email_key(person.get("email") or ""):
            emails.setdefault(email_key(person["email"]), person["email"])
        if phone_key(str(person.get("phone") or "")):
            phones.setdefault(phone_key(str(person["phone"])), str(person["phone"]))
    for payee in [claim.get("payee")] + [h.get("payee") for h in heirs]:
        bank = _bank(payee)
        if bank and account_key(bank):
            accounts[account_key(bank)] = str(bank.get("account_number") or "")
            if name_key(bank.get("account_name") or ""):
                account_names.setdefault(name_key(bank["account_name"]), set()).add(account_key(bank))
    docs = []
    for doc in claim.get("documents") or []:
        reading = doc.get("reading") or {}
        agreement = reading.get("agreement") or {}
        docs.append({"sha": doc.get("sha256") or "", "kind": doc.get("kind") or "other",
                     "label": (doc.get("kind_label") or documents.KINDS.get(doc.get("kind"), "document")).lower(),
                     "hash": hashes.get(doc.get("sha256") or ""),
                     "disagreed": list(agreement.get("disagreed") or []) if agreement.get("status") == "disagree" else []})
    origin = claim.get("origin") or {}
    try:
        created = datetime.fromisoformat(claim.get("created_at") or "").timestamp()
    except ValueError:
        created = 0.0
    return {"id": claim["id"], "state": claim.get("state"), "created": created,
            "created_at": claim.get("created_at") or "",
            "holder": normalise(record.get("holder_name") or ""), "holder_name": record.get("holder_name") or "",
            "property": cl.property_key(claim), "name": claimant.get("name") or "",
            "name_key": name_key(claimant.get("name") or ""), "country": (claimant.get("country") or "").upper(),
            "emails": emails, "phones": phones, "address_key": address_key(claimant.get("address") or ""),
            "address": claimant.get("address") or "", "accounts": accounts, "account_names": account_names,
            "docs": docs, "network": origin.get("network") or "", "agent": origin.get("agent") or "",
            "amount": float(record.get("amount") or 0), "currency": record.get("currency") or "USD"}


def same_person(a: dict, b: dict) -> bool:
    """One person behind two claims: the same name word for word (in any order), the same country, and the same
    email, phone or typed address. Such a pair shares an account and a contact because it is one person, so no
    signal is raised between them."""
    if not a["name_key"] or a["name_key"] != b["name_key"] or a["country"] != b["country"]:
        return False
    return bool(set(a["emails"]) & set(b["emails"]) or set(a["phones"]) & set(b["phones"])
                or (a["address_key"] and a["address_key"] == b["address_key"]))


def household(a: dict, b: dict) -> bool:
    """Members of one family at one address: the same typed address, a name word in common (three letters or
    more), and names that are neither the same nor variants of each other. Between them an address, a network,
    a device, an email, a phone, a burst and a shared bill mean nothing. A shared bank account, a shared
    identity document and a pattern in the readings still count."""
    if not a["address_key"] or a["address_key"] != b["address_key"] or a["name_key"] == b["name_key"]:
        return False
    if not any(len(w) >= 3 for w in set(a["name_key"]) & set(b["name_key"])):
        return False
    return not name_variant(a["name"], b["name"])


_HOUSEHOLD_STILL_COUNTS = frozenset({"account", "reading_pattern"})
_IDENTITY_WEIGHTS = documents.TIES_A_PERSON_TO_THE_OWNER


def _is_identity(kind: str) -> bool:
    return documents.WEIGHT.get(kind) in _IDENTITY_WEIGHTS


# ---- the graph -----------------------------------------------------------------------------------------------

def _pairs(ids):
    ids = sorted(set(ids))
    return [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]


def analyse(claims: list[dict], hashes: dict[str, str | None] | None = None) -> dict:
    """The whole picture for a list of claim files: {"edges", "groups", "by_claim"}.

    `edges` maps a pair of claim ids to the signals between them. `groups` are the linked groups, strongest
    first, each with its nodes, edges, shared elements, points table and total. `by_claim` maps a claim id to
    its group id and its own link keys (used to tell a new signal from an old one after a release)."""
    feats = {c["id"]: features(c, hashes or {}) for c in claims}
    ids = sorted(feats)

    # One person with several properties. Past SAME_PERSON_MAX the claims are compared like anyone else's.
    person_of = {i: i for i in ids}

    def root(i):
        while person_of[i] != i:
            person_of[i] = person_of[person_of[i]]
            i = person_of[i]
        return i

    by_name: dict[tuple, list[str]] = {}
    for i in ids:
        by_name.setdefault((feats[i]["name_key"], feats[i]["country"]), []).append(i)
    for bucket in by_name.values():
        for a, b in _pairs(bucket):
            if same_person(feats[a], feats[b]):
                person_of[root(a)] = root(b)
    members: dict[str, set] = {}
    for i in ids:
        members.setdefault(root(i), set()).add(i)
    one_person = {i: root(i) for i in ids
                  if len(members[root(i)]) > 1
                  and len({feats[m]["property"] for m in members[root(i)]}) <= SAME_PERSON_MAX}

    edges: dict[tuple[str, str], dict[str, dict]] = {}

    def add(a: str, b: str, kind: str, element: str, key: str) -> None:
        if a == b:
            return
        a, b = sorted((a, b))
        fa, fb = feats[a], feats[b]
        if a in one_person and one_person.get(b) == one_person[a]:
            return
        if kind not in _HOUSEHOLD_STILL_COUNTS and household(fa, fb):
            if kind not in ("document", "image") or not key.startswith("identity:"):
                return
        found = edges.setdefault((a, b), {})
        if kind not in found:
            found[kind] = {"kind": kind, "points": POINTS[kind][0], "label": POINTS[kind][2], "element": element,
                           "key": cl.digest([kind, key])[:16]}

    def bucketed(values) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for claim_id, key in values:
            out.setdefault(key, []).append(claim_id)
        return {k: v for k, v in out.items() if len(set(v)) > 1}

    # the same bank account, and accounts in the same holder's name
    for key, bucket in bucketed((i, k) for i in ids for k in feats[i]["accounts"]).items():
        for a, b in _pairs(bucket):
            add(a, b, "account", mask_account(feats[a]["accounts"][key]), key)
    for key, bucket in bucketed((i, k) for i in ids for k in feats[i]["account_names"]).items():
        for a, b in _pairs(bucket):
            if feats[a]["account_names"][key] != feats[b]["account_names"][key]:      # different account numbers
                add(a, b, "account_name", "one holder's name", " ".join(key))

    # contacts
    for key, bucket in bucketed((i, k) for i in ids for k in feats[i]["emails"]).items():
        for a, b in _pairs(bucket):
            add(a, b, "email", mask_email(key), key)
    for key, bucket in bucketed((i, k) for i in ids for k in feats[i]["phones"]).items():
        for a, b in _pairs(bucket):
            add(a, b, "phone", mask_phone(key), key)
    for key, bucket in bucketed((i, feats[i]["address_key"]) for i in ids if feats[i]["address_key"]).items():
        for a, b in _pairs(bucket):
            add(a, b, "address", mask_address(feats[a]["address"]), key)

    # the same file, and near-identical images
    shas = [(i, d) for i in ids for d in feats[i]["docs"] if d["sha"]]
    for key, bucket in bucketed((i, d["sha"]) for i, d in shas).items():
        doc = next(d for _, d in shas if d["sha"] == key)
        for a, b in _pairs(bucket):
            add(a, b, "document", f"one {doc['label']} file", ("identity:" if _is_identity(doc["kind"]) else "") + key)
    # Near-identical pictures are looked for among photo identification only. Each honest card arrives as its
    # own photograph or scan with its own portrait. Bills and letters printed from one template differ in a few
    # words by nature (measured on sample bills: 2 to 8 tiles of 96), so they are compared as whole files only.
    images = [(i, d) for i, d in shas if d["hash"] and documents.WEIGHT.get(d["kind"]) == documents.GOVERNMENT_PHOTO_ID]
    for n, (a, da) in enumerate(images):
        for b, db in images[n + 1:]:
            if a != b and da["sha"] != db["sha"]:
                apart = tiles_apart(da["hash"], db["hash"], NEAR_IMAGE_TILES)
                if apart <= NEAR_IMAGE_TILES:
                    add(a, b, "image", f"{apart} of {TILES} tiles differ",
                        "identity:" + ":".join(sorted((da["sha"], db["sha"]))))

    # the network and the device a claim was opened from
    for key, bucket in bucketed((i, feats[i]["network"]) for i in ids if feats[i]["network"]).items():
        if len(set(bucket)) > NETWORK_CROWD:
            continue
        for a, b in _pairs(bucket):
            if feats[a]["agent"] and feats[a]["agent"] == feats[b]["agent"]:
                add(a, b, "device", "one device", key + feats[a]["agent"])
            else:
                add(a, b, "network", "one network", key)

    # many claims for one holder in a short time
    for holder, bucket in bucketed((i, feats[i]["holder"]) for i in ids if feats[i]["holder"] and feats[i]["created"]).items():
        line = sorted(set(bucket), key=lambda i: feats[i]["created"])
        for n, first in enumerate(line):
            window = [i for i in line[n:] if feats[i]["created"] - feats[first]["created"] <= BURST_MINUTES * 60]
            if len({feats[i]["property"] for i in window}) >= BURST_CLAIMS:
                minutes = max(1, round((feats[window[-1]]["created"] - feats[first]["created"]) / 60))
                for a, b in _pairs(window):
                    if feats[a]["property"] != feats[b]["property"]:
                        add(a, b, "burst", f"{len(window)} claims in {minutes} minutes", holder)

    # the same field of the same kind of document disagreeing between its two readings
    for key, bucket in bucketed((i, f"{d['kind']}|{field}") for i in ids for d in feats[i]["docs"]
                                for field in d["disagreed"]).items():
        if len(set(bucket)) >= PATTERN_CLAIMS:
            kind, field = key.split("|", 1)
            label = documents.KINDS.get(kind, "document").lower()
            for a, b in _pairs(bucket):
                add(a, b, "reading_pattern", f"the {field}", key)

    # near-identical names on different properties
    named = [i for i in ids if len(feats[i]["name_key"]) >= 2]
    for n, a in enumerate(named):
        for b in named[n + 1:]:
            fa, fb = feats[a], feats[b]
            if fa["property"] != fb["property"] and fa["name_key"] != fb["name_key"] \
                    and abs(len(" ".join(fa["name_key"])) - len(" ".join(fb["name_key"]))) <= 4 \
                    and name_variant(fa["name"], fb["name"]):
                add(a, b, "name_variant", "a letter or two apart", "|".join(sorted((a, b))))

    # groups: claims joined by linked pairs
    linked = {pair for pair, found in edges.items()
              if sum(s["points"] for s in found.values()) >= LINK_AT and LINKING & set(found)}
    group_of = {i: i for i in ids}

    def top(i):
        while group_of[i] != i:
            group_of[i] = group_of[group_of[i]]
            i = group_of[i]
        return i

    for a, b in linked:
        group_of[top(a)] = top(b)
    grouped: dict[str, list[str]] = {}
    for i in ids:
        grouped.setdefault(top(i), []).append(i)

    groups, by_claim = [], {}
    for member_ids in grouped.values():
        if len(member_ids) < 2:
            continue
        inside = set(member_ids)
        member_ids = sorted(member_ids, key=lambda i: (feats[i]["created"], i))
        own = {pair: found for pair, found in edges.items() if pair[0] in inside and pair[1] in inside}
        table = points_table(own, len(member_ids))
        total = sum(row["points"] for row in table)
        group_id = "g" + member_ids[0][:10]
        group = {"id": group_id, "points": total, "flagged": total >= FLAG_AT, "table": table,
                 "members": member_ids,
                 "edges": [{"a": a, "b": b, "linked": (a, b) in linked,
                            "points": sum(s["points"] for s in found.values()),
                            "signals": sorted(found.values(), key=lambda s: -s["points"])}
                           for (a, b), found in sorted(own.items())],
                 "shared": shared_elements(own)}
        groups.append(group)
        for i in member_ids:
            links = sorted({f"{s['key']}:{b if a == i else a}" for (a, b), found in own.items() if i in (a, b)
                            for s in found.values()})
            by_claim[i] = {"group": group_id, "flagged": group["flagged"], "points": total, "links": links}
    groups.sort(key=lambda g: (-g["points"], g["id"]))
    return {"edges": edges, "groups": groups, "by_claim": by_claim, "features": feats}


def points_table(edges: dict, size: int) -> list[dict]:
    """The group's rating as rows: each signal found between any two claims of the group, once, at its fixed
    value, then the points for the size of the group. The rating is the sum of the rows."""
    rows = []
    for kind, (points, words, _) in POINTS.items():
        found = [(pair, signals[kind]) for pair, signals in edges.items() if kind in signals]
        if found:
            rows.append({"kind": kind, "points": points, "words": words, "pairs": len(found),
                         "claims": len({i for pair, _ in found for i in pair}),
                         "elements": sorted({s["element"] for _, s in found})[:6]})
    for least, points, words in SIZE_POINTS:
        if size >= least:
            rows.append({"kind": "size", "points": points, "words": words, "pairs": 0, "claims": size,
                         "elements": [f"{size} claims"]})
            break
    return rows


def shared_elements(edges: dict) -> list[dict]:
    """The shared things of a group, each with the claims that share it: one bank account, one email, one set
    of name variants. This is what the screen draws in the middle of the graph."""
    parent: dict[tuple, tuple] = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    chained = ("name_variant", "image", "burst", "reading_pattern", "network", "device", "account_name")
    facts = {}
    for (a, b), signals in edges.items():
        for kind, s in signals.items():
            lane = kind if kind in chained else f"{kind}:{s['key']}"
            parent[find((lane, a))] = find((lane, b))
            facts.setdefault(lane, s)
    sets: dict[tuple, set] = {}
    for lane, claim_id in list(parent):
        sets.setdefault(find((lane, claim_id)), set()).add(claim_id)
    out = []
    for (lane, _), claim_ids in sets.items():
        s = facts[lane]
        element = s["element"]
        if s["kind"] == "image" and len(claim_ids) > 2:
            element = "a few tiles differ"
        out.append({"kind": s["kind"], "label": s["label"], "element": element, "points": s["points"],
                    "linking": s["kind"] in LINKING, "claims": sorted(claim_ids)})
    return sorted(out, key=lambda e: (-e["points"], e["kind"], e["claims"]))


# ---- the status of one claim ---------------------------------------------------------------------------------

HELD, SUSPENDED, RELEASED, PAID_BEFORE, CLOSED, CLEAR = "held", "suspended", "released", "paid_before", "closed", "clear"
BLOCKED = (HELD, SUSPENDED)


def status_for(claim: dict, found: dict | None) -> str | None:
    """What the risk state of a claim should be now. `found` is its entry in `by_claim`, or None.

    A released claim stays released while every link it has now is one it already had when it was released. A
    new link (a signal with a claim, or a signal of a kind, that was not there at the release) holds it again."""
    risk = claim.get("risk") or {}
    if not found or not found["flagged"]:
        return CLEAR if risk.get("status") else None
    release = risk.get("release")
    if release and set(found["links"]) <= set(release.get("links") or []):
        return RELEASED
    if claim["state"] in MONEY_GONE:
        return PAID_BEFORE
    if claim["state"] == cl.REJECTED:
        return CLOSED
    return SUSPENDED if claim["state"] == cl.APPROVED else HELD


def reasons_in_words(group: dict, limit: int = 3) -> str:
    """The strongest signals of a group as part of a sentence: "the same bank account ..., and ...". """
    rows = [r for r in group["table"] if r["kind"] != "size"][:limit]
    words = [r["words"] for r in rows]
    return ", and ".join([", ".join(words[:-1]), words[-1]]) if len(words) > 1 else (words[0] if words else "")


# ---- the decision cards (the same four lines as cards.py) ----------------------------------------------------

def group_card(group: dict, rows: dict[str, dict]) -> dict:
    """One group as a decision card. `rows` maps claim ids to {"status", "amount", "currency", "state"}."""
    mine = [rows[i] for i in group["members"] if i in rows]
    count = lambda status: sum(1 for r in mine if r["status"] == status)
    usd = lambda found: sum(Decimal(str(r["amount"] or 0)) for r in found)
    held, suspended, released, gone = count(HELD), count(SUSPENDED), count(RELEASED), count(PAID_BEFORE)
    lead = next((r for r in group["table"] if r["kind"] != "size"), None)
    happened = f"{_count(len(group['members']), 'claim')} are linked: {lead['words'] if lead else 'by shared details'}."
    why = [f"{r['words'][0].upper()}{r['words'][1:]}: {r['points']} points"
           + (f" ({'; '.join(r['elements'][:3])})." if r["kind"] != "size" else ".") for r in group["table"]]
    why.append(f"The points add up to {group['points']}. A group is held from {FLAG_AT} points.")
    if not group["flagged"]:
        return {"kind": "ring_linked", "tone": "go", "title": "Linked claims, below the line", "at": None,
                "happened": happened,
                "allowed": f"Linked claims are held from {FLAG_AT} points. This group has {group['points']}.",
                "did": "Held nothing. The link is shown so that you can look.",
                "money": f"{_money(usd(mine))} across the group, none of it held.", "why": why}
    parts = []
    if held:
        parts.append(f"held {_count(held, 'claim')}")
    if suspended:
        parts.append(f"suspended {_count(suspended, 'approval')}")
    did = (" and ".join(parts) + " before any money moved." if parts else "Nothing is held now.")
    did = did[0].upper() + did[1:]
    if released:
        did += f" You released {_count(released, 'claim')}."
    blocked = [r for r in mine if r["status"] in BLOCKED]
    money = f"{_money(usd(blocked))} held."
    if gone:
        money += f" {_money(usd([r for r in mine if r['status'] == PAID_BEFORE]))} had already left on {_count(gone, 'claim')}."
        why.append("Money that had left before the link showed is recorded and not called back.")
    return {"kind": "ring_hold", "tone": "stop" if blocked else "ask", "title": "Linked claims held", "at": None,
            "happened": happened, "allowed": FIXED_RULE, "did": did, "money": money, "why": why}


def release_card(claim_row: dict, release: dict) -> dict:
    """A release, as a decision card: the person's decision, with the reason on file."""
    return {"kind": "ring_release", "tone": "go", "title": "Released by a person", "at": release.get("at"),
            "happened": "A person at the holder looked at the links and released this claim.",
            "allowed": "A release is always a person's decision. The agent never releases a held claim.",
            "did": "Lifted the hold on this claim. A new link will hold it again.",
            "money": f"{_money(claim_row['amount'], claim_row.get('currency') or 'USD')} can move again.",
            "why": [f"Reason on file: {release.get('reason')}"]}


# ---- the detector kept beside a claim store ------------------------------------------------------------------

class Rings:
    """Looks across every claim file in a store, keeps each claim's risk state up to date, and refuses approvals
    and payments on held claims. The analysis is worked out again only when a claim file has changed."""

    def __init__(self, store: cl.ClaimStore):
        self.store = store
        self._seen: tuple[str, dict] | None = None
        self._hashes: dict[str, str | None] | None = None

    # ---- the fingerprint of where a claim was opened from ----

    @property
    def salt_path(self) -> Path:
        return self.store.folder / "origin_salt.txt"

    def _salt(self) -> bytes:
        try:
            return self.salt_path.read_text().strip().encode()
        except OSError:
            self.store.folder.mkdir(parents=True, exist_ok=True)
            self.salt_path.write_text(secrets.token_hex(16))
            return self.salt_path.read_text().strip().encode()

    def fingerprint(self, address: str, agent: str, forwarded: bool = False) -> dict:
        """What is kept about where a claim was opened from: a keyed hash of the client address and a keyed hash
        of the browser's User-Agent line, each cut to 16 characters. The address and the line themselves are
        not kept. Behind a proxy (a forwarding header is present) the address is the proxy's, so none is kept."""
        def tag(value: str) -> str:
            return hmac.new(self._salt(), value.encode(), hashlib.sha256).hexdigest()[:16] if value else ""
        return {"network": "" if forwarded else tag(address), "agent": tag(agent), "at": cl.now()}

    def on_create(self, claim: dict, request) -> None:
        """The creation hook: stores the fingerprint in claim["origin"]. The claimant never sees it."""
        try:
            address = request.client.host if request.client else ""
            headers = request.headers
            forwarded = any(h in headers for h in ("x-forwarded-for", "forwarded", "x-real-ip"))
            claim["origin"] = self.fingerprint(address, headers.get("user-agent") or "", forwarded)
        except Exception:
            claim["origin"] = None

    # ---- image hashes, worked out once per file ----

    @property
    def hashes_path(self) -> Path:
        return self.store.folder / "image_hashes.json"

    def hashes_for(self, claims: list[dict]) -> dict[str, str | None]:
        if self._hashes is None:
            try:
                self._hashes = json.loads(self.hashes_path.read_text())
            except (OSError, ValueError):
                self._hashes = {}
        new = False
        for claim in claims:
            for doc in claim.get("documents") or []:
                sha = doc.get("sha256")
                if not sha or sha in self._hashes:
                    continue
                is_image = (doc.get("content_type") or "").startswith("image/")
                path = self.store.files(claim["id"]) / (doc.get("stored_as") or "")
                self._hashes[sha] = image_hash(path) if is_image and path.is_file() else None
                new = True
        if new:
            self.store.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.hashes_path.with_name(self.hashes_path.name + ".tmp")
            tmp.write_text(json.dumps(self._hashes, sort_keys=True))
            os.replace(tmp, self.hashes_path)
        return self._hashes

    # ---- the analysis ----

    @staticmethod
    def _inputs(claim: dict) -> list:
        """The parts of a claim file the analysis reads. A change anywhere else does not cause a new analysis."""
        return [claim["id"], claim.get("state"), claim.get("created_at"), claim.get("claimant"),
                (claim.get("record") or {}).get("holder_name"), cl.property_key(claim),
                (claim.get("payee") or {}).get("hash"),
                [[h.get("id"), h.get("email"), h.get("phone"), (h.get("payee") or {}).get("hash")]
                 for h in ((claim.get("estate") or {}).get("heirs") or []) if isinstance(h, dict)],
                [[d.get("sha256"), d.get("kind"), ((d.get("reading") or {}).get("agreement") or {})]
                 for d in claim.get("documents") or []],
                claim.get("origin")]

    def analysis(self, claims: list[dict] | None = None) -> dict:
        claims = self.store.all() if claims is None else claims
        key = cl.digest([self._inputs(c) for c in sorted(claims, key=lambda c: c["id"])])
        if self._seen is None or self._seen[0] != key:
            self._seen = (key, analyse(claims, self.hashes_for(claims)))
        return self._seen[1]

    # ---- keeping each claim's risk state ----

    def _apply(self, claim: dict, found: dict | None, group: dict | None) -> bool:
        """Sets claim["risk"] to what it should be now and writes a dated line when the status changes. Returns
        True when the claim was changed."""
        wanted = status_for(claim, found)
        risk = claim.get("risk") or {}
        if wanted is None or (risk.get("status") == wanted and risk.get("group") == (found or {}).get("group")
                              and risk.get("links") == (found or {}).get("links", [])):
            return False
        before = risk.get("status")
        at = cl.now()
        risk = {**risk, "status": wanted, "group": (found or {}).get("group"), "points": (found or {}).get("points"),
                "links": (found or {}).get("links", [])}
        if wanted != before:
            amount = _money((claim.get("record") or {}).get("amount"), (claim.get("record") or {}).get("currency") or "USD")
            why = reasons_in_words(group) if group else ""
            others = len(group["members"]) - 1 if group else 0
            note = {
                HELD: (f"Held by the fixed safety rule: this claim is linked to {_count(others, 'other claim')} "
                       f"({why}). No approval and no payment until a person at the holder releases it."
                       + (" It had been released, and a new link has appeared since." if before == RELEASED else "")),
                SUSPENDED: (f"The holder's approval is suspended: after it was given, this claim was linked to "
                            f"{_count(others, 'other claim')} ({why}). No payment starts until a person at the "
                            "holder releases the claim."),
                PAID_BEFORE: (f"This claim was linked to {_count(others, 'other claim')} ({why}) after its payment "
                              f"had started. {amount} had already left. Nothing is called back; the other claims "
                              "of the group are held."),
                CLOSED: f"This rejected claim is part of a group of linked claims ({why}).",
                RELEASED: "",
                CLEAR: "The links that held this claim are no longer there, so the hold has ended.",
            }[wanted]
            risk["since"] = at
            if note:
                event = {"at": at, "kind": wanted, "note": note}
                if wanted == PAID_BEFORE:
                    event["amount"] = f"{float((claim.get('record') or {}).get('amount') or 0):.2f}"
                    event["currency"] = (claim.get("record") or {}).get("currency") or "USD"
                risk.setdefault("events", [])
                risk["events"] = risk["events"] + [event]
                claim.setdefault("history", []).append({"state": claim["state"], "at": at, "note": note})
        claim["risk"] = risk
        return True

    def sync(self, only: str | None = None) -> dict:
        """Brings every claim's risk state up to date (or one claim's, by id) and returns the analysis."""
        with self.store.lock:
            claims = self.store.all()
            found = self.analysis(claims)
            groups = {g["id"]: g for g in found["groups"]}
            for claim in claims:
                if only and claim["id"] != only:
                    continue
                mine = found["by_claim"].get(claim["id"])
                if self._apply(claim, mine, groups.get((mine or {}).get("group"))):
                    self.store.save(claim)
            return found

    def _refuse_if_blocked(self, claim: dict, for_claimant: bool) -> None:
        with self.store.lock:
            found = self.sync()
            try:
                now = self.store.load(claim["id"])
            except cl.ClaimError:
                return
            # The caller's copy carries what was just recorded, so a save by the caller does not undo it.
            claim["risk"] = now.get("risk")
            have = {(e.get("at"), e.get("note")) for e in claim.get("history") or []}
            claim.setdefault("history", []).extend(e for e in now.get("history") or []
                                                   if (e.get("at"), e.get("note")) not in have)
            status = (now.get("risk") or {}).get("status")
            if status not in BLOCKED:
                return
            if for_claimant:
                raise cl.ClaimError(409, HELD_FOR_CLAIMANT)
            mine = found["by_claim"][claim["id"]]
            group = next(g for g in found["groups"] if g["id"] == mine["group"])
            raise cl.ClaimError(409, f"This claim is held. It is linked to "
                                     f"{_count(len(group['members']) - 1, 'other claim')}: {reasons_in_words(group)}. "
                                     "Look at the group in the risk view. A person can release the claim there, "
                                     "with a reason.")

    def check_approval(self, claim: dict) -> None:
        """An approval check for ClaimStore.approval_checks: refuses while the claim is held."""
        self._refuse_if_blocked(claim, for_claimant=False)

    def check_payment(self, claim: dict) -> None:
        """A payment check for ClaimStore.payment_checks: refuses while the claim is held or its approval is
        suspended. The words are for the claimant and say nothing about any other claim."""
        self._refuse_if_blocked(claim, for_claimant=True)

    def release(self, claim_id: str, reason: str) -> dict:
        """The holder's decision to lift the hold on one claim, with the reason. The links the claim has now are
        kept with the release: only a link that is not among them holds the claim again."""
        with self.store.lock:
            self.sync()
            claim = self.store.load(claim_id)
            risk = claim.get("risk") or {}
            if risk.get("status") not in BLOCKED:
                raise cl.ClaimError(409, "This claim is not held, so there is nothing to release.")
            at = cl.now()
            release = {"at": at, "reason": reason, "links": list(risk.get("links") or []), "from": risk["status"]}
            note = f"A person at the holder released this claim from the hold. Reason: {reason}"
            claim["risk"] = {**risk, "status": RELEASED, "since": at, "release": release,
                             "releases": (risk.get("releases") or []) + [release],
                             "events": (risk.get("events") or []) + [{"at": at, "kind": RELEASED, "note": note}]}
            claim["history"].append({"state": claim["state"], "at": at, "note": note})
            self.store.save(claim)
            return claim

    # ---- the holder's view ----

    def view(self) -> dict:
        """Everything the risk screen shows. Names are cut to a first name and initials, account numbers to
        their last four digits, emails to their first letter and domain. No network address exists to show."""
        found = self.sync()
        claims = {c["id"]: c for c in self.store.all()}
        feats = found["features"]
        rows = {}
        for claim_id, claim in claims.items():
            risk = claim.get("risk") or {}
            mine = found["by_claim"].get(claim_id) or {}
            record = claim.get("record") or {}
            release = risk.get("release") if risk.get("status") == RELEASED else None
            rows[claim_id] = {
                "id": claim_id, "state": claim.get("state"), "created_at": claim.get("created_at"),
                "claimant": mask_person(feats[claim_id]["name"]), "country": feats[claim_id]["country"],
                "amount": record.get("amount") or 0, "currency": record.get("currency") or "USD",
                "holder_name": record.get("holder_name"), "owner": record.get("owner"),
                "status": risk.get("status") or CLEAR, "group": mine.get("group"),
                "group_flagged": bool(mine.get("flagged")), "since": risk.get("since"),
                "release": release and {"at": release["at"], "reason": release["reason"]},
                "events": [{k: e.get(k) for k in ("at", "kind", "note")} for e in risk.get("events") or []][-4:],
                "sample": (record.get("source") or "") in ("DEMO", "SAMPLE"),
                "from_notice": bool(claim.get("notice")), "is_estate": bool(claim.get("estate")),
            }
        groups = []
        for g in found["groups"]:
            groups.append({
                "id": g["id"], "points": g["points"], "flagged": g["flagged"], "flag_at": FLAG_AT,
                "table": g["table"], "shared": g["shared"],
                "nodes": [{k: rows[i][k] for k in ("id", "claimant", "country", "amount", "currency", "state",
                                                    "status", "created_at", "holder_name")} for i in g["members"]],
                "edges": [{"a": e["a"], "b": e["b"], "linked": e["linked"], "points": e["points"],
                           "signals": [{k: s[k] for k in ("kind", "label", "element", "points")} for s in e["signals"]]}
                          for e in g["edges"]],
                "card": group_card(g, rows),
                "held_usd": round(sum(float(rows[i]["amount"]) for i in g["members"] if rows[i]["status"] in BLOCKED), 2),
            })
        order = {HELD: 0, SUSPENDED: 1, PAID_BEFORE: 2, RELEASED: 3, CLOSED: 4, CLEAR: 5}
        listed = sorted(rows.values(), key=lambda r: (order.get(r["status"], 9), r["group"] or "~", r["created_at"] or ""))
        blocked = [r for r in listed if r["status"] in BLOCKED]
        gone = [r for r in listed if r["status"] == PAID_BEFORE]
        return {
            "counts": {"claims": len(rows), "groups_flagged": sum(1 for g in groups if g["flagged"]),
                       "groups_linked": sum(1 for g in groups if not g["flagged"]),
                       "held": sum(1 for r in blocked if r["status"] == HELD),
                       "suspended": sum(1 for r in blocked if r["status"] == SUSPENDED),
                       "released": sum(1 for r in listed if r["status"] == RELEASED),
                       "paid_before": len(gone),
                       "from_notice": sum(1 for r in rows.values() if r["from_notice"]),
                       "estates": sum(1 for r in rows.values() if r["is_estate"]),
                       "held_usd": round(sum(float(r["amount"]) for r in blocked), 2),
                       "paid_before_usd": round(sum(float(r["amount"]) for r in gone), 2)},
            "claims": listed, "groups": groups,
            "rule": {"text": RULE, "fixed": FIXED_RULE, "link_at": LINK_AT, "flag_at": FLAG_AT,
                     "points": [{"kind": k, "points": p, "words": w, "linking": k in LINKING}
                                for k, (p, w, _) in POINTS.items()]
                               + [{"kind": "size", "points": p, "words": w, "linking": False} for _, p, w in SIZE_POINTS]},
            "demonstration": bool(rows) and all(r["sample"] for r in rows.values()),
            "measurement": self.measurement(),
        }

    def measurement(self) -> dict | None:
        """The figures the measurement wrote beside these claims (scripts/make_ring_claims.py), or None."""
        try:
            held = json.loads((self.store.folder / "ring_measurement.json").read_text())
        except (OSError, ValueError):
            return None
        keys = ("seed", "ring_claims", "ring_claims_caught", "ring_claims_paid_before", "honest_claims",
                "honest_claims_held", "rings", "rings_flagged", "measured_at")
        return {k: held.get(k) for k in keys} if isinstance(held, dict) else None
