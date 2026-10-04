import json

import pytest

from hyd_calibrator.acquisition_snapshot import prepare_acquisition
from hyd_calibrator.provenance_overlay import build_overlay, recover_link
from tests.test_acquisition_snapshot import setup_source


def test_recovers_explicit_link_not_guessed_from_id():
    row = {"source": "PleIAs/YouTube-Commons", "video_link": "https://www.youtube.com/watch?v=fixture", "url": None}
    assert recover_link(row) == row["video_link"]
    assert recover_link({**row, "video_link": None, "id": "fixture"}) is None
    assert recover_link({**row, "url": "https://example.org/original"}) is None


def test_common_corpus_explicit_identifier_url_not_synthesized():
    assert recover_link({"source": "PleIAs/common_corpus", "id": "https://example.org/paper"}) == "https://example.org/paper"
    assert recover_link({"source": "PleIAs/common_corpus", "id": "paper:123"}) is None
    assert recover_link({"source": "PleIAs/common_corpus", "id": "http://127.0.0.1/paper"}) is None


@pytest.mark.parametrize("value", ["http://youtube.com/watch", "https://youtube.com.evil.test/watch",
                                    "https://name:password@youtube.com/watch", "https://[", 17])
def test_invalid_origin_does_not_create_provenance(value):
    assert recover_link({"source": "PleIAs/YouTube-Commons", "video_link": value}) is None


def test_overlay_preserves_sources_and_does_not_approve_training(tmp_path):
    root, source, inventory, _ = setup_source(tmp_path)
    import gzip
    from hyd_calibrator.acquisition_snapshot import file_hash
    with gzip.open(source, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    for row in rows:
        row.update(source="PleIAs/YouTube-Commons", url=None, video_link="https://youtu.be/fixture")
    with gzip.open(source, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    data = json.loads(inventory.read_text())
    data["files"][0]["sha256"] = file_hash(source)
    inventory.write_text(json.dumps(data))
    snapshot = tmp_path / "snapshot"
    prepare_acquisition(root, inventory, snapshot)
    before = file_hash(snapshot / "review.jsonl.gz")
    report = build_overlay(snapshot, tmp_path / "overlay")
    assert report["rows"] == 4 and report["training_allowed"] is False
    assert file_hash(snapshot / "review.jsonl.gz") == before
    with pytest.raises(ValueError, match="new overlay"):
        build_overlay(snapshot, tmp_path / "overlay")
