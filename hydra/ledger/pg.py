# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""PostgreSQL ledger: one append-only, hash-chained, signed chain shared by every node.

Same contract as the file ``Ledger`` (``append``, ``correct``, ``anchor_now``, ``events``,
``for_object``, ``search``, ``anchors``, ``proof``, ``verify``, ``export_jsonl``) on the
``ip_events`` / ``ledger_anchors`` tables of ``sql/schema.sql``:

* every append takes a transaction-scoped advisory lock, reads the chain head and writes the next
  sequence explicitly, so concurrent writers on many hosts still produce one gap-free chain;
* the exact serialized event is stored in ``body`` and is what verification recomputes (TIMESTAMPTZ
  and JSONB columns are for querying; they do not preserve the hashed representation byte for byte);
* triggers reject UPDATE, DELETE and TRUNCATE: corrections are new ``EVENT_CORRECTION`` events.

Requires ``psycopg`` 3 (``pip install "hydra-engine[postgres]"``)."""

from __future__ import annotations

import json
import threading
from typing import Any, Iterator

from hydra.core.hashing import canonical_json, merkle_root
from hydra.ledger.chain import (
    GENESIS,
    ChainReport,
    Ledger,
    LedgerAnchor,
    LedgerEvent,
    LedgerEventType,
    event_hash,
    inclusion_proof,
    verify_chain,
)
from hydra.ledger.signing import Signer

# Arbitrary constant: the advisory lock that serialises appends to the chain.
_CHAIN_LOCK = 0x48594452  # "HYDR"

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS ip_events (
    sequence_id        BIGSERIAL PRIMARY KEY,
    event_id           UUID NOT NULL UNIQUE,
    project_id         TEXT NOT NULL DEFAULT 'hydra',
    event_type         TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    actor_type         TEXT NOT NULL,
    actor_id           TEXT NOT NULL,
    object_type        TEXT NOT NULL DEFAULT '',
    object_id          TEXT NOT NULL DEFAULT '',
    payload            JSONB NOT NULL,
    previous_hash      TEXT,
    event_hash         TEXT NOT NULL,
    signature          TEXT,
    signing_key_id     TEXT,
    confidentiality    TEXT NOT NULL,
    created_by_service TEXT NOT NULL
);
ALTER TABLE ip_events ADD COLUMN IF NOT EXISTS body TEXT;
CREATE INDEX IF NOT EXISTS ip_events_object ON ip_events (object_type, object_id);
CREATE INDEX IF NOT EXISTS ip_events_type ON ip_events (event_type, sequence_id);
CREATE OR REPLACE FUNCTION hydra_ledger_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ip_events is append-only: use an EVENT_CORRECTION event';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS ip_events_no_update ON ip_events;
CREATE TRIGGER ip_events_no_update BEFORE UPDATE OR DELETE ON ip_events
    FOR EACH ROW EXECUTE FUNCTION hydra_ledger_immutable();
DROP TRIGGER IF EXISTS ip_events_no_truncate ON ip_events;
CREATE TRIGGER ip_events_no_truncate BEFORE TRUNCATE ON ip_events
    FOR EACH STATEMENT EXECUTE FUNCTION hydra_ledger_immutable();
CREATE TABLE IF NOT EXISTS ledger_anchors (
    first_sequence   BIGINT NOT NULL,
    last_sequence    BIGINT NOT NULL,
    merkle_root      TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    external_timestamp_ref TEXT,
    PRIMARY KEY (first_sequence, last_sequence)
);
ALTER TABLE ledger_anchors ADD COLUMN IF NOT EXISTS body TEXT;
"""

_INSERT = """
INSERT INTO ip_events (sequence_id, event_id, project_id, event_type, created_at, actor_type, actor_id,
    object_type, object_id, payload, previous_hash, event_hash, signature, signing_key_id,
    confidentiality, created_by_service, body)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


class LedgerConflict(RuntimeError):
    """The PostgreSQL ledger and the local file ledger disagree; nothing was imported."""


class PostgresLedger:
    backend = "postgres"

    def __init__(self, url: str, signer: Signer | None = None, anchor_every: int = 1000) -> None:
        import psycopg  # optional dependency

        self._psycopg = psycopg
        self.url = url
        self.signer = signer
        self.anchor_every = anchor_every
        self._local = threading.local()
        con = self._con()
        with con.transaction():
            con.execute(LEDGER_SCHEMA)

    # ------------------------------------------------------------------ plumbing
    def _con(self):
        con = getattr(self._local, "con", None)
        if con is None or con.closed:
            con = self._psycopg.connect(self.url, autocommit=True)
            self._local.con = con
        return con

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None and not con.closed:
            con.close()

    @staticmethod
    def _event(body: str) -> LedgerEvent:
        return LedgerEvent.model_validate_json(body)

    def _insert(self, con, e: LedgerEvent) -> None:
        con.execute(_INSERT, (e.sequence, e.event_id, e.project_id, e.event_type, e.created_at, e.actor_type,
                              e.actor_id, e.object_type, e.object_id, canonical_json(e.payload), e.previous_hash,
                              e.event_hash, e.signature, e.signing_key_id, e.confidentiality, e.producer,
                              e.model_dump_json()))

    def _insert_anchor(self, con, a: LedgerAnchor) -> None:
        con.execute("INSERT INTO ledger_anchors (first_sequence, last_sequence, merkle_root, created_at, "
                    "external_timestamp_ref, body) VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (first_sequence, last_sequence) DO NOTHING",
                    (a.first_sequence, a.last_sequence, a.merkle_root, a.created_at, a.external_timestamp_ref,
                     a.model_dump_json()))

    def _hashes(self, con, first: int, last: int) -> list[str]:
        return [h for (h,) in con.execute("SELECT event_hash FROM ip_events WHERE sequence_id BETWEEN %s AND %s "
                                          "ORDER BY sequence_id", (first, last)).fetchall()]

    # ------------------------------------------------------------------ write
    def append(self, event_type: LedgerEventType | str, payload: dict[str, Any] | None = None, *,
               object_type: str = "", object_id: str = "", actor_type: str = "service", actor_id: str = "hydra",
               confidentiality: str = "INTERNAL_CONFIDENTIAL", project_id: str = "hydra",
               producer: str = "hydra") -> LedgerEvent:
        et = event_type.value if isinstance(event_type, LedgerEventType) else str(event_type)
        payload = json.loads(canonical_json(payload or {}))
        con = self._con()
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(%s)", (_CHAIN_LOCK,))
            head = con.execute("SELECT sequence_id, event_hash FROM ip_events ORDER BY sequence_id DESC "
                               "LIMIT 1").fetchone()
            sequence, previous = (head[0] + 1, head[1]) if head else (1, GENESIS)
            e = LedgerEvent(sequence=sequence, event_type=et, actor_type=actor_type, actor_id=actor_id,
                            object_type=object_type, object_id=object_id, project_id=project_id,
                            payload=payload, confidentiality=confidentiality, producer=producer,
                            previous_hash=previous)
            e.event_hash = event_hash(e.previous_hash, et, e.created_at, f"{actor_type}:{actor_id}", payload)
            if self.signer is not None:
                e.signature, e.signing_key_id = self.signer.sign(e.event_hash), self.signer.key_id
            self._insert(con, e)
            if self.anchor_every and e.sequence % self.anchor_every == 0:
                first = e.sequence - self.anchor_every + 1
                self._insert_anchor(con, LedgerAnchor(first_sequence=first, last_sequence=e.sequence,
                                                      merkle_root=merkle_root(self._hashes(con, first, e.sequence))))
        return e

    def correct(self, original_event_id: str, correction: dict[str, Any], reason: str, **kw) -> LedgerEvent:
        return self.append(LedgerEventType.EVENT_CORRECTION,
                           {"corrects": original_event_id, "correction": correction, "reason": reason}, **kw)

    def anchor_now(self) -> LedgerAnchor | None:
        con = self._con()
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(%s)", (_CHAIN_LOCK,))
            last_anchor = con.execute("SELECT max(last_sequence) FROM ledger_anchors").fetchone()[0] or 0
            count = len(self)
            if last_anchor + 1 > count:
                return None
            a = LedgerAnchor(first_sequence=last_anchor + 1, last_sequence=count,
                             merkle_root=merkle_root(self._hashes(con, last_anchor + 1, count)))
            self._insert_anchor(con, a)
            return a

    # ------------------------------------------------------------------ read
    def __len__(self) -> int:
        return self._con().execute("SELECT coalesce(max(sequence_id), 0) FROM ip_events").fetchone()[0]

    def events(self, event_type: str | None = None) -> Iterator[LedgerEvent]:
        if event_type is None:
            rows = self._con().execute("SELECT body FROM ip_events ORDER BY sequence_id").fetchall()
        else:
            rows = self._con().execute("SELECT body FROM ip_events WHERE event_type = %s ORDER BY sequence_id",
                                       (event_type,)).fetchall()
        for (body,) in rows:
            yield self._event(body)

    def for_object(self, object_type: str, object_id: str) -> list[LedgerEvent]:
        rows = self._con().execute("SELECT body FROM ip_events WHERE object_type = %s AND object_id = %s "
                                   "ORDER BY sequence_id", (object_type, object_id)).fetchall()
        return [self._event(body) for (body,) in rows]

    def search(self, needle: str) -> list[LedgerEvent]:
        pattern = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self._con().execute("SELECT body FROM ip_events WHERE object_id LIKE %s OR payload::text LIKE %s "
                                   "ORDER BY sequence_id", (pattern, pattern)).fetchall()
        return [e for e in (self._event(b) for (b,) in rows)
                if needle in e.object_id or needle in canonical_json(e.payload)]

    def anchors(self) -> list[LedgerAnchor]:
        rows = self._con().execute("SELECT body, first_sequence, last_sequence, merkle_root FROM ledger_anchors "
                                   "ORDER BY first_sequence").fetchall()
        return [LedgerAnchor.model_validate_json(body) if body else
                LedgerAnchor(first_sequence=f, last_sequence=last, merkle_root=root)
                for body, f, last, root in rows]

    def proof(self, sequence: int) -> dict[str, Any] | None:
        return inclusion_proof(self.anchors(), sequence, lambda f, last: self._hashes(self._con(), f, last))

    # ------------------------------------------------------------------ verify / portability
    def verify(self, public_keys: dict[str, str] | None = None) -> ChainReport:
        rows = self._con().execute("SELECT sequence_id, body FROM ip_events ORDER BY sequence_id").fetchall()
        events = []
        for sequence, body in rows:
            if body is None:
                return ChainReport(ok=False, events=len(rows), broken_at=sequence, reason="event body missing")
            events.append(self._event(body))
        return verify_chain(events, self.anchors(), self.signer, public_keys)

    def export_jsonl(self) -> tuple[str, str]:
        events = "".join(e.model_dump_json() + "\n" for e in self.events())
        anchors = "".join(a.model_dump_json() + "\n" for a in self.anchors())
        return events, anchors

    def import_file_ledger(self, source: Ledger, public_keys: dict[str, str] | None = None) -> int:
        """Copy a verified file ledger into an empty PostgreSQL ledger (hashes and signatures preserved).
        A PostgreSQL ledger that already holds the same chain is left as is; a different one is refused."""
        report = source.verify(public_keys)
        if not report.ok:
            raise LedgerConflict(f"file ledger does not verify ({report.reason} at {report.broken_at}); "
                                 "not imported")
        file_events = list(source.events())
        con = self._con()
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(%s)", (_CHAIN_LOCK,))
            present = len(self)
            if present:
                prefix = min(present, len(file_events))
                stored = self._hashes(con, 1, prefix)
                if stored != [e.event_hash for e in file_events[:prefix]]:
                    raise LedgerConflict("PostgreSQL ledger and file ledger are different chains; "
                                         "nothing imported")
                if present >= len(file_events):
                    return 0
            for e in file_events[present:]:
                self._insert(con, e)
            for a in source.anchors():
                self._insert_anchor(con, a)
        return len(file_events) - present


def open_ledger(backend: str, root, signer: Signer | None, anchor_every: int, postgres_url: str = ""):
    """The node's ledger. PostgreSQL ledgers adopt an existing file ledger once (verified, file kept)."""
    import logging

    log = logging.getLogger("hydra.ledger")
    if backend not in ("auto", "file", "postgres"):
        raise ValueError(f"unknown ledger backend {backend!r}; use auto, file or postgres")
    if backend == "postgres" and not postgres_url:
        raise ValueError("HYDRA_LEDGER_BACKEND=postgres requires HYDRA_POSTGRES_URL")
    if backend != "file" and postgres_url:
        try:
            ledger = PostgresLedger(postgres_url, signer, anchor_every=anchor_every)
        except ImportError:
            if backend == "postgres":
                raise RuntimeError('the PostgreSQL ledger needs psycopg: pip install "hydra-engine[postgres]"') \
                    from None
            log.warning("HYDRA_POSTGRES_URL is set but psycopg is not installed: the ledger stays in local files "
                        "and is NOT shared with other nodes")
        else:
            if (root / "events.jsonl").exists():
                imported = ledger.import_file_ledger(Ledger(root, signer, anchor_every=0))
                if imported:
                    log.warning("imported %d events of the file ledger %s into PostgreSQL; the file is kept "
                                "as a read-only copy and is no longer written", imported, root)
            return ledger
    return Ledger(root, signer, anchor_every=anchor_every)
