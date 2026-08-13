"""Ensure the repo root is on sys.path so `import app.main` works from pytest."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: test runs against the app deployed in a Kind cluster",
    )
