# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model fingerprint: two files called ``hydra-q5.gguf`` may not be the same model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hydra.core.hashing import sha256_file as _sha256_file
from hydra.model_factory.manifest import Fingerprint

CHUNK = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    return _sha256_file(path, CHUNK)


def _hash(obj: Any) -> str:
    data = obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(data).hexdigest()[:16]


def weight_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(p for p in path.iterdir() if p.suffix in (".safetensors", ".gguf", ".bin", ".npz", ".onnx"))
    return files


def fingerprint(path: Path, gguf_metadata: dict[str, Any] | None = None) -> Fingerprint:
    files = weight_files(path)
    h = hashlib.sha256()
    for f in files:
        h.update(sha256_file(f).encode())
    weights = h.hexdigest() if len(files) != 1 else sha256_file(files[0])

    tokenizer = config = template = None
    if gguf_metadata is not None:
        tok = {k: v for k, v in gguf_metadata.items() if k.startswith("tokenizer.") and k != "tokenizer.chat_template"}
        tokenizer = _hash(tok) if tok else None
        cfg = {k: v for k, v in gguf_metadata.items() if not k.startswith("tokenizer.")}
        config = _hash(cfg)
        if t := gguf_metadata.get("tokenizer.chat_template"):
            template = _hash(t.encode())
    elif path.is_dir():
        for name in ("tokenizer.json", "tokenizer.model"):
            if (path / name).exists():
                tokenizer = sha256_file(path / name)[:16]
                break
        if (path / "config.json").exists():
            config = _hash(json.loads((path / "config.json").read_text(encoding="utf-8")))
        tc = path / "tokenizer_config.json"
        if tc.exists():
            t = json.loads(tc.read_text(encoding="utf-8")).get("chat_template")
            if t:
                template = _hash(str(t).encode())
    return Fingerprint(weights_sha256=weights, tokenizer_hash=tokenizer, config_hash=config,
                       chat_template_hash=template)
