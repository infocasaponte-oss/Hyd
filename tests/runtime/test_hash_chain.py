# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.hash_chain import canonical_hash


def test_canonical_hash_is_order_independent():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
