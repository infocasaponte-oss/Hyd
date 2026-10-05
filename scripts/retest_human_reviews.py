# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Separate target corrections from real retraining in development-only human LOPO."""
import argparse
import json
from pathlib import Path

from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_candidates import file_sha, prepare, train_candidate
from hydra.training.decision_compare import paired_summary
from hydra.training.decision_review_import import rescore_rows
from hydra.training.evidence_io import write_json


def run(original, revised, baseline_root, checkpoint, out):
    if out.exists():
        raise FileExistsError("new development output required")
    old, new = read_rows(original), read_rows(revised)
    if any(r.get('label_review', {}).get('unresolved') for r in new):
        raise ValueError("adjudicate unresolved reviews before training")
    folds = [('A', 'person-owner', 'frozen', 'balanced'),
             ('B', 'person-juan', 'person-juan', 'balanced-person-juan'),
             ('C', 'person-belen', 'person-belen', 'balanced-person-belen')]
    spec = json.loads((baseline_root / 'encoder-spec.json').read_text(encoding='utf-8'))
    records, pinned = {}, None
    # Validate all recorded evidence against actual unchanged weights before any fit.
    for cohort, person, frozen_name, balanced_name in folds:
        for recipe, name in [('frozen', frozen_name), ('balanced', balanced_name)]:
            path = baseline_root / ('comparison-' + name + '-kev-r1.json')
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('complete') is not True or data.get('format') != 'hyd-kev-paired/1':
                raise ValueError('completed real inference required')
            binding = (data['kev_checkpoint_files'], data['kev_calibration_sha256'])
            if pinned is not None and binding != pinned:
                raise ValueError('inconsistent baseline checkpoint/calibration')
            pinned = binding
            if file_sha(checkpoint / 'router-calibrator.json') != pinned[1]:
                raise ValueError('Kev calibration changed')
            if any(file_sha(checkpoint / name) != sha for name, sha in pinned[0].items()):
                raise ValueError('Kev checkpoint changed')
            paired_summary(data['hyd_rows'], data['kev_rows'])
            records[(cohort, recipe)] = (path, data, rescore_rows(data['hyd_rows'], old, new),
                                         rescore_rows(data['kev_rows'], old, new))
    out.mkdir(parents=True)
    report = {'format': 'hyd-reviewed-retest/1', 'authority': False, 'independent_test': False,
              'original_corpus_sha256': file_sha(original), 'revised_corpus_sha256': file_sha(revised),
              'kev_inference': 'recorded real inference; identical inputs and weights, targets rescored only',
              'encoder_spec': spec, 'folds': {}, 'complete': False}
    combined = {stage: {'hyd': [], 'kev': []} for stage in
                ('rescored_frozen', 'rescored_balanced', 'retrained_frozen', 'retrained_balanced')}
    for cohort, person, _, _ in folds:
        print('Preparing human fold ' + cohort, flush=True)
        snapshot = out / ('snapshot-' + cohort)
        paths = prepare(revised, snapshot, person)
        for recipe in ('frozen', 'balanced'):
            path, baseline, rescored_hyd, rescored_kev = records[(cohort, recipe)]
            before = paired_summary(rescored_hyd, rescored_kev)
            stage = combined['rescored_' + recipe]
            stage['hyd'].extend(rescored_hyd)
            stage['kev'].extend(rescored_kev)
            candidate = out / ('candidate-' + cohort + '-' + recipe)
            print('Training ' + cohort + ' ' + recipe, flush=True)
            trained = train_candidate(paths, candidate, spec, epochs=300, seed=42, class_balance=recipe == 'balanced')
            predictions = read_rows(candidate / 'predictions.jsonl')
            summary = paired_summary(predictions, rescored_kev)
            stage = combined['retrained_' + recipe]
            stage['hyd'].extend(predictions)
            stage['kev'].extend(rescored_kev)
            report['folds'][cohort + '_' + recipe] = {
                'baseline_evidence_sha256': file_sha(path), 'unchanged_models_original_targets': baseline['summary'],
                'unchanged_models_reviewed_targets': before, 'retrained_hyd_reviewed_targets': summary,
                'reload_parity': trained['reload_parity'], 'policy_passed': trained['policy_passed'],
                'candidate_revision': trained['model_revision'], 'partition_counts': {k: len(read_rows(Path(v))) for k, v in paths.items()}}
            print(json.dumps({'fold': cohort, 'recipe': recipe, 'rescored_old_hyd': before['hyd']['accuracy'],
                              'retrained_hyd': summary['hyd']['accuracy'], 'kev': summary['kev']['accuracy']}), flush=True)
            write_json(out / 'aggregate.json', report)
    report['aggregate'] = {name: paired_summary(value['hyd'], value['kev']) for name, value in combined.items()}
    report['complete'] = True
    report['limitation'] = 'Partially reviewed, previously inspected development corpus; revisions may be informed by previous comparisons. No independent test, no authority, no updated latency benchmark.'
    write_json(out / 'aggregate.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'revised', 'baseline-root', 'checkpoint', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.original, args.revised, args.baseline_root, args.checkpoint, args.out)


if __name__ == '__main__':
    main()
