"""Integration tests for /health against the deployed app."""

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_health_returns_200(app_url):
    resp = httpx.get(f"{app_url}/health", timeout=5.0)
    assert resp.status_code == 200


def test_health_schema(app_url):
    resp = httpx.get(f"{app_url}/health", timeout=5.0)
    assert resp.json() == {"status": "ok"}
