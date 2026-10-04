# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Private keys live outside the data directory (audit finding M-03)."""
from __future__ import annotations

import base64
import tarfile

import pytest
from cryptography.fernet import Fernet

from hydra.core.keystore import KeyStore, KeyStoreError
from hydra.governance.recovery import backup, restore
from hydra.governance.secrets import SecretsBroker
from hydra.ledger.signing import Signer


class MemoryKeyring:
    """Stand-in for an OS keyring backend (never touches the real credential store)."""

    priority = 5

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password


def private_files(data_dir):
    return sorted(p.name for p in data_dir.rglob("*") if p.name in {"hydra-ed25519.pem", ".broker.key"})


def test_new_keys_go_to_the_keyring_and_never_to_the_data_dir(tmp_path):
    data, ring = tmp_path / "data", MemoryKeyring()
    store = KeyStore(data, keyring_backend=ring, namespace="t")
    signer = Signer.load_or_create(data / "keys", keystore=store)
    SecretsBroker(data / "secrets", keystore=store).put("secret://gh/token", "s3cr3t")
    assert private_files(data) == []
    assert (data / "keys" / "hydra-ed25519.pub.pem").read_text(encoding="utf-8") == signer.public_pem
    assert {u for _, u in ring.items} == {"t:ledger-ed25519", "t:secrets-broker"}
    # Same identity and same secrets on the next start.
    again = KeyStore(data, keyring_backend=ring, namespace="t")
    assert Signer.load_or_create(data / "keys", keystore=again).public_pem == signer.public_pem
    assert SecretsBroker(data / "secrets", keystore=again)._value("secret://gh/token") == "s3cr3t"


def test_legacy_keys_are_migrated_verified_and_removed(tmp_path):
    data = tmp_path / "data"
    legacy = KeyStore(data, backend="legacy")
    signer = Signer.load_or_create(data / "keys", keystore=legacy)
    SecretsBroker(data / "secrets", keystore=legacy).put("secret://db/pw", "pw-123456")
    assert private_files(data) == [".broker.key", "hydra-ed25519.pem"]

    ring = MemoryKeyring()
    store = KeyStore(data, keyring_backend=ring, namespace="m")
    assert Signer.load_or_create(data / "keys", keystore=store).public_pem == signer.public_pem
    assert SecretsBroker(data / "secrets", keystore=store)._value("secret://db/pw") == "pw-123456"
    assert private_files(data) == []


def test_failed_migration_keeps_the_legacy_file(tmp_path):
    data = tmp_path / "data"
    Signer.load_or_create(data / "keys", keystore=KeyStore(data, backend="legacy"))

    class LossyKeyring(MemoryKeyring):
        def get_password(self, service, username):
            return None  # writes are silently dropped

    with pytest.raises(KeyStoreError, match="could not be verified"):
        Signer.load_or_create(data / "keys", keystore=KeyStore(data, keyring_backend=LossyKeyring()))
    assert (data / "keys" / "hydra-ed25519.pem").is_file()


def test_keys_dir_backend_and_its_guard_rails(tmp_path):
    data, keys = tmp_path / "data", tmp_path / "secrets-mount"
    store = KeyStore(data, backend="file", keys_dir=keys)
    Signer.load_or_create(data / "keys", keystore=store)
    assert (keys / "ledger-ed25519.key").is_file() and private_files(data) == []
    with pytest.raises(KeyStoreError, match="outside"):
        KeyStore(data, backend="file", keys_dir=data / "keys")
    with pytest.raises(KeyStoreError, match="HYDRA_KEYS_DIR"):
        KeyStore(data, backend="file")
    with pytest.raises(KeyStoreError, match="unknown key backend"):
        KeyStore(data, backend="kms")


def test_environment_keys_win(tmp_path, monkeypatch):
    fernet = Fernet.generate_key()
    pem = Signer.generate()._key.private_bytes(*_pem_args())
    monkeypatch.setenv("HYDRA_KEY_SECRETS_BROKER", fernet.decode())
    monkeypatch.setenv("HYDRA_KEY_LEDGER_ED25519", base64.b64encode(pem).decode())
    store = KeyStore(tmp_path / "data", keyring_backend=MemoryKeyring())
    assert store.get_or_create("secrets-broker", tmp_path / "x", Fernet.generate_key) == fernet
    signer = Signer.load_or_create(tmp_path / "data" / "keys", keystore=store)
    assert signer.public_pem == Signer(_load(pem)).public_pem
    assert private_files(tmp_path / "data") == []


def test_backup_can_carry_keyring_keys_and_restore_migrates_them(tmp_path):
    data, ring = tmp_path / "data", MemoryKeyring()
    store = KeyStore(data, keyring_backend=ring, namespace="b")
    signer = Signer.load_or_create(data / "keys", keystore=store)
    SecretsBroker(data / "secrets", keystore=store).put("secret://a/b", "value-1")

    plain = backup(data, tmp_path / "plain.tar.gz")
    with tarfile.open(tmp_path / "plain.tar.gz") as tar:
        assert not any(n.endswith(("hydra-ed25519.pem", ".broker.key")) for n in tar.getnames())
    assert not plain.include_private_keys

    backup(data, tmp_path / "full.tar.gz", include_private_keys=True, keystore=store)
    restored = tmp_path / "restored"
    assert restore(tmp_path / "full.tar.gz", restored).ok
    new_ring = MemoryKeyring()
    fresh = KeyStore(restored, keyring_backend=new_ring, namespace="r")
    assert Signer.load_or_create(restored / "keys", keystore=fresh).public_pem == signer.public_pem
    assert SecretsBroker(restored / "secrets", keystore=fresh)._value("secret://a/b") == "value-1"
    assert private_files(restored) == []


def _pem_args():
    from cryptography.hazmat.primitives import serialization

    return serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()


def _load(pem: bytes):
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(pem, password=None)


def test_empty_keys_dir_setting_is_unset(monkeypatch, tmp_path):
    from hydra.core.config import Settings

    monkeypatch.setenv("HYDRA_KEYS_DIR", "")
    assert Settings(data_dir=tmp_path).keys_dir is None
