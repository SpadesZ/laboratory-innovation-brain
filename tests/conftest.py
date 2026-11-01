"""Shared test configuration.

AGT-007: the suite must be verifiable with no PostgreSQL, no Lumerical seat and no
outbound network. Tests needing any of those carry a marker and are deselected unless
the corresponding opt-in environment variable is set, so a bare `pytest` is always green
or genuinely broken -- never "green because it skipped the real checks" without saying so.
"""

from __future__ import annotations

import os

import pytest

from lab_brain.llm_runtime import spend
from tests.free_test_endpoints import TestEndpointsFree

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


@pytest.fixture(autouse=True)
def _postgres_tests_treat_their_test_servers_as_free(
    request: pytest.FixtureRequest,
) -> object:
    """Since 011v a request to this machine is metered like any other, and the research flows the
    PostgreSQL tests drive (qualify a model, lock it, run an episode) talk to throwaway model
    servers on 127.0.0.1. Those servers are the tests' own, not proxies to anything, so for a
    `postgres` test they stand in as declared free (`tests/free_test_endpoints.py`) -- the role the
    Owner's declaration plays in a deployment. A test of the spend ceiling itself is marked
    `real_spend_guard` and sees exactly what a deployment sees; nothing in `src/` can declare free.
    """
    if (
        request.node.get_closest_marker("postgres") is None
        or request.node.get_closest_marker("real_spend_guard") is not None
    ):
        yield None
        return
    with spend.installed(TestEndpointsFree()):
        yield None
