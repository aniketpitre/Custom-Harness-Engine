import pytest
from core.gateway.webhooks import dispatch_webhook
import os
import json

@pytest.mark.asyncio
async def test_dispatch_webhook(monkeypatch, httpx_mock):
    # Set ENV for webhook
    monkeypatch.setenv("HARNESS_WEBHOOK_ENDPOINTS", "http://test-webhook.local/push")
    
    # Mock httpx response
    httpx_mock.add_response(url="http://test-webhook.local/push", status_code=200)
    
    # Call dispatch
    results = await dispatch_webhook("sess-123", "success", {"some": "data"})
    
    # Check results
    assert len(results) == 1
    assert results[0].status_code == 200
    
    # Check payload
    request = httpx_mock.get_request()
    assert request is not None
    payload = json.loads(request.read().decode('utf-8'))
    assert payload["event"] == "session_completed"
    assert payload["session_id"] == "sess-123"
    assert payload["status"] == "success"
    assert payload["receipt"]["some"] == "data"
