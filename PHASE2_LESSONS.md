# Phase 2 Lessons — Kubernetes Manifests

Learning notes from deploying the Phase 1 FastAPI app to a local Kubernetes cluster (Kind), with manifests and repeatable setup/teardown scripts.

---

## 1. What we built

Four manifests in `k8s/` plus two scripts in `scripts/`:

| File | Kind | Purpose |
|------|------|---------|
| `k8s/namespace.yaml` | Namespace | Isolates everything under `qa-demo` |
| `k8s/configmap.yaml` | ConfigMap | App config (`APP_NAME`, `LOG_LEVEL`) injected as env vars |
| `k8s/deployment.yaml` | Deployment | Runs 2 replicas of the app image, with probes + limits |
| `k8s/service.yaml` | Service | Stable ClusterIP that load-balances across the pods |
| `scripts/setup-cluster.sh` | script | create cluster → build → load image → apply → wait |
| `scripts/teardown.sh` | script | delete the cluster |

**Verified end-to-end:** 2 pods `Running` (1/1 ready), API reachable through the Service via port-forward (health 200, full CRUD), clean setup → deploy → teardown.

---

## 2. The mental model: how the pieces connect

```
Docker image (k8s-qa-demo:local)   <- built in Phase 1
        |
   kind load docker-image          <- copy image into the cluster's node
        |
   Deployment  --> ReplicaSet --> 2 Pods (each runs the container)
        |                              ^
        | selector: app=qa-demo        | probes hit /health
        v                              |
     Service (ClusterIP :8000) --------+   load-balances to ready pods
        |
   kubectl port-forward             <- tunnel from your laptop to the Service
        |
   http://127.0.0.1:8000
```

Key ideas:
- **Kubernetes runs container images, not source.** Phase 1's Dockerfile is what makes this phase possible.
- **You declare desired state; K8s reconciles.** You don't start pods — you tell the Deployment "I want 2 replicas of this image" and the controller makes it so (and keeps it so — that's what Phase 3's resilience tests exploit).
- **Labels + selectors are the glue.** The Service finds its pods by matching `app: qa-demo`, not by name or IP.

---

## 3. How to run it locally

Prerequisites: Docker running, `kind` and `kubectl` installed.

```bash
# from repo root
bash scripts/setup-cluster.sh          # create + deploy everything

# reach the API (leave this running in its own terminal)
kubectl port-forward svc/qa-demo 8000:8000 -n qa-demo
# then, in another terminal:
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/api/testcases \
  -H "Content-Type: application/json" -d '{"title":"hi","status":"pass"}'

# inspect
kubectl get pods -n qa-demo -o wide
kubectl describe deployment qa-demo -n qa-demo
kubectl logs -n qa-demo -l app=qa-demo   # logs from all matching pods

# tear it all down
bash scripts/teardown.sh
```

---

## 4. Walkthrough: the manifests

Every manifest shares four top-level keys: `apiVersion` (which API group/version defines this object), `kind` (what type), `metadata` (name, namespace, labels), and `spec` (the desired state).

### namespace.yaml
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: qa-demo
  labels:
    app: qa-demo
```
A namespace is a folder for resources — it scopes names and lets you delete everything at once. All other objects set `namespace: qa-demo` so they live here.

### configmap.yaml
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: qa-demo-config
  namespace: qa-demo
data:
  APP_NAME: k8s-qa-demo
  LOG_LEVEL: info
```
A ConfigMap holds non-secret config as key/value pairs, decoupled from the image. The deployment pulls these in as environment variables (see `envFrom` below). Change config without rebuilding the image. (Secrets go in a `Secret`, not a ConfigMap.)

### deployment.yaml — the core object
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qa-demo
  namespace: qa-demo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: qa-demo          # which pods this Deployment owns
  template:                 # the pod blueprint
    metadata:
      labels:
        app: qa-demo        # MUST match the selector above
    spec:
      containers:
        - name: qa-demo
          image: k8s-qa-demo:local
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8000
          envFrom:
            - configMapRef:
                name: qa-demo-config
          readinessProbe:
            httpGet: { path: /health, port: http }
            initialDelaySeconds: 2
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /health, port: http }
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { cpu: 250m, memory: 128Mi }
          securityContext:
            runAsNonRoot: true
            runAsUser: 10001
            allowPrivilegeEscalation: false
```
Piece by piece:
- **`replicas: 2`** — run two identical pods for availability. If one dies, the ReplicaSet recreates it.
- **`selector.matchLabels` vs `template.metadata.labels`** — the selector says "these are my pods"; the template stamps that same label onto every pod it creates. **They must match**, or the Deployment can't find its own pods. This trips people up constantly.
- **`imagePullPolicy: IfNotPresent`** — critical for Kind. Our image only exists locally (loaded with `kind load`), never pushed to a registry. The default `Always` would make K8s try to *pull* it and fail with `ErrImagePull`. `IfNotPresent` says "use the local copy if it's there."
- **`ports.name: http`** — naming the port lets the probes and the Service refer to it by name (`port: http`) instead of repeating `8000`.
- **`envFrom.configMapRef`** — injects every key in the ConfigMap as an env var. So the container sees `APP_NAME` and `LOG_LEVEL`.
- **Readiness vs liveness probe** — both hit `/health`, but they answer different questions:
  - *Readiness*: "should this pod receive traffic yet?" A failing readiness probe removes the pod from the Service's rotation but doesn't restart it.
  - *Liveness*: "is this pod wedged and needs a restart?" A failing liveness probe kills and restarts the container.
  - This is why Phase 1's trivial `/health` endpoint matters — it's the signal K8s uses for both.
- **`resources.requests` vs `limits`** — requests are what the scheduler reserves (used to place the pod); limits are the hard ceiling (exceed memory → OOM-killed; exceed CPU → throttled).
- **`securityContext`** — enforces non-root at the cluster level. `runAsUser: 10001` matches the numeric UID baked into the Dockerfile (see gotcha #3).

### service.yaml
```yaml
apiVersion: v1
kind: Service
metadata:
  name: qa-demo
  namespace: qa-demo
spec:
  type: ClusterIP
  selector:
    app: qa-demo
  ports:
    - name: http
      port: 8000
      targetPort: http
```
- **A Service is a stable address in front of ephemeral pods.** Pods come and go with changing IPs; the Service's ClusterIP stays constant and load-balances across whichever pods currently match its `selector`.
- **`type: ClusterIP`** — reachable only from inside the cluster. That's why we need `port-forward` to hit it from the laptop. (Other types: `NodePort`, `LoadBalancer` — not needed for a local demo.)
- **`targetPort: http`** — forwards to the container's named `http` port (8000). `port` is what the Service listens on; `targetPort` is where it sends traffic.

---

## 5. Walkthrough: the scripts

### setup-cluster.sh
```bash
set -euo pipefail
```
Fail fast and loud: `-e` exit on any error, `-u` error on unset variables, `-o pipefail` a pipeline fails if any stage fails. Standard hardening for a script that chains many commands.

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
```
Resolves paths relative to the script itself, so it works no matter what directory you run it from.

```bash
if kind get clusters | grep -qx "$CLUSTER"; then
  echo "    cluster already exists, reusing it"
else
  kind create cluster --name "$CLUSTER" --image "$NODE_IMAGE" --wait 120s
fi
```
**Idempotent** — re-running doesn't recreate the cluster. `grep -qx` matches the whole line exactly (so `qa-demo` doesn't accidentally match `qa-demo-2`). `--wait 120s` blocks until the control plane is Ready. `--image` pins the node version (gotcha #1).

```bash
docker build -t "$IMAGE" "$ROOT_DIR/app"
kind load docker-image "$IMAGE" --name "$CLUSTER"
```
Build the image on the host, then **copy it into the Kind node**. Without `kind load`, the node has no idea the image exists (it's not on any registry).

```bash
kubectl apply -f "$ROOT_DIR/k8s/namespace.yaml"
kubectl apply -f "$ROOT_DIR/k8s/"
```
Namespace first, then the whole directory (gotcha #2). `kubectl apply` is declarative — run it repeatedly and it converges to the desired state (`created` the first time, `unchanged` after).

```bash
kubectl rollout status deployment/qa-demo -n "$NAMESPACE" --timeout=90s
```
Blocks until all replicas are updated and available — turns "I applied it" into "it's actually running."

### teardown.sh
Mirror image: check the cluster exists, then `kind delete cluster`. Also safe to run when there's nothing to delete.

---

## 6. Gotchas we hit (the valuable part)

These three cost real debugging time and are the reason the manifests/scripts look the way they do. All are recorded in `CLAUDE.md` too.

### Gotcha 1 — Kind + cgroup v1 (the big one)
**Symptom:** `kind create cluster` failed at `wait-control-plane` with `dial tcp ...:6443: connect: connection refused`. Retrying didn't help.

**Diagnosis:** created the cluster with `--retain` (keeps the failed node container), then looked inside:
```bash
docker exec qa-demo-control-plane journalctl -u kubelet | grep -i error
# -> "kubelet is configured to not run on a host using cgroup v1"
docker exec qa-demo-control-plane stat -fc %T /sys/fs/cgroup   # tmpfs = v1
docker info | grep Cgroup                                       # Cgroup Version: 1
```
The kubelet crash-looped on cgroup v1 → static pods (etcd, apiserver) never started → API server unreachable → bootstrap failed.

**Root cause:** Docker Desktop on this WSL2 host exposes **cgroup v1**, but Kind v0.32's default node image (K8s 1.34) ships a kubelet that **refuses** cgroup v1.

**Fix:** pin an older node image whose kubelet tolerates cgroup v1:
```bash
--image kindest/node:v1.29.14@sha256:8703bd94...
```
**Lesson:** "connection refused at bootstrap" is almost never transient — get *inside* the node (`--retain` + `journalctl -u kubelet`) rather than blindly retrying. And check `docker info | grep Cgroup` before trusting a fresh Kind setup.

### Gotcha 2 — `kubectl apply -f dir/` is alphabetical
**Symptom:** `namespaces "qa-demo" not found` for configmap and deployment, but the service applied fine.

**Root cause:** `kubectl apply -f k8s/` processes files **alphabetically**: `configmap`, `deployment`, `namespace`, `service`. So configmap/deployment tried to create themselves in a namespace that didn't exist yet; service (alphabetically after namespace) got lucky.

**Fix:** apply `namespace.yaml` explicitly first, then the directory. (Alternatives: put everything in one file with the namespace first, or use a tool like Kustomize that orders by kind.)

### Gotcha 3 — `runAsNonRoot` needs a *numeric* UID
**Symptom:** would have been `container has runAsNonRoot and image has non-numeric user (appuser), cannot verify user is non-root`.

**Root cause:** the Dockerfile used `USER appuser` (a name). The kubelet can't read the image's `/etc/passwd` at admission time, so it can't prove a *named* user is non-root, and refuses to start the pod.

**Fix:** bake a numeric UID into the image and reference it in the manifest:
```dockerfile
RUN useradd --create-home --uid 10001 appuser
USER 10001
```
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
```
Caught this before deploying by reasoning about the security context — cheaper than a failed rollout.

---

## 7. Takeaways

- **Declarative, not imperative** — you describe desired state; controllers reconcile. This is the whole K8s mindset.
- **Labels/selectors wire objects together** — Service→Pods and Deployment→Pods both work by label matching, not names.
- **Local images need `kind load` + `imagePullPolicy: IfNotPresent`** — otherwise K8s tries to pull from a registry and fails.
- **Probes give K8s its signals** — readiness gates traffic, liveness triggers restarts; both lean on the humble `/health` endpoint.
- **Debug into the node, don't retry blindly** — `--retain` + `journalctl`/`crictl` turned a cryptic "connection refused" into a one-line root cause.
- **Scripts should be idempotent and path-independent** — safe to re-run, runnable from anywhere.
