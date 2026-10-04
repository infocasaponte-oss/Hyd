# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hyd_calibrator.manual_assets import import_assets


def test_multiple_files_preserved_and_not_admitted(tmp_path):
    source = tmp_path / "selected"
    source.mkdir()
    (source / "one.txt").write_bytes(b"First original")
    (source / "second.epub").write_bytes(b"Second original")
    out = tmp_path / "import"
    result = import_assets(source, out, "textos-info")
    assert len(result["files"]) == 2 and result["training_allowed"] is False
    for record in result["files"]:
        assert (out / record["id"] / "asset.raw").read_bytes() == (source / record["original_filename"]).read_bytes()
        assert record["extraction_performed"] is False and record["rights_review"] == "pending"
    with pytest.raises(ValueError):
        import_assets(source, out)


def test_unsafe_or_unsupported_file_rejected_before_copy(tmp_path):
    source = tmp_path / "selected"
    source.mkdir()
    (source / "execute.exe").write_bytes(b"fixture")
    out = tmp_path / "import"
    with pytest.raises(ValueError, match="supported"):
        import_assets(source, out)
    assert not out.exists()
