# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Read-only PostgreSQL/Supabase probe; DSN only from environment, no migrations."""
import asyncio
import json
import os

REQUIRED_TABLES = ('tasks', 'events', 'memories', 'inference_runs', 'model_metrics')


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
            tables = await connection.fetch("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' AND table_schema NOT LIKE 'pg_%' AND table_schema <> 'information_schema'")
        public_tables = {r['table_name'] for r in tables if r['table_schema'] == 'public'}
        return {"connected": True, "readonly": True, "migrations_applied": False,
                "schemas": [r["schema_name"] for r in schemas],
                "tables": [dict(r) for r in tables],
                "missing_core_public_tables": sorted(set(REQUIRED_TABLES) - public_tables),
                "write_readiness_verified": False,
                "limitation": "Table names do not establish compatible columns, isolation or write permissions. No writes tested."}
    except Exception as exc:
        raise RuntimeError("PostgreSQL read-only probe failed: " + type(exc).__name__) from None
    finally:
        if connection is not None:
            await connection.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(probe()), indent=2))
