#!/usr/bin/env bash
# Delete the Kind cluster. Safe to run even if the cluster doesn't exist.
set -euo pipefail

CLUSTER=qa-demo

if kind get clusters | grep -qx "$CLUSTER"; then
  echo "==> Deleting Kind cluster '$CLUSTER'"
  kind delete cluster --name "$CLUSTER"
else
  echo "==> Cluster '$CLUSTER' not found, nothing to do"
fi
