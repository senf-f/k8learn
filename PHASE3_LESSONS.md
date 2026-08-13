# Phase 3 Lessons — API Test Suite Against a Live Cluster

Learning notes from writing an integration test suite that runs against the Phase 1 app *as deployed in Kubernetes* (Phase 2), rather than in-process. This is the QA heart of the project: proving the deployed system behaves — including how Kubernetes keeps it healthy under disruption.

---

## 1. What we built

Four new files in `tests/`, plus a marker registration in the root `conftest.py`:

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Integration fixtures: a `PortForward` subprocess, kube client fixtures, and graceful skip when no cluster is reachable |
| `tests/test_health.py` | 2 tests — `/health` returns 200 with the right schema |
| `tests/test_crud.py` | 6 tests — create/list/get/404/delete/422 against the deployed API |
| `tests/test_resilience.py` | 3 tests — pod recreation, availability during pod deletion, scale-to-zero recovery |

**Verified end-to-end:** full suite green — **20 passed** (9 Phase 1 unit tests + 11 integration tests) against the running Kind cluster.

---

## 2. The mental model: two very different kinds of test

Phase 1's `test_app.py` and Phase 3's tests look similar (both hit HTTP endpoints and assert on responses), but they test fundamentally different things:

```
Phase 1 (unit)                        Phase 3 (integration)
--------------                        ---------------------
TestClient(app)                       kubectl port-forward -> Service -> Pods
   |                                     |
in-process, no network                real network, real container
tests THE APP's logic                 tests THE DEPLOYED SYSTEM
runs anywhere, milliseconds           needs a cluster, seconds
```

- **Unit tests** import the app object and call it directly (`TestClient(app)`). No Docker, no cluster — they verify the code's logic in isolation and run in milliseconds.
- **Integration tests** hit the app *through* the Service, over a real port-forward, in the real container image, on a real cluster. They catch things unit tests can't: a broken Dockerfile, a bad probe, a misconfigured Service selector, or the cluster failing to self-heal.

The resilience tests are a third flavor still: they don't really test *the app* at all — they test that **Kubernetes does what we declared** (recreate dead pods, load-balance, recover from scaling). That's the payoff of Phase 2's declarative manifests.

---

## 3. How to run it

```bash
# unit tests only — no cluster needed
python -m pytest tests/test_app.py -v

# full suite — integration tests need a running cluster
bash scripts/setup-cluster.sh        # create Kind + deploy (if not already up)
python -m pytest tests/ -v

# explicitly skip integration (e.g. on a machine with no Docker)
python -m pytest tests/ -m "not integration"
```

The integration tests **skip cleanly** if the kube context `kind-qa-demo` isn't reachable, so `pytest tests/` never fails just because Docker is off — it runs the 9 unit tests and skips the 11 integration ones.

---

## 4. Walkthrough: the fixtures (`tests/conftest.py`)

This file is where all the cluster plumbing lives, so the test files stay clean and declarative.

### The `PortForward` subprocess

```python
class PortForward:
    def start(self, ready_timeout=20.0):
        self._proc = subprocess.Popen([
            "kubectl", "port-forward",
            f"svc/{SERVICE}", f"{self.local_port}:{APP_PORT}",
            "-n", NAMESPACE, "--address", "127.0.0.1",
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        wait_until(self._health_ok, ...)   # don't return until it actually serves /health
        return self
```

Why a subprocess and not `&` + `kill`? **On Windows/Git Bash, backgrounding a process with `&` then `kill $PID` is unreliable** (see the project's #1 gotcha — a stale `uvicorn` once squatted on port 8000). A Python `subprocess.Popen` gives a real handle we can `terminate()`/`kill()` deterministically.

Crucially, `.start()` doesn't return until `/health` actually answers 200. A port-forward reports "Forwarding from..." instantly but isn't immediately ready — polling `/health` turns "I started it" into "it works."

### Skip-if-no-cluster

```python
def _load_kube():
    try:
        from kubernetes import client, config
    except ImportError:
        pytest.skip("kubernetes client not installed")
    try:
        config.load_kube_config(context=KUBE_CONTEXT)
    except Exception as exc:
        pytest.skip(f"kube context '{KUBE_CONTEXT}' not available: {exc}")
    return client
```

`pytest.skip()` inside a fixture skips every test that depends on it. This is what lets the suite degrade gracefully instead of erroring when there's no cluster.

### `wait_until` — the polling helper

```python
def wait_until(predicate, timeout=60.0, interval=1.0, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(f"Timed out after {timeout}s waiting for: {message}")
```

**Kubernetes is eventually-consistent.** You delete a pod and the replacement isn't `Ready` instantly — it schedules, pulls (or reuses) the image, starts, then passes its readiness probe. Every resilience assertion is therefore "poll until true, or fail after a timeout," never "assert immediately." The `message` makes timeouts self-explaining.

### Fixture layers

- `kube_core` / `kube_apps` (session) — `CoreV1Api` (pods) and `AppsV1Api` (deployments/scaling).
- `app_ready` (session) — blocks until ≥2 replicas are ready before any test hits the app.
- `app_url` (session) — one long-lived port-forward shared by the health/CRUD tests.
- `make_port_forward` (function) — a *factory* on a different local port, cleaned up per test. Resilience tests need their own fresh tunnel because they kill pods (see gotcha below).

---

## 5. Walkthrough: the resilience tests (`tests/test_resilience.py`)

These are the interesting ones — they exploit exactly the reconciliation behavior Phase 2 set up.

### Test 1 — a deleted pod is recreated
```python
victim = running_pods(kube_core)[0].metadata.name
kube_core.delete_namespaced_pod(victim, NAMESPACE)

def replaced():
    names = {p.metadata.name for p in running_pods(kube_core)}
    return len(names) >= 2 and victim not in names
wait_until(replaced, ...)
wait_until(lambda: ready_replicas(kube_apps) >= 2, ...)
```
Delete a pod out from under the Deployment; the ReplicaSet notices "actual (1) < desired (2)" and creates a new pod with a *new name*. We wait until the victim is gone **and** 2 pods are running again. This is declarative reconciliation in action.

### Test 2 — the Service stays available during a deletion
```python
kube_core.delete_namespaced_pod(victim, NAMESPACE)
pf = make_port_forward()          # .start() polls /health until 200
for _ in range(5):
    assert httpx.get(f"{pf.url}/health").status_code == 200
```
With 2 replicas, killing one should be invisible to a client — the other serves traffic. The key subtlety is in the port-forward (gotcha #2 below): we start a *fresh* one *after* triggering the delete, so it resolves to a ready endpoint (the survivor), not the terminating victim.

### Test 3 — scale to zero, then recover
```python
_scale(kube_apps, 0)
wait_until(lambda: ready_replicas(kube_apps) == 0, ...)
wait_until(lambda: len(running_pods(kube_core)) == 0, ...)
_scale(kube_apps, 2)
wait_until(lambda: ready_replicas(kube_apps) >= 2, ...)
assert httpx.get(f"{make_port_forward().url}/health").status_code == 200
```
Scaling to 0 proves the system genuinely goes dark (no pods), and scaling back to 2 proves it recovers to a serving state. We verify "unavailable" via the K8s API (0 ready replicas, 0 running pods) rather than an HTTP timeout, which would be flaky.

Each test that mutates the cluster **restores 2 ready replicas before finishing**, so the tests are independent and order-insensitive.

---

## 6. Gotchas we hit (the valuable part)

### Gotcha 1 — Kubernetes is eventually-consistent; never assert immediately
The first instinct is `delete_pod(); assert len(pods) == 2`. That fails: right after a delete you might see 1 (terminating gone) or 3 (new one starting, old one still terminating). **Every state check must poll with a timeout** (`wait_until`), because the controller reconciles asynchronously. This is the single biggest mindset shift from unit testing.

### Gotcha 2 — `kubectl port-forward svc/...` binds to one pod, it does not load-balance per request
A port-forward to a Service resolves to **a single ready endpoint** at connection time and stays glued to it — it is *not* per-request round-robin. So if you hold a tunnel open and then kill the pod it's bound to, the tunnel breaks. The availability test sidesteps this by starting a **fresh** port-forward *after* the delete, so it resolves to the surviving replica. (Reusing the session `app_url` tunnel here would have been flaky.)

### Gotcha 3 — `runAsNonRoot` requires a numeric UID (carried over from Phase 2)
This tripped us in Phase 2 but it's worth remembering here: the pods only run because the Dockerfile bakes `USER 10001` and the manifest sets `runAsUser: 10001`. If integration tests suddenly can't reach the app, check the pods aren't stuck in a `CreateContainerConfigError` from a security-context mismatch.

### Gotcha 4 — importing helpers from `conftest.py`
The resilience test imports shared helpers with `from conftest import ready_replicas, running_pods, wait_until`. This works because pytest (default "prepend" import mode) puts the test file's directory (`tests/`) on `sys.path`, so `conftest` resolves to `tests/conftest.py`. Fixtures are auto-injected by name and need no import; plain helper functions do.

---

## 7. Takeaways

- **Integration tests catch what unit tests can't** — image, probes, Service wiring, and cluster self-healing only exist once deployed. Both layers are worth having.
- **Test the platform's promises, not just your code** — the resilience tests assert that Kubernetes recreates, load-balances, and recovers. That's the real value of declarative manifests.
- **Everything in a cluster is eventually-consistent** — poll with a timeout; never assert on cluster state synchronously.
- **Make the suite degrade gracefully** — skip integration tests when there's no cluster so `pytest tests/` is always runnable.
- **Isolate mutating tests** — each restores the deployment to a known-good state (2 ready replicas), keeping tests independent and re-runnable.
- **Prefer real subprocess handles over shell backgrounding on Windows** — deterministic cleanup beats `&`/`kill` roulette.
