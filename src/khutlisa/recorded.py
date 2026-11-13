"""The language model's answers to the public demonstration's fixed inputs, recorded once and shipped with the app.

The public copy runs without a model key. In public demonstration mode only fixed inputs are accepted anyway: the
demonstration sound files, the sample documents, the invented holder file and the demonstration people's own
words. For each of those the model was asked once, on a developer's machine (scripts/record_demo_answers.py),
and its answer is kept in recorded_answers.json under a hash of the exact input (llm.input_key: the prompt text
and the bytes of every file). In public demonstration mode llm.ask returns the recorded answer for such a call;
any other call goes on as it always did, which without a key is the honest "no model" path.

A document is read twice, by two separate calls with the same input, and the two readings are compared. Both
answers were recorded, and the calls with one key are given the recorded answers in turn.

`journeys` lists every model call the demonstration journeys make, by running the same functions the server
runs. The recording script runs it against the live model; the tests run it against the recorded file and fail
on any call that has no recorded answer.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

ANSWERS_FILE = Path(__file__).with_name("recorded_answers.json")
ROOT = Path(__file__).resolve().parents[2]


class RecordedAnswers:
    """The recorded answers, by input key. Thread-safe: the two readings of a document run side by side."""

    def __init__(self, answers: dict[str, list[str]], heard: dict | None = None):
        self.answers = {k: list(v) for k, v in answers.items() if v}
        self.heard = heard or {}
        self.used = 0
        self.missed = 0
        self._turn: dict[str, int] = {}
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: Path | str | None = None) -> "RecordedAnswers":
        try:
            data = json.loads(Path(path or ANSWERS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls({})
        return cls({k: v["answers"] for k, v in (data.get("answers") or {}).items()}, data.get("heard_on_server"))

    def answer(self, key: str) -> str | None:
        """The recorded answer for this input, or None. Calls with the same key are given the answers in turn."""
        with self._lock:
            got = self.answers.get(key)
            if not got:
                self.missed += 1
                return None
            n = self._turn.get(key, 0)
            self._turn[key] = n + 1
            self.used += 1
            return got[n % len(got)]

    def __len__(self) -> int:
        return len(self.answers)


# ---- the demonstration journeys' model calls -------------------------------------------------------------------

def _samples() -> Path:
    for place in (ROOT / "web" / "public" / "samples", ROOT / "web" / "dist" / "samples"):
        if place.is_dir():
            return place
    raise FileNotFoundError("the sample documents are not here (web/public/samples)")


def _heard() -> dict:
    for place in (ROOT / "web" / "public" / "demo" / "heard.json", ROOT / "web" / "dist" / "demo" / "heard.json"):
        if place.is_file():
            return json.loads(place.read_text(encoding="utf-8"))
    return {}


def _variants(*texts: str | None) -> list[str]:
    out: list[str] = []
    for t in texts:
        if t and t.strip() and t.strip() not in out:
            out.append(t.strip())
    return out


def journeys(heard_on_server: dict | None = None) -> list[tuple[str, Callable[[], object]]]:
    """Every model call of the demonstration journeys, as (what it is, a function that makes it). Each function
    calls the same code the server calls with the same inputs, so the prompts are the server's prompts.

    The spoken examples are transcribed on the server, and a recogniser may hear a word with another capital
    letter than it did here. `heard_on_server` holds what the public copy's recogniser heard from each sound file
    (kept in the answers file), and every version of the words is covered."""
    from . import demo, estates, holder_list, holder_file, intake, invented_holder

    heard = _heard()
    server = heard_on_server or {}
    samples = _samples()
    steps: list[tuple[str, Callable[[], object]]] = []

    # The intake of each demonstration person, and her answer to the one follow-up question. The follow-up's
    # input holds the first answer's own question, so it is made after the first call, in the same step.
    for person in demo.people():
        name = person["short_name"]
        sound, answer_sound = (Path(person.get("audio") or "").name, Path(person.get("answer_audio") or "").name)
        firsts = _variants(person["words"], (heard.get(sound) or {}).get("heard"), server.get(sound))
        answers = _variants(person["answer"], (heard.get(answer_sound) or {}).get("heard"), server.get(answer_sound))
        for i, words in enumerate(firsts):
            def run(words=words, answers=answers) -> None:
                first = intake.understand(words)
                for reply in answers:
                    intake.understand(reply, first["full_transcript"], first["follow_up"])
            steps.append((f"intake: {name}'s account (version {i + 1}) and her answer to the follow-up", run))

        # Her documents, each read twice by the same call.
        for doc in person.get("documents", []):
            from . import documents
            path = samples / doc["file"]
            for n in (1, 2):
                steps.append((f"document: {name}, {doc['label']} ({doc['kind']}), reading {n}",
                              lambda path=path, kind=doc["kind"]: documents.read_document(path, kind)))

    # The demonstration estate: the widow's words, the answer to the one question the rule asks, and every
    # document of the estate and of each heir, read twice.
    estate = json.loads((Path(__file__).with_name("demonstration_estate.json")).read_text(encoding="utf-8"))

    def family() -> None:
        said = estates.understand_family(estate["words"])
        question = estates.next_question(said["family"], said["asked"])
        if question:
            estates.understand_family(estate["answer"], said["full_transcript"], question["question"])
    steps.append(("estate: the family in the widow's words, and her answer to the one question", family))
    docs = list(estate.get("estate_documents", [])) + [d for h in estate.get("heirs", []) for d in h.get("documents", [])]
    for doc in docs:
        path = samples / doc["file"]
        for n in (1, 2):
            steps.append((f"estate document: {doc['label']} ({doc['kind']}), reading {n}",
                          lambda path=path, kind=doc["kind"]: estates.read_civil_record(path, kind)))

    # The holder's column mapping for the invented holder file, as a spreadsheet of text and as a workbook.
    table = invented_holder.rows()
    for label, data, filename in (("CSV", invented_holder.as_csv(table), invented_holder.file_name()),
                                  ("workbook", invented_holder.as_excel(table), invented_holder.file_name("excel"))):
        def mapping(data=data, filename=filename) -> None:
            read = holder_file.read(data, filename)
            holder_list.propose_from_model(read.header, read.rows, holder_list.propose_from_code(read.header, read.rows))
        steps.append((f"holder file: the column mapping of the invented file ({label})", mapping))
    return steps
