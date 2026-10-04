# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility entry point; new usage: python -m hyd_calibrator."""

from hyd_calibrator.corpus import build, normalized, report, split_of, validate
from hyd_calibrator.cli import main

__all__ = ["build", "normalized", "report", "split_of", "validate"]

if __name__ == "__main__":
    main()
