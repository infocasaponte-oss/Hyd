# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Strict structural JSON comparison used by evaluation scorers (bool is never a number)."""


def matching_json(actual, expected) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(matching_json(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(matching_json(a, b) for a, b in zip(actual, expected))
    return actual == expected
