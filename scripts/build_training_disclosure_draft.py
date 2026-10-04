"""Bind an internal disclosure draft to an actual completed training run, not new downloads."""
# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build(run_path, corpus_path, tokens_path, tokenizer, weights, out):
    out = Path(out)
    if out.exists():
        raise ValueError("choose a new disclosure file")
    run = json.loads(Path(run_path).read_text(encoding="utf-8"))
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    tokens = json.loads(Path(tokens_path).read_text(encoding="utf-8"))
    if (run.get("kind") != "hydra-base" or run.get("data_manifest") != tokens
            or tokens.get("corpus_manifest_sha256") != digest(Path(corpus_path))):
        raise ValueError("training, token and corpus manifests do not match")
    for path, expected in ((Path(tokenizer), run["tokenizer_sha256"]), (Path(weights), run["weights_sha256"])):
        if digest(path) != expected:
            raise ValueError("model artifact hash mismatch")
    result = {"format": "hyd-training-disclosure-draft/1", "publication_status": "internal-draft-not-published",
              "official_template_completed": False, "legal_review_completed": False,
              "evidence": {"training_manifest_sha256": digest(Path(run_path)), "corpus_manifest_sha256": digest(Path(corpus_path)),
                           "tokens_manifest_sha256": digest(Path(tokens_path)), "tokenizer_sha256": run["tokenizer_sha256"],
                           "weights_sha256": run["weights_sha256"]},
              "general_information": {"provider_identity": None, "model_release_identifier": None, "modality": "text",
                                      "parameters": run["parameters"], "training_tokens_seen_recorded": run["tokens_seen"],
                                      "train_tokens_available_recorded": tokens["train"]["tokens"],
                                      "validation_tokens_recorded": tokens["validation"]["tokens"],
                                      "document_framing": tokens.get("document_framing"), "run_approved_recorded": run.get("approved")},
              "data_sources": [{"name": source["name"], "kind": source["kind"], "input_sha256": source["input_sha256"],
                                "kept_units_recorded": source["kept"], "characters_recorded": source["characters"],
                                "large_public_dataset_classification": "pending", "source_url_and_version": "pending",
                                "rights_review": "pending"} for source in corpus["sources"]],
              "processing": {"corpus_totals_recorded": corpus["totals"], "filters_recorded": corpus.get("filters"),
                             "copyright_and_optout_review": "pending", "privacy_review": "pending", "complaints_contact": None},
              "limitations": ["Recorded run values are not a legal clearance or a completed official template.",
                              "Kept units can be chunks; do not treat them as counts of unique original works.",
                              "Tokens_seen records training exposure, not unique deduplicated content tokens.",
                              "Current source corpus shards and token binaries were not rehashed in this draft.",
                              "New acquisition snapshots are excluded; do not misrepresent them as used training content."]}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("run", "corpus", "tokens", "tokenizer", "weights", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = build(args.run, args.corpus, args.tokens, args.tokenizer, args.weights, args.out)
    print(json.dumps({"publication_status": result["publication_status"], "sources": len(result["data_sources"]),
                      "training_tokens_seen_recorded": result["general_information"]["training_tokens_seen_recorded"]}))
