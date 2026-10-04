# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Where HYDRA's private keys live: never next to the data they protect.

Keys (by name): ``ledger-ed25519`` (PEM, signs the ledger, releases and sync bundles),
``secrets-broker`` and ``ip-vault`` (Fernet keys for the secrets store and the trade-secret vault).

Resolution order for every key:

1. ``HYDRA_KEY_<NAME>`` environment variable (``HYDRA_KEY_LEDGER_ED25519``...): container secrets.
2. ``<HYDRA_KEYS_DIR>/<name>.key``: a directory outside ``HYDRA_DATA_DIR`` (mounted secret files).
3. The operating-system keyring (Windows Credential Manager, macOS Keychain, Secret Service) through
   the optional ``keyring`` package, under service ``hydra`` and a per-installation namespace.
4. The legacy file inside the data directory (``data/keys/hydra-ed25519.pem``...). When a secure
   backend (keyring or keys dir) is writable the key is migrated there, read back to verify, and
   only then the plaintext legacy file is deleted.

``HYDRA_KEY_BACKEND`` = ``auto`` (default: keyring, else keys dir, else legacy) | ``keyring`` |
``file`` (keys dir) | ``legacy`` (old layout, no migration: tests and air-gapped debugging).
New keys are created in the first writable backend of that order."""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path

from hydra.core.atomic import write_bytes_atomic

log = logging.getLogger("hydra.keys")

SERVICE = "hydra"
BACKENDS = {"auto", "keyring", "file", "legacy"}


class KeyStoreError(RuntimeError):
    pass


def export_keys(settings, out: Path) -> list[Path]:
    """Write every private key HYDRA uses as ``<out>/<name>.key`` (created if missing), the layout of
    ``HYDRA_KEYS_DIR``: load them into a Kubernetes Secret mounted at ``HYDRA_KEYS_DIR`` so every
    replica signs and decrypts with the same keys. Files are written with mode 0600."""
    from cryptography.fernet import Fernet

    from hydra.governance.recovery import KEY_LEGACY_PATHS
    from hydra.ledger.signing import LEDGER_KEY, Signer

    store = KeyStore.from_settings(settings)
    data = Path(settings.data_dir)
    Signer.load_or_create(data / "keys", keystore=store)  # creates the ledger key once if needed
    values = {
        LEDGER_KEY: store.get(LEDGER_KEY, data / KEY_LEGACY_PATHS[LEDGER_KEY]),
        "secrets-broker": store.get_or_create("secrets-broker", data / KEY_LEGACY_PATHS["secrets-broker"],
                                              Fernet.generate_key),
    }
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, value in values.items():
        path = out / f"{name}.key"
        write_bytes_atomic(path, value)
        _restrict(path)
        written.append(path)
    return written


def _env_name(name: str) -> str:
    return "HYDRA_KEY_" + name.upper().replace("-", "_")


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows: ACLs of the keys directory apply


def _os_keyring():
    """The usable OS keyring backend, or None (package missing, headless Linux, fail backend)."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return None
    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 0) < 1:
        return None
    return backend


class KeyStore:
    def __init__(self, data_dir: Path, *, backend: str = "auto", keys_dir: Path | None = None,
                 namespace: str | None = None, keyring_backend=None) -> None:
        if backend not in BACKENDS:
            raise KeyStoreError(f"unknown key backend {backend!r}; use one of {sorted(BACKENDS)}")
        self.data_dir = Path(data_dir)
        self.backend = backend
        self.keys_dir = Path(keys_dir) if keys_dir else None
        # Several HYDRA installations on one machine must not share keyring entries.
        self.namespace = namespace or hashlib.sha256(
            str(self.data_dir.resolve()).encode()).hexdigest()[:12]
        self._keyring = keyring_backend if keyring_backend is not None else (
            _os_keyring() if backend in ("auto", "keyring") else None)
        if backend == "keyring" and self._keyring is None:
            raise KeyStoreError("HYDRA_KEY_BACKEND=keyring but no usable OS keyring (pip install keyring)")
        if backend == "file" and self.keys_dir is None:
            raise KeyStoreError("HYDRA_KEY_BACKEND=file requires HYDRA_KEYS_DIR")
        if self.keys_dir is not None and self._inside_data_dir(self.keys_dir):
            raise KeyStoreError("HYDRA_KEYS_DIR must be outside HYDRA_DATA_DIR")

    @classmethod
    def from_settings(cls, settings) -> KeyStore:
        return cls(settings.data_dir, backend=settings.key_backend, keys_dir=settings.keys_dir,
                   namespace=settings.key_namespace or None)

    # ------------------------------------------------------------------ public
    def describe(self) -> str:
        if self.backend == "legacy":
            return "legacy (data directory)"
        if self._keyring is not None and self.backend in ("auto", "keyring"):
            return f"keyring ({type(self._keyring).__name__})"
        if self.keys_dir is not None:
            return f"file ({self.keys_dir})"
        return "legacy (data directory: no keyring or HYDRA_KEYS_DIR available)"

    def get_or_create(self, name: str, legacy_path: Path, generate: Callable[[], bytes]) -> bytes:
        value = self.get(name, legacy_path)
        if value is not None:
            return value
        value = generate()
        self._store(name, value, legacy_path)
        return value

    def get(self, name: str, legacy_path: Path) -> bytes | None:
        if (env := os.environ.get(_env_name(name))) is not None:
            return self._decode_env(name, env)
        if self.backend != "legacy":
            for reader in (self._read_keys_dir, self._read_keyring):
                if (value := reader(name)) is not None:
                    return value
        if legacy_path.is_file():
            value = legacy_path.read_bytes()
            if self.backend != "legacy" and self._secure_backend_available():
                self._migrate(name, value, legacy_path)
            return value
        return None

    def secure(self) -> bool:
        """True when keys are kept outside the data directory."""
        return self.backend != "legacy" and self._secure_backend_available()

    # ------------------------------------------------------------------ backends
    def _secure_backend_available(self) -> bool:
        return self._keyring is not None or self.keys_dir is not None

    def _read_keys_dir(self, name: str) -> bytes | None:
        if self.keys_dir is None:
            return None
        path = self.keys_dir / f"{name}.key"
        return path.read_bytes() if path.is_file() else None

    def _read_keyring(self, name: str) -> bytes | None:
        if self._keyring is None:
            return None
        try:
            secret = self._keyring.get_password(SERVICE, f"{self.namespace}:{name}")
        except Exception as exc:  # noqa: BLE001 - a locked/broken keyring must not hide the key elsewhere
            raise KeyStoreError(f"OS keyring read failed for {name}: {exc}") from exc
        return base64.b64decode(secret) if secret else None

    def _store(self, name: str, value: bytes, legacy_path: Path) -> None:
        if self.backend != "legacy" and self._keyring is not None:
            self._keyring.set_password(SERVICE, f"{self.namespace}:{name}", base64.b64encode(value).decode())
            return
        if self.backend != "legacy" and self.keys_dir is not None:
            self.keys_dir.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(self.keys_dir / f"{name}.key", value)
            _restrict(self.keys_dir / f"{name}.key")
            return
        if self.backend != "legacy":
            # Where key material sits stays out of the logs: only that a key is in the data directory.
            log.warning("no OS keyring and no HYDRA_KEYS_DIR: a private key is stored in the data directory "
                        "(use HYDRA_KEYS_DIR; `hydra keys export` writes them there)")
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(legacy_path, value)
        _restrict(legacy_path)

    def _migrate(self, name: str, value: bytes, legacy_path: Path) -> None:
        self._store(name, value, legacy_path)
        stored = self._read_keyring(name) if self._keyring is not None else self._read_keys_dir(name)
        if stored != value:
            raise KeyStoreError(f"key {name} migration could not be verified; legacy file kept")
        legacy_path.unlink()
        log.warning("key %s moved out of the data directory into %s", name, self.describe())

    def _decode_env(self, name: str, raw: str) -> bytes:
        text = raw.strip()
        if text.startswith("-----BEGIN"):
            return text.encode()
        try:
            return base64.b64decode(text, validate=True) if name == "ledger-ed25519" else text.encode()
        except (binascii.Error, ValueError) as exc:
            raise KeyStoreError(f"{_env_name(name)} is neither PEM nor base64") from exc

    def _inside_data_dir(self, path: Path) -> bool:
        data = self.data_dir.resolve()
        target = path.resolve()
        return target == data or data in target.parents
