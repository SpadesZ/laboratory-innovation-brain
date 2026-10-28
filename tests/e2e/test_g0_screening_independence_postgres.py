"""Screening independence: can content-identical evidence pass as a second, independent reading?

`012y`'s guard refuses SUPPORTS to a hypothesis proposed after screening when the supporting
observation is (a) the screened one, (b) older than the hypothesis, or (c) a deterministic repeat
-- "same capability, backend, inputs and parameters". This file asks whether the same bytes can
reach SUPPORTS through another identity, and separates what is demonstrated from what is not:

    artifact id     NOT A DEFECT. `artifact_id = 'art:' || content_hash` is a CHECK and the hash
                    is UNIQUE (002), so content-identical inputs cannot carry two ids.
    backend id      DEMONSTRATED on 012y: the same reading of the same input with the same
                    parameters, recorded under another backend id, passed (c).
    parameters      DEMONSTRATED on 012y: an inert parameter (`{"variant": ...}`) made a run whose
                    output is byte-for-byte the screened output pass (c). The deterministic readers
                    write no parameter into their output, so the bytes do not change.
    output bytes    DEMONSTRATED on 012y: any run that emits the screened run's output artifact --
                    the same content, hence the same content-addressed id -- passed, whatever its
                    capability.

`011m` closes all three: (c) no longer requires the same backend, and (d) refuses a supporting
observation whose run shares an output artifact with a run the hypothesis was conditioned on.
The control is kept: a later reading with genuinely different output content may still SUPPORT.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from lab_brain.core.models.job import Job, JobState
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.domains.silicon_photonics import vertical as sp
from tests.e2e.test_g0_exploratory_screening_postgres import (
    SCREENING,
    device,
    research,
    rows,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup
from tests.fake_llm_provider import FakeProvider
from tests.g0_standin import StandIn

pytestmark = pytest.mark.postgres


@pytest.fixture
def standin() -> Iterator[tuple[FakeProvider, StandIn]]:
    model = StandIn()
    provider = FakeProvider(api_key=KEY, rewrite=model.rewrite).start()
    yield provider, model
    provider.stop()


class Guarded:
    """One screened, conditioned hypothesis, and the means to offer it SUPPORT from a new run."""

    def __init__(self, db: Any, episode: str) -> None:
        self.db = db
        self.episode = episode
        ((self.hypothesis, conditioned_on),) = rows(
            db,
            "SELECT hypothesis_id, screening_observation_ids FROM screening_conditioned_hypotheses"
            " WHERE episode_id = %s",
            episode,
        )
        ((run_id, observation_ids),) = rows(
            db,
            "SELECT run_id, observation_ids FROM screening_observations"
            " WHERE screening_observation_id = %s",
            conditioned_on[0],
        )
        ((self.attestation,),) = rows(
            db,
            "SELECT attestation_id FROM attestations WHERE observation_id = %s",
            observation_ids[0],
        )
        self.jobs = SqlJobStore(db)
        screened = self.jobs.get_run(run_id)
        assert screened is not None
        self.screened = screened
        self.later = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)

    def fresh_output(self, name: str) -> str:
        """A new artifact with genuinely different content, otherwise like the screened output."""
        (source,) = self.screened.output_artifacts
        with self.db.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("SELECT * FROM artifacts WHERE artifact_id = %s", (source,))
            row = cur.fetchone()
        assert row is not None
        digest = "sha256:" + hashlib.sha256(f"independent reading {name}".encode()).hexdigest()
        row.update(
            artifact_id=f"art:{digest}",
            content_hash=digest,
            uri=f"{row['uri']}#{name}",
            lineage_id=f"{row['lineage_id']}-{name}",
            previous_artifact_id=None,
        )
        row.pop("created_at", None)
        values = [Jsonb(v) if isinstance(v, dict) else v for v in row.values()]
        self.db.execute(
            f"INSERT INTO artifacts ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
            values,
        )
        return str(row["artifact_id"])

    def run(self, name: str, **changes: Any) -> str:
        job = self.jobs.submit(
            Job(
                job_id=f"job:ind-{name}",
                project_id=PROJECT,
                episode_id=self.episode,
                capability_id=changes.pop("capability_id", self.screened.capability_id),
                trace_id=self.screened.trace_id,
                idempotency_key=f"ind:{name}",
                submitted_at=self.later,
            )
        )
        self.jobs.transition(job.job_id, JobState.RUNNING, self.later)
        run = self.jobs.complete(
            job.job_id,
            job.idempotency_key,
            self.screened.model_copy(
                update={
                    "run_id": f"run:ind-{name}",
                    "job_id": job.job_id,
                    "capability_id": job.capability_id,
                    "start_time": self.later,
                    "end_time": self.later,
                    **changes,
                }
            ),
        )
        return run.run_id

    def observe(self, run: str, name: str) -> str:
        observation = f"obs:ind-{name}"
        self.db.execute(
            "INSERT INTO observations (observation_id, run_id, metric_or_event, value_text,"
            " conditions, conditions_schema_version, method_ref, project_id, created_at)"
            " VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)",
            (
                observation,
                run,
                sp.OBS_CONNECTIVITY,
                "DISCONTINUOUS",
                json.dumps(dict(self.screened.conditions)),
                self.screened.conditions_schema_version,
                "sp.rule.contact_connectivity@1.0.0",
                PROJECT,
                self.later,
            ),
        )
        return observation

    def attest(self, observation: str, run: str) -> str:
        """An attestation of `observation`, otherwise like the screened reading's."""
        with self.db.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute("SELECT * FROM attestations WHERE attestation_id = %s", (self.attestation,))
            row = cur.fetchone()
        assert row is not None
        row.update(attestation_id=f"att:{observation}", observation_id=observation, run_id=run)
        row.pop("created_at", None)
        self.db.execute(
            f"INSERT INTO attestations ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
            [Jsonb(v) if isinstance(v, dict | list) else v for v in row.values()],
        )
        return f"att:{observation}"

    def support(self, observation: str, cites: list[str] | None = None) -> None:
        """SUPPORTS from `observation`, citing `cites` (default: the screened attestation, which
        is how a repeat would cite the reading it repeats)."""
        self.db.execute(
            "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
            " relation_type, supporting_attestation_ids, project_id)"
            " VALUES (%s, %s, %s, 'SUPPORTS', %s, %s)",
            (
                f"rel:{observation}",
                observation,
                self.hypothesis,
                cites if cites is not None else [self.attestation],
                PROJECT,
            ),
        )


@pytest.fixture
def guarded(db: Any, tmp_path: Any, standin: Any) -> Guarded:
    fake, _model = standin
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60, research_features=SCREENING)
    _activated(db, browser, fake)
    return Guarded(db, research(browser, device("contact-open-via")))


def _refused(g: Guarded, observation: str, why: str, cites: list[str] | None = None) -> None:
    with (
        pytest.raises(psycopg.errors.RaiseException, match=why),
        g.db.transaction(force_rollback=True),
    ):
        g.support(observation, cites)


def test_content_identical_input_cannot_carry_a_second_artifact_id(guarded):
    """Not a defect: the content hash IS the identity, so the input-id path has no gap."""
    g = guarded
    (source,) = g.screened.input_artifacts
    with g.db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("SELECT * FROM artifacts WHERE artifact_id = %s", (source,))
        row = cur.fetchone()
    assert row is not None
    row.update(artifact_id="art:another-name", uri=f"{row['uri']}#again")
    row.pop("created_at", None)
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        g.db.transaction(force_rollback=True),
    ):
        g.db.execute(
            f"INSERT INTO artifacts ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
            [Jsonb(v) if isinstance(v, dict) else v for v in row.values()],
        )


SAME_BYTES: dict[str, Callable[[Guarded], dict[str, Any]]] = {
    # The same reader's reading under another backend label.
    "relabelled_backend": lambda g: {"backend_id": "sp.local.contact_connectivity_reader.v2"},
    # An inert parameter: the reader writes no parameter into its output.
    "inert_parameter": lambda g: {"input_parameters": {"variant": "independent reading"}},
    # Another capability emitting the very same output bytes.
    "other_capability_same_output": lambda g: {
        "capability_id": sp.CAP_EXTRACTION_CONSISTENCY,
        "backend_id": "sp.local.normalization_basis_reader",
    },
    # Every identity changed at once; only the output content is the screened one.
    "everything_but_the_bytes": lambda g: {
        "backend_id": "elsewhere.reader",
        "input_parameters": {"seed": 7},
        "code_provenance": "elsewhere.reader@9.9.9",
        "reproducibility_manifest_hash": "sha256:" + "0" * 64,
    },
}


@pytest.mark.parametrize("name", sorted(SAME_BYTES))
def test_the_screened_bytes_cannot_support_under_another_identity(guarded, name):
    g = guarded
    with g.db.transaction(force_rollback=True):
        observation = g.observe(g.run(name, **SAME_BYTES[name](g)), name)
        _refused(g, observation, "repeats the screened reading|same output content")


def test_a_later_reading_with_genuinely_different_content_may_still_support(guarded):
    """The control: the guard refuses repeats, it does not freeze the hypothesis."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        run = g.run(
            "independent",
            input_parameters={"variant": "independent reading"},
            output_artifacts=(g.fresh_output("independent"),),
        )
        observation = g.observe(run, "independent")
        # It cites its OWN attestation: the evidence is the new reading, not the screened one.
        g.support(observation, [g.attest(observation, run)])
        assert rows(
            g.db,
            "SELECT 1 FROM relation_judgments WHERE to_entity_id = %s AND relation_type = 'SUPPORTS'",
            g.hypothesis,
        )


def test_a_relabelled_backend_with_fresh_bytes_is_still_a_repeat(guarded):
    """(c) without the backend: same capability, inputs and parameters is the same check."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        run = g.run(
            "relabelled-fresh",
            backend_id="sp.local.contact_connectivity_reader.v2",
            output_artifacts=(g.fresh_output("relabelled"),),
        )
        _refused(g, g.observe(run, "relabelled-fresh"), "repeats the screened reading")


# -- the basis a relation CITES, not only the entity it comes from -------------------------------
#
# DEMONSTRATED on 011m (before 011o): the guard judged only `from_entity_id`. A SUPPORTS relation
# whose source was not an observation was not checked at all, and the attestations a relation
# cites -- its actual evidence -- were never read.


def _fresh(g: Guarded, name: str) -> tuple[str, str]:
    run = g.run(
        name,
        input_parameters={"variant": name},
        output_artifacts=(g.fresh_output(name),),
    )
    return run, g.observe(run, name)


def test_the_screened_attestation_cannot_be_the_source(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _refused(g, g.attestation, "only an observation can SUPPORT|screened")


def test_a_fresh_observation_cannot_cite_the_screened_attestation(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _run, observation = _fresh(g, "cites-screened")
        _refused(g, observation, "cites", cites=[g.attestation])


def test_a_fresh_observation_cannot_borrow_a_repeat_as_its_evidence(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        _run, observation = _fresh(g, "fresh-source")
        repeat = g.run("borrowed-repeat")  # the screened reading again, same everything
        borrowed = g.observe(repeat, "borrowed-repeat")
        _refused(g, observation, "cites", cites=[g.attest(borrowed, repeat)])


def test_a_non_observation_source_is_refused(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        run, observation = _fresh(g, "behind-a-hypothesis")
        evidence = g.attest(observation, run)
        ((other,),) = rows(
            g.db,
            "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s"
            " AND hypothesis_id <> %s ORDER BY hypothesis_id LIMIT 1",
            g.episode,
            g.hypothesis,
        )
        _refused(g, other, "only an observation can SUPPORT", cites=[evidence])


def test_a_fresh_observation_cannot_cite_a_claim_attestation(guarded):
    """A reported claim (here, from the ingested measurement report) predates the hypothesis and is
    not a check: citing it as the evidence for a post-screening hypothesis is refused (011o)."""
    g = guarded
    claims = rows(
        g.db,
        "SELECT attestation_id FROM attestations WHERE project_id = %s AND claim_id IS NOT NULL"
        " ORDER BY attestation_id LIMIT 1",
        PROJECT,
    )
    assert claims, "the research run ingested a report: its claims are attested"
    ((claim_attestation,),) = claims
    with g.db.transaction(force_rollback=True):
        run, observation = _fresh(g, "cites-a-claim")
        _refused(
            g,
            observation,
            "attests no observation",
            cites=[g.attest(observation, run), claim_attestation],
        )
