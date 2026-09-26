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
    # M1-P1 / EVI-010. Child first: a representation references a unit, and the unit references
    # the artifact. The reverse order would rely on the CASCADE, which is exactly the coupling
    # ADR-0011 keeps out of this direction.
    "retrieval_representations",
    "evidence_units",
    # M3 (`005e`, `011i`, `002b`, `010c`). Child first, and all append-only, so TRUNCATE is the
    # only way to clear them. `predictions` and the debate objects reference `hypotheses`, which
    # references `hypothesis_sets` and `inference_provenance`; the novelty status references the
    # search. Outcome spaces and benchmark policies are not project-scoped, so nothing cascades
    # them away -- a threshold left behind would arm the next test's gate.
    "novelty_assessments",
    "prior_art_search_records",
    "debate_records",
    "critique_reports",
    "positions",
    "predictions",
    "hypotheses",
    "hypothesis_sets",
    "benchmark_policies",
    "outcome_spaces",
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
    # M1-P2 / OPS-001. Both named, and named together: `jobs.result_run_id` references `runs`
    # while the `runs_job_must_exist` trigger checks the other direction, so neither can be
    # cleared alone. One TRUNCATE over both is the only order that works.
    # M1 final. Ordered child-first where a plain CASCADE would fire an append-only trigger:
    # `inference_provenance` refuses DELETE, and TRUNCATE does not fire row-level triggers, so
    # naming it explicitly is both correct and the only safe way to clear it.
    "ingestion_stage_results",
    "technical_details",
    "error_records",
    "ingestion_items",
    "inference_provenance",
    # M2 / §10.7 (`007c`). Named BEFORE `jobs`, because `resource_leases.job_id` is a foreign key
    # into it: a lease left behind by one test would hold a seat in the next one, and the symptom
    # -- every simulation parking in WAITING_RESOURCE -- reads exactly like a busy licence server.
    "resource_leases",
    "resource_pools",
    "jobs",
    "runs",
    "research_episodes",
    "cost_entries",
    "budget_approvals",
    "budget_policies",
    # M2 / VER-002 (`007c`). Not project-scoped, so nothing cascades it away -- a descriptor left
    # behind would make the next test's `upsert` a contract-change refusal.
    "capabilities",
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


def admit_hypothesis_identity(
    connection,  # type: ignore[no-untyped-def]
    hypothesis_id: str,
    *,
    project_id: str = "prj:test",
    actor_id: str = "act:test",
) -> None:
    """Give a pre-M3 fixture's hypothesis the identity `011j` requires (M3 / R-12).

    Since `011j` a belief event must name a hypothesis admitted through §8's gate in its own
    project. The M0b–M2 suites predate that gate and wrote events for hypothesis ids nothing had
    admitted; this establishes the identity they always meant, rather than loosening the key: a
    human-authored §8 certificate -- mechanism, falsifier, assumptions, confounders, minimal test and
    one typed Prediction -- in a ROUTINE set (not root-cause, below its policy's inverted-retrieval
    threshold). Routine because those suites test M0b–M2 semantics, which M3's debate rules leave
    unchanged for a routine set (`011j`'s header). Called before the fixture's genesis event;
    idempotent, and a no-op once the hypothesis exists.
    """
    exists = connection.execute(
        "SELECT 1 FROM hypotheses WHERE project_id = %s AND hypothesis_id = %s",
        (project_id, hypothesis_id),
    ).fetchone()
    if exists:
        return
    episode = f"epi:identity:{project_id}"
    hypothesis_set = f"hst:identity:{project_id}"
    connection.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, start_time)"
        " VALUES (%s, %s, 'trc:identity', 'pre-M3 fixture hypotheses', '2026-09-01T00:00:00Z')"
        " ON CONFLICT DO NOTHING",
        (episode, project_id),
    )
    connection.execute(
        "INSERT INTO outcome_spaces (outcome_space_id, version, domain, action_type, outcomes)"
        " VALUES ('os:test.identity', '1.0.0', 'core', 'MEASUREMENT',"
        " ARRAY['OBSERVED', 'NOT_OBSERVED']) ON CONFLICT DO NOTHING"
    )
    connection.execute(
        "INSERT INTO hypothesis_sets (set_id, project_id, episode_id, question, research_intent,"
        " stakes, root_cause, source_policy_id, source_policy_version,"
        " inverted_retrieval_required, created_at)"
        " VALUES (%s, %s, %s, 'pre-M3 fixture hypotheses', 'DIAGNOSIS', 'NORMAL', FALSE,"
        " 'srcpol:diagnosis', '1.0.0', FALSE, '2026-09-01T00:00:00Z') ON CONFLICT DO NOTHING",
        (hypothesis_set, project_id, episode),
    )
    connection.execute(
        "INSERT INTO hypotheses (hypothesis_id, project_id, hypothesis_set_id, statement,"
        " mechanism, assumptions, falsifier, confounders, minimal_test_ref, created_in_episode,"
        " authored_by_actor_id, created_at)"
        " VALUES (%s, %s, %s, %s, %s, ARRAY['the fixture conditions hold'],"
        " 'the predicted observation is absent', ARRAY['measurement drift'], 'test:fixture',"
        " %s, %s, '2026-09-01T00:00:00Z')",
        (
            hypothesis_id,
            project_id,
            hypothesis_set,
            f"{hypothesis_id} holds",
            f"the mechanism {hypothesis_id} names",
            episode,
            actor_id,
        ),
    )
    connection.execute(
        "INSERT INTO predictions (prediction_id, project_id, hypothesis_id, observable_ref,"
        " outcome_space_id, outcome_space_version, expected_outcome,"
        " relation_effect_if_observed, created_at)"
        " VALUES (%s, %s, %s, 'test.observable', 'os:test.identity', '1.0.0', 'OBSERVED',"
        " %s::jsonb, '2026-09-01T00:00:00Z')",
        (
            f"prd:identity:{project_id}:{hypothesis_id}",
            project_id,
            hypothesis_id,
            f'[{{"relation_type": "SUPPORTS", "to_entity_id": "{hypothesis_id}"}}]',
        ),
    )


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
