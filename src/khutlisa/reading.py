"""Reads uploaded documents in the background, so an upload answers at once and the screen polls for the result."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import claims as cl
from . import documents


def read_twice(path, kind: str, read: Callable[..., dict] | None = None) -> dict:
    """Two separate readings of one document, made at the same time so the wait does not double, and combined
    by documents.combine_readings. The two calls share nothing: each is its own question to the model. A reading
    that breaks counts as failed and the other one is still kept."""
    one = read or documents.read_document

    def attempt(_) -> dict:
        try:
            return one(path, kind)
        except Exception:
            return {"status": "failed", "problem": "The document could not be read this time."}

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="reading") as pool:
        first, second = pool.map(attempt, range(2))
    return documents.combine_readings(first, second)


class ReadingRunner:
    """One thread per document, at most two documents at a time. Each document is read twice, by two separate
    calls to the model that run side by side."""

    def __init__(self, store: cl.ClaimStore, is_ready: Callable[[dict], bool] | None = None,
                 read: Callable[..., dict] | None = None):
        self.store = store
        self.is_ready = is_ready
        self.read = read   # None means documents.read_document, looked up at call time so tests can replace it
        self._gate = threading.Semaphore(2)
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def start(self, claim_id: str, doc_id: str) -> None:
        thread = threading.Thread(target=self._work, args=(claim_id, doc_id), daemon=True,
                                  name=f"reading-{claim_id}-{doc_id}")
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()

    def _work(self, claim_id: str, doc_id: str) -> None:
        with self._gate:
            try:
                claim = self.store.load(claim_id)
                doc = next(d for d in claim["documents"] if d["id"] == doc_id)
                path = self.store.files(claim_id) / doc["stored_as"]
                reading = read_twice(path, doc["kind"], self.read)
            except Exception:   # a reading must never be left as "reading" for ever
                reading = {"status": "failed", "problem": "The document could not be read this time."}
            try:
                self.store.set_reading(claim_id, doc_id, reading, self.is_ready)
            except cl.ClaimError:
                pass

    def resume_all(self) -> None:
        """Documents that were still being read when the server last stopped are read again."""
        for claim in self.store.all():
            for doc in claim.get("documents", []):
                if (doc.get("reading") or {}).get("status") == "reading":
                    self.start(claim["id"], doc["id"])

    def join(self, timeout: float = 30.0) -> None:
        """Waits for every reading under way. Used by the tests."""
        with self._lock:
            threads = list(self._threads)
        for t in threads:
            t.join(timeout)
