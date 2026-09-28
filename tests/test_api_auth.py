import pytest
from fastapi.testclient import TestClient
import os
from unittest.mock import patch

from core.gateway.api import app

client = TestClient(app)

def test_api_auth_no_token():
    response = client.get("/agents")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}

def test_api_auth_invalid_token():
    response = client.get("/agents", headers={"Authorization": "Bearer not_the_token"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid API token"}

@patch("core.gateway.api.get_secret")
def test_api_auth_valid_env_token(mock_get_secret):
    os.environ["HARNESS_API_TOKEN"] = "my_secure_test_token"
    mock_get_secret.side_effect = Exception("Should not reach vault")

    response = client.get("/agents", headers={"Authorization": "Bearer my_secure_test_token"})
    assert response.status_code == 200

    del os.environ["HARNESS_API_TOKEN"]

@patch("core.gateway.api.get_secret")
def test_api_auth_valid_vault_token(mock_get_secret):
    if "HARNESS_API_TOKEN" in os.environ:
        del os.environ["HARNESS_API_TOKEN"]
    mock_get_secret.return_value = "vault_token_123"

    response = client.get("/agents", headers={"Authorization": "Bearer vault_token_123"})
    assert response.status_code == 200
