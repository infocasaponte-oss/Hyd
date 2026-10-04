# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Knowledge graph over semantic facts: answers relational questions without similarity search."""

from __future__ import annotations

from collections import defaultdict

from hydra.memory.embeddings import tokenize
from hydra.memory.models import MemoryItem, MemoryStatus, MemoryType


class MemoryGraph:
    def __init__(self) -> None:
        self.out: dict[str, list[tuple[str, str, str]]] = defaultdict(list)  # node -> (pred, obj, item_id)
        self.inc: dict[str, list[tuple[str, str, str]]] = defaultdict(list)  # node -> (pred, subj, item_id)
        self.labels: dict[str, str] = {}

    @staticmethod
    def norm(node: str) -> str:
        return " ".join(tokenize(node))

    @classmethod
    def build(cls, items: list[MemoryItem]) -> MemoryGraph:
        g = cls()
        for item in items:
            if item.memory_type == MemoryType.SEMANTIC and item.status != MemoryStatus.CONFLICT:
                c = item.content
                g.add(c["subject"], c["predicate"], c["object"], item.id)
        return g

    def add(self, subject: str, predicate: str, obj: str, item_id: str = "") -> None:
        s, o = self.norm(subject), self.norm(obj)
        self.labels.setdefault(s, subject)
        self.labels.setdefault(o, obj)
        self.out[s].append((predicate, o, item_id))
        self.inc[o].append((predicate, s, item_id))

    def neighbors(self, node: str) -> list[tuple[str, str, str]]:
        """(subject, predicate, object) triples touching ``node``."""
        n = self.norm(node)
        triples = [(self.labels[n], p, self.labels[o]) for p, o, _ in self.out.get(n, [])]
        triples += [(self.labels[s], p, self.labels[n]) for p, s, _ in self.inc.get(n, [])]
        return triples

    def dependents(self, node: str, predicate: str = "depends_on") -> list[str]:
        """e.g. '¿Qué servicios dependen de Redis?'"""
        n = self.norm(node)
        return [self.labels[s] for p, s, _ in self.inc.get(n, []) if p == predicate]

    def mentioned(self, text: str) -> list[str]:
        """Graph nodes mentioned in free text."""
        norm_text = " " + " ".join(tokenize(text)) + " "
        return [self.labels[n] for n in self.labels if n and f" {n} " in norm_text]
