"""The CI workflow must actually arm the gates it claims to run.

The executed-coverage ratchet is the last link in the chain: it is what stops a DONE milestone from
resting on tests that never ran. A workflow edit can disarm it without touching a single line of
harness code, and nothing else in this suite would notice — the harness would keep passing while no
job executed it.

That is not hypothetical. The ratchet originally ran in all three jobs, which looked like
defence-in-depth and was not: two of those jobs cannot satisfy it. `spec-conformance` runs only
`pytest tests/spec`, so ART-001's tests never execute there; `quality` runs deliberately
backend-free, so `gate_profile: [postgres]` is never met. Both were vacuously green for as long as
no milestone was DONE, because the check short-circuits with "nothing to enforce" — and the moment
M0a was marked DONE, both failed. The fix moves the ratchet to the only job whose report can support
it, and this file is what stops the move from becoming a silent removal.

Deliberately unmarked: this validates the delivery pipeline, not a Requirement.
"""

from __future__ import annotations

import pytest
import yaml

from lab_brain.spec import load_milestones, repo_root

RATCHET = "scripts/check_requirement_coverage.py"

#: Mirrors outcome_plugin.GATE_ENV_VARS. Duplicated rather than imported so that a change to the
#: mapping has to be made in both places deliberately -- CI is configuration, not code, and a
#: workflow silently following a rename is how a gate stops being enforced.
GATE_ENV_VARS = {
    "postgres": "LAB_BRAIN_TEST_POSTGRES",
    "lumerical": "LAB_BRAIN_TEST_LUMERICAL",
    "network": "LAB_BRAIN_TEST_NETWORK",
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    path = repo_root() / ".github" / "workflows" / "ci.yml"
    assert path.is_file(), "CI workflow is missing; no gate in this repository is enforced"
    # `on:` parses as the boolean True in YAML 1.1, which is harmless here -- we only read `jobs`.
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _jobs_running(workflow: dict, script: str) -> dict[str, dict]:
    return {
        name: job
        for name, job in workflow["jobs"].items()
        if any(script in str(step.get("run", "")) for step in job.get("steps", []))
    }


def test_the_executed_coverage_ratchet_runs_somewhere(workflow):
    """A workflow that never invokes it leaves every DONE milestone unverified."""
    jobs = _jobs_running(workflow, RATCHET)
    assert jobs, (
        f"no CI job runs {RATCHET}. Every DONE milestone would then rest on an unverified claim "
        "that its tests executed and passed."
    )


def test_the_ratchet_runs_in_a_job_that_enables_every_required_gate(workflow):
    """The job running it must be able to satisfy it.

    A DONE milestone declaring `gate_profile: [postgres]` can only be validated by a run with
    `LAB_BRAIN_TEST_POSTGRES` set. Running the ratchet somewhere that cannot meet the profile
    produces a red build that says the milestone is unproven — true of that run, false of the
    repository — and the tempting fix is to delete the step.
    """
    catalog = load_milestones()
    required: set[str] = set()
    for milestone in catalog.milestones:
        if milestone.status == "DONE":
            required.update(milestone.gate_profile)

    jobs = _jobs_running(workflow, RATCHET)
    if not required:
        pytest.skip("no milestone is DONE yet, so no gate profile is required")

    satisfying = {
        name: job
        for name, job in jobs.items()
        if all(GATE_ENV_VARS[gate] in (job.get("env") or {}) for gate in required)
    }
    assert satisfying, (
        f"{RATCHET} runs in {sorted(jobs)}, but no such job sets "
        f"{sorted(GATE_ENV_VARS[gate] for gate in required)}, which DONE milestones require. "
        "The ratchet cannot pass where it runs."
    )


def test_the_ratchet_does_not_run_where_it_cannot_pass(workflow):
    """The other half: a job that runs it must not be one that structurally cannot satisfy it.

    Without this the previous test is satisfiable by adding one good job while leaving two broken
    ones in place — which is exactly the state that failed when M0a first went DONE.
    """
    catalog = load_milestones()
    required: set[str] = set()
    for milestone in catalog.milestones:
        if milestone.status == "DONE":
            required.update(milestone.gate_profile)
    if not required:
        pytest.skip("no milestone is DONE yet, so no gate profile is required")

    offenders = []
    for name, job in _jobs_running(workflow, RATCHET).items():
        env = job.get("env") or {}
        missing = sorted(gate for gate in required if GATE_ENV_VARS[gate] not in env)
        if missing:
            offenders.append(f"{name} (missing {', '.join(missing)})")
    assert not offenders, (
        f"{RATCHET} runs in jobs that cannot satisfy a DONE milestone's gate_profile: "
        f"{offenders}. Those runs report the milestone as unproven, which is true of the run and "
        "false of the repository."
    )


def test_every_declared_gate_profile_can_be_met_where_the_ratchet_runs(workflow):
    """Checked for EVERY milestone, not only DONE ones -- before sign-off, not at it.

    The two tests above look only at DONE milestones, so a profile no CI job can ever enable sits
    unnoticed until the day the milestone is signed off, and then the ratchet fails and the
    tempting fix is to weaken it. M5 declared `[postgres, network]` from the catalog's first
    version -- stricter than SAI, whose GH-001 test is fixture-based, and unmeetable by the offline
    CI AGT-007 requires. A milestone's profile must name only gates the ratchet's own job enables;
    a live-network or licensed check that is useful but not normative stays an optional,
    unmarked test instead.
    """
    catalog = load_milestones()
    jobs = _jobs_running(workflow, RATCHET)
    enabled = {
        gate
        for job in jobs.values()
        for gate, env_var in GATE_ENV_VARS.items()
        if env_var in (job.get("env") or {})
    }
    unmeetable = {
        milestone.milestone_id: sorted(set(milestone.gate_profile) - enabled)
        for milestone in catalog.milestones
        if set(milestone.gate_profile) - enabled
    }
    assert not unmeetable, (
        f"milestones declare gates the ratchet's CI job never enables: {unmeetable}. The "
        "ratchet could never sign them off; declare only the normative gate profile"
    )


def test_the_ratchet_runs_after_the_whole_suite_in_its_job(workflow):
    """Order matters: it reads the report the pytest run produced.

    It also needs that run to be the WHOLE suite. A `pytest tests/spec` report covers a hundred-odd
    tests and cannot show whether ART-001's contract tests passed, so the script refuses a partial
    report — but refusing at runtime is a worse failure than not being misconfigured.
    """
    for name, job in _jobs_running(workflow, RATCHET).items():
        runs = [str(step.get("run", "")) for step in job["steps"]]
        ratchet_at = next(index for index, run in enumerate(runs) if RATCHET in run)
        suite_at = [
            index
            for index, run in enumerate(runs)
            if "pytest" in run and "tests/spec" not in run and "--collect-only" not in run
        ]
        assert suite_at, f"job {name} runs {RATCHET} without a whole-suite pytest step"
        assert min(suite_at) < ratchet_at, (
            f"job {name} runs {RATCHET} before its pytest step, so it reads a stale report"
        )


def test_the_backend_job_still_proves_the_agt_007_guarantee(workflow):
    """A backend-free whole-suite run must remain in CI.

    AGT-007 promises a bare `pytest` needs no PostgreSQL, no Lumerical seat and no network. Moving
    the ratchet into the backend job must not tempt anyone to consolidate the two suite runs: the
    backend-free job is the only evidence that promise still holds.
    """
    backend_free = [
        name
        for name, job in workflow["jobs"].items()
        if any(
            "pytest" in str(step.get("run", "")) and "tests/spec" not in str(step.get("run", ""))
            for step in job.get("steps", [])
        )
        and not any(var in (job.get("env") or {}) for var in GATE_ENV_VARS.values())
    ]
    assert backend_free, (
        "no CI job runs the whole suite with every LAB_BRAIN_TEST_* variable unset, so AGT-007's "
        "no-backend guarantee is no longer demonstrated"
    )
