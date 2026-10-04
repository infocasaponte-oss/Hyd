# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Declared person/family connected components; never infer identity from accounts."""
import hashlib
import json


def grouped_partitions(rows, *, development=False):
    parents = list(range(len(rows)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen = {}
    keys = []
    for index, row in enumerate(rows):
        meta = row["meta"]
        current = []
        for field in ("person_id", "family_id"):
            value = meta.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError(f"row {index + 1}: explicit {field} required for grouped splitting")
            current.append((field, value))
        # Text equality is an additional link, never a substitute for provenance.
        current.append(("text", " ".join(row["text"].casefold().split())))
        keys.append(current)
        for key in current:
            if key in seen:
                parents[root(index)] = root(seen[key])
            else:
                seen[key] = index
    components = {}
    for index, current in enumerate(keys):
        components.setdefault(root(index), set()).update(current)
    ids = {component: hashlib.sha256(json.dumps(sorted(values), ensure_ascii=False).encode()).hexdigest()
           for component, values in components.items()}
    result = []
    for index in range(len(rows)):
        group_id = ids[root(index)]
        bucket = int(group_id[:8], 16) % 100
        if development:
            split = "train" if bucket < 60 else "development" if bucket < 70 else "calibration" if bucket < 85 else "test"
        else:
            split = "train" if bucket < 70 else "calibration" if bucket < 85 else "test"
        result.append((split, group_id))
    required = {"train", "calibration", "test"} | ({"development"} if development else set())
    if {split for split, _ in result} != required:
        raise ValueError("grouped corpus cannot populate all required partitions; collect more independent groups")
    return result
