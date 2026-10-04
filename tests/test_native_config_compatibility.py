# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import subprocess
import sys


def test_facade_and_legacy_configuration_share_single_snapshot():
    # The in-process fixtures replace api.settings to isolate model scanning.
    subprocess.run(
        [sys.executable, "-c", (
            "from hydra.core import native_config; "
            "from hydra.runtime import api, config; "
            "assert config is native_config; "
            "assert api.settings is native_config.settings; "
            "assert config.Settings is native_config.Settings"
        )],
        check=True, capture_output=True, text=True,
    )
