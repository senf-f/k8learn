# CLAUDE.md — k8learn

Kubernetes QA demo: a FastAPI test-case CRUD API, deployed to Kind, tested with pytest, automated with GitHub Actions. Portfolio project demonstrating deploy/test/automate skills from a QA automation perspective.

**Full plan:** `LEARNING_PLAN.md` (5 phases + stretch goals). **Live progress:** `TODO.md`. **Design notes:** `PHASE1_LESSONS.md`, `PHASE2_LESSONS.md`, `PHASE3_LESSONS.md`, `PHASE4_LESSONS.md`.

## Current status

- **Phase 1 (The Application): complete** — FastAPI app, 9 passing pytest tests, Docker image, all built test-first.
- **Phase 2 (Kubernetes manifests): complete** — namespace/configmap/deployment/service, idempotent `scripts/setup-cluster.sh` + `teardown.sh`. Verified: 2 replicas Running, API reachable via port-forward, clean setup→deploy→teardown.
- **Phase 3 (API test suite): complete** — 11 integration tests against the deployed app (2 health, 6 CRUD, 3 resilience) using the kubernetes Python client + a `kubectl port-forward` subprocess. Full suite green: 20 passed (9 unit + 11 integration). Integration tests are marked `@pytest.mark.integration` and skip cleanly when no cluster is reachable.
- **Phase 4 (GitHub Actions CI): complete** — `.github/workflows/k8s-tests.yaml` runs the full flow on push/PR to main: install kind v0.32.0, `bash scripts/setup-cluster.sh` (build → cluster → deploy → wait), then `pytest tests/ -v` (9 unit + 11 integration). Reuses the setup script as the single source of truth; dumps pod logs/describe/events on failure. First run green: 20 passed in ~21s (run 31790344163). Remaining Phase 4 item — CI badge — deferred to Phase 5 (no README yet).
- **Phase 5 (Portfolio polish): complete** — `README.md` with CI badge, mermaid architecture diagram, run instructions (incl. Windows/Git Bash note), pasted `pytest -v` output (20 passed), CI overview, layout table, and links to the phase lessons docs. Code-clarity pass found nothing to change (app/Dockerfile already clean); `.gitignore` already covered. Only optional leftover: a local teardown→setup→tests repeat (CI already proves it green).

## Layout

- `app/` — `main.py` (FastAPI CRUD API, in-memory storage), `requirements.txt`, `Dockerfile`
- `tests/` — `test_app.py` (Phase 1 unit tests via TestClient); Phase 3 integration tests `test_health.py`, `test_crud.py`, `test_resilience.py`; `conftest.py` (integration fixtures: `PortForward` subprocess, kube client fixtures, graceful skip); `requirements.txt` (adds kubernetes client)
- `k8s/` — manifests: namespace, configmap, deployment, service
- `scripts/` — `setup-cluster.sh`, `teardown.sh`
- `.github/workflows/` — `k8s-tests.yaml` (Phase 4 CI: kind + full pytest suite on push/PR)
- `conftest.py` (root) — puts repo root on `sys.path` so `import app.main` works; registers the `integration` marker

## Conventions

- **Virtualenv** at `.venv` — activate with `source .venv/Scripts/activate` (Git Bash). Install: `pip install -r app/requirements.txt -r tests/requirements.txt`.
- **TDD** — write the failing test first, watch it fail, then minimal code to pass. This is how Phase 1 was built; keep it up.
- **Commits** — author as `mate.mrse@gmail.com`: `git -c user.email=mate.mrse@gmail.com commit ...`.
- **Docker image tag:** `k8s-qa-demo:local`. Build: `docker build -t k8s-qa-demo:local ./app`.
- `LEARNING_PLAN.md` and `TODO.md` are git-ignored (personal notes); `PHASE1_LESSONS.md` is committed.

## Common commands

```bash
python -m pytest tests/test_app.py -v          # unit tests only (no cluster needed)
python -m pytest tests/ -v                      # full suite; integration tests need a running cluster
python -m pytest tests/ -m "not integration"    # explicitly skip integration tests
cd app && python -m uvicorn main:app --reload  # run app locally (http://127.0.0.1:8000/docs)
docker build -t k8s-qa-demo:local ./app        # build image
bash scripts/setup-cluster.sh                   # create Kind cluster + deploy (needed for integration tests)
```

## Gotchas

- **Windows: run repo scripts from Git Bash, not PowerShell's `bash`.** Typing `bash` in PowerShell launches WSL's bash, which has a separate Linux PATH (so `kind`/`kubectl`/`docker` → "command not found") and a different Docker socket. Git Bash inherits the Windows PATH. Use `./scripts/setup-cluster.sh` from Git Bash (forward slashes — bash treats `\` as an escape), or `& "C:\Program Files\Git\bin\bash.exe" scripts/...` from PowerShell. See `PHASE2_LESSONS.md` gotcha #4.
- **Windows/Git Bash: backgrounding a server with `&` then `kill $PID` is unreliable.** A stale `uvicorn` once kept squatting on port 8000, so tests silently hit the old process instead of the container. Prefer running servers in their own terminal (`Ctrl+C` to stop) or use Docker `-p` + `docker rm -f`. If results look wrong, check `netstat -ano | grep :8000` and `taskkill //PID <pid> //F`.
- **Kind + cgroup v1:** Docker Desktop on this WSL2 host exposes cgroup **v1**, but recent Kind default node images ship a kubelet that refuses it (kubelet crash-loops → API server never starts → "connection refused" at cluster bootstrap). `setup-cluster.sh` pins `kindest/node:v1.29.14` (K8s 1.29 tolerates cgroup v1). Don't drop the `--image` pin without checking `docker info | grep Cgroup`.
- **`kubectl apply -f k8s/` applies files alphabetically**, so namespaced resources (configmap, deployment) would be applied before `namespace.yaml`. The setup script applies `namespace.yaml` first, then the whole dir.
- **`kubectl port-forward svc/...` attaches to a single ready endpoint, not per-request load-balancing.** The resilience test for "service stays available during pod deletion" starts a *fresh* port-forward after killing a pod, so it resolves to the surviving replica. Reusing a tunnel bound to the killed pod would break.
- **Integration tests mutate the cluster** (delete pods, scale to 0). Each restores the Deployment to 2 ready replicas before finishing, so tests stay independent and order-insensitive.
