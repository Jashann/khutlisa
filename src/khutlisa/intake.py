"""Turns what a person says about their life into a history the registers can be searched with."""
from __future__ import annotations

from . import llm

PROMPT = """A person is describing, in their own words and possibly not in English, where they have lived and worked. \
We will use this to search public registers of unclaimed money for records in their name.

Their words (a speech-to-text transcript, so expect errors):
<<<
{transcript}
>>>

Return JSON with these fields:
- language: the language they spoke
- english: a faithful English translation of what they said
- given_names: every given name they use or have used (list)
- family_names: every family name they have used: birth name, married name, both halves of a double surname (list)
- places: list of objects for each place they lived or worked abroad: city, region (state or province code if known), \
postcode (only if they said it), country (ISO two-letter code), street (only if they said it), from_year, to_year, \
what (lived / worked / studied)
- employers: organisations that might have held money for them: employers, banks, insurers, landlords, utilities, \
schools (list of names as a register would write them, e.g. "KAISER FOUNDATION HOSPITALS")
- current_country: ISO two-letter code of where they live now
- follow_up: the single most useful question to ask next, in their language, if something needed for the search is \
missing. Ask for one thing only. If they named a place where they lived or worked and gave no postcode for it, ask \
for that postcode and nothing else: the postcode is what ties a record to a person, and the search never uses a \
street. Only when every place has its postcode, ask for a bank they used or another name they used then. Empty \
string if nothing important is missing.
- follow_up_english: the same question in English

Use only what they said. Do not invent names, addresses or years. Leave a field empty when it was not said."""


def history_from_words(transcript: str, model: str = "sonnet") -> dict:
    data = llm.ask_json(PROMPT.format(transcript=transcript.strip()), model=model)
    for key in ("given_names", "family_names", "places", "employers"):
        data.setdefault(key, [])
    return data


# ---- the intake as the app uses it: typed or spoken words in, a searchable history out -------------------------

MAX_WORDS = 6000            # characters of transcript kept; a spoken minute is under a thousand

# A prepared sentence for showing the flow without a microphone. The person in it is made up.
SAMPLE_TAGALOG = (
    "Ako si Amihan Dalisay Villareal. Dalisay ang apelyido ko noong dalaga pa ako, at Villareal na ngayon dahil "
    "nag-asawa ako noong 2015. Nagtrabaho ako bilang nars sa Bayview Mercy Hospital sa Daly City, California mula "
    "2009 hanggang 2018. Nakatira ako noon sa 1420 Larkmoor Street, Daly City, 94015. May account din ako noon sa "
    "Golden Coast Credit Union. Ngayon ay nakatira na ako sa Cebu City, dito sa Pilipinas."
)


def _text(value, limit: int = 120) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _year(value) -> int | None:
    try:
        year = int(str(value).strip()[:4])
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def clean_history(data: dict) -> dict:
    """The model's answer cut down to the shape the search accepts (server.HistoryIn), plus the years and the
    kind of stay for each place, which only the timeline on screen uses."""
    def names(key: str, most: int) -> list[str]:
        raw = data.get(key) or []
        raw = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        out: list[str] = []
        for item in raw:
            text = _text(item)
            if text and text.lower() not in {x.lower() for x in out}:
                out.append(text)
        return out[:most]

    places = []
    for p in data.get("places") or []:
        if not isinstance(p, dict):
            continue
        place = {k: _text(str(p.get(k) or "")) for k in ("city", "region", "postcode", "country", "street")}
        place["country"] = place["country"].upper()[:2] if len(place["country"]) == 2 else place["country"]
        place.update({"from_year": _year(p.get("from_year")), "to_year": _year(p.get("to_year")),
                      "what": _text(p.get("what") or "", 40)})
        if any(place[k] for k in ("city", "region", "postcode", "street")):
            places.append(place)
    country = _text(data.get("current_country") or "").upper()
    return {"given_names": names("given_names", 8), "family_names": names("family_names", 8),
            "places": places[:20], "employers": names("employers", 20),
            "current_country": country if len(country) == 2 and country.isalpha() else ""}


def join_answer(earlier: str, question: str, answer: str) -> str:
    """The earlier words with a follow-up answer added, so the model reads the whole account again."""
    earlier, answer = earlier.strip(), answer.strip()
    if not earlier:
        return answer
    asked = f"\n\n(They were then asked: {question.strip()})" if question.strip() else ""
    return f"{earlier}{asked}\n\nThey answered: {answer}"


def understand(words: str, earlier: str = "", question: str = "", model: str = "sonnet") -> dict:
    """What the two intake addresses return: the words, the English, the history and one follow-up question."""
    transcript = join_answer(earlier, question, words)[-MAX_WORDS:]
    data = history_from_words(transcript, model=model)
    if not isinstance(data, dict):
        raise ValueError("the model did not return a history")
    history = clean_history(data)
    follow_up = _text(data.get("follow_up") or "", 400)
    return {
        "transcript": words.strip(),
        "full_transcript": transcript,
        "language": _text(data.get("language") or "", 60),
        "english": _text(data.get("english") or "", MAX_WORDS),
        "history": history,
        "follow_up": follow_up,
        "follow_up_english": _text(data.get("follow_up_english") or "", 400),
        "follow_up_asks_for": asks_for(history) if follow_up else "",
    }


def asks_for(history: dict) -> str:
    """What the follow-up question is for, told in code from what the history still lacks: "postcode" when a place
    was named and none has a postcode, otherwise "more". The screen and anything that describes the screen say
    this, so they agree with the question that is shown."""
    places = history.get("places") or []
    return "postcode" if places and not any(p.get("postcode") for p in places) else "more"
