# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Train bounded AI-assisted shadow candidates; human and provisional grades stay separate."""
import argparse
import json
from pathlib import Path

from hydra.training.decision_active_learning import read_rows
from hydra.training.decision_candidates import file_sha, train_candidate, report_metrics
from hydra.training.decision_compare import paired_summary
from hydra.training.decision_review_import import rescore_rows
from hydra.training.decision_teacher import experimental_snapshot
from hydra.training.evidence_io import write_json


def run(original, revised, reviewed_root, baseline_root, teacher_root, synthetic, checkpoint, out):
    if out.exists():
        raise FileExistsError('new candidate experiment required')
    teacher_progress = json.loads((teacher_root / 'progress.json').read_text(encoding='utf-8'))
    proposals_path = teacher_root / 'proposals.jsonl'
    if (teacher_progress.get('complete') is not True
            or teacher_progress['binding']['corpus_sha256'] != file_sha(revised)
            or teacher_progress['proposals_sha256'] != file_sha(proposals_path)):
        raise ValueError('complete, exactly bound AI review required')
    old, human = read_rows(original), read_rows(revised)
    teacher = {r['id']: r for r in read_rows(proposals_path)}
    if set(teacher) != {r['id'] for r in human}:
        raise ValueError('AI proposals must cover all original IDs')
    for row in human:
        if teacher[row['id']]['text_sha256'] != row['text_sha256']:
            raise ValueError('AI question binding mismatch')
    spec = json.loads((baseline_root / 'encoder-spec.json').read_text(encoding='utf-8'))
    out.mkdir(parents=True)
    report = {'format': 'hyd-teacher-experiment/1', 'complete': False, 'authority': False,
              'independent_test': False, 'human_reference_corpus_sha256': file_sha(revised),
              'teacher_binding': teacher_progress['binding'], 'proposals_sha256': file_sha(proposals_path),
              'human_confirmed_rows': sum(bool(r.get('label_review')) for r in human),
              'teacher_disagrees_with_confirmed_humans': sum(bool(r.get('label_review')) and
                    teacher[r['id']]['proposed_label'] != r['expected'] for r in human),
              'real_question_texts_preserved': True, 'folds': {}}
    combined = {name: {'hyd': [], 'kev': [], 'teacher_reference': []} for name in ('teacher_only', 'teacher_synthetic')}
    folds = [('A', 'balanced'), ('B', 'balanced-person-juan'), ('C', 'balanced-person-belen')]
    for cohort, baseline_name in folds:
        baseline = json.loads((baseline_root / ('comparison-' + baseline_name + '-kev-r1.json')).read_text(encoding='utf-8'))
        if baseline.get('complete') is not True:
            raise ValueError('complete real Kev inference required')
        if (file_sha(checkpoint / 'router-calibrator.json') != baseline['kev_calibration_sha256']
                or any(file_sha(checkpoint / name) != sha for name, sha in baseline['kev_checkpoint_files'].items())):
            raise ValueError('Kev checkpoint/calibration changed')
        kev = rescore_rows(baseline['kev_rows'], old, human)
        for recipe in ('teacher_only', 'teacher_synthetic'):
            print('Training ' + cohort + ' ' + recipe, flush=True)
            snapshot = out / ('snapshot-' + cohort + '-' + recipe)
            paths = experimental_snapshot(reviewed_root / ('snapshot-' + cohort), proposals_path, snapshot,
                                          synthetic if recipe == 'teacher_synthetic' else None)
            candidate = out / ('candidate-' + cohort + '-' + recipe)
            trained = train_candidate(paths, candidate, spec, epochs=300, seed=42, class_balance=True)
            predictions = read_rows(candidate / 'predictions.jsonl')
            actual = paired_summary(predictions, kev)
            provisional = [{**r, 'expected': teacher[r['id']]['proposed_label']} for r in predictions]
            manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
            report['folds'][cohort + '_' + recipe] = {'human_reference_comparison': actual,
                'AI_teacher_agreement_not_human_accuracy': report_metrics(provisional),
                'reload_parity': trained['reload_parity'], 'policy_passed': trained['policy_passed'],
                'fit_changes': manifest['fit_label_changes'], 'fit_class_counts': manifest['fit_class_counts'],
                'synthetic_added': manifest['synthetic_examples_added_to_fit'],
                'candidate_revision': trained['model_revision'], 'evaluation_labels_changed': False}
            combined[recipe]['hyd'].extend(predictions)
            combined[recipe]['kev'].extend(kev)
            combined[recipe]['teacher_reference'].extend(provisional)
            print(json.dumps({'fold': cohort, 'recipe': recipe, 'human_accuracy': actual['hyd']['accuracy'],
                              'AI_teacher_agreement': report_metrics(provisional)['accuracy']}), flush=True)
            write_json(out / 'aggregate.json', report)
    report['aggregate'] = {recipe: {
        'human_reference_comparison': paired_summary(rows['hyd'], rows['kev']),
        'AI_teacher_agreement_not_human_accuracy': report_metrics(rows['teacher_reference'])}
        for recipe, rows in combined.items()}
    report['complete'] = True
    report['promotion_ready'] = False
    report['limitation'] = 'Previously inspected, partially reviewed human reference. AI teacher agreement is not human accuracy. Synthetic examples never enter evaluation. Human independent validation is required before promotion.'
    write_json(out / 'aggregate.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'revised', 'reviewed-root', 'baseline-root', 'teacher-root', 'synthetic', 'checkpoint', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.original, args.revised, args.reviewed_root, args.baseline_root, args.teacher_root,
        args.synthetic, args.checkpoint, args.out)


if __name__ == '__main__':
    main()
