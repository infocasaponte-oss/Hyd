# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from scripts.report_hyd_kev_comparison import collect


@pytest.fixture
def runs(tmp_path):
    names = [('frozen', 'A'), ('tuned', 'A'), ('hash', 'A'), ('person-juan', 'B'), ('person-belen', 'C'),
             ('balanced', 'A'), ('balanced-person-juan', 'B'), ('balanced-person-belen', 'C')]
    for name, cohort in names:
        row = {"id": "private-fixture-" + cohort, "text_sha256": "synthetic-digest-" + cohort,
               "expected": "coding", "selected": "coding", "group_id": "scenario-" + cohort,
               "probabilities": {"coding": 1.0}, "elapsed_ms": 1.0}
        record = {"format": "hyd-kev-paired/1", "complete": True, "kev_checkpoint_files": {"head.pt": "fixture"},
                  "kev_calibration_sha256": "fixture-calibration", "test_sha256": "test-" + cohort,
                  "hyd_rows": [row], "kev_rows": [row]}
        (tmp_path / ('comparison-' + name + '-kev-r1.json')).write_text(json.dumps(record), encoding="utf-8")
    return tmp_path


def test_aggregate_counts_cohorts_once_without_exporting_rows(runs):
    result = collect(runs)
    assert result['frozen_lopo']['paired_n'] == 3
    assert len(result['folds']) == 8
    assert result['balanced_lopo']['paired_n'] == 3
    assert 'private-fixture' not in json.dumps(result)
    assert not result['independent_test'] and not result['authority']


@pytest.mark.parametrize('key,value', [('complete', False), ('kev_calibration_sha256', 'different')])
def test_aggregate_rejects_partial_or_mismatched_experiments(runs, key, value):
    path = runs / 'comparison-person-belen-kev-r1.json'
    data = json.loads(path.read_text())
    data[key] = value
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        collect(runs)


def test_aggregate_rejects_changed_baseline_between_candidates(runs):
    path = runs / 'comparison-balanced-kev-r1.json'
    data = json.loads(path.read_text())
    data['kev_rows'][0]['selected'] = 'chat'
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='within a cohort'):
        collect(runs)
