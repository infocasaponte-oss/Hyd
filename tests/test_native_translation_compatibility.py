# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from unittest.mock import AsyncMock

import pytest

from hydra.core.request_budget import RequestBudget, RequestBudgetExceeded
from hydra.edge import native_translation
from hydra.runtime import translation


def test_legacy_translation_is_same_implementation():
    assert translation is native_translation


def test_glossary_rejects_symlink_outside_root(tmp_path):
    root = tmp_path / "glossaries"
    store = native_translation.GlossaryStore(root)
    outside = tmp_path / "outside.json"
    outside.write_text('{"terms": {"private": "value"}}', encoding="utf-8")
    try:
        (root / "escape.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="escapes"):
        store.load("escape")
    with pytest.raises(ValueError, match="escapes"):
        store.save("escape", {"overwrite": "denied"})
    assert "private" in outside.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_translation_keeps_chunk_order_and_glossary(tmp_path):
    llm = AsyncMock()
    llm.chat.side_effect = ["first", "second"]
    glossary = native_translation.GlossaryStore(tmp_path)
    glossary.save("tech", {"engine": "motor"})
    service = native_translation.TranslationService(llm, RequestBudget(), glossary)
    answer = await service.translate("a" * 6000 + "\n\nb", "gl", glossary_id="tech")
    assert answer == "first\n\nsecond"
    calls = llm.chat.call_args_list
    assert [call.args[0][1]["content"] for call in calls] == ["a" * 6000, "b"]
    assert all("engine => motor" in call.args[0][0]["content"] for call in calls)
    assert all(call.kwargs == {"temperature": 0.0, "max_tokens": 4096} for call in calls)


@pytest.mark.asyncio
async def test_chunk_limit_rejects_before_inference(tmp_path):
    llm = AsyncMock()
    service = native_translation.TranslationService(
        llm, RequestBudget(max_chunks=1), native_translation.GlossaryStore(tmp_path)
    )
    with pytest.raises(RequestBudgetExceeded):
        await service.translate("a" * 6001, "gl")
    llm.chat.assert_not_called()
