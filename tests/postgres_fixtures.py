"""PostgreSQL fixtures, shared by every suite that needs a database.

These lived in ``tests/integration/conftest.py`` until P6. That was correct while the integration
suite was the only one talking to PostgreSQL; T-OPS-003 is declared ``e2e`` in §26, and a fixture
defined in a sibling conftest is invisible to another suite -- so the choice was to duplicate the
connection handling or to move it up. Duplicated fixtures drift, and two definitions of "a clean
database" is exactly how one suite ends up truncating a table the other relies on.

Imported by ``tests/conftest.py`` rather than defined there, following the reasoning in
``tests/conftest_fixtures.py``: the root conftest stays a short, readable statement of the gating
rules instead of also being a fixture library.

Gated by the ``postgres`` marker, so a bare ``pytest`` never needs a database (AGT-007). The
executed-coverage gate knows the difference: a requirement whose only test is skipped here does not
count toward a DONE milestone, and M0a-M4 declare ``gate_profile: [postgres]`` precisely so they
cannot be signed off without these having run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

DEFAULT_URL = "postgresql://lab_brain:lab_brain@localhost:5433/lab_brain"

#: Truncated between tests. Ordered child-first so foreign keys do not block the cascade.
#:
#: The append-only tables are listed explicitly rather than left to the CASCADE. They are reached
#: by it -- `execution_spans` and `cost_entries` both reference `actors` -- but a fixture that
#: reaches them with `DELETE` instead fires their append-only triggers and fails with a confusing
#: RAISE the moment any row survives from an earlier test. TRUNCATE does not fire row-level DELETE
#: triggers, so naming them here is both correct and the only safe way to clear them.
_TABLES = (
    "belief_revision_event_attestations",
    "belief_revision_event_relations",
    "belief_revision_events",
    "transition_policies",
    "evidence_bundle_members",
    "evidence_bundles",
    "evidence_independence",
    "relation_judgments",
    "attestations",
    "observations",
    "claims",
    "source_work_identifiers",
    "source_works",
    "artifact_occurrences",
    "artifacts",
    "condition_matches",
    "condition_schemas",
    "execution_span_cost_entries",
    "execution_spans",
    "cost_entries",
    "budget_approvals",
    "budget_policies",
    "project_memberships",
    "projects",
    "actors",
)


def database_url() -> str:
    return os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="session")
def postgres_connection() -> Iterator[object]:
    psycopg = pytest.importorskip("psycopg", reason="psycopg is required for postgres tests")
    try:
        connection = psycopg.connect(database_url(), autocommit=True, connect_timeout=5)
    except Exception as exc:
        pytest.skip(f"PostgreSQL unavailable at {database_url()}: {type(exc).__name__}")

    with connection:
        applied = connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'attestations'"
        ).fetchone()
        if not applied or applied[0] == 0:
            pytest.fail(
                "migrations have not been applied to this database. Run: python scripts/migrate.py"
            )
        yield connection


@pytest.fixture
def db(postgres_connection):  # type: ignore[no-untyped-def]
    """A clean database for one test."""
    postgres_connection.execute("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE")
    postgres_connection.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) "
        "VALUES ('act:test', 'HUMAN', 'Test Actor')"
    )
    postgres_connection.execute(
        "INSERT INTO projects (project_id, name) VALUES ('prj:test', 'Test Project')"
    )
    return postgres_connection
