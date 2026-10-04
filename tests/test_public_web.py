# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4
import httpx
import pytest
from hydra.tools import public_web
from hydra.tools.definitions import ToolContext, WorkerCapabilities
from hydra.tools.web_context import requested_web
from hydra.tools.web_context import fetched_sources, attach_sources


def test_search_url_encodes_query_and_never_needs_a_key():
    url = public_web.search_url("hydra & python", "google")
    assert url == "https://www.google.com/search?q=hydra+%26+python"
    with pytest.raises(ValueError):
        public_web.search_url("x", "opera")


def test_html_parser_removes_executable_content():
    page = public_web.Page()
    page.feed('<script>steal()</script><p>Hello</p><a href="https://example.com">Source</a>')
    assert page.text == ["Hello", "Source"]
    assert page.links == [("https://example.com", "Source")]


def test_explicit_web_request_survives_technical_topic_classification():
    assert requested_web("Investiga en la web qué es asyncio de Python")
    assert requested_web("Lee https://docs.python.org/3/library/asyncio.html")
    assert not requested_web("Explica una función Python para procesar URLs")


def test_citations_only_include_successfully_read_sources():
    entries = [{"tool": "web.read", "result": {"status": 200, "url": "https://example.com", "text": "Evidence"}},
               {"tool": "web.read", "result": {"status": 403, "url": "https://blocked.test", "text": "Blocked"}},
               {"tool": "web.search", "result": {"url": "https://search.test"}}]
    assert fetched_sources(entries) == ["https://example.com"]
    assert attach_sources("Answer", fetched_sources(entries)).endswith("[Fuente 1](<https://example.com>)")
    assert attach_sources("https://example.com", fetched_sources(entries)) == "https://example.com"


async def test_private_mode_cannot_search_or_read():
    ctx = ToolContext(task_id=uuid4(), private=True, capabilities=WorkerCapabilities(public_web=True))
    with pytest.raises(PermissionError):
        await public_web.web_search({"query": "secret"}, ctx)
    with pytest.raises(PermissionError):
        await public_web.web_read({"url": "https://example.com"}, ctx)


async def test_dns_private_address_is_rejected_before_http(monkeypatch):
    monkeypatch.setattr(public_web.socket, "getaddrinfo", lambda *a: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(PermissionError):
        await public_web.public_get("https://example.com")


async def test_redirect_is_rechecked_and_public_address_is_pinned(monkeypatch):
    seen = []
    real_client = httpx.AsyncClient
    monkeypatch.setattr(public_web.socket, "getaddrinfo", lambda host, *a: [(2, 1, 6, "", ("127.0.0.1" if host == "internal.test" else "8.8.8.8", 443))])
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://internal.test/data"})
    monkeypatch.setattr(public_web.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(PermissionError):
        await public_web.public_get("https://example.com")
    assert len(seen) == 1 and seen[0].url.host == "8.8.8.8"
    assert seen[0].headers["host"] == "example.com" and seen[0].extensions["sni_hostname"] == "example.com"


async def test_search_fallback_unwraps_links_and_reports_challenges(monkeypatch):
    async def fetch(url):
        if "brave" in url:
            return {"status": 429, "text": "", "content_type": "text/html"}
        return {"status": 200, "text": '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdoc">Official source</a>', "content_type": "text/html"}
    monkeypatch.setattr(public_web, "public_get", fetch)
    result = await public_web.search("test")
    assert result["engine"] == "duckduckgo" and result["paid_api_used"] is False
    assert result["results"] == [{"title": "Official source", "url": "https://example.com/doc"}]


def test_redirect_unwrapping_only_trusts_the_real_duckduckgo_domain():
    from hydra.tools.public_web import _is_host
    assert _is_host("duckduckgo.com", "duckduckgo.com") and _is_host("html.duckduckgo.com", "duckduckgo.com")
    assert not _is_host("evilduckduckgo.com", "duckduckgo.com")
    assert not _is_host("duckduckgo.com.attacker.net", "duckduckgo.com") and not _is_host(None, "duckduckgo.com")
