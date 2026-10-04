# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Artifact signing and supply-chain security for models.

    model.gguf · manifest.json · eval.json · lineage.json · signature.sig

HYDRA production only loads artifacts with a trusted signature: a ``.gguf`` appearing in a
folder is not enough. Imported models go through: hash -> malware/file checks (pickle
opcodes) -> metadata validation -> architecture whitelist -> trust_remote_code=false."""

from __future__ import annotations

import json
import pickletools
import zipfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.hashing import canonical_json, now_iso, sha256_file, sha256_hex
from hydra.ledger.signing import Signer, verify_envelope

SIGNATURE = "signature.sig"
MANIFEST = "hydra-artifact-manifest.json"


def sign_directory(root: Path, signer: Signer, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    files = {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*"))
             if p.is_file() and p.name not in (SIGNATURE, MANIFEST)}
    manifest = {"files": files, "signed_at": now_iso(), **(extra or {})}
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    digest = sha256_hex(canonical_json({"files": files}))
    env = signer.envelope(digest)
    (root / SIGNATURE).write_text(json.dumps(env, indent=2), encoding="utf-8")
    return env


def sign_file(path: Path, signer: Signer, extra: dict[str, Any] | None = None) -> Path:
    digest = sha256_file(path)
    sig = path.with_suffix(path.suffix + ".sig")
    sig.write_text(json.dumps({**signer.envelope(digest), "file": path.name, **(extra or {})}, indent=2),
                   encoding="utf-8")
    return sig


def verify_artifact(path: Path, trusted_keys: set[str] | None = None) -> dict[str, Any]:
    """Directory (manifest + signature.sig) or single file (<file>.sig)."""
    if path.is_dir():
        sig = path / SIGNATURE
        if not sig.exists():
            return {"ok": False, "reason": "unsigned"}
        env = json.loads(sig.read_text(encoding="utf-8"))
        files = {p.relative_to(path).as_posix(): sha256_file(p) for p in sorted(path.rglob("*"))
                 if p.is_file() and p.name not in (SIGNATURE, MANIFEST)}
        digest = sha256_hex(canonical_json({"files": files}))
        ok = env.get("digest") == digest and verify_envelope(env, trusted_keys)
        return {"ok": ok, "reason": "" if ok else "tampered or untrusted", "key_id": env.get("key_id")}
    sig = path.with_suffix(path.suffix + ".sig")
    if not sig.exists():
        return {"ok": False, "reason": "unsigned"}
    env = json.loads(sig.read_text(encoding="utf-8"))
    ok = env.get("digest") == sha256_file(path) and verify_envelope(env, trusted_keys)
    return {"ok": ok, "reason": "" if ok else "tampered or untrusted", "key_id": env.get("key_id")}


# ------------------------------------------------------------------------------ supply chain
DANGEROUS_GLOBALS = {"os", "posix", "nt", "subprocess", "sys", "builtins", "__builtin__", "shutil", "socket",
                     "runpy", "importlib", "pty", "webbrowser", "requests", "urllib", "httpx", "ctypes"}
SAFE_TORCH_GLOBALS = {"torch._utils", "torch", "collections", "numpy.core.multiarray", "numpy", "_codecs",
                      "torch.nn.modules", "__torch__"}
ARCH_WHITELIST = {"LlamaForCausalLM", "MistralForCausalLM", "MixtralForCausalLM", "Qwen2ForCausalLM",
                  "Qwen3ForCausalLM", "Qwen3MoeForCausalLM", "Qwen2MoeForCausalLM", "Gemma2ForCausalLM",
                  "Gemma3ForCausalLM", "Gemma3ForConditionalGeneration", "Phi3ForCausalLM", "PhiForCausalLM",
                  "GPT2LMHeadModel", "GPTNeoXForCausalLM", "DeepseekV2ForCausalLM", "DeepseekV3ForCausalLM",
                  "Qwen2VLForConditionalGeneration", "Qwen2_5_VLForConditionalGeneration", "LlavaForConditionalGeneration",
                  "MllamaForConditionalGeneration", "BertModel", "XLMRobertaModel", "GraniteForCausalLM",
                  "OlmoForCausalLM", "Olmo2ForCausalLM", "StableLmForCausalLM", "InternLM2ForCausalLM",
                  "ChatGLMModel", "BaichuanForCausalLM", "FalconForCausalLM", "SmolLM3ForCausalLM"}


class SupplyChainReport(BaseModel):
    path: str
    ok: bool = True
    sha256: dict[str, str] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)
    pickle_files: list[str] = Field(default_factory=list)
    architecture: str | None = None
    trust_remote_code_required: bool = False
    scanned_at: str = Field(default_factory=now_iso)


def _pickle_globals(data: bytes) -> set[str]:
    out = set()
    try:
        ops = list(pickletools.genops(data))
    except Exception:
        return {"<unparseable-pickle>"}
    strings: list[str] = []
    for op, arg, _pos in ops:
        if op.name in ("SHORT_BINUNICODE", "BINUNICODE", "UNICODE", "STRING", "SHORT_BINSTRING", "BINSTRING"):
            strings.append(str(arg))
        elif op.name == "GLOBAL" and arg:
            out.add(str(arg).split(" ")[0])
        elif op.name == "STACK_GLOBAL" and len(strings) >= 2:
            out.add(strings[-2])
    return out


def scan_pickle_bytes(data: bytes) -> list[str]:
    bad = []
    for mod in _pickle_globals(data):
        root = mod.split(".")[0]
        if mod == "<unparseable-pickle>":
            bad.append(mod)
        elif root in DANGEROUS_GLOBALS and not any(mod.startswith(s) for s in SAFE_TORCH_GLOBALS):
            bad.append(mod)
    return bad


def scan_model(path: Path, *, max_hash_bytes: int = 64 * 2**30) -> SupplyChainReport:
    rep = SupplyChainReport(path=str(path))
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    for f in files:
        rel = f.name if path.is_file() else f.relative_to(path).as_posix()
        if f.stat().st_size <= max_hash_bytes:
            rep.sha256[rel] = sha256_file(f)
        suf = f.suffix.lower()
        if suf in (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt"):
            rep.pickle_files.append(rel)
            raw = f.read_bytes()[: 512 * 2**20]
            if raw[:2] == b"PK":  # torch zip format: scan every data.pkl inside
                try:
                    with zipfile.ZipFile(f) as z:
                        for n in z.namelist():
                            if n.endswith(".pkl"):
                                bad = scan_pickle_bytes(z.read(n))
                                rep.findings += [f"{rel}:{n}: dangerous global {b}" for b in bad]
                except zipfile.BadZipFile:
                    rep.findings.append(f"{rel}: corrupt zip")
            else:
                rep.findings += [f"{rel}: dangerous global {b}" for b in scan_pickle_bytes(raw)]
        elif suf == ".gguf":
            with open(f, "rb") as fh:
                if fh.read(4) != b"GGUF":
                    rep.findings.append(f"{rel}: bad GGUF magic")
        elif suf == ".safetensors":
            with open(f, "rb") as fh:
                head = fh.read(8)
                n = int.from_bytes(head, "little") if len(head) == 8 else 0
                if not 0 < n < 100 * 2**20:
                    rep.findings.append(f"{rel}: invalid safetensors header")
        elif suf == ".py":
            rep.findings.append(f"{rel}: contains Python code (remote code) - requires isolated review")
            rep.trust_remote_code_required = True
        elif f.name == "config.json":
            try:
                cfg = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                rep.findings.append(f"{rel}: invalid JSON")
                continue
            archs = cfg.get("architectures") or []
            rep.architecture = archs[0] if archs else None
            if cfg.get("auto_map"):
                rep.trust_remote_code_required = True
                rep.findings.append(f"{rel}: auto_map requires trust_remote_code (disabled by default)")
            if rep.architecture and rep.architecture not in ARCH_WHITELIST:
                rep.findings.append(f"{rel}: architecture {rep.architecture} not in whitelist")
    rep.ok = not rep.findings
    return rep
