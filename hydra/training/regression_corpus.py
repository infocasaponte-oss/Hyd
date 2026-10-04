# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Small hand-authored regression set, reserved from training; not a general benchmark."""
import json
from pathlib import Path

from hydra.training.verified_corpus import SYSTEM, sha256

# Explicit examples include edge cases. References are trusted code owned by HYDRA.
TASKS = [
    ("deduplicate", "Elimina duplicados de xs conservando la primera aparición. Admite listas anidadas.",
     "out=[]\n    for x in xs:\n        if x not in out: out.append(x)\n    return out",
     [([], []), ([2, 1, 2, 3, 1], [2, 1, 3]), ([[1], [1], [2]], [[1], [2]])]),
    ("runs", "Codifica xs en pares [valor, repeticiones] de elementos consecutivos iguales.",
     "out=[]\n    for x in xs:\n        if out and out[-1][0] == x: out[-1][1] += 1\n        else: out.append([x, 1])\n    return out",
     [([], []), ([1, 1, 2, 1], [[1, 2], [2, 1], [1, 1]]), ([0, 0, 0], [[0, 3]])]),
    ("second_distinct", "Devuelve el segundo mayor valor distinto de xs, o None si no existe.",
     "values=sorted(set(xs), reverse=True)\n    return values[1] if len(values)>1 else None",
     [([], None), ([5, 5], None), ([5, 5, 3, 2], 3), ([-5, -2, -3], -3)]),
    ("balanced", "xs es texto. Comprueba paréntesis (), [] y {} correctamente anidados; ignora otros caracteres.",
     "stack=[]\n    pairs={')':'(', ']':'[', '}':'{'}\n    for c in xs:\n        if c in '([{': stack.append(c)\n        elif c in pairs:\n            if not stack or stack.pop()!=pairs[c]: return False\n    return not stack",
     [("", True), ("a([{}])", True), ("([)]", False), (")(", False), ("((", False)]),
    ("merge_intervals", "Une los intervalos cerrados de xs que se solapen o compartan extremo. Devuelve listas ordenadas.",
     "out=[]\n    for a,b in sorted(xs):\n        if out and a<=out[-1][1]: out[-1][1]=max(out[-1][1],b)\n        else: out.append([a,b])\n    return out",
     [([], []), ([[5, 8], [1, 3], [3, 6]], [[1, 8]]), ([[1, 10], [2, 4]], [[1, 10]]), ([[1, 2], [4, 5]], [[1, 2], [4, 5]])]),
    ("rotate", "xs es [lista, k]. Rota la lista k posiciones a la derecha; k negativo rota a la izquierda.",
     "items,k=xs\n    if not items: return []\n    k %= len(items)\n    return items[-k:]+items[:-k]",
     [([[], 4], []), ([[1, 2, 3], 0], [1, 2, 3]), ([[1, 2, 3], -1], [2, 3, 1]), ([[1, 2, 3], 7], [3, 1, 2])]),
    ("transpose", "Transpone la matriz rectangular xs y devuelve listas. La matriz vacía devuelve [].",
     "return [list(column) for column in zip(*xs)]",
     [([], []), ([[], []], []), ([[1, 2, 3], [4, 5, 6]], [[1, 4], [2, 5], [3, 6]])]),
    ("missing_positive", "Devuelve el menor entero positivo ausente de xs, ignorando duplicados y negativos.",
     "values=set(xs)\n    n=1\n    while n in values: n+=1\n    return n",
     [([], 1), ([3, 4, -1, 1], 2), ([1, 1, 2, 0], 3), ([-1, -2], 1)]),
    ("binary_insert", "xs es [lista_ordenada, objetivo]. Devuelve el índice de inserción más a la izquierda.",
     "items,target=xs\n    for i,value in enumerate(items):\n        if value>=target: return i\n    return len(items)",
     [([[], 4], 0), ([[1, 2, 2, 4], 2], 1), ([[1, 2], 3], 2), ([[1, 2], 0], 0)]),
    ("flatten_once", "Aplana exactamente un nivel de la lista de listas xs. Conserva sublistas más profundas.",
     "return [item for group in xs for item in group]",
     [([], []), ([[], [1], [2, 3]], [1, 2, 3]), ([[[1]], [2]], [[1], 2])]),
    ("prefix", "Devuelve el prefijo común más largo de las cadenas de xs. Lista vacía devuelve cadena vacía.",
     "if not xs: return ''\n    prefix=xs[0]\n    for value in xs[1:]:\n        while not value.startswith(prefix): prefix=prefix[:-1]\n    return prefix",
     [([], ""), (["flor", "flota", "flotar"], "flo"), (["abc", ""], ""), (["árbol", "árbitro"], "árb")]),
    ("histogram", "Cuenta caracteres de la cadena xs respetando mayúsculas y espacios; devuelve diccionario.",
     "out={}\n    for c in xs: out[c]=out.get(c,0)+1\n    return out",
     [("", {}), ("aAa ", {"a": 2, "A": 1, " ": 1}), ("ññá", {"ñ": 2, "á": 1})]),
]


def build(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for family, instruction, body, cases in TASKS:
        code = "def solve(xs):\n    " + body + "\n"
        scope = {}
        exec(code, scope)  # Only the static trusted references above.
        for value, expected in cases:
            if scope["solve"](value) != expected:
                raise ValueError(f"regression reference {family} fails its own case {value!r}")
        rows.append({"id": family, "family": family,
                     "messages": [{"role": "system", "content": SYSTEM},
                                  {"role": "user", "content": "Escribe solve(xs). " + instruction},
                                  {"role": "assistant", "content": code}],
                     "verification": {"passed": True, "cases": [
                         {"input": value, "expected": expected} for value, expected in cases]},
                     "provenance": "HYDRA authored static regression cases",
                     "training_allowed": False})
    path = output / "test.jsonl"
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ValueError("refusing to replace a different frozen regression set")
    path.write_text(content, encoding="utf-8")
    manifest = {"version": 2, "kind": "small_coding_regression", "training_allowed": False,
                "limitations": "12 authored tasks; not independent quality certification or training data",
                "generator_sha256": sha256(Path(__file__)),
                "files": {"test.jsonl": {"sha256": sha256(path), "examples": len(rows)}}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(Path("data/hydra-regression-v2")), indent=2))
