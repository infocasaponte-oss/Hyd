# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hand a built HYDRA.gguf candidate to the HYDRA-SO deployment plane.

``build_hydra`` leaves ``build-manifest.json`` (status CANDIDATE_REQUIRES_EVALUATION, never
auto-approved). This bridge turns it into a physical variant with full lineage (base weights,
dataset manifest, training run) and promotes it only through the runtime promotion gate with a
*measured* benchmark (quality, TTFT, tokens/s, peak VRAM). The result is the body of
``POST /hydra/v1/admin/deployments/register``; from there the candidate follows
CANDIDATE -> SHADOW -> CANARY -> ACTIVE with recorded evidence and rollback.

    python -m hydra.model_factory.deploy_bridge models/hydra-pilot --benchmark bench.json
        --capability coding --endpoint http://127.0.0.1:11434/v1 --served-model hydra-local
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hydra.model_factory.physical.benchmark import BenchmarkResult
from hydra.model_factory.contracts import BuildState, ModelLineage, ModelVariant
from hydra.model_factory.physical.promotion_gate import PromotionPolicy, apply_promotion_gate

READY = "CANDIDATE_REQUIRES_EVALUATION"


def _canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def variant_from_build(build_dir: str | Path, models_root: str | Path = "models") -> ModelVariant:
    """QUANTIZED variant for a finished build (refuses failed builds and artifacts outside models_root)."""
    root = Path(build_dir).resolve()
    manifest = json.loads((root / "build-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != READY:
        raise ValueError(f"build is not a finished candidate (status={manifest.get('status')!r})")
    artifact = Path(manifest["artifact"]).resolve()
    models = Path(models_root).resolve()
    if models not in artifact.parents:
        raise ValueError(f"artifact {artifact} is outside the deployment models root {models}")
    inputs = manifest["inputs"]
    recipe = inputs.get("recipe", {})
    lineage = ModelLineage(
        base_model=str(recipe.get("base_model", "unknown")),
        base_model_sha256=inputs["base_sha256"],
        dataset_manifest_sha256=_canonical_sha256(inputs["dataset"]),
        training_run_id=f"build:{root.name}:{_canonical_sha256(manifest['stages'])[:16]}",
    )
    return ModelVariant(
        lineage=lineage, quantization=manifest.get("quantization", "Q4_K_M"),
        artifact_path=artifact.relative_to(models).as_posix(), artifact_sha256=manifest["sha256"],
        state=BuildState.QUANTIZED,
        metadata={"build_manifest": str(root / "build-manifest.json"), "architecture": manifest.get("architecture"),
                  "trainer_sha256": inputs.get("trainer_sha256"), "quantizer_sha256": inputs.get("quantizer_sha256")},
    )


def promote_with_benchmark(variant: ModelVariant, benchmark: BenchmarkResult,
                           policy: PromotionPolicy | None = None) -> ModelVariant:
    """QUANTIZED -> BENCHMARKED -> PROMOTED, or PromotionDenied when the measurements fail the gate."""
    if benchmark.variant_id != str(variant.variant_id) and benchmark.variant_id != variant.artifact_sha256:
        raise ValueError("benchmark does not belong to this variant (use its variant_id or artifact sha256)")
    variant = variant.model_copy(deep=True)
    variant.state = BuildState.BENCHMARKED
    variant.metadata["benchmark"] = benchmark.model_dump()
    return apply_promotion_gate(variant, benchmark, policy)


def register_request(build_dir: str | Path, benchmark: BenchmarkResult, capabilities: list[str],
                     models_root: str | Path = "models", generation: int = 0,
                     policy: PromotionPolicy | None = None, *, endpoint: str, served_model: str) -> dict[str, Any]:
    parsed = urlparse(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("deployment endpoint must be local HTTP without credentials, query or fragment")
    if not served_model.strip():
        raise ValueError("served_model is required to route inference to the GGUF candidate")
    variant = promote_with_benchmark(variant_from_build(build_dir, models_root), benchmark, policy)
    variant.metadata.update(endpoint=endpoint.rstrip("/"), served_model=served_model.strip())
    return {"variant": variant.model_dump(mode="json"), "capabilities": capabilities, "generation": generation}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("build_dir", type=Path)
    parser.add_argument("--benchmark", type=Path, required=True, help="BenchmarkResult JSON (measured)")
    parser.add_argument("--capability", action="append", required=True)
    parser.add_argument("--models-root", default="models")
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument("--endpoint", required=True, help="Local OpenAI-compatible API, e.g. http://127.0.0.1:11434/v1")
    parser.add_argument("--served-model", required=True, help="Exact candidate model name served by that API")
    args = parser.parse_args()
    bench = BenchmarkResult.model_validate_json(args.benchmark.read_text(encoding="utf-8"))
    print(json.dumps(register_request(args.build_dir, bench, args.capability, args.models_root, args.generation,
                                      endpoint=args.endpoint, served_model=args.served_model),
                     indent=2))
