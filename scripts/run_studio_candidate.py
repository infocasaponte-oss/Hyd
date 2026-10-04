# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Isolated Studio using the native Hyd decision observer."""
import argparse
from pathlib import Path
import uvicorn
from hydra.api.main import create_app
from hydra.core.config import Settings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18084)
    parser.add_argument("--version", choices=["3", "4", "5", "6", "7", "8"], default="3")
    parser.add_argument("--backend", choices=["ollama", "llamacpp"], default="ollama")
    parser.add_argument("--grounded-specialist", action="store_true",
                        help="v8 generalist + v5 specialist for requests that bring a source (llamacpp, v8)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    suffix = "-llamacpp" if args.backend == "llamacpp" else ""
    catalog = root / f"config/models.hydra-instruction-v{args.version}{suffix}.yaml"
    if args.grounded_specialist:
        if args.backend != "llamacpp" or args.version != "8":
            parser.error("--grounded-specialist needs --backend llamacpp --version 8")
        catalog, suffix = root / "config/models.hydra-v8-v5-grounded-llamacpp.yaml", "-grounded"
    settings = Settings(models_config=catalog, offline=False,
                        evaluation_candidate_version=int(args.version) if int(args.version)>=6 else 5,
                        data_dir=root / f"runtime/studio-candidate-v{args.version}{suffix}/state", capture=False, public_web_enabled=True,
                        deterministic_first=True,
                        budget_time_scale=6, hyd_enabled=True, decision_shadow_endpoint="",
                        hyd_model_path=root / "config/hyd/model.json",
                        hyd_calibration_path=root / "config/hyd/calibration.json",
                        hyd_authority_evidence_path=None,
                        decision_local_model_path=None, decision_authority_evidence_path=None)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
