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
    e3 = commands.add_parser("e3-report")
    e3.add_argument("--corpus", required=True, type=Path)
    e3.add_argument("--predictions", required=True, type=Path)
    e3.add_argument("--selections", required=True, type=Path)
    e3.add_argument("--out", required=True, type=Path)
    dedup = commands.add_parser("deduplicate-evaluation")
    dedup.add_argument("--source", required=True, type=Path)
    dedup.add_argument("--out", required=True, type=Path)
    dedup.add_argument("--text-field", required=True)
    dedup.add_argument("--reference-field", required=True)
    dedup.add_argument("--evaluation-kind", required=True, choices=("general-response", "hyd-routing"))
    dedup.add_argument("--review-only", action="store_true", help="Preserve originals and report conflicts without selecting references")
    acquisition = commands.add_parser("acquisition-report")
    acquisition.add_argument("--root", required=True, type=Path)
    acquisition.add_argument("--out", required=True, type=Path)
    prepare = commands.add_parser("prepare-acquisition")
    prepare.add_argument("--root", required=True, type=Path)
    prepare.add_argument("--inventory", required=True, type=Path)
    prepare.add_argument("--out", required=True, type=Path)
    download = commands.add_parser("download-asset")
    download.add_argument("--plan", required=True, type=Path)
    download.add_argument("--out", required=True, type=Path)
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
        if args.command == "deduplicate-evaluation":
            from .data_review import deduplicate_evaluation
            result = deduplicate_evaluation(args.source, args.out, text_field=args.text_field,
                                           reference_field=args.reference_field, evaluation_kind=args.evaluation_kind,
                                           review_only=args.review_only)
        elif args.command == "download-asset":
            from .downloader import download_asset
            result = download_asset(args.plan, args.out)
        elif args.command == "prepare-acquisition":
            from .acquisition_snapshot import prepare_acquisition
            result = prepare_acquisition(args.root, args.inventory, args.out)
        elif args.command == "acquisition-report":
            from .data_review import acquisition_report
            result = acquisition_report(args.root, args.out)
        elif args.command == "e3-report":
            import hashlib
            from .e3_evaluation import evaluate_e3
            if args.out.exists():
                raise ValueError("output file already exists")
            rows = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
            predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
            selections = json.loads(args.selections.read_text(encoding="utf-8"))
            result = evaluate_e3(rows, predictions, selections)
            result["input_sha256"] = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                      for name, path in (("corpus", args.corpus), ("predictions", args.predictions),
                                                         ("selections", args.selections))}
            write_text_atomic(args.out, json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        elif args.command == "build":
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
