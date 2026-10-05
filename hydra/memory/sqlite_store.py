# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Local, namespaced persistent memory; portable JSONL exports, no model dependency."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from hydra.memory.models import MemoryItem, MemoryType
from hydra.memory.store import MemoryStore


class SQLiteMemoryStore(MemoryStore):
    def __init__(self, path: Path, namespace: str = "default"):
        if not namespace.strip():
            raise ValueError("memory namespace required")
        self.path, self.namespace = Path(path), namespace
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS memories(namespace TEXT,id TEXT,payload TEXT,revoked INTEGER DEFAULT 0,PRIMARY KEY(namespace,id))")
            db.execute("CREATE TABLE IF NOT EXISTS memory_events(seq INTEGER PRIMARY KEY,namespace TEXT,id TEXT,action TEXT,at TEXT,payload_sha256 TEXT)")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _event(self, db, identity, action, payload=""):
        db.execute("INSERT INTO memory_events(namespace,id,action,at,payload_sha256) VALUES(?,?,?,?,?)",
                   (self.namespace, identity, action, datetime.now(UTC).isoformat(), hashlib.sha256(payload.encode()).hexdigest()))

    async def save(self, item: MemoryItem):
        payload = item.model_dump_json()
        with self._db() as db:
            current = db.execute("SELECT revoked FROM memories WHERE namespace=? AND id=?", (self.namespace, item.id)).fetchone()
            if current and current[0]:
                raise ValueError("revoked memory cannot be silently restored")
            db.execute("INSERT INTO memories(namespace,id,payload) VALUES(?,?,?) ON CONFLICT(namespace,id) DO UPDATE SET payload=excluded.payload",
                       (self.namespace, item.id, payload))
            self._event(db, item.id, "save", payload)

    async def get(self, item_id):
        with self._db() as db:
            row = db.execute("SELECT payload FROM memories WHERE namespace=? AND id=? AND revoked=0", (self.namespace, item_id)).fetchone()
        return MemoryItem.model_validate_json(row[0]) if row else None

    async def all(self, memory_type: MemoryType | None = None):
        with self._db() as db:
            rows = db.execute("SELECT payload FROM memories WHERE namespace=? AND revoked=0 ORDER BY id", (self.namespace,)).fetchall()
        items = [MemoryItem.model_validate_json(row[0]) for row in rows]
        return [i for i in items if memory_type is None or i.memory_type == memory_type]

    async def touch(self, ids):
        with self._db() as db:
            for identity in ids:
                row = db.execute("SELECT payload FROM memories WHERE namespace=? AND id=? AND revoked=0", (self.namespace, identity)).fetchone()
                if row:
                    item = MemoryItem.model_validate_json(row[0])
                    item.last_accessed_at = datetime.now(UTC)
                    db.execute("UPDATE memories SET payload=? WHERE namespace=? AND id=?", (item.model_dump_json(), self.namespace, identity))

    async def revoke(self, identity):
        with self._db() as db:
            db.execute("UPDATE memories SET revoked=1 WHERE namespace=? AND id=?", (self.namespace, identity))
            self._event(db, identity, "revoke")

    async def export(self, path: Path):
        if path.exists():
            raise FileExistsError("choose a new export")
        with self._db() as db:
            rows = db.execute("SELECT payload,revoked FROM memories WHERE namespace=? ORDER BY id", (self.namespace,)).fetchall()
        records = [{"namespace": self.namespace, "payload": json.loads(payload), "revoked": bool(revoked),
                    "payload_sha256": hashlib.sha256(payload.encode()).hexdigest()} for payload, revoked in rows]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        return {"records": len(records), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    async def import_export(self, path: Path):
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        validated = []
        for record in records:
            item = MemoryItem.model_validate(record["payload"])
            if record["namespace"] != self.namespace or hashlib.sha256(item.model_dump_json().encode()).hexdigest() != record["payload_sha256"]:
                raise ValueError("memory export namespace or hash mismatch")
            validated.append((item, record["revoked"]))
        with self._db() as db:
            for item, revoked in validated:
                previous = db.execute("SELECT revoked FROM memories WHERE namespace=? AND id=?", (self.namespace, item.id)).fetchone()
                db.execute("INSERT INTO memories(namespace,id,payload,revoked) VALUES(?,?,?,?) ON CONFLICT(namespace,id) DO UPDATE SET payload=excluded.payload,revoked=excluded.revoked",
                           (self.namespace, item.id, item.model_dump_json(), int(revoked or bool(previous and previous[0]))))
                self._event(db, item.id, "import", item.model_dump_json())

    def backup(self, path: Path):
        if path.exists():
            raise FileExistsError("choose a new backup")
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as source, sqlite3.connect(path) as target:
            source.backup(target)
