"""Reloadable shadow E2 head with integrity and encoder provenance checks."""
import hashlib
import json
import re

import numpy as np

from .contract import CRITERIA


def write_manifest(directory, encoder, revision, partition_hashes):
    payload = {"format": "hyd-e2-runtime/1", "encoder": encoder, "encoder_revision": revision,
               "normalize_embeddings": True, "status": "SHADOW_ONLY", "authority": False,
               "criteria": CRITERIA, "partition_sha256": partition_hashes,
               "files": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                         for name in ("head.npz", "report.json")}}
    (directory / "runtime.json").write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
    return payload


class E2Runtime:
    def __init__(self, directory):
        manifest = json.loads((directory / "runtime.json").read_text(encoding="utf-8"))
        if (manifest.get("format") != "hyd-e2-runtime/1" or manifest.get("criteria") != CRITERIA
                or manifest.get("authority") is not False or manifest.get("status") != "SHADOW_ONLY"
                or manifest.get("normalize_embeddings") is not True
                or not isinstance(manifest.get("encoder"), str) or not manifest["encoder"]
                or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("encoder_revision", ""))):
            raise ValueError("invalid E2 runtime contract")
        for name in ("head.npz", "report.json"):
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest.get("files", {}).get(name):
                raise ValueError(f"E2 integrity mismatch: {name}")
        with np.load(directory / "head.npz", allow_pickle=False) as head:
            self.coef, self.intercept = head["coef"].copy(), head["intercept"].copy()
            self.labels = head["labels"].tolist()
            self.temperature = float(head["T"])
            self.confidence = float(head["min_confidence"])
            self.margin = float(head["min_margin"])
            if head["abstain_all"].dtype != np.dtype(bool) or head["abstain_all"].shape != ():
                raise ValueError("invalid abstention flag")
            self.abstain_all = bool(head["abstain_all"])
        if (self.labels != sorted(CRITERIA) or self.coef.ndim != 2 or self.coef.shape[0] != len(self.labels)
                or self.coef.shape[1] < 1 or self.intercept.shape != (len(self.labels),)
                or not np.isfinite(self.coef).all() or not np.isfinite(self.intercept).all()
                or not np.isfinite(self.temperature) or self.temperature <= 0
                or not 0 <= self.confidence <= 1 or not 0 <= self.margin <= 1):
            raise ValueError("invalid E2 head dimensions or calibration")
        self.manifest = manifest
        self.encoder = None

    def predict_embeddings(self, embeddings):
        matrix = np.asarray(embeddings)
        if matrix.ndim != 2 or matrix.shape[1] != self.coef.shape[1] or not np.isfinite(matrix).all():
            raise ValueError("invalid E2 embedding dimensions or values")
        if not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5):
            raise ValueError("E2 requires normalized embeddings")
        logits = (matrix @ self.coef.T + self.intercept) / self.temperature
        logits -= logits.max(axis=1, keepdims=True)
        mass = np.exp(logits)
        probabilities = mass / mass.sum(axis=1, keepdims=True)
        result = []
        for row in probabilities:
            ordered = np.sort(row)
            accepted = not self.abstain_all and ordered[-1] >= self.confidence and ordered[-1] - ordered[-2] >= self.margin
            result.append({"label": self.labels[int(row.argmax())], "probabilities": dict(zip(self.labels, row.tolist())),
                           "accepted": bool(accepted), "status": "SHADOW_ONLY", "authority": False})
        return result

    def predict(self, texts):
        if not isinstance(texts, list) or not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("nonempty list of questions required")
        if self.encoder is None:
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer(self.manifest["encoder"],
                                               revision=self.manifest["encoder_revision"], device="cpu")
        embeddings = self.encoder.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
        return self.predict_embeddings(embeddings)
