# Phase 1 Lessons — The Application

Learning notes from building the FastAPI test-case CRUD app, test-first, and packaging it with Docker.

---

## 1. What we built

A tiny REST API (`app/main.py`) that stores "test cases" in memory, plus a pytest suite, plus a Dockerfile to package it. Five endpoints:

| Method | Path | Does | Success code |
|--------|------|------|--------------|
| GET | `/health` | liveness/readiness check | 200 |
| GET | `/api/testcases` | list all | 200 |
| POST | `/api/testcases` | create one | 201 |
| GET | `/api/testcases/{id}` | fetch one | 200 (404 if missing) |
| DELETE | `/api/testcases/{id}` | delete one | 204 (404 if missing) |

Files:
- `app/main.py` — the FastAPI app
- `app/requirements.txt` — runtime deps (`fastapi`, `uvicorn`)
- `app/Dockerfile` + `app/.dockerignore` — how to containerize it
- `tests/test_app.py` — 9 pytest tests
- `tests/requirements.txt` — test deps
- `conftest.py` — makes `import app.main` work when pytest runs
- `.gitignore` — keeps `.venv`, caches out of git

---

## 2. The method: TDD (test-driven development)

**Write the test first, watch it fail, then write just enough code to make it pass.** If you never saw the test fail, you don't actually know it tests anything. The order followed:

1. Wrote `tests/test_app.py` — 9 tests describing what the API *should* do.
2. Ran them → they failed with `ModuleNotFoundError: No module named 'app.main'` (correct failure: the app doesn't exist yet).
3. Wrote `app/main.py`.
4. Ran them again → all 9 green.
5. Refactored: added the `reset_storage` fixture for test isolation, stayed green.

This is the Red → Green → Refactor cycle.

---

## 3. How to run it all locally

Run from the project root: `C:\Users\mate.mrse\privatno\moji-projekti\k8learn`.

**1. Create and activate a virtual environment** (isolates this project's packages from system Python):
```bash
python -m venv .venv
source .venv/Scripts/activate    # Git Bash on Windows
# (.venv\Scripts\activate       if you're in cmd/PowerShell)
```
Prompt shows `(.venv)` when active.

**2. Install dependencies:**
```bash
pip install -r app/requirements.txt -r tests/requirements.txt
```

**3. Run the tests:**
```bash
python -m pytest tests/test_app.py -v
```
Expect `9 passed`. `-v` gives one line per test.

**4. Run the app for real:**
```bash
cd app
python -m uvicorn main:app --reload --port 8000
```
`main:app` = "in `main.py`, use the variable named `app`". `--reload` restarts on edits. Then in a browser:
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/docs ← FastAPI auto-generates an interactive API page — create/list/delete with buttons, no curl needed.

`Ctrl+C` to stop.

**5. Try it from the command line** (second terminal, while uvicorn runs):
```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/api/testcases \
  -H "Content-Type: application/json" \
  -d '{"title":"my first test","status":"pass"}'
curl http://127.0.0.1:8000/api/testcases
```

**6. Build and run the Docker image:**
```bash
docker build -t k8s-qa-demo:local ./app        # package it
docker run -d --name qa -p 8000:8000 k8s-qa-demo:local   # run in background
curl http://127.0.0.1:8000/health               # hit it
docker logs qa                                   # see its output
docker rm -f qa                                  # stop + remove when done
```
`-d` = detached (background), `-p 8000:8000` = map host port 8000 to the container's 8000.

**Why the Dockerfile matters for later:** Kubernetes doesn't run Python files — it runs *container images*. The Dockerfile is the recipe that turns `main.py` into an image K8s can schedule. That's the bridge into Phase 2.

---

## 4. Walkthrough: `app/main.py`

### Imports
```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
```
- `FastAPI` — the web framework; create one app object from it.
- `HTTPException` — how you tell FastAPI "stop and return an error response" (e.g. a 404).
- `Response` — a raw HTTP response with no body; used for the 204 delete.
- `BaseModel` — from Pydantic. Declare the *shape* of your data as a class, and FastAPI auto-validates incoming JSON against it and serializes outgoing objects to JSON.

### The app object
```python
app = FastAPI(title="k8s-qa-demo")
```
The whole application. The variable is literally named `app` — that's the `app` in `uvicorn main:app`. `title` shows on the `/docs` page.

### The data models — the key design choice
```python
class TestCaseIn(BaseModel):
    title: str
    status: str = "pending"

class TestCase(TestCaseIn):
    id: int
```
Two models:
- `TestCaseIn` — what a client may *send*. `title` required (no default), `status` optional (defaults to `"pending"`). **No `id`** — the client doesn't pick the ID, the server assigns it.
- `TestCase` — what the server *stores and returns*. Inherits `title`/`status`, adds `id: int`.

Why split? If clients could send an `id`, they could overwrite records or create gaps. Keeping `id` out of the input model keeps the server in control. "Separate input model from output model" is a standard real-API pattern.

Type annotations aren't just docs — Pydantic *enforces* them. Send `{"status": "pass"}` with no `title` and Pydantic rejects it before your code runs, returning a 422.

### The "database"
```python
_testcases: dict[int, TestCase] = {}
_next_id = 1
```
- `_testcases` — a dict mapping `id → TestCase`. In-memory only: **lives in RAM**, so a process restart wipes it. Fine for a demo, and it's why Phase 3's resilience tests are interesting — killing a pod wipes its data.
- `_next_id` — counter for handing out IDs.
- Leading underscore = Python convention for "internal." (Tests reach in to reset these for isolation — a pragmatic exception.)

### Endpoint 1 — health
```python
@app.get("/health")
def health():
    return {"status": "ok"}
```
`@app.get("/health")` **decorator** registers this function for `GET /health`. The return value is auto-converted to JSON → `200` with `{"status": "ok"}`. Looks trivial but it's the backbone of Phase 2: K8s calls `/health` as a **readiness probe** (ready for traffic?) and **liveness probe** (still alive, or restart it?).

### Endpoint 2 — list
```python
@app.get("/api/testcases")
def list_testcases() -> list[TestCase]:
    return list(_testcases.values())
```
Returns all stored cases as a JSON array. `-> list[TestCase]` tells FastAPI/`/docs` the response shape.

### Endpoint 3 — create
```python
@app.post("/api/testcases", status_code=201)
def create_testcase(payload: TestCaseIn) -> TestCase:
    global _next_id
    tc = TestCase(id=_next_id, **payload.model_dump())
    _testcases[tc.id] = tc
    _next_id += 1
    return tc
```
- `status_code=201` — overrides default 200. 201 = "Created," correct for a successful POST that makes a resource.
- `payload: TestCaseIn` — because the parameter is typed as a Pydantic model, FastAPI reads the request **body as JSON** and validates it. Invalid body → automatic 422, code never runs.
- `global _next_id` — needed because we *reassign* it. (Not needed for `_testcases` — we only mutate it, never reassign.)
- `TestCase(id=_next_id, **payload.model_dump())` — `model_dump()` → dict like `{"title": ..., "status": ...}`; `**` spreads it as keyword args. Combined with `id=_next_id`, builds the full stored object. **This is where the server-assigned ID gets attached.**

### Endpoint 4 — get by ID
```python
@app.get("/api/testcases/{tc_id}")
def get_testcase(tc_id: int) -> TestCase:
    tc = _testcases.get(tc_id)
    if tc is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    return tc
```
- `{tc_id}` is a **path parameter**; the argument `tc_id: int` captures it. `int` annotation → FastAPI converts the URL string to int; `/api/testcases/abc` gives 422 (not an int).
- `.get(tc_id)` returns `None` if missing (safer than `_testcases[tc_id]`, which raises `KeyError`).
- Missing → `raise HTTPException(404, ...)` → clean 404 with `{"detail": "Test case not found"}`. You **raise**, not return.

### Endpoint 5 — delete
```python
@app.delete("/api/testcases/{tc_id}", status_code=204)
def delete_testcase(tc_id: int):
    if tc_id not in _testcases:
        raise HTTPException(status_code=404, detail="Test case not found")
    del _testcases[tc_id]
    return Response(status_code=204)
```
- `204 No Content` = conventional code for successful delete; deliberately no body.
- Check existence first; 404 if absent (so deleting twice gives 404 the second time).
- `del` removes the key. Return a bare `Response(status_code=204)` — 204 must have an empty body, so returning a dict would contradict it.

### Mental model
1. **Decorators wire functions to routes** — `@app.get(...)` / `@app.post(...)`.
2. **Pydantic models are the contract** — annotations become automatic validation (422s) + JSON serialization, no manual parsing.
3. **Errors are raised, not returned** — `HTTPException` produces 4xx responses.

---

## 5. Walkthrough: `tests/test_app.py`

### Imports
```python
import pytest
from fastapi.testclient import TestClient
from app import main
from app.main import app
```
- `TestClient` — FastAPI's built-in test tool. Calls your API **in the same process, no server, no network, no ports**. Fast, and avoids the port-8000 gotcha.
- Two imports of the same module: `from app.main import app` grabs the app object for `TestClient`; `from app import main` grabs the *module* so we can reach its globals in the reset fixture.

### What a fixture is
A **fixture** is pytest's setup/teardown mechanism. Decorate a function with `@pytest.fixture`; any test that names it as a parameter gets it automatically. It's dependency injection for tests.

### Fixture 1 — reset_storage
```python
@pytest.fixture(autouse=True)
def reset_storage():
    main._testcases.clear()
    main._next_id = 1
    yield
```
Solves a real problem: the app stores data in **module-level globals** that persist across the whole test run. Without resetting, tests leak state — `test_create_...id == 1` would only pass if it ran first.
- `autouse=True` — runs before **every** test automatically, no need to request it. Right choice for a global reset.
- Clears the dict and resets the counter so every test starts empty with first ID = 1.
- `yield` — code before it is setup (runs before the test); code after would be teardown. Bare `yield` = setup-only.

This was the refactor after the initial green: without it the suite passed only by luck of ordering.

### Fixture 2 — client
```python
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
```
- Wraps the app in a `TestClient`; tests taking a `client` parameter receive `c`.
- `with ... as c:` — entering triggers FastAPI startup events, exiting triggers shutdown. Correct and future-proof even though we don't use those hooks yet.
- No `autouse` — a test only gets a client if it lists `client` as a parameter.

### The nine tests — pattern
Every test is **Arrange → Act → Assert**. Recurring tools:
- `client.get/post/delete(...)` — send a request, get a response. `json={...}` on POST serializes the body.
- `resp.status_code` and `resp.json()` — inspect status and parse JSON.

1. **`test_health_returns_200_and_status`** — GET `/health`, assert 200 + exact body. The endpoint K8s will probe.
2. **`test_list_testcases_starts_empty`** — GET list on fresh store → 200 + `[]`. Depends on `reset_storage` — proof the fixture works.
3. **`test_create_testcase_returns_201_with_id`** — POST valid body → 201, `id == 1`, echoed title/status. Verifies server assigns the ID.
4. **`test_created_testcase_appears_in_list`** — create then list, confirm title present. Tests two endpoints together; line uses a list comprehension over titles.
5. **`test_get_testcase_by_id_returns_correct_data`** — `.post(...).json()` creates *and* parses in one line; fetch by the real returned ID; assert fetched == created. Round-trip integrity.
6. **`test_get_missing_testcase_returns_404`** — GET id 9999 → 404. The `raise HTTPException(404)` path.
7. **`test_delete_testcase_returns_204_then_get_404`** — full lifecycle: create → delete (204) → get same id (404). Confirms delete actually removes.
8. **`test_delete_missing_testcase_returns_404`** — delete something never there → 404. Guards a naive `del` that would crash.
9. **`test_create_with_invalid_data_returns_422`** — POST missing `title` → 422. We wrote no validation code — **Pydantic does it automatically** from `title: str`. Free, and locked in by this test.

### Takeaways
- **`TestClient` = fast, in-process API testing** — real requests/responses, no server or network.
- **`autouse` fixtures = automatic per-test setup** — reset global state so tests can't contaminate each other.
- **Use real returned IDs, not hardcoded ones** — read `created['id']` so tests stay correct even if ID assignment changes.
- **Cover happy path + error path** — 200/201/204 successes *and* 404/422 failures. That mix makes a suite trustworthy.

---

## 6. Gotcha we hit: stale process squatting on port 8000

During the Docker smoke test, a "fresh" container showed leftover state and wrong IDs — impossible with in-memory storage. Cause: an earlier local `uvicorn` had survived a `kill` and was still bound to `127.0.0.1:8000`, so `curl 127.0.0.1:8000` was hitting the **old process**, not the container (which Docker published to `0.0.0.0:8000`).

Diagnosis and fix:
```bash
netstat -ano | grep :8000        # shows the PID holding the port
taskkill //PID <pid> //F         # kill it (Windows)
```

**Lesson for later phases:** on Windows/Git Bash, backgrounding a server with `&` then `kill $PID` is unreliable. Prefer running the server in its own terminal and stopping with `Ctrl+C`, or use Docker's `-p` + `docker rm -f`. If results look weird, check what owns the port first.
