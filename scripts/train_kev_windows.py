# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Run upstream Kev training on Windows with an explicit RSS telemetry adapter."""
import os
import argparse
import runpy
import sys
import types
import time
from pathlib import Path


def configure_windows():
    root = Path(__file__).resolve().parents[1]
    os.environ["HF_HOME"] = str(root / "runtime/kev-cache")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    # Kev imports POSIX resource solely for its final peak-RSS metric. Leave
    # model math and the reviewed upstream source unchanged.
    if os.name == "nt":
        import psutil
        def getrusage(who):
            if who != 0:
                raise ValueError("only current-process RSS is supported")
            info = psutil.Process().memory_info()
            peak = getattr(info, "peak_wset", info.rss)
            return types.SimpleNamespace(ru_maxrss=peak / 1024)
        shim = types.ModuleType("resource")
        shim.RUSAGE_SELF = 0
        shim.getrusage = getrusage
        sys.modules["resource"] = shim
        # Preserve real interprocess locking; never replace POSIX flock with a
        # no-op. Upstream uses only exclusive locks, released on file close.
        import msvcrt
        locks = types.ModuleType("fcntl")
        locks.LOCK_EX, locks.LOCK_NB, locks.LOCK_UN = 2, 4, 8
        def flock(file, operation):
            fd = file if isinstance(file, int) else file.fileno()
            if operation not in (2, 6, 8):
                raise NotImplementedError("only exclusive file locks are supported")
            position = os.lseek(fd, 0, os.SEEK_CUR)
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if operation == 8:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    return
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        return
                    except OSError as exc:
                        if operation == 6 or exc.errno not in (13, 11, 36):
                            raise
                        time.sleep(.05)
            finally:
                os.lseek(fd, position, os.SEEK_SET)
        locks.flock = flock
        sys.modules["fcntl"] = locks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--source-root", type=Path)
    options, remaining = parser.parse_known_args()
    if options.source_root:
        source = options.source_root.resolve()
        source.relative_to(Path(__file__).resolve().parents[1] / "runtime")
        if not (source / "kev/train.py").is_file():
            raise ValueError("Missing Kev source")
        sys.path.insert(0, str(source))
    sys.argv = [sys.argv[0], *remaining]
    configure_windows()
    runpy.run_module("kev.train", run_name="__main__")
