# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows-only compatibility")
def test_kev_adapter_keeps_real_interprocess_exclusion(tmp_path):
    pytest.importorskip("psutil")  # the Windows adapter measures memory with psutil
    path = tmp_path / "training.lock"
    parent = path.open("a")
    import msvcrt
    msvcrt.locking(parent.fileno(), msvcrt.LK_NBLCK, 1)
    script = ("from scripts.train_kev_windows import configure_windows;configure_windows();"
              f"import fcntl;f=open({str(path)!r},'a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)")
    try:
        blocked = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=15)
        assert blocked.returncode != 0 and b"PermissionError" in blocked.stderr
    finally:
        parent.close()
    assert subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=15).returncode == 0
