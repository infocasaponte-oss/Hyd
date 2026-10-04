# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Multi-layer deduplication and benchmark contamination guard.

    exact (sha256) -> near-duplicate (64-bit SimHash) -> semantic (embeddings) -> structural (normalised AST)

``x = a + b`` and ``result = left + right`` are the same example structurally."""

from __future__ import annotations

import ast
import hashlib
import re

from hydra.core.hashing import sha256_hex
from hydra.core.vectors import cosine as _cos
from hydra.corpus.records import CorpusRecord

WORD = re.compile(r"\w+", re.U)
CODE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def simhash(text: str, bits: int = 64) -> int:
    tokens = WORD.findall(text.lower())
    shingles = [" ".join(tokens[i:i + 3]) for i in range(max(1, len(tokens) - 2))] or [text]
    v = [0] * bits
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for i in range(bits):
            v[i] += 1 if h >> i & 1 else -1
    return sum(1 << i for i in range(bits) if v[i] > 0)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class _Normalizer(ast.NodeTransformer):
    def __init__(self) -> None:
        self.names: dict[str, str] = {}

    def _n(self, name: str) -> str:
        return self.names.setdefault(name, f"v{len(self.names)}")

    def visit_Name(self, node: ast.Name):
        return ast.copy_location(ast.Name(id=self._n(node.id), ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg):
        node.arg = self._n(node.arg)
        node.annotation = None
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef):
        node.name = self._n(node.name)
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value="S"), node)
        return node


def structural_hash(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    tree = _Normalizer().visit(tree)
    for node in ast.walk(tree):  # drop docstrings
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant):
            node.body = node.body[1:] or [ast.Pass()]
    return sha256_hex(ast.dump(tree, annotate_fields=False))


def code_of(rec: CorpusRecord) -> str | None:
    for block in (rec.output, rec.content, rec.action or {}):
        for v in block.values():
            if isinstance(v, str):
                if m := CODE.search(v):
                    return m.group(1)
                if "def " in v or "return " in v:
                    return v
    return None


class Deduplicator:
    def __init__(self, embed=None, near_bits: int = 3, semantic_threshold: float = 0.97) -> None:
        self.exact: dict[str, str] = {}
        self.sims: list[tuple[int, str]] = []
        self.structural: dict[str, str] = {}
        self.vectors: list[tuple[list[float], str]] = []
        self.embed = embed
        self.near_bits = near_bits
        self.semantic_threshold = semantic_threshold

    def fingerprints(self, rec: CorpusRecord) -> dict[str, str]:
        text = normalize_text(rec.text())
        fp = {"exact": sha256_hex(text), "simhash": f"{simhash(text):016x}"}
        if (code := code_of(rec)) and (s := structural_hash(code)):
            fp["structural"] = s
        return fp

    def find_duplicate(self, rec: CorpusRecord) -> str | None:
        fp = rec.hashes or self.fingerprints(rec)
        rec.hashes = fp
        if fp["exact"] in self.exact:
            return self.exact[fp["exact"]]
        sh = int(fp["simhash"], 16)
        for other, rid in self.sims:
            if hamming(sh, other) <= self.near_bits:
                return rid
        if "structural" in fp and fp["structural"] in self.structural:
            return self.structural[fp["structural"]]
        if self.embed is not None:
            vec = self.embed(rec.text()[:2000])
            for other, rid in self.vectors:
                if _cos(vec, other) >= self.semantic_threshold:
                    return rid
        return None

    def add(self, rec: CorpusRecord) -> None:
        fp = rec.hashes or self.fingerprints(rec)
        rec.hashes = fp
        self.exact.setdefault(fp["exact"], rec.id)
        self.sims.append((int(fp["simhash"], 16), rec.id))
        if "structural" in fp:
            self.structural.setdefault(fp["structural"], rec.id)
        if self.embed is not None:
            self.vectors.append((self.embed(rec.text()[:2000]), rec.id))




class ContaminationGuard:
    """TRAIN/EVAL/BENCHMARK hash sets + near-duplicate check so we never train on our own exam."""

    def __init__(self, near_bits: int = 6) -> None:
        self.exact: set[str] = set()
        self.sims: list[int] = []
        self.near_bits = near_bits

    def register_eval_texts(self, texts: list[str]) -> int:
        for t in texts:
            n = normalize_text(t)
            if len(n) < 12:
                continue
            self.exact.add(sha256_hex(n))
            self.sims.append(simhash(n))
        return len(self.exact)

    @classmethod
    def from_suites(cls, suites: dict) -> ContaminationGuard:
        g = cls()
        g.register_eval_texts([c.prompt for cases in suites.values() for c in cases])
        return g

    def contaminated(self, rec: CorpusRecord) -> bool:
        texts = [str(v) for v in rec.input.values() if isinstance(v, str)] or [rec.text()]
        for t in texts:
            n = normalize_text(t)
            if sha256_hex(n) in self.exact:
                return True
            sh = simhash(n)
            if any(hamming(sh, s) <= self.near_bits for s in self.sims):
                return True
        return False
