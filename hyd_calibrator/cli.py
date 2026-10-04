import argparse
import json
from pathlib import Path
from .atomic import write_text_atomic
from .calibrate import calibrate
from .corpus import build, report
from .train import train


def main():
    parser = argparse.ArgumentParser(description="Standalone Hyd calibration and diagnostics")
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    b.add_argument("--corpus", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--grouped", action="store_true", help="Require declared person_id and family_id; isolate connected groups")
    b.add_argument("--development", action="store_true", help="Create grouped 60/10/15/15 train/development/calibration/test")
    r = commands.add_parser("report")
    r.add_argument("--dataset", required=True, type=Path)
    r.add_argument("--model-dir", required=True, type=Path)
    r.add_argument("--out", type=Path)
    c = commands.add_parser("calibrate")
    c.add_argument("--model", required=True, type=Path)
    c.add_argument("--dataset", required=True, type=Path)
    c.add_argument("--out", required=True, type=Path)
    c.add_argument("--train-dataset", type=Path)
    c.add_argument("--target", type=float, default=0.95)
    c.add_argument("--min-coverage", type=float, default=0.1)
    t = commands.add_parser("train")
    t.add_argument("--dataset", required=True, type=Path)
    t.add_argument("--out", required=True, type=Path)
    t.add_argument("--epochs", type=int, default=80)
    t.add_argument("--state-dims", type=int, choices=(512, 1024), default=512)
    t.add_argument("--option-dims", type=int, choices=(128, 256), default=128)
    args = parser.parse_args()
    try:
        if args.command in ("build", "calibrate", "train") and args.out.exists():
            raise ValueError("output directory already exists; choose a new run directory")
        if args.command == "build":
            result = build(args.corpus, args.out, grouped=args.grouped, development=args.development)
        elif args.command == "train":
            result = train(args.dataset, args.out, args.epochs, args.state_dims, args.option_dims)
        elif args.command == "report":
            if args.out and args.out.exists():
                raise ValueError("output file already exists")
            result = report(args.dataset, args.model_dir)
            if args.out:
                write_text_atomic(args.out, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            result = calibrate(args.model, args.dataset, args.out, args.target, args.min_coverage, args.train_dataset)
    except (ValueError, OSError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
