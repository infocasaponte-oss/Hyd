# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.core import native_stores
from hydra.runtime import api, pg_stores

import subprocess
import sys


def test_legacy_and_http_facade_share_store_factory():
    assert pg_stores is native_stores
    assert api.open_runtime_stores is native_stores.open_runtime_stores


def test_canonical_contracts_resolve_before_legacy_import():
    subprocess.run(
        [sys.executable, "-c", (
            "import sys; from hydra.core.native_contracts import HydraTask; "
            "assert 'hydra.runtime.contracts' not in sys.modules; "
            "task = HydraTask(goal='hello'); "
            "assert task.budget.max_model_calls == 4; "
            "assert HydraTask.model_json_schema()['title'] == 'HydraTask'"
        )],
        check=True,
        capture_output=True,
        text=True,
    )
