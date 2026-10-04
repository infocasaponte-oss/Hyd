# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Append-only event logs: the durable source of truth of the corpus and the World Model.

Both planes are event sourced: every change is one log entry and the in-memory state is the replay
of the log in order. A log lives either in a JSONL file under the data directory (one node) or in the
PostgreSQL table ``hydra_logs`` (shared by every node):

* an entry is ``(stream, seq, body)``; ``stream`` is the file's path relative to the data directory
  (``corpus/log.jsonl``, ``world/deltas.jsonl``...), ``seq`` starts at 1 and has no gaps, ``body``
  is the exact JSON line;
* an append takes a per-stream advisory lock and writes ``seq = head + 1``, so writers on many hosts
  produce one total order that every node replays identically;
* a trigger rejects UPDATE, DELETE and TRUNCATE;
* an existing file log is imported once when its stream is opened (a file that disagrees with the
  stream is refused) and the file is kept as a read-only copy.

The PostgreSQL backend requires ``psycopg`` 3 (``pip install "hydra-engine[postgres]"``)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

LOG = logging.getLogger("hydra.eventlog")

LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS hydra_logs (
    stream     TEXT NOT NULL,
    seq        BIGINT NOT NULL,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (stream, seq)
);
CREATE OR REPLACE FUNCTION hydra_logs_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'hydra_logs is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS hydra_logs_no_update ON hydra_logs;
CREATE TRIGGER hydra_logs_no_update BEFORE UPDATE OR DELETE ON hydra_logs
    FOR EACH ROW EXECUTE FUNCTION hydra_logs_immutable();
DROP TRIGGER IF EXISTS hydra_logs_no_truncate ON hydra_logs;
CREATE TRIGGER hydra_logs_no_truncate BEFORE TRUNCATE ON hydra_logs
    FOR EACH STATEMENT EXECUTE FUNCTION hydra_logs_immutable();
"""

# Advisory lock class for log streams (the object id is hashtext(stream)).
_LOG_LOCK_CLASS = 0x4C4F47  # "LOG"

Body = str | Callable[[int, str | None], str]
"""An entry body, or a builder ``(seq, previous_body) -> body`` called while the stream is locked
(for entries that embed their own sequence or point at the previous one, e.g. snapshots)."""


class LogConflict(RuntimeError):
    """The PostgreSQL stream and the local file log disagree; nothing was imported."""


def _build(body: Body, seq: int, last: str | None) -> str:
    text = body(seq, last) if callable(body) else body
    if "\n" in text or "\r" in text:
        raise ValueError("a log entry must be a single line")
    return text


_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.Lock:
    """One lock per file in this process, shared by every FileLog on that file."""
    key = str(Path(path).resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


class FileLog:
    """JSONL file log; ``seq`` is the 1-based index among non-empty lines. One writer process (several
    instances on the same file in that process are fine: appends re-read whatever the others wrote)."""

    backend = "file"
    shared = False

    def __init__(self, path: Path, stream: str = "") -> None:
        self.path = Path(path)
        self.stream = stream or self.path.name
        self._lock = _path_lock(self.path)
        self._count, self._last, self._size = 0, None, -1
        # (seq, byte offset just past it, its raw bytes): reads resume there instead of rescanning, after
        # checking those bytes are still in place (a rewritten file is read again from the start)
        self._tail: tuple[int, int, bytes] = (0, 0, b"")
        with self._lock:
            self._refresh()

    def _refresh(self) -> None:
        """Pick up lines appended by another instance (size changed); a shorter file was replaced."""
        size = self.path.stat().st_size if self.path.exists() else 0
        if size == self._size:
            return
        if size < self._size or not self._tail_intact():  # replaced or rewritten: count again
            self._count, self._last, self._tail = 0, None, (0, 0, b"")
        for seq, line in self.read(self._count):
            self._count, self._last = seq, line
        self._size = size

    def _tail_intact(self) -> bool:
        _, pos, last_raw = self._tail
        if not pos:
            return True
        try:
            with open(self.path, "rb") as f:
                f.seek(pos - len(last_raw))
                return f.read(len(last_raw)) == last_raw
        except OSError:
            return False

    def __len__(self) -> int:
        with self._lock:
            self._refresh()
            return self._count

    def append(self, body: Body) -> tuple[int, str]:
        with self._lock:
            self._refresh()
            seq = self._count + 1
            text = _build(body, seq, self._last)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "ab") as f:
                f.write((text + "\n").encode("utf-8"))
            self._count, self._last = seq, text
            self._size = self.path.stat().st_size
            self._tail = (seq, self._size, (text + "\n").encode("utf-8"))
            return seq, text

    def read(self, after: int = 0, upto: int | None = None) -> Iterator[tuple[int, str]]:
        if not self.path.exists():
            return
        if not self._tail_intact():  # rewritten, not appended: forget the position
            self._tail = (0, 0, b"")
        seq, pos, _ = self._tail if self._tail[0] <= after else (0, 0, b"")
        with open(self.path, "rb") as f:
            f.seek(pos)
            for raw in f:
                if not raw.endswith(b"\n"):
                    return  # a line still being written (or torn by a crash) is not an entry yet
                pos += len(raw)
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                seq += 1
                if seq > self._tail[0]:
                    self._tail = (seq, pos, raw)
                if upto is not None and seq > upto:
                    return
                if seq > after:
                    yield seq, line

    def export_text(self) -> str:
        return "".join(line + "\n" for _, line in self.read())


class PostgresLog:
    """One stream of ``hydra_logs``; connections come from the owning ``LogSpace``."""

    backend = "postgres"
    shared = True

    def __init__(self, space: LogSpace, stream: str) -> None:
        self._space = space
        self.stream = stream

    def _con(self):
        return self._space.connection()

    def __len__(self) -> int:
        return self._con().execute("SELECT coalesce(max(seq), 0) FROM hydra_logs WHERE stream = %s",
                                   (self.stream,)).fetchone()[0]

    def append(self, body: Body) -> tuple[int, str]:
        con = self._con()
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_LOG_LOCK_CLASS, self.stream))
            head = con.execute("SELECT seq, body FROM hydra_logs WHERE stream = %s ORDER BY seq DESC LIMIT 1",
                               (self.stream,)).fetchone()
            seq, last = (head[0] + 1, head[1]) if head else (1, None)
            text = _build(body, seq, last)
            con.execute("INSERT INTO hydra_logs (stream, seq, body) VALUES (%s, %s, %s)", (self.stream, seq, text))
        return seq, text

    def read(self, after: int = 0, upto: int | None = None) -> Iterator[tuple[int, str]]:
        if upto is None:
            rows = self._con().execute("SELECT seq, body FROM hydra_logs WHERE stream = %s AND seq > %s "
                                       "ORDER BY seq", (self.stream, after)).fetchall()
        else:
            rows = self._con().execute("SELECT seq, body FROM hydra_logs WHERE stream = %s AND seq > %s "
                                       "AND seq <= %s ORDER BY seq", (self.stream, after, upto)).fetchall()
        yield from rows

    def export_text(self) -> str:
        return "".join(body + "\n" for _, body in self.read())

    def import_file(self, source: FileLog) -> int:
        """Copy a file log into the stream once. A stream that already holds the file's entries (as a
        prefix, or the other way round) is extended or left as is; a different history is refused."""
        lines = [line for _, line in source.read()]
        con = self._con()
        with con.transaction():
            con.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", (_LOG_LOCK_CLASS, self.stream))
            present = len(self)
            if present:
                prefix = min(present, len(lines))
                stored = [body for _, body in self.read(0, prefix)]
                if stored != lines[:prefix]:
                    raise LogConflict(f"PostgreSQL stream {self.stream!r} and file {source.path} hold different "
                                      "histories; nothing imported")
            if present >= len(lines):
                return 0
            with con.cursor() as cur:
                cur.executemany("INSERT INTO hydra_logs (stream, seq, body) VALUES (%s, %s, %s)",
                                [(self.stream, seq, line) for seq, line in enumerate(lines[present:], present + 1)])
        return len(lines) - present


class LogSpace:
    """Opens the logs of one plane (``corpus``, ``world``), on files or on PostgreSQL."""

    def __init__(self, postgres_url: str = "", label: str = "") -> None:
        self.url = postgres_url
        self.label = label
        self._local = threading.local()
        if postgres_url:
            import psycopg  # optional dependency

            self._psycopg = psycopg
            con = self.connection()
            with con.transaction():
                con.execute(LOGS_SCHEMA)

    @property
    def backend(self) -> str:
        return "postgres" if self.url else "file"

    def connection(self):
        con = getattr(self._local, "con", None)
        if con is None or con.closed:
            con = self._psycopg.connect(self.url, autocommit=True)
            self._local.con = con
        return con

    def close(self) -> None:
        con = getattr(self._local, "con", None)
        if con is not None and not con.closed:
            con.close()

    def open(self, path: Path, stream: str) -> FileLog | PostgresLog:
        """``path``: the file log (written on files, imported once on PostgreSQL). ``stream``: its path
        relative to the data directory, e.g. ``corpus/log.jsonl`` (also its place in a backup)."""
        path = Path(path)
        if not self.url:
            log: FileLog | PostgresLog = FileLog(path, stream)
        else:
            log = PostgresLog(self, stream)
            if path.exists():
                imported = log.import_file(FileLog(path, stream))
                if imported:
                    LOG.warning("imported %d entries of %s into PostgreSQL (stream %s); the file is kept as a "
                                "read-only copy and is no longer written", imported, path, stream)
        return log

    def exports(self) -> dict[str, str]:
        """``{stream: JSONL text}`` of this plane's PostgreSQL streams (``<label>/...``), for backups;
        empty on files (the files themselves are backed up)."""
        if not self.url:
            return {}
        pattern = self.label.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
        streams = [s for (s,) in self.connection().execute(
            "SELECT DISTINCT stream FROM hydra_logs WHERE stream LIKE %s ORDER BY stream", (pattern,)).fetchall()]
        return {s: PostgresLog(self, s).export_text() for s in streams}


def open_log_space(backend: str, postgres_url: str = "", label: str = "") -> LogSpace:
    """``backend``: auto (PostgreSQL when ``postgres_url`` is set and psycopg is installed) | file | postgres."""
    setting = f"HYDRA_{label.upper()}_BACKEND" if label else "backend"
    if backend not in ("auto", "file", "postgres"):
        raise ValueError(f"unknown {setting} {backend!r}; use auto, file or postgres")
    if backend == "postgres" and not postgres_url:
        raise ValueError(f"{setting}=postgres requires HYDRA_POSTGRES_URL")
    if backend != "file" and postgres_url:
        try:
            return LogSpace(postgres_url, label)
        except ImportError:
            if backend == "postgres":
                raise RuntimeError(f'the PostgreSQL {label or "log"} store needs psycopg: '
                                   'pip install "hydra-engine[postgres]"') from None
            LOG.warning("HYDRA_POSTGRES_URL is set but psycopg is not installed: the %s stays in local files and "
                        "is NOT shared with other nodes", label or "log")
    return LogSpace("", label)
