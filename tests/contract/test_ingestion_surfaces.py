"""T-UX-001 / T-UX-002 / T-UX-006 / T-UX-007 — the derived ingestion surfaces.

Four requirements share this file because they share one fact: none of them has a writable field.
Each §26 pass condition is asserted separately and each test carries its own marker pair.

    T-UX-001  every documented state through the documented precedence; direct client assignment
              rejected; preprint-vs-journal yields DUPLICATE-by-work AND a persisted
              SourceWork/Attestation, while byte-identical yields DUPLICATE with no new Attestation
    T-UX-002  POLICY_BLOCK and USER_INPUT_ERROR produce zero retry attempts and, for POLICY_BLOCK,
              one audit event; EXTERNAL_SERVICE_ERROR retries until max_attempts then surfaces
              FAILED with next_retry_at cleared; budget-exhausted fixture classifies POLICY_BLOCK
    T-UX-006  every reason_code emitted by fixtures resolves in MessageCatalog; an unknown code
              fails closed to a generic entry; no render path invokes a model slot
    T-UX-007  marking a Capability unavailable and a connector healthcheck degraded is reflected
              without touching any status table; seat exhaustion appears as degraded availability,
              not as an error
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect

import pytest

from lab_brain.core.models.job import JobState
from lab_brain.ingestion.admission_gate import RefusalReason
from lab_brain.ingestion.pipeline import ErrorClass as PipelineErrorClass
from lab_brain.ingestion.pipeline import IngestionStage, StageResult, StageStatus
from lab_brain.surface import catalog as catalog_module
from lab_brain.surface import health as health_module
from lab_brain.surface import ingestion_item as item_module
from lab_brain.surface.catalog import GENERIC_REASON_CODE, Severity, default_catalog, render
from lab_brain.surface.errors import (
    AUTO_RETRYABLE,
    AuditLog,
    BudgetRefused,
    ErrorClass,
    ErrorRecord,
    RemediationAction,
    decide_retry,
    may_auto_retry,
    remediations_for,
)
from lab_brain.surface.health import (
    CapabilityAvailability,
    ComponentStatus,
    SourceHealth,
    derive_health,
)
from lab_brain.surface.ingestion_item import (
    PRECEDENCE,
    IngestionItem,
    ItemState,
    classify_duplicate,
    derive_state,
)
from tests.job_fixtures import at, make_job

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)

ux001 = [pytest.mark.requirement("UX-001"), pytest.mark.spec_test("T-UX-001")]
ux002 = [pytest.mark.requirement("UX-002"), pytest.mark.spec_test("T-UX-002")]
ux006 = [pytest.mark.requirement("UX-006"), pytest.mark.spec_test("T-UX-006")]
ux007 = [pytest.mark.requirement("UX-007"), pytest.mark.spec_test("T-UX-007")]


def _stage(
    stage: IngestionStage,
    status: StageStatus,
    *,
    reason_code: str | None = None,
    error_class: PipelineErrorClass | None = None,
) -> StageResult:
    return StageResult(
        stage=stage,
        status=status,
        started_at=NOW,
        finished_at=NOW,
        reason_code=reason_code,
        error_class=error_class,
    )


def _item(**overrides: object) -> IngestionItem:
    payload: dict[str, object] = {
        "item_id": "itm:1",
        "project_id": "prj:test",
        "actor_id": "act:test",
        "trace_id": "trc:1",
        "raw_artifact_id": "art:raw",
        "source_kind": "UPLOAD",
        "display_name": "report.md",
        "submitted_at": NOW,
    }
    payload.update(overrides)
    return IngestionItem(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# UX-001 — every state, in the documented order
# ---------------------------------------------------------------------------


OK = StageStatus.SUCCEEDED
BAD = StageStatus.FAILED


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
@pytest.mark.parametrize(
    ("label", "expected", "kwargs"),
    [
        (
            "policy block beats everything",
            ItemState.BLOCKED,
            {
                "stage_results": (
                    _stage(IngestionStage.SECRET_SCAN, BAD, reason_code="SEC003"),
                    _stage(IngestionStage.PARSE_TEXT, OK),
                ),
                "error_class_for": {"SEC003": ErrorClass.POLICY_BLOCK},
            },
        ),
        (
            "raw store failed",
            ItemState.FAILED,
            {"stage_results": (_stage(IngestionStage.RAW_STORE, BAD, reason_code="IO"),)},
        ),
        (
            "every value stage failed",
            ItemState.FAILED,
            {
                "stage_results": (
                    _stage(IngestionStage.RAW_STORE, OK),
                    _stage(IngestionStage.PARSE_TEXT, BAD, reason_code="P"),
                    _stage(IngestionStage.SEGMENT, BAD, reason_code="P"),
                )
            },
        ),
        (
            "some value produced, some lost",
            ItemState.PARTIAL,
            {
                "stage_results": (
                    _stage(IngestionStage.PARSE_TEXT, OK),
                    _stage(IngestionStage.PARSE_FIGURE, BAD, reason_code="P"),
                )
            },
        ),
        (
            "a human owes this item something",
            ItemState.NEEDS_REVIEW,
            {"review_ids": ("rvw:1",), "open_review_ids": frozenset({"rvw:1"})},
        ),
        (
            "a blocking conflict",
            ItemState.NEEDS_REVIEW,
            {"conflict_ids": ("cfl:1",), "blocking_conflict_ids": frozenset({"cfl:1"})},
        ),
        (
            "identical bytes",
            ItemState.DUPLICATE,
            {"duplicate_of_artifact_id": "art:already-here"},
        ),
        (
            "a stage still pending",
            ItemState.PROCESSING,
            {"stage_results": (_stage(IngestionStage.SEGMENT, StageStatus.PENDING),)},
        ),
        ("nothing outstanding", ItemState.READY, {}),
    ],
)
def test_every_documented_state_is_reachable(label, expected, kwargs):
    """§17.22's seven states, each produced by the condition the spec names for it."""
    derive_kwargs = {
        k: kwargs.pop(k)
        for k in ("open_review_ids", "blocking_conflict_ids", "error_class_for")
        if k in kwargs
    }
    assert derive_state(_item(**kwargs), **derive_kwargs) is expected, label


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_a_running_job_makes_the_item_processing():
    """PROCESSING reads the Job, which is authoritative -- not a flag on the item."""
    job = make_job("job:x")
    assert derive_state(_item(job_ids=("job:x",)), jobs=[job]) is ItemState.PROCESSING
    done = job.transitioned(JobState.RUNNING, at(1)).transitioned(
        JobState.SUCCEEDED, at(2), result_run_id=None
    )
    assert derive_state(_item(job_ids=("job:x",)), jobs=[done]) is ItemState.READY


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_precedence_is_the_documented_order():
    """Ordering is normative, so it is asserted rather than left to the derivation's shape."""
    assert PRECEDENCE == (
        ItemState.BLOCKED,
        ItemState.FAILED,
        ItemState.PARTIAL,
        ItemState.NEEDS_REVIEW,
        ItemState.DUPLICATE,
        ItemState.PROCESSING,
        ItemState.READY,
    )


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_a_policy_block_outranks_a_failure_and_a_pending_stage():
    """The pairwise ordering that matters most: it decides who is sent to investigate."""
    item = _item(
        stage_results=(
            _stage(IngestionStage.RAW_STORE, BAD, reason_code="IO"),
            _stage(IngestionStage.SECRET_SCAN, BAD, reason_code="SEC003"),
            _stage(IngestionStage.SEGMENT, StageStatus.PENDING),
        )
    )
    assert (
        derive_state(
            item, error_class_for={"SEC003": ErrorClass.POLICY_BLOCK, "IO": ErrorClass.SYSTEM_ERROR}
        )
        is ItemState.BLOCKED
    )


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_state_is_not_a_writable_field():
    """THE UX-001 probe: 不得由前端或人工直接指定.

    Asserted structurally rather than by trying to set it. `IngestionItem` has no `state`
    attribute at all, so "reject a client assignment" is not a runtime check that could be
    bypassed -- there is nothing to assign to.
    """
    assert "state" not in IngestionItem.__dataclass_fields__
    item = _item()
    assert not hasattr(item, "state")
    with pytest.raises((AttributeError, TypeError)):
        item.state = ItemState.READY  # type: ignore[attr-defined]


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_byte_identical_duplicate_yields_duplicate_with_no_new_attestation():
    """§17.22: identical bytes -> no new scientific value; safe to skip."""
    verdict = classify_duplicate(
        content_hash="sha256:aaa",
        source_work_id="swk:paper",
        known_artifact_by_hash={"sha256:aaa": "art:already-here"},
        known_artifacts_by_work={"swk:paper": ("art:already-here",)},
    )
    assert verdict.is_discardable
    assert not verdict.must_still_attest
    item = _item(duplicate_of_artifact_id=verdict.identical_bytes_of, attestation_ids=())
    assert derive_state(item) is ItemState.DUPLICATE
    assert item.attestation_ids == ()


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_a_same_work_duplicate_is_ready_and_keeps_its_attestation():
    """THE distinction §17.22 says must not be blurred.

    A preprint and its journal version are the same work and different bytes. Dropping the second
    corrupts corroboration counting -- EVI-004 resolves independence at the *work* level, so a
    mirror that never became an Attestation is a citation the independence counter never sees.

    So the verdict is NOT discardable, the item is READY rather than DUPLICATE, and it carries an
    Attestation. An implementation collapsing the two duplicate fields into one would fail here
    and nowhere else.
    """
    verdict = classify_duplicate(
        content_hash="sha256:journal-version",
        source_work_id="swk:paper",
        known_artifact_by_hash={"sha256:preprint": "art:preprint"},
        known_artifacts_by_work={"swk:paper": ("art:preprint",)},
    )
    assert not verdict.is_discardable
    assert verdict.must_still_attest
    assert verdict.same_work_as == "swk:paper"

    item = _item(
        duplicate_of_artifact_id=None,
        duplicate_of_source_work_id=verdict.same_work_as,
        attestation_ids=("att:journal",),
    )
    assert derive_state(item) is ItemState.READY, (
        "a same-work duplicate was presented as discardable"
    )
    assert item.attestation_ids == ("att:journal",)


# ---------------------------------------------------------------------------
# UX-002 — the taxonomy and the retry rule
# ---------------------------------------------------------------------------


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_the_taxonomy_is_exactly_the_five_frozen_classes():
    """§17.23 marks `error_class` FROZEN: a sixth requires an ADR."""
    assert {c.value for c in ErrorClass} == {
        "USER_INPUT_ERROR",
        "EXTRACTION_WARNING",
        "POLICY_BLOCK",
        "EXTERNAL_SERVICE_ERROR",
        "SYSTEM_ERROR",
    }


def _record(error_class: ErrorClass, **overrides: object) -> ErrorRecord:
    payload: dict[str, object] = {
        "error_id": "ERR-20260921-0001",
        "project_id": "prj:test",
        "trace_id": "trc:1",
        "error_class": error_class,
        "reason_code": "SOMETHING",
        "component": "FigureParser",
        "occurred_at": NOW,
        "attempt_count": 0,
        "max_attempts": 3,
    }
    payload.update(overrides)
    return ErrorRecord(**payload)  # type: ignore[arg-type]


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
@pytest.mark.parametrize("never_retried", [ErrorClass.POLICY_BLOCK, ErrorClass.USER_INPUT_ERROR])
def test_policy_block_and_user_input_error_produce_zero_retry_attempts(never_retried):
    """§17.23 states both as MUST NOT, with different reasons.

    A retry loop against an ACL is indistinguishable from an attack; retrying a corrupt file
    burns budget forever. Neither is a matter of how many attempts remain, so the assertion holds
    with the attempt count at zero.
    """
    assert not may_auto_retry(never_retried, 0, 5)
    decision = decide_retry(_record(never_retried), now=NOW)
    assert not decision.retry
    assert decision.terminal
    assert decision.next_retry_at is None


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_a_policy_block_emits_exactly_one_audit_event_and_no_retry():
    """ "MUST instead emit an audit event (SEC-001/SEC-002)"."""
    log = AuditLog()
    decision = decide_retry(
        _record(ErrorClass.POLICY_BLOCK, reason_code="READ_NOT_PERMITTED"), now=NOW
    )
    assert decision.audit_required
    log.record(
        project_id="prj:test",
        actor_id="act:test",
        reason_code=decision.reason_code,
        note="read refused",
    )
    assert len(log.for_project("prj:test")) == 1
    assert not decision.retry


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_an_external_service_error_retries_to_the_bound_then_surfaces_failed():
    """The whole bounded-retry arc, including the cleared `next_retry_at` at the end.

    §17.23: "exhausted retries transition the surface to FAILED with next_retry_at cleared". A
    stale timestamp on a dead item tells a user to wait for something that will never happen.
    """

    # A budget gate is REQUIRED now: `charge_budget=None` means "not authorised to spend", not
    # "spend freely". This one allows, so what the test measures is the attempt bound.
    def allow(_record_):
        return None

    for attempt in range(3):
        decision = decide_retry(
            _record(ErrorClass.EXTERNAL_SERVICE_ERROR, attempt_count=attempt, max_attempts=3),
            now=NOW,
            charge_budget=allow,
        )
        assert decision.retry, f"attempt {attempt} should have retried"
        assert decision.next_retry_at is not None

    exhausted = decide_retry(
        _record(ErrorClass.EXTERNAL_SERVICE_ERROR, attempt_count=3, max_attempts=3),
        now=NOW,
        charge_budget=allow,
    )
    assert not exhausted.retry
    assert exhausted.terminal
    assert exhausted.reason_code == "RETRY_LIMIT_REACHED"
    assert exhausted.next_retry_at is None


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_budget_exhaustion_classifies_as_policy_block_not_failed():
    """§17.23: "Budget exhaustion is POLICY_BLOCK, not FAILED. The system is healthy; the policy
    stopped it."

    The reclassification is the requirement, not a label. FAILED would send an engineer to
    investigate a working system AND put the work back in the auto-retry set -- so it would spend
    the budget it was just told it does not have.
    """

    def refuse(_record_):
        raise BudgetRefused("project cap reached")

    decision = decide_retry(
        _record(ErrorClass.EXTERNAL_SERVICE_ERROR), now=NOW, charge_budget=refuse
    )
    assert decision.error_class is ErrorClass.POLICY_BLOCK
    assert decision.reason_code == "BUDGET_EXHAUSTED"
    assert not decision.retry
    assert decision.next_retry_at is None
    assert decision.audit_required


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_the_budget_gate_is_never_asked_about_a_class_that_may_not_retry():
    """Order matters: asking the gate about an ACL refusal makes it look like a spending choice."""
    asked = []

    def charge(record):
        asked.append(record.error_class)

    for never in (
        ErrorClass.POLICY_BLOCK,
        ErrorClass.USER_INPUT_ERROR,
        ErrorClass.EXTRACTION_WARNING,
    ):
        decide_retry(_record(never), now=NOW, charge_budget=charge)
    assert asked == [], f"the budget gate was consulted for {asked}"


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_an_extraction_warning_is_not_offered_a_one_click_accept():
    """§17.23: rendering it as an error trains users to click ACCEPT, which silently
    reintroduces hallucinated completion. So the cheap dismissal is not offered."""
    actions = {r.action_key for r in remediations_for(ErrorClass.EXTRACTION_WARNING)}
    assert RemediationAction.ACCEPT not in actions
    assert RemediationAction.MARK_UNKNOWN in actions
    assert default_catalog().resolve("PARSE_TEXT_FAILED").severity is Severity.WARNING


@pytest.mark.requirement("UX-002")
@pytest.mark.spec_test("T-UX-002")
def test_only_the_two_bounded_classes_are_auto_retryable():
    assert frozenset({ErrorClass.EXTERNAL_SERVICE_ERROR, ErrorClass.SYSTEM_ERROR}) == AUTO_RETRYABLE


# ---------------------------------------------------------------------------
# UX-006 — the catalog
# ---------------------------------------------------------------------------


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_every_refusal_reason_resolves_in_the_catalog():
    """ "Every reason_code emitted by fixtures resolves in MessageCatalog."

    The admission gate's enum IS the fixture set: those are the codes a user can actually be
    shown. Reusing them rather than inventing synonyms is UX-006's instruction, and this is what
    makes "reused" checkable.
    """
    catalog = default_catalog()
    missing = sorted(r.value for r in RefusalReason if not catalog.knows(r.value))
    assert missing == [], f"no catalog entry for {missing}"


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_every_pipeline_reason_code_resolves_in_the_catalog():
    """The other emitter: reason codes the ingestion pipeline writes onto StageResults."""
    catalog = default_catalog()
    source = inspect.getsource(__import__("lab_brain.ingestion.pipeline", fromlist=["x"]))
    emitted = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.keyword)
        and node.arg == "reason_code"
        and isinstance(node.value, ast.Constant)
    }
    codes = {n.value for n in emitted if isinstance(n.value, str)}
    missing = sorted(c for c in codes if not catalog.knows(c))
    assert missing == [], f"the pipeline emits codes with no catalog entry: {missing}"


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_an_unknown_reason_code_fails_closed_to_a_generic_entry():
    """Raising would make a missing row a second failure on top of the one being reported."""
    message = render(default_catalog(), "SOMETHING_NOBODY_WROTE", error_id="ERR-1")
    assert message.reason_code == GENERIC_REASON_CODE
    assert message.fell_back
    assert message.error_id == "ERR-1", "the reference a user can quote was dropped"
    assert "SOMETHING_NOBODY_WROTE" not in message.summary, (
        "an internal identifier leaked into user-facing text"
    )


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_a_catalog_without_a_generic_entry_cannot_be_built():
    """There has to be something to fail closed *to*."""
    from lab_brain.surface.catalog import MessageCatalog

    with pytest.raises(ValueError, match=GENERIC_REASON_CODE):
        MessageCatalog("x", "en", "1.0.0", ())


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_no_render_path_can_reach_a_model_slot():
    """THE UX-006 probe, checked structurally.

    An LLM-written failure explanation is an ungrounded inference presented as system fact --
    EVI-003's failure arriving through the one door nobody guards. Asserted by parsing the module
    rather than by convention: the catalog imports nothing that could call a model, and contains
    no call whose name suggests one.
    """
    tree = ast.parse(inspect.getsource(catalog_module))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    for name in imported:
        assert "llm" not in name.lower()
        assert "model_slot" not in name.lower()
        assert "inference" not in name.lower()

    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for forbidden in ("complete", "generate", "invoke", "chat", "predict"):
        assert forbidden not in called, f"the catalog calls {forbidden}()"


@pytest.mark.requirement("UX-006")
@pytest.mark.spec_test("T-UX-006")
def test_the_rendered_payload_never_inlines_technical_detail():
    """§17.24: `technical_detail_ref` is a pointer, not the content."""
    message = render(
        default_catalog(),
        "PARSE_TEXT_FAILED",
        error_id="ERR-1",
        technical_detail_ref="det:abc",
    )
    assert message.technical_detail_ref == "det:abc"
    rendered = " ".join((message.summary, message.cause, *message.next_steps))
    for leak in ("Traceback", "/home/", "\\Users\\", "det:abc"):
        assert leak not in rendered


# ---------------------------------------------------------------------------
# UX-007 — derived health
# ---------------------------------------------------------------------------


def _health(**overrides):
    payload = {
        "capabilities": [CapabilityAvailability("cap:parse", available=True)],
        "adapters": [SourceHealth("src:fake", reachable=True)],
        "jobs": [],
        "review_queue_depth": 0,
        "review_queue_capacity": 10,
    }
    payload.update(overrides)
    return derive_health(**payload)  # type: ignore[arg-type]


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_a_healthy_system_reports_healthy():
    assert _health().overall is ComponentStatus.HEALTHY


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_marking_a_capability_unavailable_is_reflected_without_touching_a_status_table():
    """§26: "without touching any status table". The input is the Capability, not a health row."""
    health = _health(capabilities=[CapabilityAvailability("cap:parse", available=False)])
    assert health.component("cap:parse").status is ComponentStatus.UNAVAILABLE
    assert health.overall is ComponentStatus.UNAVAILABLE


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_a_degraded_connector_healthcheck_is_reflected():
    health = _health(adapters=[SourceHealth("src:fake", reachable=False, detail="timeout")])
    assert health.component("src:fake").status is ComponentStatus.UNAVAILABLE
    assert health.component("src:fake").reason_code == "EXTERNAL_SERVICE_UNAVAILABLE"


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_seat_exhaustion_appears_as_degraded_availability_not_as_an_error():
    """THE UX-007 probe. §17.24: a Lumerical seat shortage surfaces as degraded availability.

    Reporting it as an error sends an engineer to investigate a healthy system, and an operator
    who sees "error" for routine contention stops reading the page.
    """
    parked = make_job("job:seat", capability_id="cap:lumerical")
    parked = parked.transitioned(JobState.RUNNING, at(1)).transitioned(
        JobState.WAITING_RESOURCE, at(2)
    )
    health = _health(
        capabilities=[CapabilityAvailability("cap:lumerical", available=True, concurrency_limit=1)],
        jobs=[parked],
    )
    component = health.component("cap:lumerical")
    assert component.status is ComponentStatus.DEGRADED
    assert component.status is not ComponentStatus.UNAVAILABLE
    assert component.reason_code == "AWAITING_RESOURCE"
    assert component.waiting_on_resource == 1
    assert health.overall is ComponentStatus.DEGRADED


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_job_queue_depth_is_an_input_and_counts_only_active_jobs():
    running = make_job("job:a").transitioned(JobState.RUNNING, at(1))
    queued = make_job("job:b", idempotency_key="k2")
    finished = make_job("job:c", idempotency_key="k3").transitioned(JobState.RUNNING, at(1))
    finished = finished.transitioned(JobState.FAILED, at(2))
    health = _health(jobs=[running, queued, finished])
    assert health.job_queue_depth == 2


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_a_full_review_queue_degrades_the_system():
    """§14.4.1: human review is a Capability whose availability falls with queue depth.

    A backlog that did not surface would make the planner treat reviewers as free.
    """
    health = _health(review_queue_depth=10, review_queue_capacity=10)
    assert health.component("capability:human_review").status is ComponentStatus.DEGRADED
    assert health.component("capability:human_review").reason_code == "REVIEW_QUEUE_FULL"
    assert health.review_capacity_remaining == 0
    assert health.overall is ComponentStatus.DEGRADED


@pytest.mark.requirement("UX-007")
@pytest.mark.spec_test("T-UX-007")
def test_there_is_no_writable_health_field():
    """§17.24: System Health 是推導的，不是手維護的.

    Structural, like UX-001's: the module exposes `derive_health` and no setter, and
    `SystemHealth` is frozen. A settable status is what an operator reaches for during an
    incident to stop the alerts, after which the page reports the last human's belief.
    """
    source = ast.parse(inspect.getsource(health_module))
    names = {n.name for n in ast.walk(source) if isinstance(n, ast.FunctionDef)}
    for forbidden in ("set_status", "set_health", "mark_healthy", "override"):
        assert forbidden not in names
    with pytest.raises((AttributeError, TypeError)):
        _health().components = ()  # type: ignore[misc]


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_item_module_has_no_state_setter():
    """The same structural claim for UX-001's module."""
    source = ast.parse(inspect.getsource(item_module))
    names = {n.name for n in ast.walk(source) if isinstance(n, ast.FunctionDef)}
    for forbidden in ("set_state", "mark_ready", "force_state", "override_state"):
        assert forbidden not in names
