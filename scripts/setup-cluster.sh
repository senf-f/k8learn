#!/usr/bin/env bash
# Create the Kind cluster (if needed), build + load the app image, apply
# manifests, and wait for the deployment to be ready. Idempotent — safe to
# re-run.
set -euo pipefail

CLUSTER=qa-demo
IMAGE=k8s-qa-demo:local
NAMESPACE=qa-demo
# Pin the node image: newer Kind defaults ship a kubelet that refuses cgroup v1,
# which Docker Desktop on WSL2 still exposes here. K8s 1.29 tolerates cgroup v1.
NODE_IMAGE=kindest/node:v1.29.14@sha256:8703bd94ee24e51b778d5556ae310c6c0fa67d761fae6379c8e0bb480e6fea29

# Resolve paths relative to this script so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Ensuring Kind cluster '$CLUSTER' exists"
if kind get clusters | grep -qx "$CLUSTER"; then
  echo "    cluster already exists, reusing it"
else
  kind create cluster --name "$CLUSTER" --image "$NODE_IMAGE" --wait 120s
fi

echo "==> Building image $IMAGE"
docker build -t "$IMAGE" "$ROOT_DIR/app"

echo "==> Loading image into Kind"
kind load docker-image "$IMAGE" --name "$CLUSTER"

echo "==> Applying manifests"
# Namespace first — `kubectl apply -f dir/` processes files alphabetically, so
# the namespaced resources would otherwise be applied before the namespace exists.
kubectl apply -f "$ROOT_DIR/k8s/namespace.yaml"
kubectl apply -f "$ROOT_DIR/k8s/"

echo "==> Waiting for rollout"
kubectl rollout status deployment/qa-demo -n "$NAMESPACE" --timeout=90s

echo "==> Pods:"
kubectl get pods -n "$NAMESPACE" -o wide

cat <<EOF

Done. To reach the API:
  kubectl port-forward svc/qa-demo 8000:8000 -n $NAMESPACE
then hit http://127.0.0.1:8000/health
EOF
