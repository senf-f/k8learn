"""Resilience tests: prove Kubernetes keeps the app healthy under disruption.

Unlike the health/CRUD tests (which exercise the app), these exercise the
*cluster's* self-healing: the Deployment controller recreates deleted pods,
the Service keeps serving from surviving replicas, and scaling recovers.

They MUTATE the cluster (delete pods, scale the Deployment), so each test
restores the deployment to 2 ready replicas before it finishes.
"""

import httpx
import pytest

from conftest import ready_replicas, running_pods, wait_until

NAMESPACE = "qa-demo"
DEPLOYMENT = "qa-demo"

pytestmark = pytest.mark.integration


def _scale(kube_apps, replicas):
    kube_apps.patch_namespaced_deployment(
        DEPLOYMENT, NAMESPACE, {"spec": {"replicas": replicas}}
    )


def test_deleted_pod_is_recreated(kube_core, kube_apps):
    """Delete one pod; the ReplicaSet should replace it and return to 2 ready."""
    pods = running_pods(kube_core)
    assert len(pods) >= 2, "need 2 running pods to start"
    victim = pods[0].metadata.name

    kube_core.delete_namespaced_pod(victim, NAMESPACE)

    def replaced():
        names = {p.metadata.name for p in running_pods(kube_core)}
        return len(names) >= 2 and victim not in names

    wait_until(replaced, timeout=90, message="deleted pod to be replaced by a new one")
    wait_until(lambda: ready_replicas(kube_apps) >= 2, timeout=90,
               message="2 ready replicas after recreation")


def test_service_stays_available_during_pod_deletion(kube_core, kube_apps, make_port_forward):
    """Kill one replica; the Service should keep serving from the other.

    A fresh port-forward resolves the Service to a *ready* endpoint, so it
    attaches to the surviving pod while the victim terminates.
    """
    pods = running_pods(kube_core)
    assert len(pods) >= 2, "need 2 running pods to start"
    victim = pods[0].metadata.name

    kube_core.delete_namespaced_pod(victim, NAMESPACE)

    # .start() polls /health until 200 — reaching here proves the service
    # answered during the disruption. Hit it a few more times to be sure.
    pf = make_port_forward()
    for _ in range(5):
        assert httpx.get(f"{pf.url}/health", timeout=5.0).status_code == 200

    # Restore before leaving so later tests see a healthy deployment.
    wait_until(lambda: ready_replicas(kube_apps) >= 2, timeout=90,
               message="2 ready replicas after disruption")


def test_scale_to_zero_then_recover(kube_core, kube_apps, make_port_forward):
    """Scale to 0 (service goes dark), then back to 2 (service recovers)."""
    _scale(kube_apps, 0)
    wait_until(lambda: ready_replicas(kube_apps) == 0, timeout=90,
               message="0 ready replicas after scaling down")
    wait_until(lambda: len(running_pods(kube_core)) == 0, timeout=90,
               message="no running pods after scaling down")

    _scale(kube_apps, 2)
    wait_until(lambda: ready_replicas(kube_apps) >= 2, timeout=90,
               message="2 ready replicas after scaling back up")

    pf = make_port_forward()
    assert httpx.get(f"{pf.url}/health", timeout=5.0).status_code == 200
