# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.provenance.ledger."""
import sys
from hydra.provenance import ledger as _implementation
from hydra.provenance.ledger import (
    ProvenanceRecord,
    ProvenanceIntegrity,
    _record_body,
    _Duplicate,
    ProvenanceLedger,
)

__all__ = ['ProvenanceRecord', 'ProvenanceIntegrity', '_record_body', '_Duplicate', 'ProvenanceLedger']
sys.modules[__name__] = _implementation
