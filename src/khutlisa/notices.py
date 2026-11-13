"""The notice California requires a holder to send an owner before reporting the owner's property to the State.

What the notice must contain is in Code of Civil Procedure 1520(b), read on 13 Nov 2026 in the State Controller's
printing of the law (February 2026), and in the Controller's due diligence guide and sample letter
(docs/CALIFORNIA_CLAIMS.md, sections H1 and H11, has the words and the addresses). `ELEMENTS` lists each required
element with its source, and `check` refuses to call a notice ready while one is missing.

A notice is written twice: in English, always, and in the owner's likely language, chosen from the last known
country (`LIKELY_LANGUAGE`). Only the sentences are translated, once per language, by a language model through
khutlisa.llm, and no owner's details are in what the model sees: the sentences carry placeholders. The facts
that matter in law (the amount, the dates, the reference, the deadline, the code) are put into both languages
by code, from one set of values, and `check` compares the two finished texts fact by fact.

Nothing here sends anything. A notice is prepared; the holder sends it and marks it sent (outreach.py).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from . import llm

HEADING = ("THE STATE OF CALIFORNIA REQUIRES US TO NOTIFY YOU THAT YOUR UNCLAIMED PROPERTY MAY BE TRANSFERRED TO "
           "THE STATE IF YOU DO NOT CONTACT US.")

# The sentences of the notice and of the screen on which the owner answers it. A word in braces is a fact that
# code puts in. Changing a sentence here makes every stored translation of it out of date (`source_hash`).
STRINGS: dict[str, str] = {
    "heading": HEADING,
    "label_regarding": "Regarding",
    "label_reference": "Account or reference number ending",
    "label_amount": "Amount we hold for you",
    "label_last_activity": "Date of last activity",
    "label_deadline": "Date of transfer to the State (date of escheatment)",
    "label_code": "Your code",
    "greeting": "Dear {OWNER},",
    "intro": "{HOLDER} holds money that belongs to you: {KIND}. We are writing because the law of California, in "
             "the United States, requires us to tell you what will happen to it.",
    "no_activity": "Our records show no activity by you on this property since {LAST_ACTIVITY}.",
    "identify": "The property is {KIND}, with a reference number ending in {REFERENCE}.",
    "danger": "This property is in danger of being transferred to the State of California. The law calls this "
              "escheat.",
    "law": "California's Unclaimed Property Law requires us to transfer property of this kind to the State when "
           "it has had no activity for this many years: {YEARS}.",
    "effect": "If you do not contact us before {DEADLINE}, we must transfer {AMOUNT} to the California State "
              "Controller's Office. After the transfer you would have to file a claim with the State Controller's "
              "Office to get your property back, under California Code of Civil Procedure section 1500 and the "
              "sections that follow it.",
    "respond": "To keep your property, contact us before {DEADLINE} in one of these ways:",
    "respond_online": "Online: go to {LINK} and enter your code, {CODE}. You can read this notice in your language "
                      "there, tell us that the property is yours, and tell us where to pay you.",
    "respond_post": "By post: fill in and sign the form at the end of this notice and send the whole notice back "
                    "to us.",
    "respond_contact": "By telephone or email: {CONTACT}.",
    "recorded": "We keep a record of your answer. Once you have answered, we work with you to return your property "
                "to you instead of transferring it to the State.",
    "no_charge": "We do not charge you for this notice, and answering it costs you nothing.",
    "closing": "Sincerely,",
    "form_title": "PLEASE SIGN BELOW AND RETURN THE ENTIRE NOTICE",
    "form_signature": "Property owner's signature",
    "form_date": "Date",
    "form_name": "Name in print",
    "form_address": "Current address",
    "form_city": "City",
    "form_region": "State or province",
    "form_postcode": "Postal code",
    "form_country": "Country",
    "form_action": "Action to be taken:",
    "form_keep": "I wish to keep this property. By signing and returning this notice I show my interest in it, as "
                 "California's Code of Civil Procedure requires, and I ask {HOLDER} to keep it for me or to pay it "
                 "to me.",
    "form_other": "Other:",
    "reminder": "REMINDER. We wrote to you about this property before and have not heard from you.",
    "translation_note": "This page is a translation for your convenience. The notice in English is the one "
                        "California law requires.",
    "kind_wages": "unpaid wages",
    "kind_bank_account": "money in a bank account",
    "kind_cheque": "an uncashed cheque",
    "kind_money_order": "a money order",
    "kind_travelers_cheque": "a traveler's cheque",
    "kind_ordered_refund": "a refund",
    "kind_securities": "dividends or shares",
    "kind_life_insurance": "money from a life insurance policy",
    "kind_other": "money we owe you",
    "ui_title": "A notice about your money",
    "ui_lead": "{HOLDER} holds {AMOUNT} for you. If nobody answers before {DEADLINE}, it goes to the State of "
               "California.",
    "ui_code_label": "The code from your letter",
    "ui_code_open": "Open my notice",
    "ui_answer_title": "Answer this notice",
    "ui_answer_lead": "Tell us who you are. Your answer is recorded with {HOLDER} at once.",
    "ui_name": "Your full name",
    "ui_address": "Your address now",
    "ui_country": "The country you live in now",
    "ui_email": "Your email address",
    "ui_submit": "This is mine. Open my claim",
    "ui_next": "Next you add a photo of your identification and your bank account, so the money can be paid to you "
               "at home.",
    "ui_voice": "You can also say it or type it in your own words.",
    "ui_other_language": "Read it in English",
    "ui_own_language": "Read it in my language",
    "ui_english_steps": "The next steps are in English for now.",
    "ui_not_found": "There is no notice with that code. Check the letter and type it again.",
    "ui_answered": "You have answered this notice. Your claim is open.",
    "ui_continue": "Go on with my claim",
}
EMPHASISED = ("no_activity", "identify", "danger", "law")     # 1520(b): in bold or at least two points larger
BODY_ORDER = ("intro", "no_activity", "identify", "danger", "law", "effect", "respond", "respond_online",
              "respond_post", "respond_contact", "recorded", "no_charge")
FORM_KEYS = ("form_title", "form_signature", "form_date", "form_name", "form_address", "form_city", "form_region",
             "form_postcode", "form_country", "form_action", "form_keep", "form_other")
LEGAL_FACTS = ("AMOUNT", "LAST_ACTIVITY", "DEADLINE", "REFERENCE", "YEARS", "CODE", "LINK")

_SCO = "https://www.sco.ca.gov/Files-UPD/"
LAW_URL = "https://www.sco.ca.gov/files-upd/guide_upd_updlaw.pdf"
# Each element the notice must carry: where the rule is, and which sentences or facts satisfy it.
ELEMENTS: list[dict] = [
    {"key": "heading", "title": "The heading the law gives, at the top",
     "source": "Code of Civil Procedure 1520(b); the Controller's sample letter", "strings": ["heading"]},
    {"key": "escheat_date", "title": "The date the property goes to the State",
     "source": "1520(b): \"the time when the property will escheat\"", "strings": ["effect"], "facts": ["DEADLINE"]},
    {"key": "effects", "title": "What follows: a claim to the State is then needed",
     "source": "1520(b): \"the effects of escheat, including the need to file a claim\"", "strings": ["effect"]},
    {"key": "no_activity", "title": "No owner activity since the date of last activity, in bold",
     "source": "1520(b)(1)", "strings": ["no_activity"], "facts": ["LAST_ACTIVITY"]},
    {"key": "identifier", "title": "The account or reference, by up to four digits, in bold",
     "source": "1520(b)(2)", "strings": ["identify"], "facts": ["REFERENCE"]},
    {"key": "danger", "title": "That the property is in danger of going to the State, in bold",
     "source": "1520(b)(3)", "strings": ["danger"]},
    {"key": "law", "title": "That the law requires the transfer after the inactive period, in bold",
     "source": "1520(b)(4); the Controller's sample letter", "strings": ["law"], "facts": ["YEARS"]},
    {"key": "form", "title": "A form the owner can sign and return",
     "source": "1520(b): \"a form ... by which the owner may confirm the owner's current address\"",
     "strings": ["form_title", "form_signature", "form_address", "form_keep"]},
    {"key": "contact", "title": "A telephone number or electronic way to answer, and the holder's contact details",
     "source": "1520(b): \"a telephone number or other electronic means\"; the Controller's due diligence guide",
     "strings": ["respond_online", "respond_contact"], "facts": ["LINK", "CODE"]},
    {"key": "amount", "title": "The amount held", "source": "Khutlisa adds this; the law does not require it",
     "strings": ["effect"], "facts": ["AMOUNT"]},
]

# ---- languages ---------------------------------------------------------------------------------------------------------

# code: (the language in English, in itself, whether the letters are set without spaces between words)
LANGUAGES: dict[str, tuple[str, str, bool]] = {
    "en": ("English", "English", False), "es": ("Spanish", "Español", False), "tl": ("Filipino", "Filipino", False),
    "fr": ("French", "Français", False), "de": ("German", "Deutsch", False), "pt": ("Portuguese", "Português", False),
    "it": ("Italian", "Italiano", False), "nl": ("Dutch", "Nederlands", False), "vi": ("Vietnamese", "Tiếng Việt", False),
    "id": ("Indonesian", "Bahasa Indonesia", False), "ru": ("Russian", "Русский", False),
    "sv": ("Swedish", "Svenska", False), "ja": ("Japanese", "日本語", True), "ko": ("Korean", "한국어", False),
    "zh-Hans": ("Chinese (simplified)", "简体中文", True), "zh-Hant": ("Chinese (traditional)", "繁體中文", True),
}
# The owner's likely language, from the country of the last known address. A small table on purpose: where a
# country has no line, or its line is "en", the notice is in English only and the reason is recorded.
LIKELY_LANGUAGE: dict[str, str] = {
    **{c: "es" for c in "MX ES AR CO CL PE VE GT CR UY EC BO DO SV HN NI PA PY CU".split()},
    "PH": "tl", "JP": "ja", "CN": "zh-Hans", "TW": "zh-Hant", "HK": "zh-Hant", "MO": "zh-Hant",
    "DE": "de", "AT": "de", "CH": "de", "FR": "fr", "NL": "nl", "BE": "nl", "IT": "it", "BR": "pt", "PT": "pt",
    "KR": "ko", "VN": "vi", "ID": "id", "RU": "ru", "SE": "sv",
    **{c: "en" for c in "GB IE AU NZ CA SG IN ZA NG KE GH JM TT BS BB BM MT".split()},
}
ENGLISH_ONLY_REASON = {
    "en": "English is an official or working language there.",
    "none": "No language is chosen for this country in this build, so the notice is in English only.",
    "script": "The owner's likely language is written in a script this build cannot set in a letter, so the "
              "notice is in English only.",
}
# Countries whose main language needs letters joined or set right to left, which the PDF library does not do.
_UNSET_SCRIPTS = frozenset("IL SA AE EG JO KW QA BH OM LB MA DZ TN IQ IR PK BD TH LK NP MM KH LA".split())


def language_for(country: str, region: str = "") -> dict:
    """{"code", "name", "native", "reason"} for an owner whose last known address is in `country`."""
    country, region = (country or "").upper(), (region or "").upper().strip()
    code = LIKELY_LANGUAGE.get(country)
    if country == "CA" and region in ("QC", "QUEBEC", "QUÉBEC"):
        code = "fr"
    if code is None:
        reason = ENGLISH_ONLY_REASON["script" if country in _UNSET_SCRIPTS else "none"]
        return {"code": "en", "name": "English", "native": "English", "reason": reason}
    name, native, _ = LANGUAGES[code]
    reason = ENGLISH_ONLY_REASON["en"] if code == "en" else "The most widely used language of the last known country."
    return {"code": code, "name": name, "native": native, "reason": reason}


# ---- translations ------------------------------------------------------------------------------------------------------

SHIPPED = Path(__file__).with_name("notice_translations.json")
_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")
_DIGITS = re.compile(r"\d+")


def source_hash(strings: dict[str, str] | None = None) -> str:
    """One hash for the English sentences. A stored translation is used only while it carries this hash."""
    text = json.dumps(strings or STRINGS, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def translation_problems(translated: dict, strings: dict[str, str] | None = None) -> list[str]:
    """Why a translation of the sentences cannot be used. Empty when it can. Checked in code: every sentence is
    there, each carries exactly the placeholders and the numbers of its English sentence, and nothing else in
    braces."""
    strings = strings or STRINGS
    problems = []
    if not isinstance(translated, dict):
        return ["it is not a set of sentences"]
    for key, english in strings.items():
        text = translated.get(key)
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{key}: missing")
            continue
        if sorted(_PLACEHOLDER.findall(text)) != sorted(_PLACEHOLDER.findall(english)):
            problems.append(f"{key}: the placeholders differ from the English sentence")
        if "{" in _PLACEHOLDER.sub("", text) or "}" in _PLACEHOLDER.sub("", text):
            problems.append(f"{key}: a brace that is not a placeholder")
        if sorted(_DIGITS.findall(_PLACEHOLDER.sub("", text))) != sorted(_DIGITS.findall(_PLACEHOLDER.sub("", english))):
            problems.append(f"{key}: the numbers differ from the English sentence")
    return problems


TRANSLATE_PROMPT = """Translate the values of this JSON object from English into {language}. They are the \
sentences of a legal notice that a company in California sends to a person in another country about money it \
holds for that person, and of the web page on which the person answers.

Rules:
- Return a JSON object with exactly the same keys.
- Words in braces such as {{AMOUNT}} or {{DEADLINE}} are placeholders. Keep each one exactly as written, once for \
each time it appears in the English sentence, and put it where it reads naturally.
- Keep every number exactly as it is. Add no numbers, dates or amounts of your own.
- Translate faithfully and completely. Do not soften, shorten or add anything. This is a legal notice.
- Use plain, polite, formal language that an ordinary reader understands. Keep text that is in capitals in \
capitals where the language has them.
- Keep the names "California", "State Controller's Office" and "Code of Civil Procedure" recognisable: give them \
in {language} and keep the English name in brackets the first time where that helps.
- Do not use long dashes.

{strings}"""


def translate(code: str, model: str = "sonnet") -> dict[str, str]:
    """The sentences in one language, from the model, checked. Raises llm.ModelUnavailable when there is no
    model and ValueError when its answer fails the checks twice."""
    name = LANGUAGES[code][0]
    prompt = TRANSLATE_PROMPT.format(language=name, strings=json.dumps(STRINGS, ensure_ascii=False, indent=1))
    problems: list[str] = []
    for _ in range(2):
        answer = llm.ask_json(prompt + ("" if not problems else
                                        "\n\nYour last answer had these faults. Correct them: " + "; ".join(problems[:12])),
                              model=model, timeout=240)
        if isinstance(answer, dict):
            answer = {k: str(v).replace("\u2014", ", ").replace("\u2013", "-").strip() for k, v in answer.items() if k in STRINGS}
        problems = translation_problems(answer)
        if not problems:
            return answer
    raise ValueError(f"the {name} translation failed the checks: " + "; ".join(problems[:5]))


class Translations:
    """The sentences in each language. Shipped translations (made by the model when this was built, kept in
    notice_translations.json) are used while they match the English sentences; a language that is missing or
    out of date is asked of the model once and kept in `folder`. With no model, that language is not offered
    and the notice is in English only."""

    def __init__(self, folder: Path | str | None = None, model: str = "sonnet", use_model: bool = True):
        self.folder = Path(folder) if folder else None
        self.model, self.use_model = model, use_model
        self._held: dict[str, dict | None] = {}
        self.notes: dict[str, str] = {}

    def _stored(self, code: str) -> dict | None:
        places = [SHIPPED] + ([self.folder / "translations.json"] if self.folder else [])
        for place in reversed(places):
            try:
                entry = json.loads(place.read_text(encoding="utf-8"))["languages"].get(code)
            except (OSError, ValueError, KeyError):
                continue
            if entry and entry.get("source_hash") == source_hash() and not translation_problems(entry.get("strings")):
                return entry
        return None

    def get(self, code: str) -> dict[str, str] | None:
        """The sentences in `code`, or None when no checked translation can be had."""
        if code == "en":
            return STRINGS
        if code not in LANGUAGES:
            return None
        if code in self._held:
            held = self._held[code]
            return held["strings"] if held else None
        entry = self._stored(code)
        if entry is None and self.use_model:
            try:
                entry = {"strings": translate(code, self.model), "source_hash": source_hash(), "model": self.model,
                         "made_on": date.today().isoformat()}
                self._keep(code, entry)
            except llm.ModelUnavailable as err:
                self.notes[code] = (str(err) if getattr(err, "for_screen", False) else
                                    "No language model is available on this server, so no new translation was made.")
            except Exception:
                self.notes[code] = "The language model's translation did not pass the checks, so it was not used."
        self._held[code] = entry
        return entry["strings"] if entry else None

    def _keep(self, code: str, entry: dict) -> None:
        if not self.folder:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        place = self.folder / "translations.json"
        try:
            held = json.loads(place.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = {"languages": {}}
        held["languages"][code] = entry
        place.write_text(json.dumps(held, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# ---- one notice ----------------------------------------------------------------------------------------------------------

_CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"     # no 0, O, 1, I or L, which are misread on paper


def new_code() -> str:
    """A code for one notice: eight characters in two groups, about 39 bits. It goes on the letter and opens
    the owner's own notice; a guess is one in several hundred billion, and guesses are counted per client."""
    raw = "".join(secrets.choice(_CODE_LETTERS) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def clean_code(text: str) -> str:
    """A code as a person might type it ("k7qf 2m9x") in its stored form, or "" when it cannot be one."""
    raw = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 and all(c in _CODE_LETTERS for c in raw) else ""


def money_words(amount: str) -> str:
    return f"USD {Decimal(amount):,.2f}"


def reference_end(reference: str, row: int) -> str:
    """The last four letters or digits of the holder's reference. With no reference the row's own number
    stands in, so the notice still identifies the property "by number or identifier"."""
    plain = re.sub(r"[^A-Za-z0-9]", "", reference or "")
    return plain[-4:].upper() if len(plain) >= 2 else f"{row:04d}"[-4:]


def facts_for(balance: dict, holder: dict, code: str, public_url: str) -> dict[str, str]:
    """The facts of one notice, as the exact text both languages carry."""
    contact = ", ".join(x for x in (holder.get("phone"), holder.get("email")) if x)
    return {
        "OWNER": balance["name"], "HOLDER": holder.get("name") or "",
        "AMOUNT": money_words(balance["amount"]),
        "LAST_ACTIVITY": balance["last_activity"],
        "DEADLINE": balance["place"]["handover"],
        "REFERENCE": reference_end(balance.get("reference") or "", balance["row"]),
        "YEARS": str(balance["place"]["years"]),
        "CODE": code, "LINK": public_url.rstrip("/") + "/n",
        "CONTACT": contact,
    }


def render(strings: dict[str, str], facts: dict[str, str], kind: str) -> dict[str, str]:
    """Every sentence with its facts put in. {KIND} is the kind of property in that language."""
    values = {**facts, "KIND": strings.get(f"kind_{kind}") or strings["kind_other"]}
    return {key: _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text) for key, text in strings.items()}


def check(balance: dict, holder: dict, facts: dict[str, str], english: dict[str, str],
          other: dict[str, str] | None = None, minimum: Decimal = Decimal("50.00")) -> dict:
    """Whether one notice may be called ready: {"ready", "elements": [{key, title, source, present}],
    "problems", "warnings", "delivery"}.

    Every required element must be present in the English text with its facts filled in; the owner must be
    reachable by post, or by email with consent on record; and, where there is a second language, each legally
    required fact must stand in it exactly as often as in the English text."""
    problems: list[str] = []
    warnings: list[str] = []
    elements = []
    body = " ".join(english.get(k, "") for k in ("heading",) + BODY_ORDER + FORM_KEYS)
    for element in ELEMENTS:
        present = all(english.get(k, "").strip() for k in element["strings"])
        own = " ".join(english.get(k, "") for k in element["strings"])      # the element's own sentences
        for fact in element.get("facts", []):
            value = facts.get(fact, "")
            present = present and bool(value) and value in own
        if element["key"] == "heading":
            present = present and english.get("heading") == HEADING
        if element["key"] == "contact":
            present = present and bool(holder.get("phone") or holder.get("email")) and bool(holder.get("name"))
        elements.append({"key": element["key"], "title": element["title"], "source": element["source"],
                         "present": bool(present)})
        if not present:
            problems.append(f"Missing: {element['title'][0].lower() + element['title'][1:]}.")
    if _PLACEHOLDER.search(body):
        problems.append("A fact was not filled in.")
    if date.fromisoformat(facts["DEADLINE"]) <= date.fromisoformat(facts["LAST_ACTIVITY"]):
        problems.append("The date of transfer is not after the date of last activity.")
    # delivery
    by_post = bool(balance.get("street") and balance.get("city") and balance.get("country"))
    by_email = bool(balance.get("email")) and balance.get("e_consent") is True
    delivery = []
    if by_post:
        delivery.append({"channel": "post", "counts": True, "basis": "The law's default: by mail to the address on record."})
    if by_email:
        delivery.append({"channel": "email", "counts": True,
                         "basis": "The owner agreed to electronic notices, so email is allowed in place of post."})
    elif balance.get("email"):
        delivery.append({"channel": "email", "counts": False,
                         "basis": "An email address is on file with no consent to electronic notice. An email may "
                                  "go as an extra notice; it does not replace the letter. This is our reading of "
                                  "1520(c)."})
    if balance.get("phone"):
        delivery.append({"channel": "telephone", "counts": False,
                         "basis": "A telephone number is on file. A call is extra contact and does not replace "
                                  "the letter."})
    if not by_post and not by_email:
        problems.append("The file has no full postal address for this owner and no email with consent, so the "
                        "notice cannot be delivered. The law asks for a notice only where the holder has an address.")
    if Decimal(balance["amount"]) < minimum:
        warnings.append(f"Under {money_words(str(minimum))}: the law does not require a notice for this balance.")
    if other is not None:
        text_en = " ".join(english.values())
        text_other = " ".join(other.values())
        for fact in LEGAL_FACTS:
            value = facts[fact]
            if len(value) >= 4 and text_en.count(value) != text_other.count(value):
                problems.append(f"The {fact.lower().replace('_', ' ')} does not stand in the translation as it "
                                "does in the English text.")
        for key in BODY_ORDER + ("heading",):
            if sorted(_DIGITS.findall(english[key])) != sorted(_DIGITS.findall(other.get(key, ""))):
                problems.append(f"The numbers in one sentence of the translation ({key}) differ from the English.")
    return {"ready": not problems, "elements": elements, "problems": problems, "warnings": warnings,
            "delivery": delivery}


# ---- the letter ----------------------------------------------------------------------------------------------------------

def can_set(text: str) -> bool:
    """True when every character of `text` can be drawn with the fonts this machine embeds in a PDF."""
    from . import packet

    fonts = packet._load_fonts()
    known = fonts["KhutlisaSans"] | fonts.get("KhutlisaWide", set())
    return all(ch.isspace() or ord(ch) in known for ch in text)


def _flow(text: dict[str, str], facts: dict[str, str], balance: dict, holder: dict, *, language: str, today: str,
          reminder: bool, translated: bool, invented: bool, with_address: bool) -> list:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

    from . import packet

    wrap = "CJK" if LANGUAGES.get(language, ("", "", False))[2] else None
    ink, soft = colors.HexColor("#1b2438"), colors.HexColor("#5b6680")
    # The four statements the law wants "in boldface type or in a font a minimum of two points larger" are set
    # both bold and two points larger than the body.
    # Both weights are embedded in the PDF (Noto Sans, bundled), so the bold does not depend on what the reader's
    # machine puts in place of a font that is only named.
    fonts = packet._load_fonts()
    base = dict(fontName="KhutlisaSans", fontSize=8.6, leading=10.6, textColor=ink, wordWrap=wrap)
    body = ParagraphStyle("n-body", **base, spaceAfter=2.6)
    strong = ParagraphStyle("n-strong", **{**base, "fontName": "KhutlisaSans-Bold", "fontSize": 10.6, "leading": 12.4}, spaceAfter=2.6)
    head = ParagraphStyle("n-head", **{**base, "fontName": "KhutlisaSans-Bold", "fontSize": 10.6, "leading": 12.6}, spaceAfter=4)
    small = ParagraphStyle("n-small", **{**base, "fontSize": 8, "leading": 10, "textColor": soft})
    label = ParagraphStyle("n-label", **{**base, "fontSize": 8.5, "leading": 10.5, "textColor": soft})
    value = ParagraphStyle("n-value", **{**base, "fontName": "KhutlisaSans-Bold"})
    def t(value, bold: bool = False) -> str:
        """Safe for a Paragraph. A letter the bundled font lacks is set in the wide font, when there is one."""
        main = "KhutlisaSans-Bold" if bold else "KhutlisaSans"
        runs: list[tuple[str, str]] = []
        for ch in str(value or ""):
            font = main if ch.isspace() or ord(ch) in fonts[main] else "KhutlisaWide" if ord(ch) in fonts.get("KhutlisaWide", ()) else main
            if font == main and not ch.isspace() and ord(ch) not in fonts[main]:
                ch = "?"
            if runs and runs[-1][0] == font:
                runs[-1] = (font, runs[-1][1] + ch)
            else:
                runs.append((font, ch))
        return "".join(escape(part) if font == main else f'<font name="{font}">{escape(part)}</font>' for font, part in runs)

    P = lambda s, style=body, bold=False: Paragraph(t(s, bold), style)

    flow: list = []
    letterhead = ", ".join(x for x in (holder.get("name"), holder.get("street"),
                                      " ".join(y for y in (holder.get("city"), holder.get("region"), holder.get("postcode")) if y),
                                      "United States" if holder.get("country") == "US" else holder.get("country")) if x)
    flow.append(P(letterhead, small))
    flow.append(Spacer(1, 2 * mm))
    flow.append(P(text["heading"], head, True))
    if translated:
        flow.append(P(text["translation_note"], small))
        flow.append(Spacer(1, 2 * mm))
    if reminder:
        flow.append(P(text["reminder"], strong, True))
    flow.append(P(today, small))
    if with_address:
        from .countries import COUNTRIES

        for line in (balance["name"], balance.get("street"),
                     " ".join(x for x in (balance.get("city"), balance.get("region"), balance.get("postcode")) if x),
                     COUNTRIES.get(balance.get("country") or "", {}).get("name", balance.get("country") or "")):
            if line:
                flow.append(P(line))
    flow.append(Spacer(1, 3 * mm))
    kind = text.get(f"kind_{balance['property_class']}") or text["kind_other"]
    rows = [(text["label_regarding"], f"{kind}, {facts['HOLDER']}"), (text["label_reference"], facts["REFERENCE"]),
            (text["label_amount"], facts["AMOUNT"]), (text["label_last_activity"], facts["LAST_ACTIVITY"]),
            (text["label_deadline"], facts["DEADLINE"]), (text["label_code"], facts["CODE"])]
    table = Table([[P(a, label), P(b, value, True)] for a, b in rows], colWidths=[80 * mm, 92 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 0.6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#d5d9e2"))]))
    flow.append(table)
    flow.append(Spacer(1, 2 * mm))
    flow.append(P(text["greeting"]))
    for key in BODY_ORDER:
        if key == "respond_contact" and not facts.get("CONTACT"):
            continue
        emphasised = key in EMPHASISED
        flow.append(P(text[key], strong if emphasised else body, emphasised))
    flow.append(Spacer(1, 1 * mm))
    flow.append(P(text["closing"]))
    flow.append(P(" ".join(x for x in (holder.get("contact"), holder.get("name")) if x) or facts["HOLDER"]))
    blank = "_" * 34
    form = [P(text["form_title"], value, True), Spacer(1, 1.5 * mm),
            Table([[P(f"{text['form_signature']}: {blank}"), P(f"{text['form_date']}: {'_' * 14}")]], colWidths=[115 * mm, 55 * mm]),
            P(f"{text['form_name']}: {blank}"), P(f"{text['form_address']}: {blank}{blank}"),
            Table([[P(f"{text['form_city']}: {'_' * 14}"), P(f"{text['form_region']}: {'_' * 8}"),
                    P(f"{text['form_postcode']}: {'_' * 8}"), P(f"{text['form_country']}: {'_' * 10}")]],
                  colWidths=[48 * mm, 44 * mm, 38 * mm, 40 * mm]),
            P(text["form_action"], value, True), P("[  ] " + text["form_keep"]), P(f"[  ] {text['form_other']} {blank}")]
    flow.append(Spacer(1, 2.5 * mm))
    flow.append(KeepTogether(form))
    if invented:
        flow.append(Spacer(1, 1 * mm))
        flow.append(P("Demonstration notice. The owner, the holder and the balance are invented.", small))
    return flow


def letter_pdf(letters: list[dict]) -> bytes:
    """One PDF with every letter in `letters`, each starting on a new page: the English notice, then the same
    notice in the owner's language where there is one.

    A letter is {"balance", "holder", "facts", "english", "other" (or None), "language", "today", "reminder",
    "invented"}. The letters carry the owner's full name and postal address, so this PDF is for the holder."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate

    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, leftMargin=19 * mm, rightMargin=19 * mm, topMargin=12 * mm,
                          bottomMargin=10 * mm, title="Notice to the owner", author="Prepared with Khutlisa")
    doc.addPageTemplates(PageTemplate(id="all", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")]))
    flow: list = []
    for i, letter in enumerate(letters):
        if i:
            flow.append(PageBreak())
        common = dict(facts=letter["facts"], balance=letter["balance"], holder=letter["holder"], today=letter["today"],
                      reminder=letter.get("reminder", False), invented=letter.get("invented", False))
        flow += _flow(letter["english"], language="en", translated=False, with_address=True, **common)
        if letter.get("other"):
            flow.append(PageBreak())
            flow += _flow(letter["other"], language=letter["language"], translated=True, with_address=False, **common)
    doc.build(flow)
    return buffer.getvalue()


def web_view(text: dict[str, str], facts: dict[str, str], balance: dict, *, reminder: bool = False) -> dict:
    """One language of a notice for the screen on which the owner answers. The owner's name is not in it and
    neither is the street: the page is opened with a code alone, and the letter on paper already carries both."""
    kind = text.get(f"kind_{balance['property_class']}") or text["kind_other"]
    return {
        "heading": text["heading"],
        "reminder": text["reminder"] if reminder else "",
        "facts": [{"label": text["label_regarding"], "value": f"{kind}, {facts['HOLDER']}"},
                  {"label": text["label_reference"], "value": facts["REFERENCE"]},
                  {"label": text["label_amount"], "value": facts["AMOUNT"]},
                  {"label": text["label_last_activity"], "value": facts["LAST_ACTIVITY"]},
                  {"label": text["label_deadline"], "value": facts["DEADLINE"]}],
        "paragraphs": [{"key": key, "text": text[key], "strong": key in EMPHASISED} for key in BODY_ORDER
                       if key not in ("respond_online", "respond_post") and (key != "respond_contact" or facts.get("CONTACT"))],
        "ui": {key[3:]: value for key, value in text.items() if key.startswith("ui_")},
    }


def escape_text(value: str) -> str:
    return escape(value)
