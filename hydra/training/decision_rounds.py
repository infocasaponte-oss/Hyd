# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Durable local rounds: queue -> human events -> snapshot -> candidate -> approval.

Run tick manually or watch with a bounded interval. No command promotes weights.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4

from hydra.hyd.continual import ContinualRanker
from hydra.router.decision_contract import CRITERIA as CRITERIA_LABELS
from hydra.training.decision_active_learning import admit, make_queue, read_rows, record_review
from hydra.training.decision_candidates import PARTS, file_sha, train_candidate, validate
from hydra.training.evidence_io import write_json


class RoundController:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "rounds.sqlite3"
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY,owner TEXT,expires REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS rounds(id TEXT PRIMARY KEY,state TEXT,config TEXT,binding TEXT,lease_owner TEXT,lease_until REAL DEFAULT 0,result TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,round_id TEXT,state TEXT,at REAL,detail TEXT)")

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, identity, config):
        if not identity or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in identity):
            raise ValueError("safe round ID required")
        if type(config.get("batch", 40)) is not int or not 1 <= config.get("batch", 40) <= 500:
            raise ValueError("invalid round batch")
        minimum = config.get("min_admitted", 40)
        if type(minimum) is not int or not 1 <= minimum <= config.get("batch", 40):
            raise ValueError("invalid minimum admission budget")
        for key, default, lower, upper in (("epochs", 100, 1, 2000),
                ("max_candidates_per_day", 2, 1, 10), ("challenge_count", 40, 1, 1000)):
            value = config.get(key, default)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("invalid bounded configuration: " + key)
        config = dict(config)
        if type(config.get("class_balance", False)) is not bool:
            raise ValueError("class_balance must be boolean")
        config["paths"] = {k: str(Path(v).resolve()) for k, v in config["paths"].items()}
        config["pool"] = str(Path(config["pool"]).resolve())
        validate({k: read_rows(Path(v)) for k, v in config["paths"].items()})
        if config.get("scorer"):
            config["scorer"] = str(Path(config["scorer"]).resolve())
        inputs = [*config["paths"].values(), config["pool"], *([config["scorer"]] if config.get("scorer") else [])]
        binding = {p: file_sha(p) for p in inputs}
        for path in (Path(__file__), Path(__file__).with_name("decision_active_learning.py"),
                     Path(__file__).with_name("decision_candidates.py")):
            binding["code:" + str(path)] = file_sha(path)
        with self.db() as db:
            db.execute("INSERT INTO rounds(id,state,config,binding) VALUES(?,?,?,?)",
                       (identity, "COLLECTING", json.dumps(config), json.dumps(binding)))
            db.execute("INSERT INTO events(round_id,state,at,detail) VALUES(?,?,?,?)",
                       (identity, "COLLECTING", time.time(), "created"))
        return self.status(identity)

    def status(self, identity):
        with self.db() as db:
            row = db.execute("SELECT state,config,binding,result FROM rounds WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("unknown round")
        return {"id": identity, "state": row[0], "config": json.loads(row[1]),
                "binding": json.loads(row[2]), "result": json.loads(row[3]) if row[3] else None}

    def transition(self, identity, state, result=None):
        with self.db() as db:
            db.execute("UPDATE rounds SET state=?,result=COALESCE(?,result) WHERE id=?",
                       (state, json.dumps(result) if result is not None else None, identity))
            db.execute("INSERT INTO events(round_id,state,at,detail) VALUES(?,?,?,?)",
                       (identity, state, time.time(), "state_transition"))

    @contextlib.contextmanager
    def lease(self, identity):
        owner = str(uuid4())
        with self.db() as db:
            cursor = db.execute("INSERT INTO leases(name,owner,expires) VALUES('factory',?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires=excluded.expires WHERE leases.expires<?",
                                (owner, time.time() + 120, time.time()))
            if cursor.rowcount != 1:
                raise RuntimeError("factory busy")
            cursor = db.execute("UPDATE rounds SET lease_owner=?,lease_until=? WHERE id=? AND lease_until<?",
                                (owner, time.time() + 120, identity, time.time()))
            if cursor.rowcount != 1:
                raise RuntimeError("round busy")
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(20):
                with self.db() as db:
                    db.execute("UPDATE rounds SET lease_until=? WHERE id=? AND lease_owner=?", (time.time() + 120, identity, owner))
                    db.execute("UPDATE leases SET expires=? WHERE name='factory' AND owner=?", (time.time() + 120, owner))
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()
            with self.db() as db:
                db.execute("UPDATE rounds SET lease_until=0,lease_owner=NULL WHERE id=? AND lease_owner=?", (identity, owner))
                db.execute("UPDATE leases SET expires=0 WHERE name='factory' AND owner=?", (owner,))

    def tick(self, identity, *, train=True):
        with self.lease(identity):
            status = self.status(identity)
            cfg = status["config"]
            for path, expected in status["binding"].items():
                actual = file_sha(path[5:] if path.startswith("code:") else path)
                if actual != expected:
                    raise ValueError("round inputs or implementation changed; create a new round")
            folder = self.root / identity
            folder.mkdir(exist_ok=True)
            queue = folder / "review"
            if status["state"] == "COLLECTING":
                if not queue.exists():
                    scorer = ContinualRanker.load(Path(cfg["scorer"])) if cfg.get("scorer") else None
                    seen = set()
                    for other in self.root.glob("*/review/original.jsonl"):
                        if other.parent.parent != folder:
                            seen.update(r["text_sha256"] for r in read_rows(other))
                    import hashlib
                    remaining = [r for r in read_rows(Path(cfg["pool"]))
                        if hashlib.sha256(r.get("text", r.get("question", "")).encode()).hexdigest() not in seen]
                    pending = folder / "pending-pool.jsonl"
                    pending.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in remaining), encoding="utf-8")
                    manifest = make_queue([Path(cfg["paths"]["fit"])], pending, queue,
                        strategy=cfg.get("strategy", "safety_margin"), k=cfg.get("batch", 40), scorer=scorer,
                        reserved=[Path(cfg["paths"][p]) for p in PARTS if p != "fit"])
                else:
                    manifest = json.loads((queue / "manifest.json").read_text())
                self.transition(identity, "WAITING_REVIEW" if manifest["queued"] else "NO_NEW_DATA")
            if self.status(identity)["state"] == "WAITING_REVIEW":
                if not (queue / "reviews.sqlite3").exists():
                    return self.status(identity)
                with sqlite3.connect(queue / "reviews.sqlite3") as db:
                    decisions = {i: json.loads(p) for i, p in db.execute("SELECT id,payload FROM review_events ORDER BY seq")}
                original = read_rows(queue / "original.jsonl")
                approved = sum(e["human_label"] in CRITERIA_LABELS for e in decisions.values())
                if len(decisions) < len(original) or approved < cfg.get("min_admitted", 40):
                    return self.status(identity)
                destination = folder / "admitted.jsonl"
                if not destination.exists():
                    admit(queue, destination)
                self.transition(identity, "ADMITTED", {"admitted_sha256": file_sha(destination)})
            if self.status(identity)["state"] == "ADMITTED":
                destination = folder / "fit.jsonl"
                rows = read_rows(Path(cfg["paths"]["fit"])) + read_rows(folder / "admitted.jsonl")
                if not destination.exists():
                    destination.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
                paths = {**cfg["paths"], "fit": str(destination)}
                validate({k: read_rows(Path(v)) for k, v in paths.items()})
                write_json(folder / "snapshot.json", {"paths": paths, "sha256": {k: file_sha(v) for k, v in paths.items()}})
                self.transition(identity, "SNAPSHOT_READY")
            if self.status(identity)["state"] in ("SNAPSHOT_READY", "TRAINING"):
                if not train:
                    return self.status(identity)
                if self.status(identity)["state"] == "SNAPSHOT_READY":
                    with self.db() as db:
                        count = db.execute("SELECT COUNT(DISTINCT round_id) FROM events WHERE state='TRAINING' AND at>?",
                                           (time.time() - 86400,)).fetchone()[0]
                    if count >= cfg.get("max_candidates_per_day", 2):
                        return self.status(identity)
                snapshot = json.loads((folder / "snapshot.json").read_text())
                if any(file_sha(snapshot["paths"][k]) != h for k, h in snapshot["sha256"].items()):
                    raise ValueError("round snapshot changed")
                self.transition(identity, "TRAINING")
                # Incomplete attempts survive for inspection. A crash never replaces live weights.
                complete = list(folder.glob("candidate-*/report.json"))
                if complete:
                    candidate = complete[0].parent
                    report = json.loads(complete[0].read_text())
                    if any(file_sha(candidate / name) != h for name, h in report["artifact_sha256"].items()):
                        raise ValueError("completed candidate artifacts changed")
                else:
                    candidate = folder / ("candidate-" + uuid4().hex)
                    report = train_candidate(snapshot["paths"], candidate, cfg.get("encoder", {"kind": "hash", "dims": 512}),
                                             epochs=cfg.get("epochs", 100), seed=cfg.get("seed", 42),
                                             fine_tune_epochs=cfg.get("fine_tune_epochs", 0),
                                             class_balance=cfg.get("class_balance", False))
                self.transition(identity, "WAITING_APPROVAL", {"candidate": str(candidate.resolve()),
                    "model_revision": report["model_revision"], "independent_test": False, "authority": False})
            if self.status(identity)["state"] == "WAITING_APPROVAL":
                snapshot = json.loads((folder / "snapshot.json").read_text())
                from hydra.training.decision_challenges import generate
                challenge_folder = folder / "challenge-proposals"
                if not challenge_folder.exists():
                    generate(Path(snapshot["paths"]["fit"]), challenge_folder,
                             seed=cfg.get("seed", 42), limit=cfg.get("challenge_count", 40))
            return self.status(identity)

    def next_round(self, identity, next_identity):
        """Continue development with the new head; never approve or deploy it."""
        previous = self.status(identity)
        if previous["state"] != "WAITING_APPROVAL":
            raise ValueError("a completed development candidate is required")
        folder = self.root / identity
        snapshot = json.loads((folder / "snapshot.json").read_text())
        if any(file_sha(snapshot["paths"][k]) != h for k, h in snapshot["sha256"].items()):
            raise ValueError("previous snapshot changed")
        config = {**previous["config"], "paths": snapshot["paths"],
                  "scorer": str(Path(previous["result"]["candidate"]) / "model.json"),
                  "parent_round": identity}
        ContinualRanker.load(Path(config["scorer"]))
        return self.create(next_identity, config)

    def review(self, identity, case_id, label, reviewer, notes=""):
        with self.lease(identity):
            if self.status(identity)["state"] != "WAITING_REVIEW":
                raise ValueError("round is not awaiting reviews")
            return record_review(self.root / identity / "review", case_id, label, reviewer, notes)

    def export(self, identity, destination):
        import zipfile
        if destination.exists():
            raise FileExistsError("new export required")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.lease(identity), zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in (self.root / identity).rglob("*"):
                if path.is_file():
                    archive.write(path, str(path.relative_to(self.root)))
            archive.writestr("round-state.json", json.dumps(self.status(identity), ensure_ascii=False))
            state = self.status(identity)
            snapshot = self.root / identity / "snapshot.json"
            paths = json.loads(snapshot.read_text())["paths"] if snapshot.exists() else state["config"]["paths"]
            portable = {}
            for name, source in paths.items():
                target = "inputs/" + name + ".jsonl"
                archive.write(source, target)
                portable[name] = {"path": target, "sha256": file_sha(source)}
            archive.write(state["config"]["pool"], "inputs/pool.jsonl")
            archive.writestr("portable-manifest.json", json.dumps({"partitions": portable,
                "pool_sha256": file_sha(state["config"]["pool"]), "private_export": True,
                "base_encoder": state["config"].get("encoder", {"kind": "hash", "dims": 512}),
                "authority": False}, ensure_ascii=False))
        return {"sha256": file_sha(destination), "private_export": True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    sub = p.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create")
    new.add_argument("--config", type=Path, required=True)
    for name in ("create", "tick", "status", "review", "export", "watch", "next"):
        cmd = new if name == "create" else sub.add_parser(name)
        cmd.add_argument("--round", required=True)
        if name == "review":
            cmd.add_argument("--id", required=True)
            cmd.add_argument("--label", required=True)
            cmd.add_argument("--reviewer", required=True)
            cmd.add_argument("--notes", default="")
        if name == "export":
            cmd.add_argument("--out", type=Path, required=True)
        if name == "next":
            cmd.add_argument("--next-round", required=True)
        if name == "watch":
            cmd.add_argument("--interval", type=int, default=30)
            cmd.add_argument("--checks", type=int, default=120)
            cmd.add_argument("--auto-next", action="store_true")
            cmd.add_argument("--round-limit", type=int, default=5)
    args = p.parse_args()
    controller = RoundController(args.root)
    if args.command == "create":
        result = controller.create(args.round, json.loads(args.config.read_text()))
    elif args.command == "review":
        result = controller.review(args.round, args.id, args.label, args.reviewer, args.notes)
    elif args.command == "export":
        result = controller.export(args.round, args.out)
    elif args.command == "next":
        result = controller.next_round(args.round, args.next_round)
    elif args.command == "watch":
        if not 10 <= args.interval <= 3600 or not 1 <= args.checks <= 10000 or not 1 <= args.round_limit <= 100:
            p.error("bounded watch: interval 10..3600, checks 1..10000")
        current, round_count = args.round, 1
        for _ in range(args.checks):
            result = controller.tick(current)
            if result["state"] == "WAITING_APPROVAL" and args.auto_next and round_count < args.round_limit:
                next_identity = args.round + "-auto-" + str(round_count + 1)
                try:
                    following = controller.status(next_identity)
                    if following["config"].get("parent_round") != current:
                        raise ValueError("automatic round identity belongs to another lineage")
                except ValueError as exc:
                    if str(exc) != "unknown round":
                        raise
                    controller.next_round(current, next_identity)
                current, round_count = next_identity, round_count + 1
                continue
            if result["state"] in ("WAITING_APPROVAL", "NO_NEW_DATA"):
                break
            time.sleep(args.interval)
    else:
        result = controller.tick(args.round) if args.command == "tick" else controller.status(args.round)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
