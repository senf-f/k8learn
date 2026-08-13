"""Integration tests for the testcases CRUD API against the deployed app.

The session-scoped port-forward is a single sticky tunnel to one pod, so a
create/get/delete sequence stays consistent even though the app keeps state
per-pod in memory.
"""

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_create_returns_201_with_server_assigned_id(app_url):
    resp = httpx.post(
        f"{app_url}/api/testcases",
        json={"title": "integration create", "status": "pass"},
        timeout=5.0,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["id"], int)
    assert body["title"] == "integration create"
    assert body["status"] == "pass"


def test_created_item_appears_in_list(app_url):
    created = httpx.post(
        f"{app_url}/api/testcases",
        json={"title": "in-list", "status": "pass"},
        timeout=5.0,
    ).json()
    listed = httpx.get(f"{app_url}/api/testcases", timeout=5.0)
    assert listed.status_code == 200
    ids = [tc["id"] for tc in listed.json()]
    assert created["id"] in ids


def test_get_by_id_returns_created_data(app_url):
    created = httpx.post(
        f"{app_url}/api/testcases",
        json={"title": "fetch-me", "status": "fail"},
        timeout=5.0,
    ).json()
    resp = httpx.get(f"{app_url}/api/testcases/{created['id']}", timeout=5.0)
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_missing_returns_404(app_url):
    resp = httpx.get(f"{app_url}/api/testcases/999999", timeout=5.0)
    assert resp.status_code == 404


def test_delete_returns_204_then_get_404(app_url):
    created = httpx.post(
        f"{app_url}/api/testcases",
        json={"title": "delete-me", "status": "pass"},
        timeout=5.0,
    ).json()
    deleted = httpx.delete(f"{app_url}/api/testcases/{created['id']}", timeout=5.0)
    assert deleted.status_code == 204
    after = httpx.get(f"{app_url}/api/testcases/{created['id']}", timeout=5.0)
    assert after.status_code == 404


def test_create_with_invalid_data_returns_422(app_url):
    resp = httpx.post(
        f"{app_url}/api/testcases",
        json={"status": "pass"},  # missing required title
        timeout=5.0,
    )
    assert resp.status_code == 422
