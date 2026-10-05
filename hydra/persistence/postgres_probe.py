# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Read-only PostgreSQL/Supabase probe; DSN only from environment, no migrations."""
import asyncio
import json
import os


async def probe():
    import asyncpg
    url = os.environ.get("HYDRA_POSTGRES_URL")
    if not url:
        raise ValueError("set HYDRA_POSTGRES_URL locally; do not pass credentials in arguments")
    connection = None
    try:
        connection = await asyncpg.connect(url, timeout=10, ssl="require", statement_cache_size=0)
        async with connection.transaction(readonly=True):
            await connection.fetchval("SELECT 1")
            schemas = await connection.fetch("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%'")
        return {"connected": True, "readonly": True, "migrations_applied": False,
                "schemas": [r["schema_name"] for r in schemas]}
    except Exception as exc:
        raise RuntimeError("PostgreSQL read-only probe failed: " + type(exc).__name__) from None
    finally:
        if connection is not None:
            await connection.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), indent=2))
