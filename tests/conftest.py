"""Fixtures for Phase 3 integration tests against the app deployed in Kind.

These tests need a running cluster with the app deployed (see
`scripts/setup-cluster.sh`). If the cluster or its kube context isn't
reachable, the fixtures skip — so the Phase 1 unit tests in `test_app.py`
still run without a cluster.
"""

import subprocess
import time

import httpx
import pytest

NAMESPACE = "qa-demo"
DEPLOYMENT = "qa-demo"
SERVICE = "qa-demo"
APP_PORT = 8000
LOCAL_PORT = 18080
KUBE_CONTEXT = "kind-qa-demo"


def wait_until(predicate, timeout=60.0, interval=1.0, message="condition"):
    """Poll predicate() until truthy or timeout; return its last value."""
    deadline = time.monotonic() + timeout
    value = None
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(f"Timed out after {timeout}s waiting for: {message}")


class PortForward:
    """Manage a `kubectl port-forward` to the Service as a subprocess.

    Terminating a Python subprocess is reliable on Windows/Git Bash, unlike
    backgrounding with `&` then `kill` (see project CLAUDE.md gotcha).
    """

    def __init__(self, local_port=LOCAL_PORT):
        self.local_port = local_port
        self.url = f"http://127.0.0.1:{local_port}"
        self._proc = None

    def start(self, ready_timeout=20.0):
        self._proc = subprocess.Popen(
            [
                "kubectl", "port-forward",
                f"svc/{SERVICE}", f"{self.local_port}:{APP_PORT}",
                "-n", NAMESPACE, "--address", "127.0.0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # Wait until the tunnel actually serves /health.
        try:
            wait_until(
                self._health_ok,
                timeout=ready_timeout,
                interval=0.5,
                message="port-forward to serve /health",
            )
        except TimeoutError:
            self.stop()
            raise
        return self

    def _health_ok(self):
        if self._proc is not None and self._proc.poll() is not None:
            return False  # port-forward process already exited
        try:
            return httpx.get(f"{self.url}/health", timeout=2.0).status_code == 200
        except httpx.HTTPError:
            return False

    def stop(self):
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


def _load_kube():
    """Load kube config for the kind context, or skip if unavailable."""
    try:
        from kubernetes import client, config
    except ImportError:
        pytest.skip("kubernetes client not installed")
    try:
        config.load_kube_config(context=KUBE_CONTEXT)
    except Exception as exc:  # config missing or context absent
        pytest.skip(f"kube context '{KUBE_CONTEXT}' not available: {exc}")
    return client


@pytest.fixture(scope="session")
def kube_core():
    client = _load_kube()
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def kube_apps():
    client = _load_kube()
    return client.AppsV1Api()


def ready_replicas(apps):
    dep = apps.read_namespaced_deployment(DEPLOYMENT, NAMESPACE)
    return dep.status.ready_replicas or 0


def running_pods(core):
    pods = core.list_namespaced_pod(NAMESPACE, label_selector="app=qa-demo").items
    return [p for p in pods if p.status.phase == "Running" and p.metadata.deletion_timestamp is None]


@pytest.fixture(scope="session")
def app_ready(kube_apps):
    """Ensure the deployment has its 2 replicas ready before hitting it."""
    wait_until(lambda: ready_replicas(kube_apps) >= 2, timeout=90,
               message="2 ready replicas")


@pytest.fixture(scope="session")
def app_url(app_ready):
    """Session-wide port-forward for the health and CRUD tests."""
    pf = PortForward().start()
    try:
        yield pf.url
    finally:
        pf.stop()


@pytest.fixture
def make_port_forward():
    """Factory yielding PortForward instances, cleaned up after the test.

    Resilience tests need their own port-forward: they kill pods, which can
    break a shared session-scoped tunnel.
    """
    created = []

    def _make(local_port=LOCAL_PORT + 1):
        pf = PortForward(local_port=local_port).start()
        created.append(pf)
        return pf

    yield _make
    for pf in created:
        pf.stop()
