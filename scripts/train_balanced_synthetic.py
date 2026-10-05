# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compare fit-only synthetic augmentation without relabeling any real question."""
import argparse
import json
from pathlib import Path

from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_candidates import file_sha, train_candidate
from hydra.training.decision_compare import paired_summary
from hydra.training.decision_review_import import rescore_rows
from hydra.training.decision_teacher import experimental_snapshot
from hydra.training.evidence_io import write_json


def run(original, revised, reviewed_root, baseline_root, synthetic, checkpoint, out):
    if out.exists():
        raise FileExistsError('new experiment required')
    old, human = read_rows(original), read_rows(revised)
    spec = json.loads((baseline_root / 'encoder-spec.json').read_text(encoding='utf-8'))
    report = {'format': 'hyd-balanced-synthetic-experiment/1', 'complete': False,
              'authority': False, 'independent_test': False, 'promotion_ready': False,
              'human_reference_corpus_sha256': file_sha(revised),
              'synthetic_sha256': file_sha(synthetic), 'real_labels_changed': False, 'folds': {}}
    predictions, kev_rows = [], []
    out.mkdir(parents=True)
    for cohort, name in [('A', 'balanced'), ('B', 'balanced-person-juan'), ('C', 'balanced-person-belen')]:
        baseline = json.loads((baseline_root / ('comparison-' + name + '-kev-r1.json')).read_text(encoding='utf-8'))
        if (baseline.get('complete') is not True
                or file_sha(checkpoint / 'router-calibrator.json') != baseline['kev_calibration_sha256']
                or any(file_sha(checkpoint / name) != sha for name, sha in baseline['kev_checkpoint_files'].items())):
            raise ValueError('verified real Kev checkpoint and inference required')
        kev = rescore_rows(baseline['kev_rows'], old, human)
        snapshot = out / ('snapshot-' + cohort)
        paths = experimental_snapshot(reviewed_root / ('snapshot-' + cohort), None, snapshot, synthetic)
        print('Training human labels + balanced synthetic: ' + cohort, flush=True)
        trained = train_candidate(paths, out / ('candidate-' + cohort), spec,
                                  epochs=300, seed=42, class_balance=True)
        rows = read_rows(out / ('candidate-' + cohort) / 'predictions.jsonl')
        manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
        report['folds'][cohort] = {'human_reference_comparison': paired_summary(rows, kev),
                                  'reload_parity': trained['reload_parity'],
                                  'policy_passed': trained['policy_passed'],
                                  'augmentation': manifest}
        predictions.extend(rows)
        kev_rows.extend(kev)
        write_json(out / 'aggregate.json', report)
        print(json.dumps({'fold': cohort, 'human_accuracy': report['folds'][cohort]['human_reference_comparison']['hyd']['accuracy']}), flush=True)
    report['aggregate'] = paired_summary(predictions, kev_rows)
    report['complete'] = True
    report['limitation'] = 'Previously inspected human reference, partially reviewed. Synthetic fit tasks are not human evidence. No promotion.'
    write_json(out / 'aggregate.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'revised', 'reviewed-root', 'baseline-root', 'synthetic', 'checkpoint', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.original, args.revised, args.reviewed_root, args.baseline_root, args.synthetic,
        args.checkpoint, args.out)


if __name__ == '__main__':
    main()
