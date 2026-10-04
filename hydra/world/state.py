# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Unified World State: text, images, tool results and memory update one structured state
(objects, relations, events, time, uncertainty) instead of piling up descriptions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from hydra.memory.compiler import extract_facts
from hydra.memory.graph import MemoryGraph


def _now() -> str:
    return datetime.now(UTC).isoformat()


class WorldObject(BaseModel):
    id: str
    type: str = "entity"
    attributes: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    confidence: float = 0.6
    observed_at: str = Field(default_factory=_now)


class WorldRelation(BaseModel):
    subject: str
    predicate: str
    object: str
    source: str
    confidence: float = 0.6


class WorldEvent(BaseModel):
    time: str = Field(default_factory=_now)
    description: str
    source: str


class WorldState(BaseModel):
    objects: dict[str, WorldObject] = Field(default_factory=dict)
    relations: list[WorldRelation] = Field(default_factory=list)
    events: list[WorldEvent] = Field(default_factory=list)
    texts: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)

    @staticmethod
    def _key(name: str) -> str:
        return MemoryGraph.norm(name) or name.lower()

    def upsert(self, name: str, source: str, type_: str = "entity", confidence: float = 0.6,
               **attributes: Any) -> WorldObject:
        key = self._key(name)
        obj = self.objects.get(key)
        if obj is None:
            obj = WorldObject(id=name, type=type_, confidence=confidence)
            self.objects[key] = obj
        for k, v in attributes.items():
            old = obj.attributes.get(k)
            if old is not None and old != v:
                self.uncertainty.append(f"{name}.{k}: {old!r} vs {v!r} ({source})")
            obj.attributes[k] = v
        if source not in obj.sources:
            obj.sources.append(source)
        obj.confidence = max(obj.confidence, confidence)
        obj.observed_at = _now()
        return obj

    def relate(self, subject: str, predicate: str, obj: str, source: str, confidence: float = 0.6) -> None:
        self.upsert(subject, source)
        self.upsert(obj, source)
        for r in self.relations:
            if (self._key(r.subject), r.predicate, self._key(r.object)) == \
                    (self._key(subject), predicate, self._key(obj)):
                r.confidence = max(r.confidence, confidence)
                return
        self.relations.append(WorldRelation(subject=subject, predicate=predicate, object=obj,
                                            source=source, confidence=confidence))

    # ------------------------------------------------------------------ updaters
    def from_text(self, text: str, source: str = "user_input") -> None:
        for f in extract_facts(text):
            self.relate(f.subject, f.predicate, f.object, source, f.confidence)

    def from_memory(self, items: list[dict]) -> None:
        for m in items:
            if m.get("type") == "semantic":
                self.from_text(m.get("text", ""), source=f"memory:{m.get('id', '?')}")

    def from_tool(self, tool: str, arguments: dict, result: Any) -> None:
        src = f"tool:{tool}"
        if tool in ("filesystem.read", "filesystem.write") and "path" in arguments:
            size = len(result.get("content", "")) if isinstance(result, dict) and "content" in result else None
            self.upsert(arguments["path"], src, type_="file", confidence=0.95,
                        **({"chars": size} if size is not None else {}))
        elif tool == "python.execute" and isinstance(result, dict):
            self.events.append(WorldEvent(description=f"python exit={result.get('exit_code')} "
                                                      f"stdout={str(result.get('stdout', ''))[:120]!r}",
                                          source=src))
        elif tool == "sql.query_readonly" and "database" in arguments:
            self.upsert(arguments["database"], src, type_="database", confidence=0.95)
        else:
            self.events.append(WorldEvent(description=f"{tool} executed", source=src))

    def from_perception(self, observation: dict, source: str) -> None:
        for o in observation.get("objects", []):
            if isinstance(o, dict) and o.get("name"):
                self.upsert(o["name"], source, type_=o.get("type", "visual_object"),
                            confidence=float(o.get("confidence", 0.7)), **(o.get("attributes") or {}))
        for r in observation.get("relations", []):
            if isinstance(r, dict) and {"subject", "predicate", "object"} <= r.keys():
                self.relate(r["subject"], r["predicate"], r["object"], source, float(r.get("confidence", 0.7)))
        for t in observation.get("text", []):
            if t and t not in self.texts:
                self.texts.append(str(t))
        if d := observation.get("description"):
            self.events.append(WorldEvent(description=f"observed: {d}", source=source))

    # ------------------------------------------------------------------ rendering
    def render(self, max_items: int = 40) -> str:
        lines = []
        for o in list(self.objects.values())[:max_items]:
            attrs = ", ".join(f"{k}={v}" for k, v in o.attributes.items())
            lines.append(f"object {o.id} ({o.type}){': ' + attrs if attrs else ''}")
        lines += [f"relation {r.subject} {r.predicate} {r.object}" for r in self.relations[:max_items]]
        lines += [f"text \"{t}\"" for t in self.texts[:10]]
        lines += [f"event {e.description}" for e in self.events[-10:]]
        lines += [f"uncertain {u}" for u in self.uncertainty[:10]]
        return "\n".join(lines)

    @property
    def empty(self) -> bool:
        return not (self.objects or self.relations or self.events or self.texts)
