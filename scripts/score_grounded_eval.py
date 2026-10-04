# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Fact-level scoring of grounded evaluations (complements exact match).

Exact match punishes correct answers phrased differently from the template. This scorer checks
the extracted fact of each family against the reference answer instead: heading, section count,
literal quote, rank and date, repeal polarity, abstention, and code identifiers. Heuristic and
deterministic; it does not replace human review.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
REFUSAL = re.compile(r"\bno (?:contiene|incluye|aparece|figura|está|define|se (?:define|incluye|menciona)|"
                     r"puedo|hay|consta|existe)\b|\bsolo incluye\b|\bno se encuentra\b", re.I)
URL = re.compile(r"https://www\.boe\.es/buscar/act\.php\?id=BOE-A-\d{4}-\d+")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def quoted(text: str) -> str | None:
    match = re.search(r"«(.+)»", text, re.S)
    return match.group(1) if match else None


def ticks(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def repeal_polarity(text: str) -> bool | None:
    """True = repealed, False = not repealed, None = unclear."""
    t = norm(text)
    # "Su estado es «No»" answers "the repeal status" with the metadata value itself.
    status = re.search(r"(?:estado|derogaci[óo]n|derogada)[^.«]{0,30}«\s*(s[íi]|no)\s*»", t)
    if status:
        return status.group(1) != "no"
    if re.search(r"derogada: no|\bno\b[^.]{0,40}derogad|sin derogar|no consta como derogad|^no\b", t):
        return False
    if re.search(r"derogada: sí|^sí\b|consta como derogad|está derogad", t):
        return True
    return None


def fact_match(family: str, output: str, reference: str) -> bool:
    out = norm(output)
    if family == "boe_heading":
        heading = quoted(reference)
        return heading is not None and norm(heading).rstrip(".") in out
    if family == "boe_sections":
        count = re.search(r"tiene (\d+) apartado", reference).group(1)
        numbers = re.findall(r"\b\d+\b", re.sub(r"art[íi]culo \d+|BOE-A-[\d-]+", "", output, flags=re.I))
        return numbers[:1] == [count] or f"{count} apartado" in out
    if family == "boe_quote":
        quote = quoted(reference)
        return quote is not None and norm(quote) in out
    if family == "boe_rank_date":
        rank = quoted(reference)
        day, month, year = re.search(r"el (\d+) de (\w+) de (\d{4})", reference).groups()
        numeric = f"{int(day):02d}/{MONTHS.index(month) + 1:02d}/{year}"
        return norm(rank) in out and (f"{day} de {month} de {year}" in out or numeric in out)
    if family == "boe_repealed":
        return repeal_polarity(output) == reference.startswith("Sí")
    if family in ("boe_absent", "code_absent"):
        return REFUSAL.search(output) is not None
    if family in ("code_functions", "code_imports", "code_methods", "code_params"):
        expected = ticks(reference)
        subject: set[str] = set()
        if family in ("code_methods", "code_params"):
            # The first name is the class/function asked about: echoing it is optional.
            subject, expected = {expected[0]}, expected[1:]
        found = ticks(output) or re.findall(r"[\w.*]+", output)
        listed = set(ticks(output)) - subject
        return all(name in found for name in expected) and (not ticks(output) or listed <= set(expected))
    raise ValueError(f"unknown family {family}")


def score(report: Path, dataset: Path) -> dict:
    rows = {json.loads(line)["id"]: json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()}
    data = json.loads(report.read_text(encoding="utf-8"))
    families: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "exact": 0, "fact": 0, "cited": 0})
    for case in data["cases"]:
        family = rows[case["id"]]["family"]
        entry = families[family]
        entry["total"] += 1
        entry["exact"] += bool(case["exact_match"])
        entry["fact"] += fact_match(family, case["output"], case["reference"])
        if family.startswith("boe_") and family != "boe_absent":
            entry["cited"] += bool(URL.search(case["output"]))
    totals = {k: sum(f[k] for f in families.values()) for k in ("total", "exact", "fact")}
    boe_cited = [f for name, f in families.items() if name.startswith("boe_") and name != "boe_absent"]
    totals["boe_citation_rate"] = (sum(f["cited"] for f in boe_cited) / max(1, sum(f["total"] for f in boe_cited)))
    return {"report": str(report), "complete": data.get("complete"), "artifact_sha256": data.get("artifact_sha256"),
            "totals": totals, "families": dict(sorted(families.items()))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--dataset", type=Path, default=Path("data/hydra-grounded-v1/test.jsonl"))
    args = parser.parse_args()
    print(json.dumps([score(r, args.dataset) for r in args.reports], indent=2, ensure_ascii=False))
