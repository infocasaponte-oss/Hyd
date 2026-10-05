# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import sys
import types

import pytest

from hydra.persistence.postgres_probe import probe


async def test_probe_is_readonly_and_closes(monkeypatch):
    calls = []
    class Transaction:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
    class Connection:
        def transaction(self, *, readonly):
            assert readonly is True
            return Transaction()
        async def fetchval(self, sql):
            calls.append(sql)
            return 1
        async def fetch(self, sql):
            calls.append(sql)
            if 'information_schema.tables' in sql:
                return [{'table_schema': 'public', 'table_name': 'memories'}]
            return [{"schema_name": "public"}]
        async def close(self):
            calls.append("closed")
    async def connect(url, **kwargs):
        assert kwargs["ssl"] == "require" and kwargs["statement_cache_size"] == 0
        return Connection()
    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    monkeypatch.setenv("HYDRA_POSTGRES_URL", "postgresql://example:private@localhost/db")
    result = await probe()
    assert result["connected"] and not result["migrations_applied"]
    assert not result['write_readiness_verified']
    assert result['missing_core_public_tables'] == ['events', 'inference_runs', 'model_metrics', 'tasks']
    assert calls[-1] == "closed" and all(c.startswith("SELECT") for c in calls[:-1])


async def test_probe_does_not_expose_secret_errors(monkeypatch):
    async def connect(*args, **kwargs):
        raise ValueError("secret_password_and_hostname")
    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(connect=connect))
    monkeypatch.setenv("HYDRA_POSTGRES_URL", "postgresql://example:private@localhost/db")
    with pytest.raises(RuntimeError) as error:
        await probe()
    assert str(error.value) == "PostgreSQL read-only probe failed: ValueError"
