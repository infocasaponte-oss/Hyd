import argparse
import json
from pathlib import Path
from .atomic import write_text_atomic
from .calibrate import calibrate
from .corpus import build, report


def main():
    parser = argparse.ArgumentParser(description="Standalone Hyd calibration and diagnostics")
    commands = parser.add_subparsers(dest="command", required=True)
    b = commands.add_parser("build")
    b.add_argument("--corpus", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
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
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.corpus, args.out)
        elif args.command == "report":
            result = report(args.dataset, args.model_dir)
            if args.out:
                write_text_atomic(args.out, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            result = calibrate(args.model, args.dataset, args.out, args.target, args.min_coverage, args.train_dataset)
    except (ValueError, OSError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
