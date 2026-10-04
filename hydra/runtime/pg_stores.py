# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.native_stores."""
import sys

from hydra.core import native_stores as _implementation
from hydra.core.native_stores import (
    SCHEMA,
    _Connections,
    _iso,
    PostgresCaptureUnitOfWork,
    PostgresDeploymentEvidenceStore,
    PostgresOperatingMetricsStore,
    PostgresRuntimeHealthStore,
    PostgresTraceStore,
    RuntimeStores,
    open_runtime_stores,
    _rows,
    import_sqlite,
)

__all__ = ['SCHEMA', '_Connections', '_iso', 'PostgresCaptureUnitOfWork', 'PostgresDeploymentEvidenceStore', 'PostgresOperatingMetricsStore', 'PostgresRuntimeHealthStore', 'PostgresTraceStore', 'RuntimeStores', 'open_runtime_stores', '_rows', 'import_sqlite']
sys.modules[__name__] = _implementation
