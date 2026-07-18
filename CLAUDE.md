# CLAUDE.md — k8learn

Kubernetes QA demo: a FastAPI test-case CRUD API, deployed to Kind, tested with pytest, automated with GitHub Actions. Portfolio project demonstrating deploy/test/automate skills from a QA automation perspective.

**Full plan:** `LEARNING_PLAN.md` (5 phases + stretch goals). **Live progress:** `TODO.md`. **Design notes:** `PHASE1_LESSONS.md`, `PHASE2_LESSONS.md`.

## Current status

- **Phase 1 (The Application): complete** — FastAPI app, 9 passing pytest tests, Docker image, all built test-first.
- **Phase 2 (Kubernetes manifests): complete** — namespace/configmap/deployment/service, idempotent `scripts/setup-cluster.sh` + `teardown.sh`. Verified: 2 replicas Running, API reachable via port-forward, clean setup→deploy→teardown.
- **Next: Phase 3 (API test suite)** — pytest against the deployed app (health, CRUD, resilience via K8s client).

## Layout

- `app/` — `main.py` (FastAPI CRUD API, in-memory storage), `requirements.txt`, `Dockerfile`
- `tests/` — `test_app.py` (Phase 1 unit tests via TestClient), `requirements.txt` (Phase 3 adds kubernetes client)
- `k8s/` — manifests (Phase 2, empty so far)
- `scripts/` — setup/teardown (Phase 2, empty so far)
- `conftest.py` — puts repo root on `sys.path` so `import app.main` works under pytest

## Conventions

- **Virtualenv** at `.venv` — activate with `source .venv/Scripts/activate` (Git Bash). Install: `pip install -r app/requirements.txt -r tests/requirements.txt`.
- **TDD** — write the failing test first, watch it fail, then minimal code to pass. This is how Phase 1 was built; keep it up.
- **Commits** — author as `mate.mrse@gmail.com`: `git -c user.email=mate.mrse@gmail.com commit ...`.
- **Docker image tag:** `k8s-qa-demo:local`. Build: `docker build -t k8s-qa-demo:local ./app`.
- `LEARNING_PLAN.md` and `TODO.md` are git-ignored (personal notes); `PHASE1_LESSONS.md` is committed.

## Common commands

```bash
python -m pytest tests/test_app.py -v          # run unit tests
cd app && python -m uvicorn main:app --reload  # run app locally (http://127.0.0.1:8000/docs)
docker build -t k8s-qa-demo:local ./app        # build image
```

## Gotchas

- **Windows/Git Bash: backgrounding a server with `&` then `kill $PID` is unreliable.** A stale `uvicorn` once kept squatting on port 8000, so tests silently hit the old process instead of the container. Prefer running servers in their own terminal (`Ctrl+C` to stop) or use Docker `-p` + `docker rm -f`. If results look wrong, check `netstat -ano | grep :8000` and `taskkill //PID <pid> //F`.
- **Kind + cgroup v1:** Docker Desktop on this WSL2 host exposes cgroup **v1**, but recent Kind default node images ship a kubelet that refuses it (kubelet crash-loops → API server never starts → "connection refused" at cluster bootstrap). `setup-cluster.sh` pins `kindest/node:v1.29.14` (K8s 1.29 tolerates cgroup v1). Don't drop the `--image` pin without checking `docker info | grep Cgroup`.
- **`kubectl apply -f k8s/` applies files alphabetically**, so namespaced resources (configmap, deployment) would be applied before `namespace.yaml`. The setup script applies `namespace.yaml` first, then the whole dir.
- No git remote is configured yet — needed before Phase 4 (CI).
