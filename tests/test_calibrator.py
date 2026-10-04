import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from hyd_calibrator.calibrate import fit_temperature, nll, calibrate
from hyd_calibrator.corpus import validate, build, report, split_of
from hyd_calibrator.contract import CRITERIA
from hyd_calibrator.evaluation import load_rows, load_calibration, selective
from hyd_calibrator.model import CandidateRanker
from hyd_calibrator.train import train


class CalibratorTests(unittest.TestCase):
    def test_training_admission_reproducibility_and_no_overwrite(self):
        rows = [
            {
                "input": {"query": f"training question {i}"},
                "output": {"task_type": label},
                "split": "train",
                "training_allowed": True,
                "consent": True,
                "rights": {"verified": True, "license": "user-grant"},
            }
            for i, label in enumerate(CRITERIA)
        ]
        dataset = self.write("train.jsonl", rows)
        first = train(dataset, self.root / "first", epochs=1)
        second = train(dataset, self.root / "second", epochs=1)
        self.assertEqual(first["model_sha256"], second["model_sha256"])
        self.assertFalse(first["authority"])
        CandidateRanker.load(self.root / "first" / "model.json")
        calibration_rows = [
            dict(row, input={"query": f"calibration question {i}"}, split="calibration", training_allowed=False)
            for i, row in enumerate(rows)
        ]
        calibrated = calibrate(
            self.root / "first" / "model.json",
            self.write("calibration.jsonl", calibration_rows),
            self.root / "calibrated",
            train_dataset=dataset,
        )
        self.assertTrue(calibrated["train_overlap_checked"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            train(dataset, self.root / "first", epochs=1)
        for field, value in (("consent", False), ("split", "test"), ("training_allowed", False)):
            invalid = [dict(row) for row in rows]
            invalid[0][field] = value
            with self.assertRaisesRegex(ValueError, "training partition"):
                train(self.write("bad.jsonl", invalid), self.root / "bad", epochs=1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_admission_requires_explicit_flags_and_preserves_rights(self):
        rows = [
            {
                "text": f"question {i}",
                "expected": label,
                "meta": {"consent": True, "real": True, "suspect_template": False},
                "rights": {"license": "user-grant", "verified": True, "source": "evaluator"},
            }
            for i, label in enumerate(CRITERIA)
        ]
        path = self.write("source.jsonl", rows)
        result = build(path, self.root / "built")
        self.assertEqual(result["valid_rows"], 10)
        for part in (self.root / "built").glob("*.jsonl"):
            for line in part.read_text().splitlines():
                self.assertEqual(json.loads(line)["rights"], rows[0]["rights"])
        del rows[0]["meta"]["suspect_template"]
        del rows[1]["rights"]
        self.assertEqual(validate(self.write("invalid.jsonl", rows))[1]["n_errors"], 2)

    def test_invalid_json_and_types_are_reported(self):
        path = self.root / "invalid.jsonl"
        path.write_text('null\n[]\n{bad}\n{"meta": null}\n')
        self.assertEqual(validate(path)[1]["n_errors"], 4)

    def test_empty_and_duplicate_evaluation_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            load_rows(self.write("empty.jsonl", []))
        row = {"input": {"query": "hello"}, "output": {"task_type": "chat"}}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_rows(self.write("dups.jsonl", [row, row]))

    def test_partition_stable_under_normalization(self):
        self.assertEqual(split_of(" Hello  WORLD "), split_of("hello world"))

    def test_margin_and_no_accepted_rows(self):
        result = selective([0.8, 0.7], [0.05, 0.4], [True, False], 0.6, 0.1)
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["accuracy"], 0)
        self.assertIsNone(selective([0.8], [0.05], [True], 1, 1)["accuracy"])
        self.assertEqual(selective([1.0], [1.0], [True], 1, 1, abstain_all=True)["accepted"], 0)

    def test_temperature_reduces_nll_for_overconfident_errors(self):
        logits = np.array([[5.0, 0.0], [5.0, 0.0], [5.0, 0.0], [5.0, 0.0]])
        targets = np.array([0, 0, 0, 1])
        temperature = fit_temperature(logits, targets)
        self.assertGreater(temperature, 1)
        self.assertLess(nll(logits, targets, temperature), nll(logits, targets, 1))
        self.assertAlmostEqual(temperature, 5 / np.log(3), places=5)

    def test_hash_mismatch_rejected(self):
        model = CandidateRanker()
        model.training = {"criteria": CRITERIA}
        model.save(self.root / "model.json")
        path = self.root / "calibration.json"
        path.write_text(json.dumps({"format": "hyd-calibration/1", "model_sha256": "bad", "temperature": 1}))
        with self.assertRaisesRegex(ValueError, "mismatch"):
            load_calibration(path, model)

    def test_calibration_fail_closed_and_reproducible(self):
        source = self.root / "source"
        source.mkdir()
        model = CandidateRanker()
        model.training = {"criteria": CRITERIA}
        model.save(source / "model.json")
        rows = [
            {
                "input": {"query": f"query {i}"},
                "output": {"task_type": label},
                "split": "calibration",
                "training_allowed": False,
            }
            for i, label in enumerate(CRITERIA)
        ]
        dataset = self.write("cal.jsonl", rows)
        before = hashlib.sha256((source / "model.json").read_bytes()).hexdigest()
        first = calibrate(source / "model.json", dataset, self.root / "one")
        second = calibrate(source / "model.json", dataset, self.root / "two")
        self.assertEqual(first, second)
        self.assertFalse(first["target_met"])
        self.assertEqual(report(dataset, self.root / "one")["selective"]["accepted"], 0)
        self.assertEqual(before, hashlib.sha256((source / "model.json").read_bytes()).hexdigest())
        rows[0]["split"] = "test"
        with self.assertRaisesRegex(ValueError, "calibration partition"):
            calibrate(source / "model.json", self.write("test.jsonl", rows), self.root / "bad")

    def test_verified_train_overlap_is_rejected(self):
        train = self.write(
            "train.jsonl",
            [
                {
                    "input": {"query": " SAME question "},
                    "output": {"task_type": "chat"},
                    "split": "train",
                    "training_allowed": True,
                }
            ],
        )
        dataset = self.write(
            "cal.jsonl",
            [
                {
                    "input": {"query": "same QUESTION"},
                    "output": {"task_type": "chat"},
                    "split": "calibration",
                    "training_allowed": False,
                }
            ],
        )
        model = CandidateRanker()
        model.training = {"criteria": CRITERIA, "source_sha256": hashlib.sha256(train.read_bytes()).hexdigest()}
        model.save(self.root / "model.json")
        with self.assertRaisesRegex(ValueError, "overlap"):
            calibrate(self.root / "model.json", dataset, self.root / "out", train_dataset=train)

    def test_historical_model_temperature_mismatch(self):
        root = Path(__file__).resolve().parents[1]
        model_dir = root / "experiments" / "hyd-app-v1"
        model = CandidateRanker.load(model_dir / "model.json")
        load_calibration(model_dir / "calibration.json", model)
        original = model.probabilities("Hola, explícame qué es Python", None, CRITERIA)
        model.temperature *= 2
        softer = model.probabilities("Hola, explícame qué es Python", None, CRITERIA)
        self.assertEqual(max(original, key=original.get), max(softer, key=softer.get))
        self.assertLess(max(softer.values()), max(original.values()))
        with self.assertRaisesRegex(ValueError, "temperature mismatch"):
            load_calibration(model_dir / "calibration.json", model)


if __name__ == "__main__":
    unittest.main()
