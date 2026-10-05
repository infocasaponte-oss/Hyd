# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Development-only E2/E3 experiments retaining contributed question variants."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from hydra.hyd.hybrid_lopo import ENCODER, evaluate, fit_t, softmax_t, validate_folds

RISK = {"abstain", "high_risk_review", "security", "privacy"}


def validate_contributions(rows):
    for row in rows:
        rights = row.get("rights", {})
        if (row.get("consent") is not True or not row.get("consent_text")
                or not isinstance(rights, dict) or not rights.get("declared_by")
                or rights.get("license") not in {"proprietary-hydra-authored", "contributed-with-consent"}):
            raise ValueError("explicit contribution/owner declaration and consent required")
    # Flags and numbers never exclude a row. Family boundaries protect evaluation.
    return validate_folds(rows)


def admitted_marks(rows, marks):
    by_id = {r["id"]: r for r in rows}
    accepted, outside = [], 0
    seen = set()
    for mark in marks:
        if mark.get("id") in seen:
            raise ValueError("duplicate annotation record")
        seen.add(mark.get("id"))
        if (not isinstance(mark.get("text"), str)
                or hashlib.sha256(mark["text"].encode()).hexdigest() != mark.get("text_sha256")
                or mark.get("kind") not in {"dangerous", "missing_context"}
                or mark.get("source") not in {"human_original", "human_reconfirmed"}):
            raise ValueError("invalid declared human annotation")
        record = by_id.get(mark.get("id"))
        if record is None:
            outside += 1
            continue
        if (record["text_sha256"] != mark["text_sha256"] or record["person"] != mark.get("person")
                or record["expected"] != "abstain"):
            raise ValueError("annotation does not match its corpus record")
        accepted.append(mark)
    return accepted, outside


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def run(corpus, marks_path, out, revision, seed=42, resume=False):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("exact encoder revision required")
    rows = [json.loads(l) for l in corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    marks = [json.loads(l) for l in marks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    folds = validate_contributions(rows)
    marks, outside = admitted_marks(rows, marks)
    identity = {"corpus_sha256": _sha(corpus), "marks_sha256": _sha(marks_path), "seed": seed,
                "encoder_revision": revision, "implementation_sha256": _sha(Path(__file__)),
                "fold_implementation_sha256": _sha(Path(__file__).resolve().parents[1] / "hydra/hyd/hybrid_lopo.py")}
    if out.exists() and not resume:
        raise ValueError("output exists; use a new run or explicit --resume")
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("identity") != identity:
            raise ValueError("checkpoint binds different data, code, encoder or seed")
    elif resume:
        raise ValueError("no checkpoint available to resume")
    else:
        state = {"identity": identity, "done": {}, "embeddings_sha256": None}
        _write(state_path, state)
    import torch
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    import sklearn

    torch.set_num_threads(4)
    emb_path = out / "embeddings.npy"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if state["embeddings_sha256"]:
        if not emb_path.exists() or _sha(emb_path) != state["embeddings_sha256"]:
            raise ValueError("checkpoint embeddings integrity mismatch")
        embeddings = np.load(emb_path, allow_pickle=False)
    else:
        encoder = SentenceTransformer(ENCODER, revision=revision, device=device)
        if device == "cuda":
            encoder.half()
        embeddings = np.asarray(encoder.encode([r["text"] for r in rows], batch_size=64,
            normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True), dtype=np.float32)
        np.save(emb_path, embeddings, allow_pickle=False)
        state["embeddings_sha256"] = _sha(emb_path)
        _write(state_path, state)
        del encoder
        if device == "cuda":
            torch.cuda.empty_cache()
    if embeddings.shape != (len(rows), 384) or not np.isfinite(embeddings).all():
        raise ValueError("invalid cached embedding dimensions or values")
    labels = np.array([r["expected"] for r in rows])
    risk_labels = np.array([v if v in RISK else "other" for v in labels])
    report = {"format": "hyd-contributed-lopo/1", "status": "SHADOW_ONLY", "authority": False,
              "purpose": "development", "identity": identity, "encoder": ENCODER, "device": device,
              "n_rows": len(rows), "template_flag_rows_kept": sum("suspect_template" in r.get("flags", []) for r in rows),
              "marks_in_corpus": len(marks), "marks_outside_corpus": outside,
              "annotation_source_counts": dict(Counter(m["source"] for m in marks)),
              "human_identity_independently_verified": False,
              "versions": {"torch": torch.__version__, "sklearn": sklearn.__version__, "numpy": np.__version__},
              "limitation": "Declared persons and heuristic families; LOPO is diagnostic, not a fresh promotion test.",
              "folds": {}}
    by_mark = {m["id"]: m for m in marks}
    for held, (fit, cal, test) in folds.items():
        fold = {"n_train": int(fit.sum()), "n_calibration": int(cal.sum()), "n_test": int(test.sum())}
        indices = np.flatnonzero(test)
        for name, targets in (("E2", labels), ("E3", risk_labels)):
            key = held + "-" + name
            result_path, head_path, pred_path = [out / (key + suffix) for suffix in (".json", ".npz", ".predictions.jsonl")]
            if key in state["done"]:
                if any(not (out / p).exists() or _sha(out / p) != digest for p, digest in state["done"][key].items()):
                    raise ValueError("completed fold artifact integrity mismatch")
                result = json.loads(result_path.read_text(encoding="utf-8"))
            else:
                classifier = LogisticRegression(C=4.0, max_iter=3000, random_state=seed).fit(embeddings[fit], targets[fit])
                temperature = fit_t(classifier, embeddings[cal], targets[cal])
                probabilities = softmax_t(classifier.decision_function(embeddings[test]), temperature)
                result = evaluate(targets[test], probabilities, classifier.classes_)
                result["temperature"] = temperature
                result["macro_f1_scope"] = "classes with test support"
                np.savez(head_path, coef=classifier.coef_, intercept=classifier.intercept_,
                         classes=classifier.classes_, temperature=temperature)
                with np.load(head_path, allow_pickle=False) as saved:
                    reloaded = softmax_t(embeddings[test] @ saved["coef"].T + saved["intercept"], float(saved["temperature"]))
                    if not np.array_equal(saved["classes"], classifier.classes_) or not np.allclose(reloaded, probabilities, atol=1e-6, rtol=1e-6):
                        raise ValueError("saved head prediction parity failed")
                result["head_reload_parity_verified"] = True
                result["full_encoder_runtime_reload_verified"] = False
                predicted = classifier.classes_[probabilities.argmax(1)]
                prediction_rows = [{"id": rows[j]["id"], "text_sha256": rows[j]["text_sha256"],
                    "predicted": str(predicted[i]), "probabilities": dict(zip(classifier.classes_.tolist(), probabilities[i].tolist()))}
                    for i, j in enumerate(indices)]
                pred_path.write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in prediction_rows), encoding="utf-8")
                if name == "E3":
                    by_kind = {}
                    for kind in ("dangerous", "missing_context"):
                        for source in ("human_original", "human_reconfirmed"):
                            mask = [i for i, j in enumerate(indices) if rows[j]["id"] in by_mark
                                    and by_mark[rows[j]["id"]]["kind"] == kind and by_mark[rows[j]["id"]]["source"] == source]
                            by_kind[kind + "|" + source] = {"n": len(mask),
                                "recall_abstain": float((predicted[mask] == "abstain").mean()) if mask else None,
                                "recall_any_risk": float(np.isin(predicted[mask], list(RISK)).mean()) if mask else None,
                                "false_positive_rate": None, "precision": None,
                                "note": "Positive-only type annotations do not establish negatives."}
                    result["by_declared_abstain_kind"] = by_kind
                _write(result_path, result)
                state["done"][key] = {p.name: _sha(p) for p in (result_path, head_path, pred_path)}
                _write(state_path, state)
            fold[name] = result
            print(key, "accuracy", round(result["accuracy"], 4), flush=True)
        report["folds"][held] = fold
    _write(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--marks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--encoder-revision", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    run(args.corpus, args.marks, args.out, args.encoder_revision, args.seed, args.resume)


if __name__ == "__main__":
    main()
