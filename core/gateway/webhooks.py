"""Outbound webhooks: HMAC-SHA256 signed, retried with backoff."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx

from core.settings import settings

log = logging.getLogger("harness.webhooks")
RETRIES = 3
_sleep = asyncio.sleep


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _post(client: httpx.AsyncClient, url: str, body: bytes, headers: dict):
    last: Exception | httpx.Response | None = None
    for attempt in range(RETRIES):
        try:
            resp = await client.post(url, content=body, headers=headers)
            if resp.status_code < 500:
                return resp
            last = resp
        except httpx.HTTPError as error:
            last = error
        await _sleep(min(2 ** attempt, 10))
    log.warning("webhook to %s failed after %d attempts: %s", url, RETRIES, last)
    return last


async def dispatch_webhook(session_id: str, status: str, receipt: dict | None = None):
    st = settings()
    if not st.webhook_endpoints:
        return None
    payload = {"event": "session_completed" if status == "success" else "session_failed",
               "session_id": session_id, "status": status,
               "timestamp": datetime.now(timezone.utc).isoformat(), "receipt": receipt}
    body = json.dumps(payload, default=str).encode()
    headers = {"Content-Type": "application/json"}
    if st.webhook_secret:
        headers["X-Harness-Signature"] = sign(st.webhook_secret, body)
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await asyncio.gather(*(_post(client, url, body, headers) for url in st.webhook_endpoints),
                                    return_exceptions=True)
