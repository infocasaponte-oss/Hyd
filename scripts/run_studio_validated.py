# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Local Studio using the current source and a calibrated shadow classifier."""
from pathlib import Path
import argparse

import uvicorn

from hydra.api.main import create_app
from hydra.core.config import Settings


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18082)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = Settings(models_config=root / "config/models.hydra-local.yaml", offline=False,
                        data_dir=root / "runtime/studio-validated/state", budget_time_scale=6,
                        decision_local_model_path=root / "models/hydra-decision-v4/classifier.json",
                        decision_local_calibration_path=root / "models/hydra-decision-v4/local-calibration.json")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)
