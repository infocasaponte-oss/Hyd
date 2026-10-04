# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Minimal JSON-Schema validator (the subset HYDRA tool contracts use)."""

from __future__ import annotations

from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
    "null": (type(None),),
}


class SchemaError(ValueError):
    pass


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        ok = False
        for t in types:
            py = _TYPES.get(t, (object,))
            if isinstance(value, bool) and t in ("integer", "number"):
                continue
            if isinstance(value, py):
                ok = True
                break
        if not ok:
            return [f"{path}: expected {expected}, got {type(value).__name__}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")

    if isinstance(value, str):
        if (n := schema.get("maxLength")) is not None and len(value) > n:
            errors.append(f"{path}: longer than {n}")
        if (n := schema.get("minLength")) is not None and len(value) < n:
            errors.append(f"{path}: shorter than {n}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if (n := schema.get("minimum")) is not None and value < n:
            errors.append(f"{path}: < {n}")
        if (n := schema.get("maximum")) is not None and value > n:
            errors.append(f"{path}: > {n}")

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        for key, sub in value.items():
            if key in props:
                errors.extend(validate(sub, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: not allowed")

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))

    return errors


def check(value: Any, schema: dict[str, Any]) -> None:
    errors = validate(value, schema)
    if errors:
        raise SchemaError("; ".join(errors))
