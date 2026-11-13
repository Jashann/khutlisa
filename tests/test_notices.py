"""The notice the law requires: its elements, its languages, its facts the same in both, and the letter."""
import json
import re
from decimal import Decimal

import pytest

from khutlisa import llm, notices

HOLDER = {"name": "Empacadora Valle Sereno", "street": "410 Harvest Row", "city": "Salinas", "region": "CA", "postcode": "93901",
          "country": "US", "contact": "Payroll office", "email": "payroll@valle-sereno.example", "phone": "+1 831 555 0142"}
BALANCE = {"row": 1071, "name": "Marisol E Tolmedo", "street": "Calle Fresno 214, Colonia Americana", "city": "Guadalajara",
           "region": "JAL", "postcode": "44160", "country": "MX", "amount": "1284.60", "currency": "USD",
           "last_activity": "2025-02-14", "reference": "EVS-004471", "property_class": "wages", "email": "m@example.com",
           "phone": "", "e_consent": True, "abroad": True,
           "place": {"handover": "2027-06-01", "years": 1, "status": "remit", "window": "closed"}}
FACTS = notices.facts_for(BALANCE, HOLDER, "K7QF-2M9X", "https://khutlisa.example/")
TRANSLATIONS = notices.Translations(use_model=False)


def both(code="es", balance=BALANCE, facts=FACTS):
    return (notices.render(notices.STRINGS, facts, balance["property_class"]),
            notices.render(TRANSLATIONS.get(code), facts, balance["property_class"]))


# ---- languages ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("country, region, code", [("MX", "JAL", "es"), ("PH", "", "tl"), ("JP", "", "ja"), ("CN", "", "zh-Hans"),
                                                   ("TW", "", "zh-Hant"), ("HK", "", "zh-Hant"), ("DE", "", "de"), ("BR", "", "pt"),
                                                   ("CA", "ON", "en"), ("CA", "QC", "fr"), ("GB", "", "en"), ("IN", "", "en")])
def test_the_owners_likely_language_comes_from_the_last_known_country(country, region, code):
    assert notices.language_for(country, region)["code"] == code


def test_where_no_translation_is_offered_the_notice_is_english_only_and_says_why():
    assert "official or working language" in notices.language_for("GB")["reason"]
    assert notices.language_for("IL") == {"code": "en", "name": "English", "native": "English", "reason": notices.ENGLISH_ONLY_REASON["script"]}
    assert notices.language_for("ZZ")["reason"] == notices.ENGLISH_ONLY_REASON["none"]
    assert set(notices.LIKELY_LANGUAGE.values()) <= set(notices.LANGUAGES)


# ---- translations --------------------------------------------------------------------------------------------------

def test_every_shipped_translation_matches_the_english_sentences_and_passes_the_checks():
    shipped = json.loads(notices.SHIPPED.read_text(encoding="utf-8"))["languages"]
    assert set(shipped) == set(notices.LANGUAGES) - {"en"}
    for code, entry in shipped.items():
        # If this fails, the English sentences were changed: run scripts/make_notice_translations.py again.
        assert entry["source_hash"] == notices.source_hash(), code
        assert notices.translation_problems(entry["strings"]) == [], code
        assert TRANSLATIONS.get(code) == entry["strings"]
        assert "\u2014" not in json.dumps(entry["strings"], ensure_ascii=False)


def test_a_translation_that_drops_a_placeholder_or_changes_a_number_is_refused():
    spanish = dict(TRANSLATIONS.get("es"))
    assert notices.translation_problems(spanish) == []
    assert notices.translation_problems({**spanish, "effect": spanish["effect"].replace("{AMOUNT}", "1.000 USD")}) == [
        "effect: the placeholders differ from the English sentence", "effect: the numbers differ from the English sentence"]
    assert notices.translation_problems({**spanish, "effect": spanish["effect"].replace("1500", "1.500")}) == [
        "effect: the numbers differ from the English sentence"]
    assert notices.translation_problems({**spanish, "law": spanish["law"] + " {YEARS}"}) == ["law: the placeholders differ from the English sentence"]
    assert notices.translation_problems({**spanish, "danger": spanish["danger"] + " {oops"}) == ["danger: a brace that is not a placeholder"]
    assert notices.translation_problems({k: v for k, v in spanish.items() if k != "heading"}) == ["heading: missing"]
    assert notices.translation_problems("no") == ["it is not a set of sentences"]


def test_the_model_translates_sentences_only_and_a_faulty_answer_is_sent_back_once(monkeypatch):
    spanish = dict(TRANSLATIONS.get("es"))
    prompts = []

    def model(prompt, **kwargs):
        prompts.append(prompt)
        answer = dict(spanish) if len(prompts) > 1 else {**spanish, "effect": "Si no responde, transferimos 1.284,60 USD."}
        return json.dumps(answer, ensure_ascii=False)

    monkeypatch.setattr(llm, "ask", model)
    assert notices.translate("es") == spanish and len(prompts) == 2
    assert "Your last answer had these faults" in prompts[1] and "effect: the placeholders differ" in prompts[1]
    for word in ("Tolmedo", "1284", "1,284.60", "Calle Fresno", "2027-06-01"):      # no owner's details reach the model
        assert word not in prompts[0]


def test_a_translation_that_fails_twice_is_not_used_and_no_model_means_english_only(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: json.dumps({"heading": "x"}))
    with pytest.raises(ValueError, match="failed the checks"):
        notices.translate("es")
    monkeypatch.setattr(notices, "SHIPPED", tmp_path / "none.json")
    fresh = notices.Translations(tmp_path)
    assert fresh.get("es") is None and "did not pass the checks" in fresh.notes["es"]
    monkeypatch.setattr(llm, "ask", lambda *a, **k: (_ for _ in ()).throw(llm.ModelUnavailable("off")))
    silent = notices.Translations(tmp_path)
    assert silent.get("fr") is None and "No language model" in silent.notes["fr"] and silent.get("en") is notices.STRINGS


def test_a_translation_made_on_this_server_is_kept_for_next_time(monkeypatch, tmp_path):
    spanish = dict(TRANSLATIONS.get("es"))
    calls = []
    monkeypatch.setattr(notices, "SHIPPED", tmp_path / "none.json")
    monkeypatch.setattr(llm, "ask", lambda prompt, **kw: calls.append(1) or json.dumps(spanish, ensure_ascii=False))
    assert notices.Translations(tmp_path).get("es") == spanish and len(calls) == 1
    assert notices.Translations(tmp_path, use_model=False).get("es") == spanish and len(calls) == 1


# ---- one notice ------------------------------------------------------------------------------------------------------

def test_the_facts_are_one_set_of_values_put_into_both_languages():
    english, spanish = both()
    assert FACTS == {**FACTS, "AMOUNT": "USD 1,284.60", "LAST_ACTIVITY": "2025-02-14", "DEADLINE": "2027-06-01", "REFERENCE": "4471",
                     "YEARS": "1", "CODE": "K7QF-2M9X", "LINK": "https://khutlisa.example/n"}
    for fact in notices.LEGAL_FACTS:
        value = FACTS[fact]
        assert " ".join(english.values()).count(value) == " ".join(spanish.values()).count(value) >= 1, fact
    assert english["heading"] == notices.HEADING and spanish["heading"].startswith("EL ESTADO DE CALIFORNIA")
    assert "unpaid wages" in english["identify"] and "{" not in " ".join(english.values()) + " ".join(spanish.values())


def test_a_complete_notice_is_ready_with_every_required_element_present():
    english, spanish = both()
    result = notices.check(BALANCE, HOLDER, FACTS, english, spanish)
    assert result["ready"] and result["problems"] == [] and result["warnings"] == []
    assert [e["key"] for e in result["elements"]] == ["heading", "escheat_date", "effects", "no_activity", "identifier", "danger",
                                                      "law", "form", "contact", "amount"]
    assert all(e["present"] and e["source"] for e in result["elements"])
    assert [(d["channel"], d["counts"]) for d in result["delivery"]] == [("post", True), ("email", True)]


@pytest.mark.parametrize("change, words", [
    (lambda e, h, b, f: e.update(heading="Please contact us about your money."), "Missing: the heading the law gives"),
    (lambda e, h, b, f: e.update(no_activity=""), "Missing: no owner activity since the date of last activity"),
    (lambda e, h, b, f: e.update(effect=e["effect"].replace("2027-06-01", "next summer")), "Missing: the date the property goes to the State"),
    (lambda e, h, b, f: e.update(identify=e["identify"].replace("4471", "")), "Missing: the account or reference"),
    (lambda e, h, b, f: e.update(form_keep=""), "Missing: a form the owner can sign and return"),
    (lambda e, h, b, f: h.update(phone="", email=""), "Missing: a telephone number or electronic way to answer"),
    (lambda e, h, b, f: e.update(law="California law requires {YEARS} years."), "A fact was not filled in."),
    (lambda e, h, b, f: b.update(street="", email=""), "cannot be delivered"),
    (lambda e, h, b, f: f.update(DEADLINE="2024-01-01"), "The date of transfer is not after the date of last activity."),
])
def test_a_notice_with_a_required_element_missing_cannot_be_ready(change, words):
    english, _ = both()
    holder, balance, facts = dict(HOLDER), dict(BALANCE), dict(FACTS)
    change(english, holder, balance, facts)
    result = notices.check(balance, holder, facts, english)
    assert not result["ready"] and any(words in problem for problem in result["problems"]), result["problems"]


def test_a_fact_that_differs_between_the_two_languages_holds_the_notice_back():
    english, spanish = both()
    spanish["effect"] = spanish["effect"].replace("USD 1,284.60", "USD 1,248.60")
    result = notices.check(BALANCE, HOLDER, FACTS, english, spanish)
    assert not result["ready"] and "The amount does not stand in the translation as it does in the English text." in result["problems"]
    english, spanish = both()
    spanish["respond"] = spanish["respond"].replace("2027-06-01", "2027-01-06")
    assert any("deadline" in p for p in notices.check(BALANCE, HOLDER, FACTS, english, spanish)["problems"])


def test_under_fifty_dollars_is_a_warning_and_email_without_consent_does_not_replace_the_letter():
    small = {**BALANCE, "amount": "12.00", "e_consent": None}
    english, _ = both(balance=small, facts=notices.facts_for(small, HOLDER, "K7QF-2M9X", "https://khutlisa.example"))
    result = notices.check(small, HOLDER, notices.facts_for(small, HOLDER, "K7QF-2M9X", "https://khutlisa.example"), english,
                           minimum=Decimal("50"))
    assert result["ready"] and result["warnings"] == ["Under USD 50.00: the law does not require a notice for this balance."]
    assert [(d["channel"], d["counts"]) for d in result["delivery"]] == [("post", True), ("email", False)]
    assert "our reading" in result["delivery"][1]["basis"]


def test_codes_are_hard_to_guess_easy_to_type_and_read_however_they_are_typed():
    codes = {notices.new_code() for _ in range(500)}
    assert len(codes) == 500 and all(re.fullmatch(r"[A-HJ-KM-NP-Z2-9]{4}-[A-HJ-KM-NP-Z2-9]{4}", c) for c in codes)
    assert notices.clean_code("k7qf 2m9x") == notices.clean_code("K7QF-2M9X") == "K7QF-2M9X"
    assert notices.clean_code("K7QF-2M9") == "" and notices.clean_code("K7QF-2M9O") == "" and notices.clean_code("") == ""


def test_the_reference_is_at_most_four_characters_and_never_empty():
    assert notices.reference_end("EVS-004471", 12) == "4471" and notices.reference_end("AB", 12) == "AB"
    assert notices.reference_end("", 1071) == "1071" and notices.reference_end("-", 7) == "0007"


# ---- the letter and the screen -------------------------------------------------------------------------------------

def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf))


def test_the_letter_is_a_pdf_with_the_english_notice_and_then_the_owners_language():
    english, spanish = both()
    letter = {"balance": BALANCE, "holder": HOLDER, "facts": FACTS, "english": english, "other": spanish, "language": "es",
              "today": "2026-11-13", "invented": True}
    pdf = notices.letter_pdf([letter])
    assert pdf[:4] == b"%PDF" and pages(pdf) == 2
    assert pages(notices.letter_pdf([{**letter, "other": None}])) == 1
    assert pages(notices.letter_pdf([letter, {**letter, "other": None}, {**letter, "reminder": True}])) == 5


def test_every_shipped_language_can_be_set_in_a_letter_or_is_reported():
    english, _ = both()
    for code in notices.LANGUAGES:
        if code == "en":
            continue
        text = notices.render(TRANSLATIONS.get(code), FACTS, "wages")
        if not notices.can_set(" ".join(text.values())):
            assert notices.LANGUAGES[code][2] or code == "ko"        # only the scripts that need a wide font
            continue
        letter = {"balance": BALANCE, "holder": HOLDER, "facts": FACTS, "english": english, "other": text, "language": code,
                  "today": "2026-11-13"}
        assert 2 <= pages(notices.letter_pdf([letter])) <= 3, code


def test_the_notice_on_screen_carries_no_name_and_no_street():
    english, spanish = both()
    for text in (english, spanish):
        view = notices.web_view(text, FACTS, BALANCE)
        shown = json.dumps(view, ensure_ascii=False)
        assert "Tolmedo" not in shown and "Calle Fresno" not in shown and "Marisol" not in shown
        assert view["facts"][2]["value"] == "USD 1,284.60" and view["facts"][-1]["value"] == "2027-06-01"
        assert [p["key"] for p in view["paragraphs"] if p["strong"]] == list(notices.EMPHASISED)
        assert set(view["ui"]) >= {"title", "lead", "submit", "name", "address", "country", "email", "not_found"}
