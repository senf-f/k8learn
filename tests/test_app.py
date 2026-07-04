"""Phase 1 unit tests — exercise the FastAPI app in-process via TestClient.

Phase 3 adds integration tests that run against the app deployed in Kind.
"""

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app


@pytest.fixture(autouse=True)
def reset_storage():
    """Isolate tests — the app keeps test cases in module-level globals."""
    main._testcases.clear()
    main._next_id = 1
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_returns_200_and_status(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_testcases_starts_empty(client):
    resp = client.get("/api/testcases")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_testcase_returns_201_with_id(client):
    resp = client.post("/api/testcases", json={"title": "login works", "status": "pass"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 1
    assert body["title"] == "login works"
    assert body["status"] == "pass"


def test_created_testcase_appears_in_list(client):
    client.post("/api/testcases", json={"title": "a", "status": "pass"})
    resp = client.get("/api/testcases")
    assert resp.status_code == 200
    titles = [tc["title"] for tc in resp.json()]
    assert "a" in titles


def test_get_testcase_by_id_returns_correct_data(client):
    created = client.post("/api/testcases", json={"title": "b", "status": "fail"}).json()
    resp = client.get(f"/api/testcases/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_missing_testcase_returns_404(client):
    resp = client.get("/api/testcases/9999")
    assert resp.status_code == 404


def test_delete_testcase_returns_204_then_get_404(client):
    created = client.post("/api/testcases", json={"title": "c", "status": "pass"}).json()
    del_resp = client.delete(f"/api/testcases/{created['id']}")
    assert del_resp.status_code == 204
    get_resp = client.get(f"/api/testcases/{created['id']}")
    assert get_resp.status_code == 404


def test_delete_missing_testcase_returns_404(client):
    resp = client.delete("/api/testcases/9999")
    assert resp.status_code == 404


def test_create_with_invalid_data_returns_422(client):
    resp = client.post("/api/testcases", json={"status": "pass"})  # missing title
    assert resp.status_code == 422
