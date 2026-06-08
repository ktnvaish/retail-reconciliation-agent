"""Smoke tests confirming the package is importable and wired up.

These are intentionally trivial; richer tests arrive with each feature phase.
"""

from __future__ import annotations

import pytest

import reconcile


@pytest.mark.unit
def test_package_exposes_version() -> None:
    assert isinstance(reconcile.__version__, str)
    assert reconcile.__version__.count(".") >= 2
