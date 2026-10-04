# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Run under a supported Linux/WSL vLLM environment. Does not install vLLM.

Teacher-force every declared candidate using raw prompt logprobs; never top-k renormalization.
Dataset format: {id, split: calibration|validation, prompt, expected: label}.
"""
import argparse
import json
import math
from pathlib import Path

from hydra.training.verified_corpus import sha256


def collect(model: Path, dataset: Path, labels: list[str], output: Path):
    if output.exists() or output.with_suffix(".identity.json").exists():
        raise FileExistsError("use a new versioned score output")
    if len(set(labels)) != len(labels) or len(labels) < 2:
        raise ValueError("unique complete label set required")
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("nonempty dataset with unique IDs required")
    for r in rows:
        if r["split"] not in ("calibration", "validation") or r["expected"] not in labels or not r["prompt"]:
            raise ValueError("invalid split, prompt or expected label")
    # Explicit single-file fingerprint matches the current 1.5B merged artifact.
    identity = dict(weights_sha256=sha256(model/"model.safetensors"),
                    tokenizer_sha256=sha256(model/"tokenizer.json"), quantization="none",
                    dataset_sha256=sha256(dataset))
    import vllm
    from vllm import LLM, SamplingParams
    identity["backend_version"] = vllm.__version__
    llm = LLM(model=str(model), dtype="bfloat16", max_model_len=2048,
              gpu_memory_utilization=.75, logprobs_mode="raw_logprobs", seed=42,
              generation_config="vllm")
    tok = llm.get_tokenizer()
    outputs = []
    for row in rows:
        prompt = tok.apply_chat_template([dict(role="user", content=row["prompt"])],
                                         tokenize=False, add_generation_prompt=True)
        prefix = tok.encode(prompt, add_special_tokens=False)
        scores = {}
        for label in labels:
            full = tok.encode(prompt+label, add_special_tokens=False)
            if full[:len(prefix)] != prefix or len(full) <= len(prefix):
                raise ValueError("candidate tokenization changes prompt boundary")
            if tok.eos_token_id is None:
                raise ValueError("EOS token required for complete candidate events")
            full.append(tok.eos_token_id)
            result = llm.generate([dict(prompt_token_ids=full)],
                                 SamplingParams(temperature=1, max_tokens=1, prompt_logprobs=0),
                                 use_tqdm=False)[0]
            logs = result.prompt_logprobs
            if logs is None or len(logs) != len(full):
                raise ValueError("complete raw prompt logprobs unavailable")
            score = 0.
            for i in range(len(prefix),len(full)):
                if logs[i] is None or full[i] not in logs[i]:
                    raise ValueError("candidate token missing from teacher-forced logprobs")
                score += logs[i][full[i]].logprob
            if not math.isfinite(score):
                raise ValueError("nonfinite candidate score")
            scores[label] = score
        outputs.append(dict(id=row["id"], split=row["split"], expected=row["expected"],
                            candidate_logprobs=scores, logprobs_mode="raw_logprobs"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(r)+"\n" for r in outputs), encoding="utf-8")
    output.with_suffix(".identity.json").write_text(json.dumps(identity,indent=2), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--labels", nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    collect(a.model,a.dataset,a.labels,a.output)
