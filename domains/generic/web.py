"""SSRF-guarded web tools. Results are untrusted external content (they taint the run)."""
from __future__ import annotations

import html
import re
from urllib.parse import quote, urljoin

from core.confine import SSRFError, check_url
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.settings import settings
from core.tools import ToolSpec

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 5
_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(raw: str) -> str:
    text = _TAG.sub(" ", _COMMENT.sub("", _SCRIPT.sub("", raw)))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


async def fetch(url: str, allow: tuple[str, ...] = ()) -> tuple[int, str, str]:
    """GET with manual redirects; every hop is SSRF-checked. Returns (status, content_type, body)."""
    import httpx

    async with httpx.AsyncClient(timeout=15, follow_redirects=False,
                                 headers={"User-Agent": "harness-engine/0.2"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(url, allow)
            async with client.stream("GET", url) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break
                body = b"".join(chunks)[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
                return resp.status_code, resp.headers.get("content-type", ""), body
    raise SSRFError("Too many redirects")


async def web_fetch(args: dict, ctx) -> str:
    status, ctype, body = await fetch(args["url"], settings().web_allow_domains)
    text = html_to_text(body) if "html" in ctype.lower() or body.lstrip().startswith("<") else body
    return f"HTTP {status} {ctype}\n{text}"


async def web_search(args: dict, ctx) -> str:
    url = f"https://html.duckduckgo.com/html/?q={quote(args['query'])}"
    status, _ctype, body = await fetch(url)
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
    snippets = re.findall(r'class="result__snippet[^>]*>(.*?)</a>', body, re.S)
    if not links:
        return f"No search results found or blocked (HTTP {status})."
    return "\n\n".join(f"{html_to_text(t)}\n{u}\n{html_to_text(s)}"
                       for (u, t), s in zip(links[:8], snippets + [""] * 8, strict=False))


class WebPlugin(Plugin):
    name = "web"

    def register(self, ctx: PluginContext) -> None:
        base = dict(capability="Web", risk=RiskTier.R1, read_only=True, parallel_safe=True,
                    untrusted=True, policy_tool="web")
        ctx.tool(ToolSpec("web_fetch", "Fetch a public http(s) URL as text. Private addresses are blocked.",
                          {"type": "object", "properties": {"url": {"type": "string"}},
                           "required": ["url"], "additionalProperties": False},
                          web_fetch, policy_action="fetch", **base))
        ctx.tool(ToolSpec("web_search", "Search the web.",
                          {"type": "object", "properties": {"query": {"type": "string"}},
                           "required": ["query"], "additionalProperties": False},
                          web_search, policy_action="search", **base))
