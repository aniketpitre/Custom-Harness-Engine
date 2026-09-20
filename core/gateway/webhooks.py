import httpx
import os
import asyncio
import json
from datetime import datetime, timezone

async def dispatch_webhook(session_id: str, status: str, receipt: dict | None = None):
    endpoints_str = os.getenv("HARNESS_WEBHOOK_ENDPOINTS", "")
    if not endpoints_str:
        return
        
    endpoints = [e.strip() for e in endpoints_str.split(",") if e.strip()]
    if not endpoints:
        return
        
    payload = {
        "event": "session_completed" if status == "success" else "session_failed",
        "session_id": session_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "receipt": receipt
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = []
        for endpoint in endpoints:
            tasks.append(client.post(endpoint, json=payload))
            
        # Fire and forget / gather results
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
