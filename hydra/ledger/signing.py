# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Ed25519 signing for ledger events, release manifests, model artifacts and edge deltas.

Private keys are resolved through ``hydra.core.keystore`` (OS keyring, HYDRA_KEYS_DIR or container
secrets; the plaintext ``<data_dir>/keys`` file is only a legacy fallback). The public key is always
written to ``<data_dir>/keys/<name>.pub.pem`` so ledgers and backups can be verified. Workers only
receive public keys."""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from hydra.core.hashing import sha256_hex

LEDGER_KEY = "ledger-ed25519"


class Signer:
    algorithm = "Ed25519"

    def __init__(self, private_key: Ed25519PrivateKey, key_id: str | None = None) -> None:
        self._key = private_key
        self.public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.key_id = key_id or f"hydra-{sha256_hex(self.public_pem)[:16]}"

    @classmethod
    def generate(cls) -> Signer:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load_or_create(cls, directory: Path, name: str = "hydra-ed25519", keystore=None) -> Signer:
        """Load the node signing key (creating it once). ``keystore`` (hydra.core.keystore.KeyStore)
        decides where the private part lives; without one the legacy file layout is used."""
        from hydra.core.keystore import KeyStore

        directory.mkdir(parents=True, exist_ok=True)
        store = keystore or KeyStore(directory.parent, backend="legacy")

        def generate() -> bytes:
            return Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

        pem = store.get_or_create(LEDGER_KEY, directory / f"{name}.pem", generate)
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("ledger signing key is not an Ed25519 private key")
        signer = cls(key)
        public = directory / f"{name}.pub.pem"
        if not public.is_file() or public.read_text(encoding="utf-8") != signer.public_pem:
            public.write_text(signer.public_pem, encoding="utf-8")
        return signer

    def sign(self, data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return base64.b64encode(self._key.sign(data)).decode()

    def envelope(self, digest: str) -> dict:
        return {"algorithm": self.algorithm, "key_id": self.key_id, "digest": digest,
                "signature": self.sign(digest), "public_key": self.public_pem}


def verify_signature(public_pem: str, data: bytes | str, signature_b64: str) -> bool:
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        key = serialization.load_pem_public_key(public_pem.encode())
        assert isinstance(key, Ed25519PublicKey)
        key.verify(base64.b64decode(signature_b64), data)
        return True
    except (InvalidSignature, ValueError, AssertionError):
        return False


def verify_envelope(env: dict, trusted_keys: set[str] | None = None) -> bool:
    """Check a signature envelope; ``trusted_keys`` restricts which public keys are accepted."""
    if trusted_keys is not None and env.get("public_key") not in trusted_keys:
        return False
    return verify_signature(env.get("public_key", ""), env.get("digest", ""), env.get("signature", ""))
