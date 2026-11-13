"""Our own ids for register rows, so the State's property number never leaves the server.

The register's own number for a property opens the owner's full name and address on the State's website, so it
must not appear in a reply or an address. Each row we show gets an id of our own instead: a keyed hash of the
source, the State's number and the owner's name. The hash cannot be turned back into the number, so the way back
is a small table kept on the server (id to source and number). The owner's name is not stored in it.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
from pathlib import Path


class RecordIds:
    def __init__(self, path: Path | str, secret: str | None = None):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._known: dict[str, tuple[str, str]] = {}
        self._secret = (secret or os.environ.get("KHUTLISA_ID_SECRET") or "").encode() or None

    def _db(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.execute("create table if not exists ids (id text primary key, source text, record_id text)")
        con.execute("create table if not exists meta (key text primary key, value text)")
        return con

    def _key(self) -> bytes:
        if self._secret is None:
            with self._lock, self._db() as con:
                row = con.execute("select value from meta where key = 'secret'").fetchone()
                if row is None:
                    con.execute("insert into meta values ('secret', ?)", [secrets.token_hex(32)])
                    row = con.execute("select value from meta where key = 'secret'").fetchone()
                self._secret = row[0].encode()
            con.close()
        return self._secret

    def public(self, record: dict) -> str:
        """The id to show for one register row. The same row always gets the same id."""
        source, record_id = record.get("source") or "", record.get("record_id") or ""
        text = "\x1f".join((source, record_id, record.get("owner_name") or ""))
        shown = "k" + hmac.new(self._key(), text.encode(), hashlib.sha256).hexdigest()[:23]
        if shown not in self._known:
            with self._lock, self._db() as con:
                con.execute("insert or ignore into ids values (?, ?, ?)", [shown, source, record_id])
            con.close()
            self._known[shown] = (source, record_id)
        return shown

    def find(self, shown: str) -> tuple[str, str] | None:
        """(source, the register's own number) for an id we handed out, or None."""
        if shown in self._known:
            return self._known[shown]
        with self._lock, self._db() as con:
            row = con.execute("select source, record_id from ids where id = ?", [shown]).fetchone()
        con.close()
        if row:
            self._known[shown] = (row[0], row[1])
        return tuple(row) if row else None
