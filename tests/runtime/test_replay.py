# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.replay import ReplayManifest, ReplayStore


def test_replay_manifest_is_hashed(tmp_path):
    manifest = ReplayStore(tmp_path).put(
        ReplayManifest(
            task_id=uuid4(),
            trace_id="trace",
            hydra_version="test",
            model_id="local-main",
            artifact_hashes=["abc"],
            event_types=["hydra.task.created"],
        )
    )
    assert len(manifest.manifest_hash) == 64
