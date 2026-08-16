#!/usr/bin/env bash
# Create the Kind cluster (if needed), build + load the app image, deploy the
# Helm chart, and wait for the deployment to be ready. Idempotent — safe to
# re-run.
set -euo pipefail

CLUSTER=qa-demo
IMAGE=k8s-qa-demo:local
NAMESPACE=qa-demo
RELEASE=qa-demo
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

echo "==> Deploying Helm chart"
# --create-namespace lets Helm own the namespace (charts shouldn't template a
# Namespace object). --wait blocks until the Deployment's pods are Ready, so it
# subsumes the old `kubectl rollout status`. Image repo/tag come from $IMAGE so
# it stays the single source of truth for build, load, and deploy.
helm upgrade --install "$RELEASE" "$ROOT_DIR/charts/qa-demo" \
  --namespace "$NAMESPACE" --create-namespace \
  --set image.repository="${IMAGE%%:*}" \
  --set image.tag="${IMAGE##*:}" \
  --wait --timeout 120s

echo "==> Pods:"
kubectl get pods -n "$NAMESPACE" -o wide

cat <<EOF

Done. To reach the API:
  kubectl port-forward svc/qa-demo 8000:8000 -n $NAMESPACE
then hit http://127.0.0.1:8000/health
EOF
