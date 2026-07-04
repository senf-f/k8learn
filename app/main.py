"""FastAPI CRUD API for test cases, backed by in-memory storage.

Deployed to Kubernetes and exercised by the pytest suite. The /health
endpoint backs the readiness and liveness probes.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI(title="k8s-qa-demo")


class TestCaseIn(BaseModel):
    title: str
    status: str = "pending"


class TestCase(TestCaseIn):
    id: int


_testcases: dict[int, TestCase] = {}
_next_id = 1


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/testcases")
def list_testcases() -> list[TestCase]:
    return list(_testcases.values())


@app.post("/api/testcases", status_code=201)
def create_testcase(payload: TestCaseIn) -> TestCase:
    global _next_id
    tc = TestCase(id=_next_id, **payload.model_dump())
    _testcases[tc.id] = tc
    _next_id += 1
    return tc


@app.get("/api/testcases/{tc_id}")
def get_testcase(tc_id: int) -> TestCase:
    tc = _testcases.get(tc_id)
    if tc is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    return tc


@app.delete("/api/testcases/{tc_id}", status_code=204)
def delete_testcase(tc_id: int):
    if tc_id not in _testcases:
        raise HTTPException(status_code=404, detail="Test case not found")
    del _testcases[tc_id]
    return Response(status_code=204)
