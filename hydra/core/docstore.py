# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Named JSON documents shared by every node, changed by atomic read-modify-write.

Small registries of the engine and the model factory (feature flags, secret policies, lab
experiments, glossaries, model lifecycle, factory registry, failure memory) are one JSON document
each. On one node a document is its file under the data directory (written atomically). With
PostgreSQL (HYDRA_DOCUMENTS_BACKEND) it is a row of ``hydra_documents``:

* ``update(fn)`` locks the row (``SELECT ... FOR UPDATE``), applies ``fn`` to the latest value and
  writes the result, so changes made by different nodes are never lost;
* ``get()`` returns a cached value refreshed at most every ``refresh_s`` seconds (and always after
  this node's own updates), so hot paths do not query the database on every call;
* an existing file is adopted once, when its row does not exist yet (the file is kept).

Requires ``psycopg`` 3 for PostgreSQL."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hydra.core.atomic import write_text_atomic

log = logging.getLogger("hydra.documents")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hydra_documents (
    name       TEXT PRIMARY KEY,
    body       JSONB NOT NULL,
    version    BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class DocumentStore:
    """Where the documents live: files (``url`` empty) or PostgreSQL."""

    def __init__(self, postgres_url: str = "") -> None:
        self.url = postgres_url
        self._local = threading.local()
        if postgres_url:
            import psycopg  # optional dependency
            from psycopg.types.json import Jsonb

            self._psycopg, self._jsonb = psycopg, Jsonb
            con = self.connection()
            with con.transaction():
                con.execute(SCHEMA)

    @property
    def backend(self) -> str:
        return "postgres" if self.url else "file"

    def connection(self):
        con = getattr(self._local, "con", None)
        if con is None or con.closed:
            con = self._psycopg.connect(self.url, autocommit=True)
            self._local.con = con
        return con

    def exports(self) -> dict[str, str]:
        """``{name: JSON text}`` of every PostgreSQL document, for backups (archived at ``data/<name>``);
        empty on files (the files themselves are backed up)."""
        if not self.url:
            return {}
        rows = self.connection().execute("SELECT name, body FROM hydra_documents ORDER BY name").fetchall()
        return {name: json.dumps(body, indent=2, ensure_ascii=False) for name, body in rows}

    def document(self, name: str, path: Path | None, default: Callable[[], Any] = dict,
                 refresh_s: float = 1.0) -> Document:
        """``name``: the document's key (also its place in a backup); ``path``: its file (None: kept in
        memory only, as stores without a path always were)."""
        store = self if path is not None else _MEMORY
        return Document(store, name, Path(path) if path is not None else None, default, refresh_s)


_MEMORY = DocumentStore("")


class Document:
    def __init__(self, store: DocumentStore, name: str, path: Path, default: Callable[[], Any],
                 refresh_s: float) -> None:
        self.store, self.name, self.path, self.default = store, name, path, default
        self.refresh_s = refresh_s
        self._lock = threading.RLock()
        self._value: Any = None
        self._version = -1
        self._checked = 0.0
        if store.backend == "postgres":
            self._adopt_file()

    @property
    def shared(self) -> bool:
        return self.store.backend == "postgres"

    # ------------------------------------------------------------------ files
    def _read_file(self) -> Any:
        if self.path is None or not self.path.is_file():
            return self.default()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_file(self, value: Any) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.path, json.dumps(value, indent=2, ensure_ascii=False, default=str))

    # ------------------------------------------------------------------ PostgreSQL
    def _adopt_file(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        cur = self.store.connection().execute(
            "INSERT INTO hydra_documents (name, body, version) VALUES (%s, %s, 1) ON CONFLICT (name) DO NOTHING",
            (self.name, self.store._jsonb(self._read_file())))
        if cur.rowcount:
            log.warning("adopted %s into PostgreSQL (document %s); the file is kept and no longer written",
                        self.path, self.name)

    # ------------------------------------------------------------------ API
    def get(self) -> Any:
        """The current value (do not mutate it: use ``update``)."""
        with self._lock:
            if not self.shared:
                if self._version < 0:
                    self._value, self._version = self._read_file(), 0
                return self._value
            if self._version < 0 or time.monotonic() - self._checked >= self.refresh_s:
                row = self.store.connection().execute(
                    "SELECT version FROM hydra_documents WHERE name = %s", (self.name,)).fetchone()
                version = row[0] if row else 0
                if version != self._version:
                    body = self.store.connection().execute(
                        "SELECT body FROM hydra_documents WHERE name = %s", (self.name,)).fetchone()
                    self._value = body[0] if body else self.default()
                    self._version = version
                self._checked = time.monotonic()
            return self._value

    def update(self, fn: Callable[[Any], Any]) -> Any:
        """Apply ``fn`` to a copy of the latest value and store what it returns; returns that value.
        On PostgreSQL the row stays locked from the read to the write."""
        with self._lock:
            if not self.shared:
                value = fn(copy.deepcopy(self.get()))
                self._write_file(value)
                self._value, self._version = value, 0
                return value
            con = self.store.connection()
            with con.transaction():
                con.execute("INSERT INTO hydra_documents (name, body, version) VALUES (%s, %s, 0) "
                            "ON CONFLICT (name) DO NOTHING", (self.name, self.store._jsonb(self.default())))
                body, version = con.execute("SELECT body, version FROM hydra_documents WHERE name = %s FOR UPDATE",
                                            (self.name,)).fetchone()
                value = fn(body)
                # JSON round trip: what is cached is exactly what other nodes will read
                value = json.loads(json.dumps(value, default=str))
                con.execute("UPDATE hydra_documents SET body = %s, version = %s, updated_at = now() WHERE name = %s",
                            (self.store._jsonb(value), version + 1, self.name))
            self._value, self._version, self._checked = value, version + 1, time.monotonic()
            return value

    def set(self, value: Any) -> Any:
        return self.update(lambda _: value)


def open_document_store(backend: str, postgres_url: str = "") -> DocumentStore:
    """``backend``: auto (PostgreSQL when ``postgres_url`` is set and psycopg is installed) | file | postgres."""
    if backend not in ("auto", "file", "postgres"):
        raise ValueError(f"unknown HYDRA_DOCUMENTS_BACKEND {backend!r}; use auto, file or postgres")
    if backend == "postgres" and not postgres_url:
        raise ValueError("HYDRA_DOCUMENTS_BACKEND=postgres requires HYDRA_POSTGRES_URL")
    if backend != "file" and postgres_url:
        try:
            return DocumentStore(postgres_url)
        except ImportError:
            if backend == "postgres":
                raise RuntimeError('the PostgreSQL document store needs psycopg: pip install "hydra-engine[postgres]"') \
                    from None
            log.warning("HYDRA_POSTGRES_URL is set but psycopg is not installed: documents stay in local files and "
                        "are NOT shared with other nodes")
    return DocumentStore("")


class KeyedModels:
    """A ``{key: model}`` registry stored as one document: reads are cached per document version,
    each write changes one key on the latest value (writes to different keys from different nodes
    never overwrite each other). ``model``: a pydantic model class, or None for plain JSON values."""

    def __init__(self, doc: Document, model=None) -> None:
        self.doc, self.model = doc, model
        self._raw: Any = None
        self._parsed: dict[str, Any] = {}

    def _parse(self, raw: dict) -> dict[str, Any]:
        if raw is not self._raw:
            self._parsed = {k: self.model.model_validate(v) if self.model else v for k, v in raw.items()}
            self._raw = raw
        return self._parsed

    def all(self) -> dict[str, Any]:
        """The current registry (read-only: change it with ``put``/``remove``)."""
        return self._parse(self.doc.get())

    def _dump(self, value):
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value

    def put(self, key: str, value):
        self._parse(self.doc.update(lambda d: {**d, key: self._dump(value)}))
        return value

    def change(self, key: str, fn: Callable[[Any], Any]):
        """``fn(current or None) -> new value`` applied on the latest stored value of ``key``."""
        holder = {}

        def apply(d: dict) -> dict:
            current = d.get(key)
            if current is not None and self.model:
                current = self.model.model_validate(current)
            holder["v"] = fn(current)
            return {**d, key: self._dump(holder["v"])}

        self._parse(self.doc.update(apply))
        return holder["v"]
