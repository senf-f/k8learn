# Archived: raw Kubernetes manifests (Phase 2)

These are the original hand-written manifests from **Phase 2**, kept here as a
learning and showcase reference. They are **no longer used to deploy** — Phase 7
replaced them with the Helm chart in [`charts/qa-demo/`](../../charts/qa-demo).

| File | Kind |
|------|------|
| `namespace.yaml` | Namespace `qa-demo` |
| `configmap.yaml` | ConfigMap `qa-demo-config` (`APP_NAME`, `LOG_LEVEL`) |
| `deployment.yaml` | Deployment `qa-demo` (2 replicas, probes, limits, non-root) |
| `service.yaml` | Service `qa-demo` (ClusterIP :8000) |

## Why keep them?

This is a portfolio project built phase by phase; each phase is a learning
artifact. These manifests show the *explicit* form of every object — exactly
what the Helm templates render to. Reading the chart's
`helm template charts/qa-demo` output next to these files is a good way to see
what templating adds (and what it hides).

`PHASE2_LESSONS.md` walks through each manifest in detail.

## What changed in Phase 7

- The four objects became templates under `charts/qa-demo/templates/`, with
  their hardcoded values lifted into `charts/qa-demo/values.yaml`.
- `namespace.yaml` has **no chart equivalent** — Helm creates the namespace via
  `helm install --create-namespace` instead (templating a Namespace inside a
  chart is discouraged).
- Resource names (`qa-demo`, `qa-demo-config`) and the `app: qa-demo` selector
  label are unchanged, so the test suite runs identically against either.

To deploy the archived manifests manually (not the normal path):

```bash
kubectl apply -f archive/k8s-raw-manifests/namespace.yaml
kubectl apply -f archive/k8s-raw-manifests/
```
