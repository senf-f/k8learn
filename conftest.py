"""Ensure the repo root is on sys.path so `import app.main` works from pytest."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
