# Phase 4 Lessons — GitHub Actions CI on an Ephemeral Cluster

Learning notes from automating the whole flow — build → spin up Kind → deploy → run the full test suite — on every push and PR. This is where the project stops being "works on my machine" and becomes "provably works on a clean machine, every time."

---

## 1. What we built

One file:

| File | Purpose |
|------|---------|
| `.github/workflows/k8s-tests.yaml` | On push/PR to `main`: install kind, run `scripts/setup-cluster.sh`, run `pytest tests/ -v`, dump diagnostics on failure |

**Verified end-to-end:** first run green — **20 passed in ~21s** (9 unit + 11 integration), including the resilience tests hitting a real Kind cluster created fresh on the runner (run `31790344163`).

---

## 2. The mental model: an ephemeral cluster per run

```
GitHub push
    |
ubuntu-latest runner (fresh VM, has Docker + kubectl preinstalled)
    |
install kind CLI  ->  bash scripts/setup-cluster.sh
    |                        |  (build image, create Kind cluster,
    |                        |   load image, apply manifests, wait)
    |                        v
    |                  a real, throwaway K8s cluster
    |                        |
    +--> pytest tests/ -v  --+  (unit run in-process; integration
                                 port-forward to the Service and hit it)
    |
runner is destroyed when the job ends -> nothing to clean up
```

Key ideas:
- **The cluster is disposable.** Every run gets a brand-new VM and a brand-new Kind cluster, then throws both away. There's no teardown step because the runner itself is ephemeral — this is the cleanest possible test environment, impossible to leave in a dirty state.
- **CI is the ultimate "clone → setup → test" check.** The runner starts with none of your local state (no `.venv`, no cached cluster, no locally-built image). If it passes there, a stranger cloning the repo can reproduce it. That's the whole point of a portfolio project.
- **The same script runs locally and in CI.** No separate "CI mode" — CI is just a clean machine running the same `setup-cluster.sh` you run by hand.

---

## 3. How it runs

Nothing to invoke manually — it triggers on push/PR to `main`. To watch or inspect:

```bash
gh run list --workflow=k8s-tests.yaml      # recent runs
gh run watch <run-id> --exit-status        # follow a run live
gh run view <run-id> --log                 # full logs (grep for "passed")
```

Triggers (`on:` block): `push` and `pull_request`, both scoped to `branches: [main]`.

---

## 4. Walkthrough: the workflow

### Trigger + runner
```yaml
on:
  push:        { branches: [main] }
  pull_request:{ branches: [main] }
jobs:
  k8s-tests:
    runs-on: ubuntu-latest
```
A single job on GitHub's Ubuntu runner. It already ships **Docker** and **kubectl**, so we only install what's missing.

### Install kind
```yaml
- name: Install kind
  run: |
    curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.32.0/kind-linux-amd64
    chmod +x ./kind
    sudo mv ./kind /usr/local/bin/kind
```
Pin the kind version (`v0.32.0`, matching the locally-installed one) rather than "latest" — reproducible builds shouldn't silently change when kind cuts a release.

### Bring up the cluster — reuse the script
```yaml
- name: Create cluster and deploy
  run: bash scripts/setup-cluster.sh
```
This is the central design decision (see §5). Instead of re-listing create/build/load/apply/wait as YAML steps, CI calls the one script that already does all of it. One source of truth, zero drift.

### Run tests
```yaml
- name: Install test dependencies
  run: pip install -r app/requirements.txt -r tests/requirements.txt
- name: Run tests
  run: python -m pytest tests/ -v
```
The integration tests bring up their **own** `kubectl port-forward` subprocess (Phase 3's `conftest.py`), so there's no separate "start port-forward in the background" CI step — the tests are self-contained. Because the cluster *is* reachable here, the integration tests run rather than skip.

### Diagnostics on failure
```yaml
- name: Dump diagnostics on failure
  if: failure()
  run: |
    kubectl get pods -n qa-demo -o wide || true
    kubectl describe deployment qa-demo -n qa-demo || true
    kubectl logs -n qa-demo -l app=qa-demo --all-containers --tail=200 || true
    kubectl get events -n qa-demo --sort-by=.lastTimestamp || true
```
`if: failure()` runs this step **only when an earlier step failed**. On a remote runner you can't attach a debugger, so a red build must leave behind enough forensic evidence (pod status, describe, logs, events) to diagnose it from the logs alone. `|| true` keeps one missing resource from masking the rest.

---

## 5. The one real design decision: reuse the script, don't re-list steps

The plan (`LEARNING_PLAN.md:93`) spells CI out as ~12 discrete steps: build, create cluster, load image, apply manifests, wait for rollout, etc. The tempting literal translation is one YAML `run:` per step. We didn't — we ran `bash scripts/setup-cluster.sh` instead.

**Why:** those exact steps already live in `setup-cluster.sh`, tested by hand across Phases 2–3. Duplicating them in YAML creates **two definitions of "how to deploy"** that will silently diverge — someone fixes the local script and forgets the workflow (or vice versa), and CI passes while local breaks, or worse, CI tests a different deployment than the one you run. Calling the script keeps a single source of truth: fix it once, both paths benefit.

The trade-off: the script must be CI-friendly — no interactive prompts, non-zero exit on failure (`set -euo pipefail`, already there), path-independent (it resolves paths from `BASH_SOURCE`, already there). It was, because Phase 2 wrote it that way. Idempotent, hardened, path-independent scripts pay off precisely when you reuse them somewhere new.

---

## 6. Gotchas (and near-misses)

Unlike Phases 2–3, this phase went green on the first run — so most of these are traps we *avoided* by design rather than debugged after the fact.

### Gotcha 1 — the cgroup-v1 node-image pin is a local fix, harmless in CI
`setup-cluster.sh` pins `kindest/node:v1.29.14` because this WSL2 host exposes **cgroup v1** (Phase 2, gotcha #1). GitHub runners use **cgroup v2**, where that pin isn't needed — but an older K8s node image still runs fine on cgroup v2, so reusing the script needed no change. The lesson: a pin added to work around one environment's quirk was backward-compatible with the other, so one script served both. (If the pin had been cgroup-v2-*only*, CI and local would have needed different images — worth checking before assuming a workaround travels.)

### Gotcha 2 — don't re-run the tests' plumbing in CI
It's tempting to add a "start port-forward" step before pytest, mirroring the manual instructions in `PHASE2_LESSONS.md`. That would be wrong here: the integration fixtures already manage their own port-forward (and tear it down). A manual CI port-forward would collide on the port or leak a process. **Know what your test harness already does before scripting around it.**

### Gotcha 3 — a red build on a remote runner is only as debuggable as its logs
Locally you'd `kubectl describe` a stuck pod interactively. On a runner the VM is gone by the time you look. The `if: failure()` diagnostics step exists so a failure isn't just "pytest exited 1" — it's the pod states, events, and logs captured at the moment of failure. Cheap insurance you only appreciate when something breaks at 2am.

### Gotcha 4 — `bash scripts/...` on the runner, not the Windows `bash` trap
Worth contrasting with `PHASE2_LESSONS.md` gotcha #4: locally, `bash` in PowerShell is WSL's bash with a broken PATH. On the Linux runner there's no such ambiguity — `bash` is *the* bash, `kind`/`kubectl`/`docker` are on the PATH, and forward slashes are the only slashes. CI is in some ways a *simpler* shell environment than the Windows dev box.

### Non-blocking annotation — Node 20 deprecation
GitHub warns that `actions/checkout@v4` and `actions/setup-python@v5` target Node 20 (being retired); the runner force-runs them on Node 24. These are the latest major tags, so there's nothing to bump yet — noted so a future red herring doesn't send anyone chasing it.

---

## 7. Takeaways

- **CI on an ephemeral runner is the honest "clean clone" test** — it has none of your local state, so passing there means it genuinely reproduces.
- **One definition of "how to deploy"** — reusing `setup-cluster.sh` beats re-listing steps in YAML; two copies drift and you end up testing something other than what you ship.
- **Scripts written to be idempotent, hardened, and path-independent pay off when reused** — Phase 2's discipline is exactly why the script dropped into CI unchanged.
- **A failing remote build must leave forensic evidence** — `if: failure()` diagnostics turn "it broke" into "here's the pod state, events, and logs when it broke."
- **Pin your tools** (kind version, node image) so a green build stays green — "latest" is how a passing pipeline breaks with no code change.
- **Let the test harness own its plumbing** — the fixtures manage their own port-forward; CI shouldn't duplicate it.
