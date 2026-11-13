"""Records the language model's answers for every model call of the public demonstration's journeys.

    uv run python scripts/record_demo_answers.py                       # record what is missing, keep the rest
    uv run python scripts/record_demo_answers.py --fresh               # ask the model again for everything
    uv run python scripts/record_demo_answers.py --heard-from https://35-222-83-164.sslip.io
                                                                       # first ask the public copy what its
                                                                       # recogniser hears in each sound file

It runs on a developer's machine, where khutlisa.llm reaches the model through the `claude` program (or the API
with ANTHROPIC_API_KEY). It runs the same functions the server runs (recorded.journeys), so every prompt is the
server's own prompt, and keeps each answer in src/khutlisa/recorded_answers.json under the hash of the exact
input (the prompt and the bytes of every file). Only answers that parse as JSON are kept. A document is read
twice and both answers are kept. Inputs the journeys no longer make are dropped from the file.

The public copy, which has no model key, answers those calls from the file (recorded.py). Nothing here holds a
real person's details: every input is a demonstration input, invented.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from khutlisa import llm, recorded

LIVE = llm.ask


def heard_from(base: str) -> dict:
    """What the public copy's recogniser hears in each demonstration sound file (no model is asked for this)."""
    import httpx

    out = {}
    for path in sorted((recorded.ROOT / "web" / "public" / "demo").glob("*.m4a")):
        r = httpx.post(base.rstrip("/") + "/api/intake/heard", timeout=300,
                       files={"file": (path.name, path.read_bytes(), "audio/mp4")})
        r.raise_for_status()
        out[path.name] = r.json()["transcript"].strip()
        print(f"heard on {base}: {path.name}: {out[path.name]}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="ask the model again for every input")
    parser.add_argument("--heard-from", help="the public copy whose recogniser's words are added as inputs")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    try:
        old = json.loads(recorded.ANSWERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    heard = dict(old.get("heard_on_server") or {})
    if args.heard_from:
        heard.update(heard_from(args.heard_from))
    kept = {} if args.fresh else {k: list(v["answers"]) for k, v in (old.get("answers") or {}).items()}

    lock = threading.Lock()
    turn: dict[str, int] = {}
    new: dict[str, dict] = {}
    asked = [0]
    what = threading.local()

    def write() -> None:
        recorded.ANSWERS_FILE.write_text(json.dumps({
            "note": "The language model's answers to the public demonstration's fixed inputs, keyed by "
                    "llm.input_key (a hash of the prompt and the file bytes). Made by "
                    "scripts/record_demo_answers.py. Every input is invented demonstration material.",
            "recorded_on": date.today().isoformat(),
            "heard_on_server": heard,
            "answers": dict(sorted(new.items())),
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def ask(prompt: str, *, files=None, **kw) -> str:
        key = llm.input_key(prompt, files)
        with lock:
            n = turn.get(key, 0)
            turn[key] = n + 1
            entry = new.setdefault(key, {"what": what.label, "answers": []})
            if n < len(kept.get(key, [])):
                answer = kept[key][n]
                entry["answers"].append(answer)
                return answer
        answer = LIVE(prompt, files=files, **kw)
        try:
            llm._extract_json(answer)
        except (ValueError, json.JSONDecodeError):
            return answer            # not kept: ask_json asks again, and that answer is the one recorded
        with lock:
            asked[0] += 1
            entry["answers"].append(answer)
            write()
        return answer

    llm.ask = ask
    llm.recorded = None
    llm.gate = None
    problems = []

    def run(step) -> None:
        label, call = step
        what.label = label
        try:
            call()
            print("done:", label, flush=True)
        except Exception as err:
            problems.append(f"{label}: {type(err).__name__}: {str(err)[:200]}")
            print("FAILED:", label, err, flush=True)

    steps = recorded.journeys(heard)
    # The two readings of one document must not share a turn with another step: run each journey's steps in
    # order of the list, several at a time.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, steps))
    with lock:
        for entry in new.values():
            entry["answers"] = entry["answers"][:2]
        write()
    print(f"\n{len(new)} inputs recorded, {asked[0]} answers asked of the model this run, {len(steps)} steps.")
    for p in problems:
        print("problem:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
