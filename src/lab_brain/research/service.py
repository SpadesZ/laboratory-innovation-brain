"""A research episode, end to end: goal + local files in, one coherent report out.

A COMPOSITION OF EXISTING AUTHORITIES, NOT A NEW ONE. This module decides no scientific question.
Each stage calls the service that already owns it, unchanged, and records what it returned:

    authorize      `ScientificReadGate.require_project` -- the actor must be an active member
    episode        `IngestionService.open_episode` -- §17.3's episode and its trace
    ingest         `IngestionService.submit` + `ingest` -- raw bytes hashed and stored before any
                   parse, one Job and one Run per file, the Knowledge Inbox item (UX-001, UX-004)
    evidence       `research.evidence.StatementAdmitter` -- verbatim REPORTED statements through
                   M1's `admission_gate` (ACL, EVI-010 re-derivation, canonical body)
    external       `research.literature` over M5's registry, snapshot service and admission -- only
                   with a provider and a query the actor declared PUBLIC
    hypotheses     M3's `StructuredDebate` -- intent-aware retrieval, Stage A positions, the
                   Critic's inverted retrieval, §8 admission, typed predictions -- with the
                   ACTIVE LLM runtime behind the model slots (`research.reasoning`), or, with none
                   active, the pack's rule-based catalog reasoner (the explicit fallback)
    verification   M4's `VerificationLoop` -- least-cost planning, typed tools, Jobs and Runs,
                   evidence admission, governed belief moves, the failure analysis
    pending        M4's `LeastCostPlanner` asked, over the loop's own final state, which action it
                   would choose if the pack's declared capabilities could all run here. If that is
                   a capability this deployment cannot execute, it is reported as a PENDING
                   requirement -- never executed, never mocked, never counted as evidence

THE EPISODE ENDS HONESTLY. Confirmed -> the episode is closed with that outcome. Waiting on a
simulator, a person or a seat -> the episode is SUSPENDED with the reason, so it can be resumed as
the same episode when the blocker is gone. Nothing sufficient left -> closed INCONCLUSIVE. A debate
that FAILED before any hypothesis set existed (a model call that timed out, a route that was
unavailable, a reply no parser accepted) concluded nothing: SUSPENDED, and a continuation retries
the debate over the statements this run admitted -- recorded by reference before the debate
(`012k`), never ingested or admitted again.

A NEW RUN ALWAYS OPENS A NEW EPISODE, under an id this service mints; a caller never names the
episode a first run writes into. `ResearchRequest.episode_id` means CONTINUE that episode, and only
`research.continuation`'s rules lead there: the opener's own, SUSPENDED (or left by a run that
died) episode in this project, resumed through `006b`'s lifecycle, reasoning over the hypothesis set
it already debated. Every run is recorded in `012c`'s `research_runs` under a lease on its episode.

A STAGE THAT FAILS DOES NOT TAKE THE REPORT WITH IT. Each stage records DONE / SKIPPED / REFUSED /
FAILED with its reason; later stages that depend on it are SKIPPED and say why. Only authorization
is fatal: an actor who may not read the project gets no report at all (`ScientificReadRefused`).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, cast

from lab_brain.cognition.brain import HypothesisBrain, set_divergence_gate
from lab_brain.cognition.budgeted import BudgetedInferenceDispatcher, cost_contract_for
from lab_brain.cognition.catalog_reasoner import PROVIDER as CATALOG_PROVIDER
from lab_brain.cognition.catalog_reasoner import CatalogReasoner, reasoner_slots
from lab_brain.cognition.debate import DebateOutcome, DebatePolicy, DebateRequest, StructuredDebate
from lab_brain.cognition.debate_metrics import DebateGate
from lab_brain.cognition.evidence import EvidenceItem, EvidenceResearcher, StaticEvidenceCatalog
from lab_brain.cognition.llm import Completion, ModelSlot, PromptTemplate, ScientificLLM
from lab_brain.cognition.roles import core_prompts
from lab_brain.cognition.routing import ModelRouter
from lab_brain.composition import IngestionService
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.hypothesis_admission import HypothesisAdmissionService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.belief_event import BeliefRevisionEvent, BeliefState
from lab_brain.core.models.cost import BudgetCaps, CostVector
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.episode import EpisodeState
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.models.job import JobState
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.repositories.belief_events import (
    SqlBeliefEventStore,
    SqlBeliefTransitionDecisionStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.benchmark import SqlBenchmarkStore
from lab_brain.core.repositories.budget import SqlBudgetApprovalClaims, SqlCostLedger
from lab_brain.core.repositories.conditions import SqlConditionSchemaStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.debate import SqlDebateStore
from lab_brain.core.repositories.episodes import SqlEpisodeStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.evidence_bundles import SqlEvidenceBundleRepository
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.repositories.failures import SqlFailureStore
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.inference import SqlInferenceProvenanceStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.observability import SqlSpanRepository
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.repositories.source_works import SqlClaimStore, SqlSourceWorkStore
from lab_brain.core.repositories.verification_plans import SqlVerificationPlanStore
from lab_brain.core.revision_gate import HypothesisRevisionGate
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.evidence.dense_index import EmbeddingSpace, hashing_embedder
from lab_brain.evidence.source_policy import SourcePolicyRegistry, default_source_policies
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.research.continuation import (
    INTERRUPTED,
    ContinuationJobs,
    ContinuationRefused,
    EpisodeFinished,
    EpisodeInProgress,
    EpisodeNotContinuable,
    ExcludingPlanner,
    PriorVerification,
    ResearchRunRecord,
    SqlResearchRunStore,
    load_debate,
    prior_verification,
)
from lab_brain.research.evidence import (
    DOCUMENT_STATEMENT_SCHEMA,
    AdmittedStatement,
    StatementAdmitter,
)
from lab_brain.research.literature import LiteratureRequest, LiteratureResult, run_literature_stage
from lab_brain.research.reasoning import ReasoningRuntime
from lab_brain.research.report import (
    ActionLine,
    BeliefLine,
    Conclusion,
    ContinuationSection,
    DebateSection,
    EpisodeReport,
    EvidenceLine,
    HypothesisLine,
    InputStatus,
    LiteratureLine,
    LiteratureSection,
    PendingAction,
    PlanLine,
    StageStatus,
)
from lab_brain.research.vertical import (
    BlockedCapability,
    InputRefused,
    ProductVertical,
    VerificationInput,
    VerticalFactory,
)
from lab_brain.security.egress import EgressAuditLog, EgressGate
from lab_brain.security.external import AuthorizedExternalRunner, ExternalReach
from lab_brain.storage.postgres.capabilities import PostgresResourceBroker
from lab_brain.storage.postgres.external_artifacts import SqlExternalArtifactSink
from lab_brain.storage.postgres.run_outputs import SqlRunOutputSink
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from lab_brain.surface.ingestion_item import derive_state
from lab_brain.tools.dispatch import BudgetedToolDispatcher
from lab_brain.verification.least_cost import LeastCostPlanner
from lab_brain.verification.loop import (
    LoopDependencies,
    LoopRequest,
    LoopResult,
    Planner,
    VerificationLoop,
)
from lab_brain.verification.workflows import WorkflowStatus

#: The genesis policy a debate's hypotheses are admitted under (DRAFT -> ACTIVE).
ADMISSION_POLICY = TransitionPolicy(
    policy_id="tp:research.admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)
EMBEDDING_SPACE = EmbeddingSpace(model="hashing-embedder", version="1.0.0", dimensions=64)
EMBEDDING_SLOT = ModelSlot(
    LogicalSlot.EMBEDDING,
    EMBEDDING_SPACE.model,
    EMBEDDING_SPACE.version,
    provider="local",
    reach=ExternalReach.LOCAL,
)
REASONING_SLOTS = (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY)
BUDGET_POLICY_ID = "bp:research-run"

#: Stops that wait on something outside the episode: it is parked, not closed.
_WAITING = frozenset({"HUMAN_ACTION_REQUIRED", "AWAITING_RESOURCE", "BUDGET_BLOCKED"})


@dataclass(frozen=True)
class InputDocument:
    name: str
    data: bytes
    media_type: str
    uri: str
    #: The trust class the USER declares for this file's statements (§6.5) -- never inferred.
    trust_class: TrustClass


@dataclass(frozen=True)
class ProjectData:
    """Research data ALREADY in the project (`research.data`): an artifact ingested earlier, used
    as it was ingested. Its units are admitted for this run exactly as an uploaded document's are;
    nothing is ingested again and no unit is copied."""

    artifact_id: str
    name: str
    #: The trust class the USER declares for this material in this run (§6.5) -- never inferred.
    trust_class: TrustClass


@dataclass(frozen=True)
class ResearchRequest:
    project_id: str
    actor_id: str
    goal: str
    documents: tuple[InputDocument, ...]
    #: (display name, bytes) of the pack's verification input, e.g. a device project.
    verification_input: tuple[str, bytes] | None = None
    literature: LiteratureRequest | None = None
    #: CONTINUE this episode (`research.continuation`). `None` opens a new one under a minted id.
    #: A continuation carries no documents, verification input, literature or framing, and its
    #: goal, when given, must be the episode's.
    episode_id: str | None = None
    trace_id: str | None = None
    #: The classification of the goal and the documents in this project (§14.1).
    sensitivity: SensitivityLabel = SensitivityLabel.INTERNAL
    symptom: str | None = None
    expected_behavior: str | None = None
    observed_behavior: str | None = None
    token_budget: int = 200_000
    wall_clock_budget_s: int = 86_400
    max_steps: int = 8
    #: Research data already in the project, used as ingested (see `ProjectData`).
    project_data: tuple[ProjectData, ...] = ()


class UuidEpisodeIds:
    """`BeliefEpisode`'s ids for a production episode: random, never reused."""

    def decision_id(self) -> str:
        return f"dec:{new_id('trace').split(':', 1)[1]}"

    def event_id(self) -> str:
        return new_id("belief_revision_event")

    def conflict_id(self) -> str:
        return f"cfl:{new_id('trace').split(':', 1)[1]}"

    def review_id(self) -> str:
        return f"rvw:{new_id('trace').split(':', 1)[1]}"


@dataclass(frozen=True)
class _Continuation:
    """What a continuation resumed from, checked before anything was written."""

    earlier: tuple[ResearchRunRecord, ...]
    resumed_from: str
    resumed_reason: str | None
    interrupted: tuple[int, ...]
    orphaned_jobs: tuple[str, ...]
    superseded_jobs: tuple[str, ...]
    prior: PriorVerification
    debate: DebateOutcome | None


@dataclass
class _Run:
    """What the stages produced, as the report is assembled from it."""

    record: ResearchRunRecord
    continuation: _Continuation | None = None
    stages: list[StageStatus] = field(default_factory=list)
    inputs: list[InputStatus] = field(default_factory=list)
    statements: list[AdmittedStatement] = field(default_factory=list)
    verification: VerificationInput | None = None
    verification_artifact: str | None = None
    literature: LiteratureResult | None = None
    debate: DebateOutcome | None = None
    loop: LoopResult | None = None
    loop_request: LoopRequest | None = None
    pending: list[PendingAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def stage(self, name: str, status: str, detail: str) -> None:
        self.stages.append(StageStatus(name, status, detail))


def debate_minimum(vertical: ProductVertical) -> int:
    """How many competing hypotheses Stage A asks for in this vertical: one per mechanism its
    DomainPack catalogues -- the domain's number, which the generic LLM runtime is GIVEN (a model on
    REASONING_PRIMARY must have demonstrated it) and never assumes."""
    return len(vertical.catalog.mechanisms)


class ResearchEpisodeService:
    def __init__(
        self,
        *,
        connection: Any,
        artifact_store: Any,
        vertical_factory: VerticalFactory,
        clock: Callable[[], dt.datetime] = utc_now,
        mint: Callable[[str], str] = new_id,
        reasoning: ReasoningRuntime | None = None,
    ) -> None:
        """`reasoning` is the active language-model runtime, if one is active. `None` is the
        explicit fallback: the pack's local catalog reasoner serves every model slot."""
        self._connection = connection
        self._store = artifact_store
        self._factory = vertical_factory
        self._clock = clock
        self._mint = mint
        self._reasoning = reasoning
        self._service = IngestionService(
            connection=connection, artifact_store=artifact_store, clock=clock
        )

    # -- the episode --------------------------------------------------------------------------

    def run(self, request: ResearchRequest) -> EpisodeReport:
        # Authorization first and fatal: no episode, no rows, no report for a non-member.
        gate = self._service.read_gate()
        gate.require_project(actor_id=request.actor_id, project_id=request.project_id)
        # Research data the run will use must be THIS project's and readable by this actor --
        # checked before anything is written, with the same one refusal for every reason.
        for data in request.project_data:
            decision = gate.authorize_artifact(
                actor_id=request.actor_id,
                project_id=request.project_id,
                artifact_id=data.artifact_id,
            )
            if not decision.allowed:
                raise ScientificReadRefused(decision)
        if request.episode_id is not None:
            return self._continue(request, request.episode_id)
        return self._open(request)

    def _open(self, request: ResearchRequest) -> EpisodeReport:
        """A new episode, under an id minted here -- never one the caller names."""
        if not request.goal.strip():
            raise ValueError("a research run that opens an episode needs a goal")
        c = self._connection
        ledger = SqlResearchRunStore(c)
        episode_id = self._mint("episode")
        if not ledger.lease(episode_id):  # pragma: no cover - nobody else knows a minted id
            raise EpisodeInProgress(f"episode {episode_id} is held by another research run")
        record: ResearchRunRecord | None = None
        try:
            started = self._clock()
            vertical, outputs = self._vertical()
            episode = self._service.open_episode(
                project_id=request.project_id,
                goal=request.goal,
                trace_id=request.trace_id or new_id("trace"),
                episode_id=episode_id,
            )
            # `012c` refuses this row unless the episode is this project's, new and gathering.
            record = ledger.start(
                ResearchRunRecord(
                    research_run_id=self._mint("research_run"),
                    episode_id=episode.episode_id,
                    project_id=request.project_id,
                    actor_id=request.actor_id,
                    ordinal=1,
                    hypothesis_set_id=None,
                    verification_artifact_id=None,
                    symptom=request.symptom,
                    expected_behavior=request.expected_behavior,
                    observed_behavior=request.observed_behavior,
                    started_at=started,
                )
            )
            run = _Run(record=record)
            budget = self._budget(request)
            self._ingest(request, episode.episode_id, episode.trace_id, run)
            self._verification_input(request, vertical, outputs, run)
            if run.verification_artifact is not None:
                ledger.record_verification_input(record.research_run_id, run.verification_artifact)
            self._literature(request, vertical, run)
            # Before the debate: if it fails, a continuation retries it over exactly these.
            ledger.record_statements(record.research_run_id, run.statements, at=self._clock())
            debated = self._debate(
                request, vertical, episode.episode_id, episode.trace_id, budget, run
            )
            if run.debate is not None:
                ledger.record_hypothesis_set(
                    record.research_run_id, run.debate.hypothesis_set.set_id
                )
            if debated is not None:
                self._verify(
                    request, vertical, episode.episode_id, episode.trace_id, budget, *debated, run
                )
            report = self._report(
                request, vertical, episode.episode_id, episode.trace_id, started, run
            )
            ledger.finish(record.research_run_id, outcome=_outcome(report), at=self._clock())
            return report
        except BaseException as failed:
            self._abandon(ledger, record, failed)
            raise
        finally:
            with suppress(Exception):
                ledger.release(episode_id)

    def _continue(self, request: ResearchRequest, episode_id: str) -> EpisodeReport:
        """The same episode, resumed through its lifecycle, over the reasoning it already has.

        Every refusal happens before the first write. The order is the security argument: the
        request's own shape first (no read at all), then ONE scoped lookup whose every miss gets
        the same answer, and only then -- for the opener's own episode -- the lease and the state.
        """
        _require_nothing_new(request)
        c = self._connection
        ledger = SqlResearchRunStore(c)
        opener = ledger.opener(project_id=request.project_id, episode_id=episode_id)
        if opener is None or opener.actor_id != request.actor_id:
            raise EpisodeNotContinuable(
                episode_id=episode_id, actor_id=request.actor_id, project_id=request.project_id
            )
        if not ledger.lease(episode_id):
            raise EpisodeInProgress(
                f"Episode {episode_id} has a research run in progress; continue it after that "
                "run has finished."
            )
        record: ResearchRunRecord | None = None
        try:
            # Read again under the lease: the opening run records its set and input while it is
            # live, so only now is what it recorded final. Who opened it cannot have changed.
            opener = ledger.opener(project_id=request.project_id, episode_id=episode_id) or opener
            episodes = SqlEpisodeStore(c)
            episode = episodes.get(episode_id)
            assert episode is not None  # `012c`'s foreign key from the opening run
            if episode.state in (EpisodeState.COMPLETED, EpisodeState.ABANDONED):
                raise EpisodeFinished(
                    f"Episode {episode_id} is {episode.state.value} "
                    f"({episode.outcome_status or 'no outcome recorded'}); a finished episode "
                    "receives no new research run. Open a new episode: `research run` without "
                    "--episode."
                )
            if request.goal.strip() and request.goal != episode.goal:
                raise ContinuationRefused(
                    f"Episode {episode_id} is about {episode.goal!r}; a continuation keeps the "
                    "episode's goal. Open a new episode for a new question."
                )
            if request.trace_id is not None and request.trace_id != episode.trace_id:
                raise ContinuationRefused(
                    f"Episode {episode_id} runs on trace {episode.trace_id}; a continuation keeps "
                    "the episode's trace."
                )
            # The reasoning history, loaded and checked BEFORE anything is written: the set a run
            # of the episode recorded (the opener's, or a retry's), else -- no set at all -- the
            # opening run's admitted statements, for retrying the debate that never produced one.
            recorded = ledger.recorded_set(project_id=request.project_id, episode_id=episode_id)
            debate: DebateOutcome | None = None
            retry: tuple[AdmittedStatement, ...] = ()
            if recorded is not None:
                debate = load_debate(
                    c,
                    project_id=request.project_id,
                    episode_id=episode_id,
                    set_id=recorded,
                )
            elif sets := ledger.other_hypothesis_sets(
                project_id=request.project_id, episode_id=episode_id
            ):
                raise ContinuationRefused(
                    f"Episode {episode_id}'s opening run was interrupted after its debate wrote "
                    f"{', '.join(sets)} and before the run recorded it; an incomplete reasoning "
                    "history is neither continued nor replaced. Open a new episode."
                )
            else:
                retry = ledger.statements(opener.research_run_id)
            if (
                opener.verification_artifact_id is not None
                and self._read_bytes(opener.verification_artifact_id) is None
            ):
                raise ContinuationRefused(
                    f"Episode {episode_id}'s verification input {opener.verification_artifact_id} "
                    "is not in this artifact store; continue with the --artifact-root the episode "
                    "was run with."
                )

            # -- writes start here -----------------------------------------------------------
            started = self._clock()
            # We hold the lease, so a run still marked live died with its connection.
            interrupted = ledger.interrupt_live(
                project_id=request.project_id, episode_id=episode_id, at=started
            )
            jobs = SqlJobStore(c)
            prior = prior_verification(
                jobs, c, project_id=request.project_id, episode_id=episode_id
            )
            research_run_id = self._mint("research_run")
            for orphan in prior.orphaned:
                jobs.transition(
                    orphan.job_id,
                    JobState.FAILED,
                    started,
                    structured_error={
                        "code": "RESEARCH_RUN_INTERRUPTED",
                        "detail": (
                            f"the research run executing this job on episode {episode_id} ended "
                            "without recording a Run; a continuation does not resume an "
                            "execution whose outcome it cannot know"
                        ),
                    },
                )
            for parked in prior.parked:
                jobs.transition(
                    parked.job_id,
                    JobState.CANCELLED,
                    started,
                    structured_error={
                        "code": "SUPERSEDED_BY_CONTINUATION",
                        "detail": (
                            f"parked by an earlier research run of episode {episode_id} and never "
                            f"run; research run {research_run_id} continues the episode and "
                            "submits its own job if it still chooses this check"
                        ),
                    },
                )
            resumed_from, resumed_reason = episode.state.value, episode.suspend_reason
            # THE AUTHORITATIVE LIFECYCLE: `episode_resume` locks the row and refuses a finished
            # episode; `012c` refuses the run below unless the episode is now gathering evidence.
            episode = episodes.resume(episode_id)
            earlier = ledger.runs(project_id=request.project_id, episode_id=episode_id)
            record = ledger.start(
                ResearchRunRecord(
                    research_run_id=research_run_id,
                    episode_id=episode_id,
                    project_id=request.project_id,
                    actor_id=request.actor_id,
                    ordinal=len(earlier) + 1,
                    hypothesis_set_id=recorded,
                    verification_artifact_id=opener.verification_artifact_id,
                    symptom=opener.symptom,
                    expected_behavior=opener.expected_behavior,
                    observed_behavior=opener.observed_behavior,
                    started_at=started,
                )
            )
            # The episode's own framing, from here on: this request adds nothing.
            effective = dataclasses.replace(
                request,
                goal=episode.goal,
                trace_id=episode.trace_id,
                symptom=opener.symptom,
                expected_behavior=opener.expected_behavior,
                observed_behavior=opener.observed_behavior,
            )
            run = _Run(
                record=record,
                continuation=_Continuation(
                    earlier=earlier,
                    resumed_from=resumed_from,
                    resumed_reason=resumed_reason,
                    interrupted=interrupted,
                    orphaned_jobs=tuple(o.job_id for o in prior.orphaned),
                    superseded_jobs=tuple(j.job_id for j in prior.parked),
                    prior=prior,
                    debate=debate,
                ),
            )
            vertical, _outputs = self._vertical()
            budget = self._budget(effective)
            run.stage(
                "episode",
                "RESUMED",
                f"run {record.ordinal} of this episode; resumed through episode_resume from "
                f"{resumed_from}" + (f" ({resumed_reason})" if resumed_reason else ""),
            )
            run.stage(
                "ingestion",
                "SKIPPED",
                "a continuation takes no new documents; the episode's evidence stands as admitted",
            )
            if retry:
                run.statements.extend(retry)
                run.stage(
                    "evidence",
                    "RESUMED",
                    f"{len(retry)} statement(s) admitted by run {opener.ordinal}, reasoned over as "
                    "admitted: nothing ingested or admitted again",
                )
            else:
                run.stage(
                    "evidence", "SKIPPED", "no statements added; the episode's own are unchanged"
                )
            self._resumed_input(vertical, opener, run)
            run.stage("external evidence", "SKIPPED", "a continuation contacts no external source")
            debated = self._debate(
                effective, vertical, episode_id, episode.trace_id, budget, run, resumed=debate
            )
            if debate is None and run.debate is not None:
                # The retried debate produced the episode's first set: recorded once, by this run.
                ledger.record_hypothesis_set(
                    record.research_run_id, run.debate.hypothesis_set.set_id
                )
            if debated is not None:
                self._verify(
                    effective, vertical, episode_id, episode.trace_id, budget, *debated, run
                )
            report = self._report(effective, vertical, episode_id, episode.trace_id, started, run)
            ledger.finish(record.research_run_id, outcome=_outcome(report), at=self._clock())
            return report
        except BaseException as failed:
            self._abandon(ledger, record, failed)
            raise
        finally:
            with suppress(Exception):
                ledger.release(episode_id)

    def _abandon(
        self, ledger: SqlResearchRunStore, record: ResearchRunRecord | None, failed: BaseException
    ) -> None:
        """Finish a run that raised, if the connection still allows it. If not, its lease dies
        with the session and the next continuation records it INTERRUPTED."""
        if record is None:
            return
        with suppress(Exception):
            ledger.finish(
                record.research_run_id,
                outcome=f"FAILED:{type(failed).__name__}",
                at=self._clock(),
            )

    def hypothesis_minimum(self) -> int:
        """How many competing hypotheses this deployment's research asks the Hypothesis Engine
        for (`debate_minimum` of its vertical): the number a model serving REASONING_PRIMARY must
        have demonstrated. A read: the vertical is built and nothing is registered or written."""
        c = self._connection
        vertical = self._factory(
            outputs=SqlRunOutputSink(connection=c, store=self._store, now=self._clock),
            jobs=SqlJobStore(c),
            broker=PostgresResourceBroker(c),
            now=self._clock,
        )
        return debate_minimum(vertical)

    def capabilities(self) -> tuple[str, Mapping[str, str], tuple[BlockedCapability, ...]]:
        """What this deployment can execute and what it cannot, as the report's deployment
        section states it: (domain, executable backends, blocked capabilities). A read: the
        vertical is built and nothing is registered or written."""
        c = self._connection
        vertical = self._factory(
            outputs=SqlRunOutputSink(connection=c, store=self._store, now=self._clock),
            jobs=SqlJobStore(c),
            broker=PostgresResourceBroker(c),
            now=self._clock,
        )
        return vertical.domain, dict(vertical.backends), tuple(vertical.blocked)

    def _vertical(self) -> tuple[ProductVertical, SqlRunOutputSink]:
        c = self._connection
        outputs = SqlRunOutputSink(connection=c, store=self._store, now=self._clock)
        vertical = self._factory(
            outputs=outputs, jobs=SqlJobStore(c), broker=PostgresResourceBroker(c), now=self._clock
        )
        self._register(vertical)
        return vertical, outputs

    @staticmethod
    def _budget(request: ResearchRequest) -> BudgetPolicy:
        return BudgetPolicy(
            policy_id=BUDGET_POLICY_ID,
            policy_version="1.0.0",
            project_id=request.project_id,
            caps=BudgetCaps(
                token_count=request.token_budget, wall_clock_s=request.wall_clock_budget_s
            ),
        )

    def _resumed_input(
        self, vertical: ProductVertical, opener: ResearchRunRecord, run: _Run
    ) -> None:
        """The opening run's verification input, read back from the artifact store."""
        artifact_id = opener.verification_artifact_id
        data = self._read_bytes(artifact_id) if artifact_id is not None else None
        if artifact_id is None or data is None:
            run.stage(
                "verification input",
                "SKIPPED",
                "the episode's opening run recorded no verification input",
            )
            return
        name = f"verification input of run {opener.ordinal}"
        try:
            reading = vertical.read_input(data)
        except InputRefused as refused:
            run.inputs.append(
                InputStatus(
                    name,
                    "verification input",
                    vertical.input_media_type,
                    artifact_id,
                    "REFUSED",
                    detail=str(refused),
                )
            )
            run.stage("verification input", "REFUSED", str(refused))
            return
        run.verification = reading
        run.verification_artifact = artifact_id
        run.inputs.append(
            InputStatus(
                name,
                "verification input",
                reading.kind,
                artifact_id,
                "STORED",
                detail=reading.summary,
            )
        )
        run.stage(
            "verification input", "DONE", f"reused from run {opener.ordinal}: {reading.summary}"
        )

    # -- durable registrations the episode stands on --------------------------------------------

    def _register(self, vertical: ProductVertical) -> None:
        c = self._connection
        schemas = SqlConditionSchemaStore(c)
        schemas.ensure(DOCUMENT_STATEMENT_SCHEMA)
        for registration in vertical.condition_schemas:
            schemas.ensure(registration)
        policies = SqlTransitionPolicyStore(c)
        for policy in (ADMISSION_POLICY, *vertical.transition_policies):
            if policies.get(policy.policy_id, policy.version) is None:
                policies.register(policy)
        benchmarks = SqlBenchmarkStore(c)
        for space in vertical.registry.registries.disagreement_metrics.declared_spaces():
            if benchmarks.outcome_space(space.outcome_space_id, space.version) is None:
                benchmarks.add_outcome_space(space)

    # -- 1. ingest + 2. statements ----------------------------------------------------------------

    def _ingest(self, request: ResearchRequest, episode_id: str, trace_id: str, run: _Run) -> None:
        if not request.documents and not request.project_data:
            run.stage("ingestion", "SKIPPED", "no research documents were given")
            run.stage("evidence", "SKIPPED", "no documents to read statements from")
            return
        evidence_sink = SqlEvidenceSink(connection=self._connection, outputs=None)  # type: ignore[arg-type]
        admitter = StatementAdmitter(
            service=self._service,
            load_artifact=evidence_sink.load_artifact,
            read_bytes=self._read_bytes,
            claims=SqlClaimStore(self._connection),
            attestations=SqlAttestationStore(self._connection),
            mint=self._mint,
            now=self._clock,
        )
        ingested = 0
        for document in request.documents:
            digest = hashlib.sha256(document.data).hexdigest()
            job = self._service.submit(
                project_id=request.project_id,
                actor_id=request.actor_id,
                idempotency_key=f"episode:{episode_id}:{digest}",
                trace_id=trace_id,
                episode_id=episode_id,
            )
            result = self._service.ingest(
                document.data,
                job_id=job.job_id,
                actor_id=request.actor_id,
                sensitivity_label=request.sensitivity,
                uri=document.uri,
                media_type=document.media_type,
            )
            artifact_id = result.artifact.artifact_id if result.artifact is not None else None
            statements: tuple[AdmittedStatement, ...] = ()
            detail = ""
            if result.succeeded and artifact_id is not None:
                ingested += 1
                statements = admitter.admit(
                    project_id=request.project_id,
                    actor_id=request.actor_id,
                    artifact_id=artifact_id,
                    trust_class=document.trust_class,
                    source_name=document.name,
                )
                run.statements.extend(statements)
            else:
                failed = [r.reason_code for r in result.outcome.stage_results if r.reason_code]
                detail = "ingestion did not succeed: " + (", ".join(failed) or "no evidence units")
            run.inputs.append(
                InputStatus(
                    name=document.name,
                    role="document",
                    declared_kind=document.trust_class.value,
                    artifact_id=artifact_id,
                    state=self._inbox_state(request, result.outcome.item_id),
                    job_id=job.job_id,
                    run_id=result.run.run_id if result.run is not None else None,
                    evidence_units=len(result.evidence_units),
                    statements=len(statements),
                    detail=detail,
                )
            )
        # Research data already in the project: its units, admitted as they were ingested. No job,
        # no second ingestion, no copied unit -- the run's admission is the only new record, and
        # it is the one an uploaded document gets.
        for data in request.project_data:
            statements = admitter.admit(
                project_id=request.project_id,
                actor_id=request.actor_id,
                artifact_id=data.artifact_id,
                trust_class=data.trust_class,
                source_name=data.name,
            )
            run.statements.extend(statements)
            run.inputs.append(
                InputStatus(
                    name=data.name,
                    role="research data",
                    declared_kind=data.trust_class.value,
                    artifact_id=data.artifact_id,
                    state=self._artifact_state(request, data.artifact_id),
                    evidence_units=self._unit_count(request.project_id, data.artifact_id),
                    statements=len(statements),
                    detail="already in the project; used as ingested, not ingested again",
                )
            )
        total = len(request.documents)
        if request.project_data:
            run.stage(
                "ingestion",
                "DONE" if ingested == total else ("PARTIAL" if ingested else "FAILED"),
                f"{ingested} of {total} new document(s) stored, parsed and segmented; "
                f"{len(request.project_data)} research data item(s) already in the project used "
                "as ingested",
            )
        else:
            run.stage(
                "ingestion",
                "DONE" if ingested == total else ("PARTIAL" if ingested else "FAILED"),
                f"{ingested} of {total} document(s) stored, parsed and segmented",
            )
        run.stage(
            "evidence",
            "DONE" if run.statements else "SKIPPED",
            f"{len(run.statements)} verbatim statement(s) admitted as REPORTED evidence through "
            "the admission gate",
        )

    def _inbox_state(self, request: ResearchRequest, item_id: str) -> str:
        view = self._service.inbox(actor_id=request.actor_id, project_id=request.project_id)
        for item in view.items:
            if item.item_id == item_id:
                return derive_state(
                    item,
                    jobs=view.jobs_for(item.item_id),
                    open_review_ids=view.open_review_ids,
                    blocking_conflict_ids=view.blocking_conflict_ids,
                ).value
        return "UNKNOWN"

    def _artifact_state(self, request: ResearchRequest, artifact_id: str) -> str:
        """The derived state of the project's FIRST item holding this artifact."""
        view = self._service.inbox(actor_id=request.actor_id, project_id=request.project_id)
        holders = sorted(
            (i for i in view.items if i.raw_artifact_id == artifact_id),
            key=lambda i: (i.submitted_at, i.item_id),
        )
        return self._inbox_state(request, holders[0].item_id) if holders else "UNKNOWN"

    def _unit_count(self, project_id: str, artifact_id: str) -> int:
        row = self._connection.execute(
            "SELECT count(*) FROM evidence_unit_occurrences"
            " WHERE project_id = %s AND artifact_id = %s",
            (project_id, artifact_id),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def _read_bytes(self, artifact_id: str) -> bytes | None:
        content_hash = artifact_id.removeprefix("art:")
        if not self._store.exists(content_hash):
            return None
        data: bytes = self._store.open(content_hash)
        return data

    # -- 3. the verification input ----------------------------------------------------------------

    def _verification_input(
        self,
        request: ResearchRequest,
        vertical: ProductVertical,
        outputs: SqlRunOutputSink,
        run: _Run,
    ) -> None:
        if request.verification_input is None:
            run.stage(
                "verification input",
                "SKIPPED",
                "no verification input was given; verification planning needs one",
            )
            return
        name, data = request.verification_input
        try:
            reading = vertical.read_input(data)
        except InputRefused as refused:
            run.inputs.append(
                InputStatus(
                    name,
                    "verification input",
                    vertical.input_media_type,
                    None,
                    "REFUSED",
                    detail=str(refused),
                )
            )
            run.stage("verification input", "REFUSED", str(refused))
            return
        artifact_id = outputs.put(
            project_id=request.project_id, media_type=vertical.input_media_type, data=data
        )
        run.verification = reading
        run.verification_artifact = artifact_id
        run.inputs.append(
            InputStatus(
                name,
                "verification input",
                reading.kind,
                artifact_id,
                "STORED",
                detail=reading.summary,
            )
        )
        run.stage("verification input", "DONE", reading.summary)

    # -- 4. external literature --------------------------------------------------------------------

    def _literature(self, request: ResearchRequest, vertical: ProductVertical, run: _Run) -> None:
        if request.literature is None:
            run.stage(
                "external evidence",
                "SKIPPED",
                "no literature provider and public query were given; no external source was "
                "contacted",
            )
            return
        c = self._connection
        store = SqlExternalSourceStore(c)
        try:
            result = run_literature_stage(
                request.literature,
                project_id=request.project_id,
                actor_id=request.actor_id,
                clearance=self._clearance(request.actor_id, request.project_id),
                classifier=self._classifier(),
                store=store,
                sink=SqlExternalArtifactSink(connection=c, store=self._store, now=self._clock),
                works=SqlSourceWorkStore(c),
                claims=SqlClaimStore(c),
                attestations=SqlAttestationStore(c),
                gate=EvidenceAdmissionGate(
                    load_artifact=SqlEvidenceSink(connection=c, outputs=None).load_artifact,  # type: ignore[arg-type]
                    load_evidence_unit=lambda _unit: None,
                ),
                mint=self._mint,
                now=self._clock,
            )
        except Exception as failed:  # the report records the failure; the episode continues
            run.stage("external evidence", "FAILED", f"{type(failed).__name__}: {failed}")
            return
        run.literature = result
        run.statements.extend(result.admitted)
        run.stage(
            "external evidence",
            "DONE",
            f"{result.discovered} passage(s) discovered via {result.provider}; "
            f"{len(result.consulted)} pinned; {len(result.admitted)} admitted as REPORTED",
        )
        del vertical

    def _clearance(self, actor_id: str, project_id: str) -> frozenset[SensitivityLabel]:
        row = self._connection.execute(
            "SELECT sensitivity_clearance FROM project_memberships"
            " WHERE actor_id = %s AND project_id = %s AND active",
            (actor_id, project_id),
        ).fetchone()
        return frozenset(SensitivityLabel(v) for v in (row[0] or ())) if row else frozenset()

    def _classifier(self) -> Any:
        return self._service.classifier(
            artifact_of_cited_work=SqlExternalSourceStore(
                self._connection
            ).snapshot_artifact_of_attestation
        )

    # -- 5. competing hypotheses: M3's debate -----------------------------------------------------

    def _debate(
        self,
        request: ResearchRequest,
        vertical: ProductVertical,
        episode_id: str,
        trace_id: str,
        budget: BudgetPolicy,
        run: _Run,
        *,
        resumed: DebateOutcome | None = None,
    ) -> tuple[HypothesisBrain, BeliefEpisode] | None:
        """The episode's competing hypotheses: debated now, or -- continuing -- the debate the
        opening run recorded, and never a second one."""
        c = self._connection
        regs = vertical.registry.registries
        if run.continuation is not None and resumed is None and not run.statements:
            run.stage(
                "hypotheses",
                "SKIPPED",
                "the episode has no recorded hypothesis set and its opening run recorded no "
                "admitted statements to debate over",
            )
            run.stage("verification", "SKIPPED", "no hypotheses to verify")
            return None
        if resumed is None and not run.statements:
            run.stage("hypotheses", "SKIPPED", "no admitted evidence to debate over")
            run.stage("verification", "SKIPPED", "no hypotheses to verify")
            return None
        model_slots, complete, egress = self._model_route(vertical)
        for slot in sorted({s.logical_slot for s in model_slots}):
            contract = cost_contract_for(slot)
            if regs.capabilities.estimator(contract) is None:
                regs.capabilities.register_estimator(
                    contract, lambda params: CostVector(token_count=int(params["prompt_tokens"]))
                )
        prompts = [
            *core_prompts(),
            *(
                PromptTemplate(r.prompt_id, r.prompt_version, r.prompt_template)
                for r in regs.specialists.all()
            ),
        ]
        llm = ScientificLLM(
            slots=model_slots,
            prompts=prompts,
            complete=complete,
            runner=AuthorizedExternalRunner(gate=egress, audit=EgressAuditLog()),
            classifier=self._classifier(),
            source_policy_version="srcpol@1.0.0",
        )
        dispatcher = BudgetedInferenceDispatcher(
            service=self._service.inference_service(llm),
            estimators=regs.capabilities,
            spans=SqlSpanRepository(c),
            ledger=SqlCostLedger(c),
            claims=SqlBudgetApprovalClaims(c),
            now=self._clock,
        )
        items = tuple(
            EvidenceItem(
                attestation_id=s.attestation_id,
                project_id=s.project_id,
                text=s.text,
                trust_class=s.trust_class,
                domain=vertical.domain,
                source_work_id=s.source_work_id,
            )
            for s in run.statements
        )
        hypotheses = SqlHypothesisStore(c)
        events = SqlBeliefEventStore(c)
        debates = SqlDebateStore(c)
        attestations = SqlAttestationStore(c)
        gate = DebateGate(
            SqlBenchmarkStore(c),
            domain=vertical.domain,
            benchmark_set_id=vertical.debate_benchmark_id,
        )
        debate = StructuredDebate(
            router=ModelRouter([s.logical_slot for s in model_slots]),
            dispatcher=dispatcher,
            researcher=EvidenceResearcher(
                catalog=StaticEvidenceCatalog(items),
                bundles=SqlEvidenceBundleRepository(c),
                mint=self._mint,
                now=self._clock,
            ),
            source_policies=SourcePolicyRegistry(default_source_policies()),
            admission=HypothesisAdmissionService(
                store=hypotheses,
                append=cast(Callable[[object], BeliefRevisionEvent], events.append),
                outcome_space=regs.disagreement_metrics.outcome_space,
                provenance=SqlInferenceProvenanceStore(c).get,
                attestations=attestations.get,
                atomic=c.transaction,
            ),
            hypotheses=hypotheses,
            debates=debates,
            specialists=regs.specialists,
            metrics=regs.disagreement_metrics,
            capabilities=regs.capabilities,
            gate=gate,
            embed=hashing_embedder(EMBEDDING_SPACE),
            embedding_space=EMBEDDING_SPACE,
            policy=DebatePolicy(
                policy_id="debate:research-run",
                minimum_hypotheses=debate_minimum(vertical),
                max_rounds=2,
            ),
            mint=self._mint,
            now=self._clock,
        )
        if resumed is not None:
            outcome = resumed
            run.debate = outcome
            run.stage(
                "hypotheses",
                "RESUMED",
                f"hypothesis set `{outcome.hypothesis_set.set_id}` and debate "
                f"`{outcome.record.debate_id}` recorded by run 1: {len(outcome.certificates)} "
                "competing hypotheses, not debated again",
            )
            return self._brain(vertical, debate, hypotheses, events, debates, attestations, gate)
        try:
            outcome = debate.run(
                DebateRequest(
                    project_id=request.project_id,
                    episode_id=episode_id,
                    trace_id=trace_id,
                    actor_id=request.actor_id,
                    question=request.goal,
                    intent=vertical.intent,
                    stakes=vertical.stakes,
                    domain=vertical.domain,
                    admission_policy=ADMISSION_POLICY,
                    budget_policy=budget,
                    question_label=request.sensitivity,
                    available_inputs=(
                        frozenset({run.verification.kind})
                        if run.verification is not None
                        else frozenset()
                    ),
                )
            )
        except Exception as failed:  # recorded; verification cannot proceed without rivals
            run.stage("hypotheses", "FAILED", f"{type(failed).__name__}: {failed}")
            run.stage("verification", "SKIPPED", "the debate did not produce admitted hypotheses")
            return None
        run.debate = outcome
        run.stage(
            "hypotheses",
            "DONE",
            f"{len(outcome.certificates)} competing hypotheses admitted after "
            f"{outcome.record.rounds} debate round(s) and an independent critique"
            + (
                " -- the episode's first debate, retried: an earlier run's failed before any "
                "hypothesis set existed"
                if run.continuation is not None
                else ""
            ),
        )
        return self._brain(vertical, debate, hypotheses, events, debates, attestations, gate)

    def _model_route(
        self, vertical: ProductVertical
    ) -> tuple[list[ModelSlot], Completion, EgressGate]:
        """The slots, transport and egress gate the one `ScientificLLM` is built from."""
        if self._reasoning is None:
            # The explicit fallback. Every slot is LOCAL: nothing leaves this machine, and no
            # egress policy is declared for model calls -- a slot that were EXTERNAL would be
            # refused by this gate.
            return (
                [*reasoner_slots(vertical.catalog, REASONING_SLOTS), EMBEDDING_SLOT],
                CatalogReasoner(vertical.catalog),
                EgressGate(policy_for=lambda _p: None, clearance_of=lambda _a, _p: frozenset()),
            )
        # An active runtime: its slots and transport, the SAME gates. An EXTERNAL route leaves
        # only under THIS project's own egress policy AND the actor's own clearance.
        return (
            [*self._reasoning.slots, EMBEDDING_SLOT],
            self._reasoning.complete,
            EgressGate(policy_for=self._reasoning.egress_policy, clearance_of=self._clearance),
        )

    def _brain(
        self,
        vertical: ProductVertical,
        debate: StructuredDebate,
        hypotheses: SqlHypothesisStore,
        events: SqlBeliefEventStore,
        debates: SqlDebateStore,
        attestations: SqlAttestationStore,
        gate: DebateGate,
    ) -> tuple[HypothesisBrain, BeliefEpisode]:
        c = self._connection
        episode = BeliefEpisode(
            policies=SqlTransitionPolicyStore(c),
            decisions=SqlBeliefTransitionDecisionStore(c),
            events=events,
            relations=SqlRelationStore(c),
            authority_classes=attestations,
            conflicts=SqlConflictStore(c),
            reviews=SqlReviewItemStore(c),
            ids=UuidEpisodeIds(),
            authority_policies=vertical.authority_policies,
        )
        brain = HypothesisBrain(
            debate=debate,
            hypotheses=hypotheses,
            revision_gate=HypothesisRevisionGate(
                hypotheses=hypotheses,
                critiques=debates,
                history=events.history,
                divergence_gate=set_divergence_gate(debates, gate),
            ),
            episode=episode,
            attestations=attestations.get,
        )
        return brain, episode

    # -- 6. verification: M4's loop, and 7. the pending question --------------------------------

    def _verify(
        self,
        request: ResearchRequest,
        vertical: ProductVertical,
        episode_id: str,
        trace_id: str,
        budget: BudgetPolicy,
        brain: HypothesisBrain,
        belief: BeliefEpisode,
        run: _Run,
    ) -> None:
        assert run.debate is not None
        if run.verification is None or run.verification_artifact is None:
            run.stage(
                "verification",
                "SKIPPED",
                "no verification input: the pack's verification actions all require one",
            )
            return
        c = self._connection
        regs = vertical.registry.registries
        jobs = SqlJobStore(c)
        outputs = SqlRunOutputSink(connection=c, store=self._store, now=self._clock)
        evidence = SqlEvidenceSink(connection=c, outputs=outputs)
        failures = SqlFailureStore(c)
        events = SqlBeliefEventStore(c)
        planner = cast(
            Planner,
            LeastCostPlanner(
                capabilities=regs.capabilities,
                metrics=regs.disagreement_metrics,
                validators=regs.validators,
                mint=self._mint,
                now=self._clock,
                case_memory=failures,
            ),
        )
        loop_jobs: Any = jobs
        continuing = run.continuation
        if continuing is not None:
            # What earlier runs of THIS episode executed is never executed again, and this run's
            # jobs are keyed in its own namespace (`research.continuation`).
            planner = ExcludingPlanner(planner, _executed_before(run))
            loop_jobs = ContinuationJobs(jobs, episode_id=episode_id, ordinal=run.record.ordinal)
        loop = VerificationLoop(
            LoopDependencies(
                planner=planner,
                plans=SqlVerificationPlanStore(c),
                workflows=regs.workflows,
                capabilities=regs.capabilities,
                conditions=regs.conditions,
                authority_policy=vertical.authority_policy,
                belief=belief,
                reviser=brain,
                history=events.history,
                evidence=evidence,
                admission=EvidenceAdmissionGate(
                    load_artifact=evidence.load_artifact,
                    load_evidence_unit=lambda _unit: None,
                    load_run=jobs.get_run,
                    is_artifact_in_project=evidence.artifact_in_project,
                ),
                jobs=loop_jobs,
                dispatcher=BudgetedToolDispatcher(
                    tools=regs.tools,
                    capabilities=regs.capabilities,
                    spans=SqlSpanRepository(c),
                    ledger=SqlCostLedger(c),
                    jobs=jobs,
                    claims=SqlBudgetApprovalClaims(c),
                    now=self._clock,
                ),
                failures=failures,
                mint=self._mint,
                now=self._clock,
            )
        )
        loop_request = LoopRequest(
            project_id=request.project_id,
            episode_id=episode_id,
            trace_id=trace_id,
            actor_id=request.actor_id,
            hypothesis_set=run.debate.hypothesis_set,
            certificates=run.debate.certificates,
            symptom=request.symptom or request.goal,
            expected_behavior=request.expected_behavior or "not stated by the user",
            observed_behavior=request.observed_behavior or request.goal,
            input_artifacts=(run.verification_artifact,),
            available_inputs=frozenset({run.verification.kind}),
            conditions=dict(run.verification.conditions),
            conditions_schema_version=run.verification.conditions_schema_version,
            selection_policy=vertical.selection_policy,
            targets=vertical.targets,
            budget_policy=budget,
            max_steps=request.max_steps,
        )
        try:
            result = loop.run(loop_request)
        except Exception as failed:  # recorded; the report still shows what ran before it
            run.stage("verification", "FAILED", f"{type(failed).__name__}: {failed}")
            return
        run.loop = result
        run.loop_request = loop_request
        executed = len(result.executed)
        run.stage(
            "verification",
            "DONE",
            f"{len(result.plans)} plan(s), {executed} check(s) executed; stopped: "
            f"{result.stop_reason.value}",
        )
        if result.stop_reason.value != "CONFIRMED":
            self._pending(request, vertical, loop, loop_request, result, run)
        else:
            run.stage("pending simulation", "SKIPPED", "the root cause is confirmed")

    def _pending(
        self,
        request: ResearchRequest,
        vertical: ProductVertical,
        loop: VerificationLoop,
        loop_request: LoopRequest,
        result: LoopResult,
        run: _Run,
    ) -> None:
        """What the planner would choose if every declared capability could run here.

        Asked of the SAME planner over the loop's own final state, with the pack's declared
        descriptors in place of this deployment's. The plan is not stored: it is a question about
        a deployment that does not exist, and a VerificationPlan is a record of what WAS decided.
        """
        blocked = {b.capability_id: b for b in vertical.blocked}
        if not blocked:
            run.stage("pending simulation", "SKIPPED", "every declared capability can run here")
            return
        regs = vertical.registry.registries
        states, match = loop.planning_inputs(loop_request)
        what_if = LeastCostPlanner(
            capabilities=vertical.planning_capabilities,
            metrics=regs.disagreement_metrics,
            validators=regs.validators,
            mint=lambda kind: f"{kind}:not-stored",
            now=self._clock,
            case_memory=None,
        ).plan(
            project_id=loop_request.project_id,
            episode_id=loop_request.episode_id,
            hypotheses=states,
            targets=loop_request.targets,
            policy=loop_request.selection_policy,
            authority_policy=vertical.authority_policy,
            available_inputs=loop_request.available_inputs,
            conditions=loop_request.conditions,
            symptom=loop_request.symptom,
            exclude=frozenset(result.executed) | _executed_before(run),
            projected_condition_match=match,
        )
        plan = what_if.plan
        chosen = plan.chosen_action_id
        for action_id in plan.ranked_action_ids:
            summary = plan.sufficiency_results[action_id]
            if action_id not in blocked or not summary.sufficient:
                continue
            capability = vertical.planning_capabilities.resolve(action_id)
            cost = what_if.costs.get(action_id)
            run.pending.append(
                PendingAction(
                    capability_id=action_id,
                    action_type=capability.action_type.value,
                    best_next=action_id == chosen,
                    would_decide=_would_decide(summary.discriminating, run),
                    estimated_cost=_cost(cost),
                    blocked_because=blocked[action_id].reason,
                    requires=blocked[action_id].requires,
                )
            )
        if run.pending:
            best = next((p for p in run.pending if p.best_next), None)
            run.stage(
                "pending simulation",
                "BLOCKED",
                (
                    f"best next action {best.capability_id} requires an unavailable simulator"
                    if best is not None
                    else f"{len(run.pending)} sufficient simulation action(s) cannot run here"
                ),
            )
        else:
            run.stage(
                "pending simulation",
                "SKIPPED",
                "no simulation action would change any decision from the current state",
            )
        del request

    # -- the report --------------------------------------------------------------------------

    def _report(
        self,
        request: ResearchRequest,
        vertical: ProductVertical,
        episode_id: str,
        trace_id: str,
        started: dt.datetime,
        run: _Run,
    ) -> EpisodeReport:
        c = self._connection
        regs = vertical.registry.registries
        mechanisms: dict[str, str] = {}
        hypotheses: list[HypothesisLine] = []
        belief: list[BeliefLine] = []
        objections: dict[str, list[str]] = {}
        debate_section: DebateSection | None = None
        episode_store = SqlEpisodeStore(c)
        if run.debate is not None:
            outcome = run.debate
            for critique in outcome.critiques:
                for o in critique.objections:
                    objections.setdefault(o.target_id, []).append(
                        f"{o.kind.value} ({o.severity.value}): {o.text}"
                    )
            belief_reader = BeliefEpisode(
                policies=SqlTransitionPolicyStore(c),
                decisions=SqlBeliefTransitionDecisionStore(c),
                events=SqlBeliefEventStore(c),
                relations=SqlRelationStore(c),
                authority_classes=SqlAttestationStore(c),
                conflicts=SqlConflictStore(c),
                reviews=SqlReviewItemStore(c),
                ids=UuidEpisodeIds(),
                authority_policies=vertical.authority_policies,
            )
            for certificate in sorted(
                outcome.certificates, key=lambda x: (x.hypothesis.mechanism, x.hypothesis_id)
            ):
                h = certificate.hypothesis
                mechanisms[h.hypothesis_id] = h.mechanism
                state = belief_reader.project(
                    project_id=request.project_id,
                    hypothesis_id=h.hypothesis_id,
                    projected_at=self._clock(),
                ).current_state
                state_name = state.value if state is not None else "UNKNOWN"
                hypotheses.append(
                    HypothesisLine(
                        hypothesis_id=h.hypothesis_id,
                        mechanism=h.mechanism,
                        statement=h.statement,
                        falsifier=h.falsifier,
                        minimal_test=h.minimal_test_ref or "-",
                        predictions=tuple(_prediction(p) for p in certificate.predictions),
                        final_state=state_name,
                        objections=tuple(objections.get(h.hypothesis_id, ())),
                    )
                )
                moves = tuple(
                    f"{e.from_state.value if e.from_state else 'genesis'} -> {e.to_state.value} "
                    f"({e.policy_id}@{e.policy_version}, `{e.event_id}`)"
                    for e in SqlBeliefEventStore(c).history(request.project_id, h.hypothesis_id)
                )
                belief.append(BeliefLine(h.hypothesis_id, h.mechanism, state_name, moves))
            record = outcome.record
            reasoner = self._reasoner_of(outcome, vertical)
            debate_section = DebateSection(
                debate_id=record.debate_id,
                reasoner=reasoner,
                rounds=record.rounds,
                stop_reason=record.stop_reason,
                positions=tuple(f"{p.role_id}: {p.mechanism_view}" for p in outcome.positions),
                critic_evidence=len(
                    {a for b in (outcome.primary_bundle,) for a in b.ordered_attestation_ids}
                    | {a for b in outcome.inverted_bundles for a in b.ordered_attestation_ids}
                ),
                inverted_evidence=len(
                    {a for b in outcome.inverted_bundles for a in b.ordered_attestation_ids}
                ),
                alternatives_named=tuple(
                    sorted({m for cr in outcome.critiques for m in cr.alternative_mechanisms})
                ),
                surviving=tuple(sorted(mechanisms.get(i, i) for i in outcome.surviving_ids)),
                contradicted=tuple(sorted(mechanisms.get(i, i) for i in outcome.contradicted_ids)),
                gate=_gate(record.gate_evaluations),
            )

        plans: list[PlanLine] = []
        completed: list[ActionLine] = []
        human: list[str] = []
        failure: str | None = None
        candidates: tuple[str, ...] = ()
        conclusion = Conclusion(
            status="NOT_REACHED",
            statement="the episode did not reach verification; see Stages for why",
        )
        episode_state = "EVIDENCE_GATHERING"
        loop = run.loop
        jobs = SqlJobStore(c)
        if loop is not None:
            capabilities = regs.capabilities
            for p in loop.plans:
                plans.append(
                    PlanLine(
                        plan_id=p.plan_id,
                        decision=p.rationale.decision.value,
                        chosen=p.chosen_action_id,
                        summary=p.rationale.summary,
                        candidates=tuple(
                            _candidate(a, p.sufficiency_results[a]) for a in p.ranked_action_ids
                        ),
                    )
                )
            for step in loop.steps:
                if step.chosen is None:
                    continue
                capability = capabilities.resolve(step.chosen)
                if step.status is None:
                    human.append(
                        f"`{step.chosen}` ({capability.action_type.value}) -- {step.detail}"
                    )
                    continue
                durable = jobs.get_run(step.run_id) if step.run_id else None
                completed.append(
                    ActionLine(
                        capability_id=step.chosen,
                        action_type=capability.action_type.value,
                        status=step.status.value,
                        job_id=step.job_id,
                        run_id=step.run_id,
                        backend=vertical.backends.get(
                            step.chosen, durable.backend_id if durable else "-"
                        ),
                        outcomes=tuple(
                            f"{o.observable_ref} = **{o.outcome}** ({o.authority_class}, rule "
                            f"{o.method_ref})"
                            for o in step.outcomes
                        ),
                        output_artifacts=durable.output_artifacts if durable else (),
                        detail=step.detail if step.status is not WorkflowStatus.EXECUTED else "",
                    )
                )
            analysis = loop.failure_analysis
            failure = f"`{analysis.failure_analysis_id}` -- {analysis.resolution_status.value}" + (
                f", root cause `{analysis.confirmed_root_cause}`"
                if analysis.confirmed_root_cause
                else ""
            )
            candidates = tuple(
                f"`{h.candidate_id}`: {h.trigger_pattern} -> check {', '.join(h.suggested_checks)}"
                for h in loop.candidates
            )
            conclusion, episode_state = self._conclude(
                loop, hypotheses, mechanisms, run, request, episode_id
            )
        elif any(s.stage == "verification" and s.status == "FAILED" for s in run.stages):
            # An error is not an answer. Closing the episode would make the failure final and
            # forbid the retry; parked, it is continued -- same episode, same hypotheses.
            episode_store.suspend(
                episode_id,
                reason="verification failed with an error; continue the episode to retry",
                at=self._clock(),
            )
            episode_state = "SUSPENDED"
            conclusion = Conclusion(
                status="NOT_REACHED",
                statement=(
                    "verification failed with an error before reaching a result (see Stages); "
                    "the episode is SUSPENDED so it can be continued, not closed"
                ),
            )
        elif (
            run.debate is None
            and (
                failed := next(
                    (s for s in run.stages if s.stage == "hypotheses" and s.status == "FAILED"),
                    None,
                )
            )
            is not None
            and not SqlResearchRunStore(c).other_hypothesis_sets(
                project_id=request.project_id, episode_id=episode_id
            )
        ):
            # Not a conclusion: the debate failed before any hypothesis set existed, so nothing
            # was reasoned. Closed, the failure would be final; parked, the same episode retries
            # the debate over the statements this episode already admitted.
            episode_store.suspend(
                episode_id,
                reason=(
                    "the debate failed before a hypothesis set existed "
                    f"({failed.detail[:240]}); continue the episode to retry it"
                ),
                at=self._clock(),
            )
            episode_state = "SUSPENDED"
            conclusion = Conclusion(
                status="NOT_REACHED",
                statement=(
                    "the debate failed before producing a hypothesis set (see Stages); the episode "
                    "is SUSPENDED so it can be continued and the debate retried over the evidence "
                    "it already admitted"
                ),
            )
        else:
            episode_store.close(episode_id, outcome="NOT_REACHED", at=self._clock())
            episode_state = "COMPLETED"

        evidence_lines = tuple(
            EvidenceLine(
                attestation_id=s.attestation_id,
                source=s.source_name,
                locator=s.locator,
                trust_class=s.trust_class.value,
                excerpt=s.text,
                origin="external literature" if s.source_work_id else "internal document",
            )
            for s in run.statements
        )
        literature: LiteratureSection | None = None
        if run.literature is not None:
            lit = run.literature
            literature = LiteratureSection(
                provider=lit.provider,
                description=lit.description,
                query=lit.query,
                egress_policy=lit.egress_policy,
                discovered=lit.discovered,
                consulted=tuple(
                    LiteratureLine(
                        title=x.title,
                        locator=x.snapshot.canonical_locator,
                        trust_class=x.snapshot.trust_class.value,
                        license=x.snapshot.license_identifier or x.snapshot.license_class.value,
                        retention=x.snapshot.retention.value,
                        status=x.status or "UNKNOWN",
                        admitted_attestation_id=(
                            x.admitted.attestation_id if x.admitted is not None else None
                        ),
                        note=x.note,
                    )
                    for x in lit.consulted
                ),
                refusals=lit.refusals,
            )
        return EpisodeReport(
            episode_id=episode_id,
            project_id=request.project_id,
            actor_id=request.actor_id,
            trace_id=trace_id,
            goal=request.goal,
            domain=vertical.domain,
            started_at=started,
            finished_at=self._clock(),
            episode_state=episode_state,
            stages=tuple(run.stages),
            inputs=tuple(run.inputs),
            verification_input=(
                f"{run.verification.summary} (`{run.verification_artifact}`)"
                if run.verification is not None
                else None
            ),
            evidence=evidence_lines,
            literature=literature,
            hypotheses=tuple(hypotheses),
            debate=debate_section,
            belief=tuple(belief),
            plans=tuple(plans),
            completed=tuple(completed),
            pending=tuple(run.pending),
            human_actions=tuple(human),
            conclusion=conclusion,
            failure_analysis=failure,
            heuristic_candidates=candidates,
            next_steps=self._next_steps(run, conclusion, human, request, episode_id, episode_state),
            provenance=self._provenance(run, episode_id, trace_id),
            deployment=(
                *(
                    (
                        f"Reasoner: rules:{vertical.catalog.catalog_id}@"
                        f"{vertical.catalog.version}, a local rule-based reader of the pack's "
                        "mechanism catalog (provider local-rules, reach LOCAL). No language model "
                        "is configured or was called.",
                    )
                    if self._reasoning is None
                    else (
                        *self._reasoning.description,
                        self._reasoning.egress_statement(request.project_id),
                    )
                ),
                "Executable verification backends: "
                + ", ".join(f"`{k}` via {v}" for k, v in sorted(vertical.backends.items())),
                "Unavailable here: "
                + (
                    ", ".join(f"`{b.capability_id}` ({b.action_type})" for b in vertical.blocked)
                    or "none"
                ),
            ),
            not_performed=self._not_performed(run, vertical, self._reasoning is not None),
            notes=tuple(run.notes) + (tuple(loop.notes) if loop is not None else ()),
            continuation=self._continuation_section(run),
        )

    def _conclude(
        self,
        loop: LoopResult,
        hypotheses: Sequence[HypothesisLine],
        mechanisms: dict[str, str],
        run: _Run,
        request: ResearchRequest,
        episode_id: str,
    ) -> tuple[Conclusion, str]:
        store = SqlEpisodeStore(self._connection)
        at = self._clock()
        ruled_out = tuple(
            f"{h.mechanism} ({h.final_state})"
            for h in hypotheses
            if h.final_state in (BeliefState.CONTRADICTED.value,)
        )
        competing = tuple(
            f"{h.mechanism} ({h.final_state})"
            for h in hypotheses
            if h.final_state in (BeliefState.ACTIVE.value, BeliefState.CHALLENGED.value)
        )
        stop = loop.stop_reason.value
        if stop == "CONFIRMED" and loop.confirmed_root_cause is not None:
            cause = loop.confirmed_root_cause
            trace = loop.trace
            store.close(episode_id, outcome=f"CONFIRMED:{cause}", at=at)
            return (
                Conclusion(
                    status="CONFIRMED",
                    statement=(
                        f"the root cause is {mechanisms.get(cause, cause)} (`{cause}`): SUPPORTED "
                        "through TransitionPolicy on evidence that traces to an executed Run and "
                        "its stored artifacts"
                    ),
                    confirmed_hypothesis=cause,
                    ruled_out=ruled_out,
                    still_competing=competing,
                    trace=(
                        tuple(f"run `{r}`" for r in trace.run_ids)
                        + tuple(f"artifact `{a}`" for a in trace.artifact_ids)
                        if trace is not None
                        else ()
                    ),
                ),
                "COMPLETED",
            )
        best = next((p for p in run.pending if p.best_next), None)
        if stop in _WAITING or best is not None:
            reason = (
                f"awaiting simulator for {best.capability_id}"
                if best is not None
                else f"awaiting {stop.lower().replace('_', ' ')}"
            )
            store.suspend(episode_id, reason=reason, at=at)
            state = "SUSPENDED"
        else:
            store.close(episode_id, outcome=f"INCONCLUSIVE:{stop}", at=at)
            state = "COMPLETED"
        leading = ", ".join(c.split(" (")[0] for c in competing) or "none"
        statement = (
            f"not confirmed. The executed checks ruled out {len(ruled_out)} of "
            f"{len(hypotheses)} competing mechanisms; {len(competing)} remain ({leading}). "
            + (
                f"The check that would discriminate next is `{best.capability_id}`, a "
                f"simulation this deployment cannot run; it is pending, not assumed."
                if best is not None
                else "No further check available here would change a decision."
            )
        )
        del request
        return (
            Conclusion(
                status="PROVISIONAL" if competing else "INCONCLUSIVE",
                statement=statement,
                ruled_out=ruled_out,
                still_competing=competing,
            ),
            state,
        )

    @staticmethod
    def _next_steps(
        run: _Run,
        conclusion: Conclusion,
        human: Sequence[str],
        request: ResearchRequest,
        episode_id: str,
        episode_state: str,
    ) -> tuple[str, ...]:
        steps: list[str] = []
        for p in run.pending:
            if p.best_next:
                steps.append(
                    f"Run `{p.capability_id}` once {p.requires}; then resume this episode."
                )
        if episode_state == EpisodeState.SUSPENDED.value:
            steps.append(
                "Continue this same episode -- its hypotheses, belief states and executed checks "
                f"carry over -- with `lab-brain research run --project {request.project_id} "
                f"--actor {request.actor_id} --episode {episode_id} --artifact-root <the same "
                "artifact root>` (no new inputs)."
            )
        for action in human:
            steps.append(f"A person can act now: {action}")
        if conclusion.status == "CONFIRMED":
            steps.append("Review the confirmed root cause and its trace before acting on it.")
        if any(i.state not in ("READY", "STORED") for i in run.inputs):
            steps.append(
                "Some inputs did not become ready; `lab-brain inbox` and `lab-brain explain` "
                "show why."
            )
        if run.continuation is not None:
            pass  # a continuation takes no inputs; what it could add belongs to a new episode
        elif run.verification is None:
            steps.append("Provide the pack's verification input (a device project) to plan checks.")
        if run.continuation is None and request.literature is None:
            steps.append(
                "Optionally re-run with a literature provider and a query you declare public, so "
                "the Critic's inverted retrieval can search external literature."
            )
        return tuple(steps) or ("Nothing further is required.",)

    def _provenance(self, run: _Run, episode_id: str, trace_id: str) -> tuple[str, ...]:
        lines = [
            f"Episode `{episode_id}`, trace `{trace_id}`; research run "
            f"`{run.record.research_run_id}` (run {run.record.ordinal} of this episode)."
        ]
        if run.debate is not None:
            outcome = run.debate
            lines.append(
                f"Hypothesis set `{outcome.hypothesis_set.set_id}`; debate record "
                f"`{outcome.record.debate_id}`; primary evidence bundle "
                f"`{outcome.primary_bundle.bundle_id}`"
                + (
                    "; inverted bundles "
                    + ", ".join(f"`{b.bundle_id}`" for b in outcome.inverted_bundles)
                    if outcome.inverted_bundles
                    else ""
                )
                + "."
            )
            inference_ids = sorted(
                {p.inference_provenance_id for p in outcome.positions}
                | {cr.inference_provenance_id for cr in outcome.critiques}
            )
            models = self._connection.execute(
                "SELECT DISTINCT model_id, model_version FROM inference_provenance"
                " WHERE inference_id = ANY(%s)",
                (inference_ids,),
            ).fetchall()
            lines.append(
                f"{len(inference_ids)} recorded inference(s) (InferenceProvenance), produced by "
                + ", ".join(f"{m}@{v}" for m, v in models)
                + "."
            )
        if run.loop is not None:
            lines.append(
                "Verification plans: " + ", ".join(f"`{p.plan_id}`" for p in run.loop.plans) + "."
            )
        statements = [s for s in run.statements if not s.source_work_id]
        if statements:
            lines.append(
                f"{len(statements)} internal statement(s) extracted by "
                "research.verbatim_statement@1.0.0 from the uploaded documents."
            )
        return tuple(lines)

    def _reasoner_of(self, outcome: DebateOutcome, vertical: ProductVertical) -> str:
        """What produced this debate, as its InferenceProvenance records it -- not as the current
        configuration says: a continuation reuses a debate an earlier run's reasoner produced."""
        ids = sorted(
            {p.inference_provenance_id for p in outcome.positions}
            | {cr.inference_provenance_id for cr in outcome.critiques}
        )
        recorded = self._connection.execute(
            "SELECT DISTINCT provider, model_id, model_version, logical_slot"
            " FROM inference_provenance WHERE inference_id = ANY(%s)"
            " ORDER BY logical_slot, model_id",
            (ids,),
        ).fetchall()
        if all(r[0] == CATALOG_PROVIDER for r in recorded):
            return (
                f"rules:{vertical.catalog.catalog_id}@{vertical.catalog.version} "
                "(local rule-based catalog reasoner; no language model)"
            )
        return "language model: " + "; ".join(
            f"{slot} -> {model}@{version} via {provider}"
            for provider, model, version, slot in recorded
        )

    @staticmethod
    def _continuation_section(run: _Run) -> ContinuationSection | None:
        k = run.continuation
        if k is None:
            return None
        return ContinuationSection(
            run_ordinal=run.record.ordinal,
            resumed_from=(
                k.resumed_from
                + (f" ({k.resumed_reason})" if k.resumed_reason else "")
                + " to EVIDENCE_GATHERING through episode_resume"
            ),
            reasoning=(
                f"hypothesis set `{k.debate.hypothesis_set.set_id}` and debate "
                f"`{k.debate.record.debate_id}`, recorded by run 1 -- reused, not debated again"
                if k.debate is not None
                else "none -- the opening run recorded no hypothesis set, and a continuation "
                "never starts a debate"
            ),
            earlier_runs=tuple(
                f"run {r.ordinal} (`{r.research_run_id}`) by `{r.actor_id}`, started "
                f"{r.started_at.isoformat()}: {r.outcome or 'unfinished'}"
                for r in k.earlier
            ),
            earlier_checks=tuple(
                f"`{capability}` -- job `{job.job_id}`, run `{job.result_run_id}`"
                for capability, job in sorted(k.prior.executed.items())
            ),
            superseded_jobs=tuple(
                f"job `{j}` was parked by an earlier run and never ran; recorded CANCELLED "
                "(SUPERSEDED_BY_CONTINUATION) -- this run submits its own if it still chooses it"
                for j in k.superseded_jobs
            ),
            recovered=tuple(
                f"run {n} was left unfinished by a process that ended; recorded {INTERRUPTED}"
                for n in k.interrupted
            )
            + tuple(
                f"job `{j}` was left RUNNING by it with no Run; recorded FAILED "
                "(RESEARCH_RUN_INTERRUPTED) and not resumed"
                for j in k.orphaned_jobs
            ),
        )

    @staticmethod
    def _not_performed(
        run: _Run, vertical: ProductVertical, language_model: bool = False
    ) -> tuple[str, ...]:
        lines = (
            []
            if language_model
            else [
                "no language model was called; every hypothesis, position and critique came from "
                "the local rule-based catalog reasoner, recorded as such in its "
                "InferenceProvenance",
            ]
        )
        if run.continuation is not None:
            lines.append(
                "this run did not debate, ingest or search: it continued the episode's recorded "
                "hypotheses and inputs, and executed no check an earlier run had executed"
            )
        if vertical.blocked:
            lines.append(
                "no simulation was run and none was emulated: "
                + ", ".join(b.capability_id for b in vertical.blocked)
                + " have no backend in this deployment"
            )
        if run.literature is None:
            lines.append("no external source was contacted")
        else:
            lines.append(
                f"external evidence came only from {run.literature.description}; no network "
                "provider was contacted unless that description says so"
            )
        return tuple(lines)


def _would_decide(discriminating: Sequence[tuple[str, str, str]], run: _Run) -> tuple[str, ...]:
    """(hypothesis, to_state, outcome) triples, by mechanism, each move once, strongest first."""
    names = (
        {c.hypothesis_id: c.hypothesis.mechanism for c in run.debate.certificates}
        if run.debate is not None
        else {}
    )
    order = {"SUPPORTED": 0, "CONTRADICTED": 1, "CHALLENGED": 2}
    moves: dict[tuple[str, str], str] = {}
    for hypothesis_id, to_state, outcome in discriminating:
        key = (names.get(hypothesis_id, hypothesis_id), outcome)
        if key not in moves or order.get(to_state, 9) < order.get(moves[key], 9):
            moves[key] = to_state
    return tuple(
        f"{mechanism} -> {to_state} if {outcome}"
        for (mechanism, outcome), to_state in sorted(
            moves.items(), key=lambda kv: (kv[0][0], order.get(kv[1], 9))
        )
    )


def _cost(cost: CostVector | None) -> str:
    if cost is None:
        return "not estimated"
    parts = [
        f"{name.replace('_', ' ')} {value}"
        for name, value in cost.model_dump().items()
        if value not in (0, "0", None) and str(value) not in ("0", "NONE")
    ]
    return ", ".join(parts) or "negligible"


def _gate(evaluations: Sequence[Any]) -> str:
    """LLM-002's gate, as the debate recorded it: enforced only by a calibrated policy."""
    final = [e for e in evaluations if e.get("round") == "debate"] or list(evaluations)
    if not final:
        return "no gate evaluation recorded"
    if not any(e.get("enforced") for e in final):
        return (
            "advisory only -- no calibrated BenchmarkPolicy is active for this domain, so the "
            "debate metrics are recorded and enforce nothing"
        )
    return "; ".join(
        f"{e.get('metric_key')}: {'passed' if e.get('passed') else 'FAILED'} "
        f"({e.get('policy_ref')})"
        for e in final
    )


def _prediction(prediction: Any) -> str:
    effects = "/".join(t.relation_type.value for t in prediction.relation_effect_if_observed)
    return f"{prediction.observable_ref} = {prediction.expected_outcome} {effects}"


def _candidate(action_id: str, summary: Any) -> str:
    verdict = "sufficient" if summary.sufficient else "not sufficient"
    reason = f" ({summary.reason})" if summary.reason else ""
    return f"`{action_id}` -- {verdict}{reason}"


def _require_nothing_new(request: ResearchRequest) -> None:
    """A continuation resumes the episode's own inputs. Checked on the request alone, before any
    read, so the refusal says nothing about any episode."""
    given = [
        name
        for name, value in (
            ("documents", request.documents),
            ("research data", request.project_data),
            ("a verification input", request.verification_input),
            ("literature", request.literature),
            ("a symptom", request.symptom),
            ("an expected behavior", request.expected_behavior),
            ("an observed behavior", request.observed_behavior),
        )
        if value
    ]
    if given:
        raise ContinuationRefused(
            "A continuation resumes the episode's own inputs and takes no new ones (given: "
            + ", ".join(given)
            + "). New evidence to debate is a new episode: `research run` without --episode."
        )


def _executed_before(run: _Run) -> frozenset[str]:
    """Capabilities an earlier run of this episode executed. Empty for an opening run."""
    if run.continuation is None:
        return frozenset()
    return frozenset(run.continuation.prior.executed)


def _outcome(report: EpisodeReport) -> str:
    return f"{report.episode_state}:{report.conclusion.status}"


__all__ = [
    "ADMISSION_POLICY",
    "ContinuationRefused",
    "EpisodeFinished",
    "EpisodeInProgress",
    "EpisodeNotContinuable",
    "InputDocument",
    "ResearchEpisodeService",
    "ResearchRequest",
    "UuidEpisodeIds",
]
