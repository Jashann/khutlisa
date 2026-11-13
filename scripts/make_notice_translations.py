"""Asks the language model for the notice's sentences in each language and keeps the ones that pass the checks.

    uv run python scripts/make_notice_translations.py            # every language that is missing or out of date
    uv run python scripts/make_notice_translations.py es tl      # only these

The result is src/khutlisa/notice_translations.json, which ships with the product, so a server with no language
model still has the notice in these languages. Only the sentences go to the model: they carry placeholders, and
no owner's details exist at this point. Each answer is checked in code (notices.translation_problems): every
sentence present, the same placeholders and the same numbers as the English sentence. A language that fails
twice is left out, and the notice for its countries is then in English only.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from khutlisa import notices

MODEL = "sonnet"


def one(code: str):
    try:
        return code, notices.translate(code, MODEL), None
    except Exception as err:      # the model is missing, or the answer failed the checks
        return code, None, str(err)[:300]


if __name__ == "__main__":
    try:
        held = json.loads(notices.SHIPPED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = {"languages": {}}
    now = notices.source_hash()
    wanted = sys.argv[1:] or [c for c in notices.LANGUAGES if c != "en"
                              and (held["languages"].get(c) or {}).get("source_hash") != now]
    print(f"English sentences: {len(notices.STRINGS)}, hash {now}. To translate: {', '.join(wanted) or 'nothing'}")
    with ThreadPoolExecutor(max_workers=6) as pool:
        for code, strings, problem in pool.map(one, wanted):
            if strings is None:
                print(f"{code}: not kept. {problem}")
                continue
            held["languages"][code] = {"strings": strings, "source_hash": now, "model": MODEL,
                                       "made_on": date.today().isoformat(), "language": notices.LANGUAGES[code][0]}
            print(f"{code}: kept, {len(strings)} sentences")
            held["note"] = ("Translations of the notice's sentences, made by a language model and checked in code. "
                            "No owner's details were in what the model saw. Not reviewed by a translator or a lawyer.")
            notices.SHIPPED.write_text(json.dumps(held, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
