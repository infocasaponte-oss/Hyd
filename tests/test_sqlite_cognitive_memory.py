# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.memory.embeddings import HashingEmbedder
from hydra.memory.models import MemoryItem, MemoryStatus, MemoryType
from hydra.memory.retriever import MemoryRetriever
from hydra.memory.sqlite_store import SQLiteMemoryStore


async def test_persistence_namespace_revoke_export_and_restore(tmp_path):
    path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(path, "alice")
    item = MemoryItem(memory_type=MemoryType.SEMANTIC, text="hecho", content={}, status=MemoryStatus.SUPPORTED)
    await store.save(item)
    assert (await SQLiteMemoryStore(path, "alice").get(item.id)).text == "hecho"
    assert await SQLiteMemoryStore(path, "bob").get(item.id) is None
    export = tmp_path / "export.jsonl"
    await store.export(export)
    restored = SQLiteMemoryStore(tmp_path / "restored.db", "alice")
    await restored.import_export(export)
    assert (await restored.get(item.id)).text == "hecho"
    await store.revoke(item.id)
    await store.import_export(export)
    assert await store.get(item.id) is None
    with pytest.raises(ValueError, match="revoked"):
        await store.save(item)
    backup = tmp_path / "backup.db"
    restored.backup(backup)
    assert (await SQLiteMemoryStore(backup, "alice").get(item.id)).text == "hecho"
    broken = json.loads(export.read_text())
    broken["payload"]["text"] = "changed"
    export.write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="hash mismatch"):
        await restored.import_export(export)


async def test_retrieval_excludes_untrusted_and_test_memories(tmp_path):
    store, embedder = SQLiteMemoryStore(tmp_path / "memory.db"), HashingEmbedder()
    [vector] = await embedder.embed(["postgres memoria"])
    for status, split in [(MemoryStatus.VERIFIED, "fit"), (MemoryStatus.UNVERIFIED, "fit"),
                          (MemoryStatus.CONFLICT, "fit"), (MemoryStatus.VERIFIED, "reserved_test")]:
        await store.save(MemoryItem(memory_type=MemoryType.EPISODIC, text="postgres memoria", embedding=vector,
                                   content={"split": split}, status=status))
    result = await MemoryRetriever(store, embedder).retrieve("postgres memoria", "chat")
    assert len(result) == 1 and result[0][0].content["split"] == "fit"
