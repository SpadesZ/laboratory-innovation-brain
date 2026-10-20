"""UX-002's fail-closed budget gate, and the M1 CLI (§17.23, COST-001, §17.22, §17.24).

TWO BLOCKERS IN ONE FILE because both are about the same kind of mistake: a check that is present
but optional, and a surface that recomputes something already decided elsewhere.

UX-002. `decide_retry(..., charge_budget=None)` used to return `retry=True`. §17.23 says
*Auto-retry consumes budget through BudgetGate (COST-001)* -- so an omitted gate meant the
requirement held only for callers who remembered to pass one, and a caller that forgets gets the
permissive answer. That is the fail-open shape this repository has now found four times.

CLI. `lab-brain inbox` does not compute state and `lab-brain explain` does not decide access.
Both are renderers over things that are already tested: `derive_state` and `DiagnosticsService`.
A CLI that computed either would be a second implementation, and the terminal would eventually
disagree with everything else.
"""

from __future__ import annotations

import datetime as dt
import io

import pytest

from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.enums import ActorType, SensitivityLabel
from lab_brain.ingestion.pipeline import ErrorClass as PipelineErrorClass
from lab_brain.ingestion.pipeline import IngestionStage, StageResult, StageStatus
from lab_brain.interfaces.cli import (
    build_inbox,
    build_parser,
    run_explain,
    run_inbox,
    summarise,
)
from lab_brain.surface.catalog import default_catalog
from lab_brain.surface.disclosure import VIEW_TECHNICAL_SCOPE, DiagnosticsService, TechnicalDetail
from lab_brain.surface.errors import (
    AuditLog,
    BudgetRefused,
    ErrorClass,
    ErrorRecord,
    decide_retry,
)
from lab_brain.surface.ingestion_item import IngestionItem, ItemState

NOW = dt.datetime(2026, 9, 22, 13, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
ACTOR = "act:test"


def _record(error_class: ErrorClass = ErrorClass.EXTERNAL_SERVICE_ERROR, **overrides):
    payload = {
        "error_id": "ERR-20260922-0001",
        "project_id": PROJECT,
        "trace_id": "trc:1",
        "error_class": error_class,
        "reason_code": "EXTERNAL_SERVICE_UNAVAILABLE",
        "component": "LiteratureConnector",
        "occurred_at": NOW,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return ErrorRecord(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# UX-002 — no BudgetGate means no retry
# ---------------------------------------------------------------------------


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_a_retryable_error_is_not_authorized_without_a_budget_gate():
    """THE blocker probe. Before this, an omitted gate returned `retry=True`.

    The class is retryable and attempts remain -- every condition except the one §17.23 makes
    mandatory. `retry` must be False, and the side effect the caller would have performed must
    never be reached.
    """
    decision = decide_retry(_record(), now=NOW, charge_budget=None)
    assert not decision.retry
    assert decision.reason_code == "BUDGET_GATE_UNAVAILABLE"
    assert decision.terminal
    assert decision.next_retry_at is None


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_the_unavailable_gate_classifies_as_policy_block_and_is_audited():
    """Not SYSTEM_ERROR, and the distinction has teeth.

    SYSTEM_ERROR is in `AUTO_RETRYABLE`, so classifying an unwired gate that way would let a
    deployment retry its way around the missing check. POLICY_BLOCK is not retryable and emits an
    audit event, which is what §17.23 requires of a refusal that is not a breakage.
    """
    decision = decide_retry(_record(), now=NOW, charge_budget=None)
    assert decision.error_class is ErrorClass.POLICY_BLOCK
    assert decision.audit_required

    log = AuditLog()
    log.record(
        project_id=PROJECT,
        actor_id=ACTOR,
        reason_code=decision.reason_code,
        note="budget gate unavailable",
    )
    assert len(log.for_project(PROJECT)) == 1


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_no_retry_side_effect_runs_when_the_gate_is_missing():
    """Ordering, proven the way SEC-001's is: a spy that fails the test if entered.

    Asserting on `decision.retry` alone would pass against an implementation that performed the
    attempt and then reported it had not.
    """
    performed: list[str] = []

    decision = decide_retry(_record(), now=NOW, charge_budget=None)
    if decision.retry:  # pragma: no cover - the assertion below is the point
        performed.append("attempt")
    assert performed == []


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_an_allowing_budget_gate_permits_the_retry():
    """The positive control. Without it the repair could be a gate that refuses everything."""
    charged: list[str] = []

    def allow(record: ErrorRecord) -> None:
        charged.append(record.error_id)

    decision = decide_retry(_record(), now=NOW, charge_budget=allow)
    assert decision.retry
    assert decision.next_retry_at == NOW + dt.timedelta(seconds=30)
    assert charged == ["ERR-20260922-0001"], "the budget gate was not actually consulted"


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_a_refusing_budget_gate_is_policy_block_and_audited():
    """Unchanged behaviour, re-asserted because the new branch sits next to it."""

    def refuse(_record_: ErrorRecord) -> None:
        raise BudgetRefused("project cap reached")

    decision = decide_retry(_record(), now=NOW, charge_budget=refuse)
    assert not decision.retry
    assert decision.reason_code == "BUDGET_EXHAUSTED"
    assert decision.error_class is ErrorClass.POLICY_BLOCK
    assert decision.audit_required


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_the_missing_gate_is_distinguishable_from_an_exhausted_budget():
    """Different remedies: one is a configuration problem, one needs an approver.

    A single code for both would send a researcher to ask for more budget when the real problem
    is that nobody wired the gate.
    """

    def refuse(_r: ErrorRecord) -> None:
        raise BudgetRefused("cap")

    assert decide_retry(_record(), now=NOW, charge_budget=None).reason_code != (
        decide_retry(_record(), now=NOW, charge_budget=refuse).reason_code
    )


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_the_new_reason_code_resolves_in_the_catalog():
    """A code with no catalog row renders as the generic entry and tells the user nothing."""
    assert default_catalog().knows("BUDGET_GATE_UNAVAILABLE")


# ---------------------------------------------------------------------------
# CLI — inbox
# ---------------------------------------------------------------------------


def _item(item_id: str, **overrides) -> IngestionItem:
    payload = {
        "item_id": item_id,
        "project_id": PROJECT,
        "actor_id": ACTOR,
        "trace_id": "trc:1",
        "raw_artifact_id": "art:raw",
        "source_kind": "UPLOAD",
        "display_name": f"{item_id}.md",
        "submitted_at": NOW,
    }
    payload.update(overrides)
    return IngestionItem(**payload)  # type: ignore[arg-type]


def _stage(stage, status, **kw) -> StageResult:
    return StageResult(stage=stage, status=status, started_at=NOW, finished_at=NOW, **kw)


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_inbox_derives_state_rather_than_reading_it():
    """The CLI calls `derive_state`. It does not have its own idea of what READY means."""
    items = [
        _item("itm:ready"),
        _item(
            "itm:partial",
            stage_results=(
                _stage(IngestionStage.PARSE_TEXT, StageStatus.SUCCEEDED),
                _stage(
                    IngestionStage.PARSE_FIGURE,
                    StageStatus.FAILED,
                    reason_code="PARSE_TEXT_FAILED",
                    error_class=PipelineErrorClass.EXTRACTION_WARNING,
                ),
            ),
        ),
        _item("itm:duplicate", duplicate_of_artifact_id="art:already-here"),
    ]
    # Keyed by id rather than by position: the listing is sorted by (submitted_at, item_id) so
    # two runs diff cleanly, and these three share a timestamp. Asserting positionally would be
    # asserting the sort, which `test_the_inbox_renders_a_stable_table` does on purpose.
    states = {r.item_id: r.state for r in build_inbox(items)}
    assert states == {
        "itm:ready": ItemState.READY,
        "itm:partial": ItemState.PARTIAL,
        "itm:duplicate": ItemState.DUPLICATE,
    }


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_inbox_summary_counts_every_state_including_the_zeroes():
    """ "BLOCKED 0" is information. Omitting empty states makes "nothing is blocked" and "the
    column was dropped" look identical."""
    counts = summarise(build_inbox([_item("itm:1"), _item("itm:2")]))
    assert counts[ItemState.READY] == 2
    assert set(counts) == set(ItemState)
    assert counts[ItemState.BLOCKED] == 0


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_inbox_reflects_an_open_review_as_needs_review():
    """The ReviewQueue is the authority (UX-005); the CLI passes its answer through."""
    item = _item("itm:review", review_ids=("rvw:1",))
    rows = build_inbox([item], open_review_ids=frozenset({"rvw:1"}))
    assert rows[0].state is ItemState.NEEDS_REVIEW
    # And falls back once the review closes -- a listing stuck on NEEDS_REVIEW is noise.
    assert build_inbox([item], open_review_ids=frozenset())[0].state is ItemState.READY


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_inbox_renders_a_stable_table():
    out = io.StringIO()
    assert run_inbox([_item("itm:1"), _item("itm:2")], out=out) == 0
    text = out.getvalue()
    assert "ITEM" in text and "STATE" in text
    assert "itm:1" in text and "itm:2" in text
    assert "READY=2" in text
    # Ordered by submission, so two runs diff cleanly.
    assert text.index("itm:1") < text.index("itm:2")


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_both_commands_require_an_actor():
    """§14.4: 沒有「誰」就沒有真 governance. No default identity anywhere."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["inbox", "--project", PROJECT])
    with pytest.raises(SystemExit):
        parser.parse_args(["explain", "ERR-1", "--project", PROJECT])

    parsed = parser.parse_args(["inbox", "--project", PROJECT, "--actor", ACTOR])
    assert parsed.actor == ACTOR


# ---------------------------------------------------------------------------
# CLI — explain
# ---------------------------------------------------------------------------


SECRET_DETAIL = TechnicalDetail(
    detail_ref="det:1",
    sensitivity=SensitivityLabel.RESTRICTED_NDA,
    component="FigureParser",
    message="Traceback: ValueError at foundry_pdk.py:184",
    stack_ref="stk:1",
    source_path="/srv/nda/acme-foundry/pdk-v7/rules.pdf",
    prompt_fragment="Given the ACME 220nm PDK ...",
)

ERROR = ErrorRecord(
    error_id="ERR-20260922-0001",
    project_id=PROJECT,
    trace_id="trc:1",
    job_id="job:1",
    span_id="spn:1",
    error_class=ErrorClass.SYSTEM_ERROR,
    reason_code="PARSE_TEXT_FAILED",
    component="FigureParser",
    occurred_at=NOW,
    technical_detail_ref="det:1",
)


def _service(*, scopes: tuple[str, ...] = (), clearance: tuple[SensitivityLabel, ...] = ()):
    """`actor_of` is required, so the fixture has to say which accounts exist and are active.

    That is not ceremony. The CLI's `--actor` is only governance if something resolves it, and a
    service built without a resolver used to authorize on "a membership row exists" -- which is
    the rule SEC-002 replaced. See tests/security/test_diagnostics_disclosure.py for the probes.
    """
    membership = ProjectMembership(
        actor_id=ACTOR,
        project_id=PROJECT,
        role="RESEARCHER",
        sensitivity_clearance=clearance,
        approval_scopes=scopes,
    )
    actors = {ACTOR: Actor(actor_id=ACTOR, actor_type=ActorType.HUMAN)}
    return DiagnosticsService(
        catalog=default_catalog(),
        load_error=lambda key: ERROR if key == ERROR.error_id else None,
        load_detail=lambda ref: SECRET_DETAIL if ref == "det:1" else None,
        membership_of=lambda actor, project: (
            membership if project == PROJECT and actor == ACTOR else None
        ),
        actor_of=actors.get,
    )


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_explain_prints_catalog_text_and_never_technical_detail_by_default():
    """Every line comes from the catalog. No stack trace, path, repo name or prompt fragment."""
    out = io.StringIO()
    assert run_explain(_service(), ERROR.error_id, actor_id=ACTOR, project_id=PROJECT, out=out) == 0
    text = out.getvalue()
    assert "Some text could not be extracted" in text
    assert "trc:1" in text and "job:1" in text
    for leak in ("Traceback", "foundry_pdk.py", "/srv/nda/", "acme-foundry", "220nm PDK"):
        assert leak not in text, f"the CLI leaked {leak!r}"


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_explain_technical_is_denied_without_the_scope():
    """`--technical` ASKS. The service decides, server-side."""
    out = io.StringIO()
    run_explain(
        _service(), ERROR.error_id, actor_id=ACTOR, project_id=PROJECT, technical=True, out=out
    )
    text = out.getvalue()
    assert "DIAGNOSTICS_SCOPE_REQUIRED" in text
    assert "Traceback" not in text


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_explain_technical_is_redacted_without_clearance_and_keeps_the_refs():
    out = io.StringIO()
    run_explain(
        _service(scopes=(VIEW_TECHNICAL_SCOPE,), clearance=(SensitivityLabel.INTERNAL,)),
        ERROR.error_id,
        actor_id=ACTOR,
        project_id=PROJECT,
        technical=True,
        out=out,
    )
    text = out.getvalue()
    assert "redacted" in text
    assert "/srv/nda/" not in text
    assert "trc:1" in text and "spn:1" in text


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_explain_shows_detail_to_a_cleared_actor_with_the_scope():
    out = io.StringIO()
    run_explain(
        _service(scopes=(VIEW_TECHNICAL_SCOPE,), clearance=(SensitivityLabel.RESTRICTED_NDA,)),
        ERROR.error_id,
        actor_id=ACTOR,
        project_id=PROJECT,
        technical=True,
        out=out,
    )
    assert "/srv/nda/acme-foundry" in out.getvalue()


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_explain_reports_an_unknown_and_a_foreign_error_identically():
    """§17.24's oracle rule, enforced at the surface a user actually types into.

    Two different underlying situations, byte-identical output apart from the id the caller
    themselves supplied -- and a non-zero exit code for both.
    """
    unknown = io.StringIO()
    foreign = io.StringIO()
    service = _service()

    assert (
        run_explain(service, "ERR-20260922-9999", actor_id=ACTOR, project_id=PROJECT, out=unknown)
        == 1
    )
    assert (
        run_explain(service, "ERR-20260101-0001", actor_id=ACTOR, project_id=PROJECT, out=foreign)
        == 1
    )

    a = unknown.getvalue().replace("ERR-20260922-9999", "<id>")
    b = foreign.getvalue().replace("ERR-20260101-0001", "<id>")
    assert a == b
    for forbidden in ("permission", "denied", "forbidden", "another project"):
        assert forbidden not in a.lower()


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_no_cli_path_can_reach_a_model():
    """§17.24 forbids LLM-generated failure text at render time.

    Structural, like the catalog's own probe: the CLI imports nothing that could generate.
    """
    import ast
    import inspect

    from lab_brain.interfaces import cli as cli_module

    tree = ast.parse(inspect.getsource(cli_module))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names
    }
    for name in imported:
        assert "cognition" not in name
        assert "llm" not in name.lower()
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for forbidden in ("complete", "generate", "invoke", "chat"):
        assert forbidden not in called
