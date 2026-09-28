"""The report renderer: every section present, pending work stated as blocked, absences stated."""

from __future__ import annotations

import datetime as dt

from lab_brain.research.render import render_markdown
from lab_brain.research.report import (
    Conclusion,
    ContinuationSection,
    EpisodeReport,
    InputStatus,
    PendingAction,
    StageStatus,
)

T0 = dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC)


def _report(**overrides: object) -> EpisodeReport:
    fields: dict[str, object] = {
        "episode_id": "epi:1",
        "project_id": "prj:1",
        "actor_id": "act:1",
        "trace_id": "trc:1",
        "goal": "why | is Rs high",
        "domain": "silicon_photonics",
        "started_at": T0,
        "finished_at": T0,
        "episode_state": "SUSPENDED",
        "stages": (StageStatus("verification", "DONE", "2 checks"),),
        "inputs": (InputStatus("r.md", "document", "INTERNAL_MEASUREMENT", "art:x", "READY"),),
        "verification_input": None,
        "evidence": (),
        "literature": None,
        "hypotheses": (),
        "debate": None,
        "belief": (),
        "plans": (),
        "completed": (),
        "pending": (
            PendingAction(
                capability_id="cap:sim",
                action_type="SIMULATION",
                best_next=True,
                would_decide=("mesh -> SUPPORTED if UNSTABLE",),
                estimated_cost="wall clock s 240",
                blocked_because="no simulator here",
                requires="a licensed solver",
            ),
        ),
        "human_actions": (),
        "conclusion": Conclusion(status="PROVISIONAL", statement="not confirmed"),
        "failure_analysis": None,
        "heuristic_candidates": (),
        "next_steps": ("run cap:sim",),
        "provenance": ("episode epi:1",),
        "deployment": ("reasoner: rules",),
        "not_performed": ("no simulation was run",),
    }
    fields.update(overrides)
    return EpisodeReport(**fields)  # type: ignore[arg-type]


def test_every_section_is_rendered_and_pending_work_is_blocked_not_done():
    text = render_markdown(_report())
    for heading in (
        "## Result",
        "## Stages",
        "## Inputs",
        "## Evidence and sources",
        "## Competing hypotheses",
        "## Debate and critique",
        "## Belief state",
        "## Verification plan",
        "## Completed actions",
        "## Pending simulation actions",
        "## Next steps",
        "## Provenance",
        "## What ran, and what did not",
    ):
        assert heading in text
    assert "**PROVISIONAL**" in text
    assert "`cap:sim` (SIMULATION, best next action) -- **BLOCKED**: no simulator here" in text
    assert "**Pending simulation:** `cap:sim`" in text
    assert "Not performed: no simulation was run" in text
    assert "No verification action was executed." in text
    assert "The debate did not run." in text


def test_the_report_is_plain_markdown_and_table_cells_cannot_break_their_table():
    text = render_markdown(_report(inputs=(InputStatus("a|b.md", "document", "X", None, "READY"),)))
    assert "a\\|b.md" in text
    rows = [line for line in text.splitlines() if line.startswith("| a")]
    assert len(rows) == 1 and rows[0].count(" | ") == 6, "one row, seven cells"


def test_a_continuation_says_which_run_it_is_and_what_it_did_not_redo():
    """A reader must never mistake a continuation for a fresh episode, or a check an earlier run
    executed for one this run skipped."""
    fresh = render_markdown(_report())
    assert "Continuation" not in fresh
    text = render_markdown(
        _report(
            continuation=ContinuationSection(
                run_ordinal=2,
                resumed_from="SUSPENDED (awaiting simulator) to EVIDENCE_GATHERING through "
                "episode_resume",
                reasoning="hypothesis set `hst:1` and debate `dbt:1`, recorded by run 1 -- reused, "
                "not debated again",
                earlier_runs=("run 1 (`rrn:1`) by `act:a`, started T: SUSPENDED:PROVISIONAL",),
                earlier_checks=("`cap:x` -- job `job:1`, run `run:1`",),
                superseded_jobs=("job `job:2` was parked by an earlier run and never ran",),
            )
        )
    )
    assert "## Continuation: run 2 of this episode" in text
    assert "Resumed from SUSPENDED (awaiting simulator)" in text
    assert "- run 1 (`rrn:1`)" in text
    assert "Checks executed by earlier runs (not executed again):" in text
    assert "- `cap:x` -- job `job:1`, run `run:1`" in text
    assert "- job `job:2` was parked" in text
    assert "This run admitted no statement." in text
    assert text.index("## Continuation") < text.index("## Result")
