"""Shared test configuration.

AGT-007: the suite must be verifiable with no PostgreSQL, no Lumerical seat and no
outbound network. Tests needing any of those carry a marker and are deselected unless
the corresponding opt-in environment variable is set, so a bare `pytest` is always green
or genuinely broken -- never "green because it skipped the real checks" without saying so.
"""

from __future__ import annotations

import os

import pytest

# Re-exported so every suite sees them, not only tests/integration. T-OPS-003 is declared `e2e`
# in §26, and a fixture defined in a sibling conftest is invisible across suites. See
# tests/postgres_fixtures.py for why they moved rather than being duplicated.
from tests.postgres_fixtures import (  # noqa: F401  (fixtures are used by name, not by reference)
    database_url,
    db,
    postgres_connection,
)

#: Records the real outcome of every traceability-marked test. Registered here because the
#: skip logic below is itself a coverage hazard: it turns a backend-gated test into SKIPPED,
#: which a collection-based coverage count would have read as "covered".
pytest_plugins = ("lab_brain.spec.outcome_plugin",)

_ENV_GATES: dict[str, str] = {
    "postgres": "LAB_BRAIN_TEST_POSTGRES",
    "lumerical": "LAB_BRAIN_TEST_LUMERICAL",
    "network": "LAB_BRAIN_TEST_NETWORK",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for marker_name, env_var in _ENV_GATES.items():
        if os.environ.get(env_var):
            continue
        skip = pytest.mark.skip(reason=f"requires {marker_name}; set {env_var}=1 to enable")
        for item in items:
            if marker_name in item.keywords:
                item.add_marker(skip)
