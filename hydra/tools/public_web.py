# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Public search pages and URL reading without a paid search API."""
import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit, parse_qs
import httpx

ENGINES = {"brave": "https://search.brave.com/search", "google": "https://www.google.com/search",
           "bing": "https://www.bing.com/search", "duckduckgo": "https://html.duckduckgo.com/html/"}
MAX_BYTES = 1024 * 1024


def search_url(query: str, engine: str) -> str:
    if engine not in ENGINES or not query.strip() or len(query) > 1000:
        raise ValueError("Unsupported engine or invalid query")
    return ENGINES[engine] + "?" + urlencode({"q": query})


async def public_get(url: str) -> dict:
    """Resolve and pin a public IP, retaining the original Host and TLS SNI."""
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            target = httpx.URL(url)
            port = target.port or (443 if target.scheme == "https" else 80)
            if target.scheme not in ("http", "https") or target.userinfo or port not in (80, 443):
                raise PermissionError("Only public HTTP(S) URLs on standard ports are permitted")
            addresses = await asyncio.to_thread(socket.getaddrinfo, target.host, port, 0, socket.SOCK_STREAM)
            ips = list(dict.fromkeys(row[4][0] for row in addresses))
            if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                raise PermissionError("Private and special-use network addresses are forbidden")
            pinned = target.copy_with(host=ips[0])
            host = target.host if port == (443 if target.scheme == "https" else 80) else f"{target.host}:{port}"
            async with client.stream("GET", pinned, headers={"Host": host, "User-Agent": "HYDRA/1.0 public research reader"},
                                     extensions={"sni_hostname": target.host}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers["location"])
                    continue
                data = bytearray()
                truncated = False
                async for chunk in response.aiter_bytes():
                    room = MAX_BYTES - len(data)
                    data.extend(chunk[:room])
                    if len(chunk) > room:
                        truncated = True
                        break
                kind = response.headers.get("content-type", "")
                if not any(t in kind.lower() for t in ("text/", "application/json", "application/xhtml")):
                    raise ValueError("Unsupported content type; this reader handles text and HTML")
                return {"url": url, "status": response.status_code, "content_type": kind,
                        "text": data.decode(response.encoding or "utf-8", "replace"), "truncated": truncated}
        raise ValueError("Too many redirects")


def _is_host(hostname: str | None, domain: str) -> bool:
    """Exact domain or a real subdomain of it (not evil-duckduckgo.com)."""
    return bool(hostname) and (hostname == domain or hostname.endswith("." + domain))


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.text = []
        self.links = []
        self.anchor = None
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "nav", "header", "footer", "aside", "head"):
            self.skip += 1
        if tag == "a" and not self.skip:
            self.anchor = [dict(attrs).get("href", ""), []]
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "nav", "header", "footer", "aside", "head") and self.skip:
            self.skip -= 1
        if tag == "a" and self.anchor:
            self.links.append((self.anchor[0], " ".join(self.anchor[1])))
            self.anchor = None
    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())
            if self.anchor:
                self.anchor[1].append(data.strip())


async def read_url(url: str) -> dict:
    response = await public_get(url)
    if "html" in response["content_type"]:
        page = Page()
        page.feed(response["text"])
        response["text"] = "\n".join(page.text)
    response["text_truncated"] = len(response["text"]) > 24000
    response["text"] = response["text"][:24000]
    response["untrusted_content"] = True
    return response


async def search(query: str, engine="brave", limit=5) -> dict:
    if not 1 <= limit <= 10:
        raise ValueError("Limit must be 1..10")
    engines = [engine, *(e for e in ("brave", "duckduckgo", "bing") if e != engine)]
    alternatives = {e: search_url(query, e) for e in ENGINES}
    attempts = []
    for candidate in engines:
        url = search_url(query, candidate)
        try:
            response = await public_get(url)
            page = Page()
            page.feed(response["text"])
            challenge = any(s in " ".join(page.text).casefold() for s in
                            ("unusual traffic", "verify you are human", "complete the captcha", "bots use duckduckgo"))
            if response["status"] != 200 or challenge:
                attempts.append({"engine": candidate, "status": "blocked", "http_status": response["status"]})
                continue
            results, seen = [], set()
            for link, title in page.links:
                link = urljoin(url, link)
                parsed = urlsplit(link)
                params = parse_qs(parsed.query)
                if parsed.hostname in ("www.google.com", "google.com") and parsed.path == "/url":
                    link = params.get("q", params.get("url", [link]))[0]
                elif _is_host(parsed.hostname, "duckduckgo.com") and "uddg" in params:
                    link = params["uddg"][0]
                parsed = urlsplit(link)
                hostname = parsed.hostname or ""
                if (parsed.scheme not in ("http", "https") or not title.strip() or link in seen
                    or any(hostname == h or hostname.endswith("."+h) for h in
                           ("brave.com", "google.com", "gstatic.com", "duckduckgo.com", "bing.com", "microsoft.com"))):
                    continue
                seen.add(link)
                results.append({"title": title[:300], "url": link})
                if len(results) == limit:
                    break
            if results:
                return {"status": "ok", "engine": candidate, "results": results, "search_urls": alternatives,
                        "attempts": attempts, "paid_api_used": False, "untrusted_content": True}
            attempts.append({"engine": candidate, "status": "no_parseable_results"})
        except (httpx.HTTPError, OSError, ValueError) as exc:
            attempts.append({"engine": candidate, "status": "unavailable", "error": type(exc).__name__})
    return {"status": "browser_required", "results": [], "search_urls": alternatives,
            "attempts": attempts, "paid_api_used": False}


async def web_search(args, ctx):
    if ctx.private:
        raise PermissionError("Web access is disabled in private mode")
    try:
        return await asyncio.wait_for(search(args["query"], args.get("engine", "brave"), args.get("limit", 5)), 45)
    except TimeoutError:
        return {"status": "browser_required", "results": [], "paid_api_used": False,
                "search_urls": {e: search_url(args["query"], e) for e in ENGINES}, "reason": "search_timeout"}


async def web_read(args, ctx):
    from hydra.tools.policy import allowed_domain
    if ctx.private or not (ctx.capabilities.public_web or allowed_domain(ctx, args["url"])):
        raise PermissionError("Public URL access not granted")
    return await asyncio.wait_for(read_url(args["url"]), 20)
