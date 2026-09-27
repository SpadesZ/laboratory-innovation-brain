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
                   Critic's inverted retrieval, §8 admission, typed predictions -- with the pack's
                   rule-based catalog reasoner behind the model slots (no model is configured)
    verification   M4's `VerificationLoop` -- least-cost planning, typed tools, Jobs and Runs,
                   evidence admission, governed belief moves, the failure analysis
    pending        M4's `LeastCostPlanner` asked, over the loop's own final state, which action it
                   would choose if the pack's declared capabilities could all run here. If that is
                   a capability this deployment cannot execute, it is reported as a PENDING
                   requirement -- never executed, never mocked, never counted as evidence

THE EPISODE ENDS HONESTLY. Confirmed -> the episode is closed with that outcome. Waiting on a
simulator, a person or a seat -> the episode is SUSPENDED with the reason, so it can be resumed as
the same episode when the blocker is gone. Nothing sufficient left -> closed INCONCLUSIVE.

A STAGE THAT FAILS DOES NOT TAKE THE REPORT WITH IT. Each stage records DONE / SKIPPED / REFUSED /
FAILED with its reason; later stages that depend on it are SKIPPED and say why. Only authorization
is fatal: an actor who may not read the project gets no report at all (`ScientificReadRefused`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from lab_brain.cognition.brain import HypothesisBrain, set_divergence_gate
from lab_brain.cognition.budgeted import BudgetedInferenceDispatcher, cost_contract_for
from lab_brain.cognition.catalog_reasoner import CatalogReasoner, reasoner_slots
from lab_brain.cognition.debate import DebateOutcome, DebatePolicy, DebateRequest, StructuredDebate
from lab_brain.cognition.debate_metrics import DebateGate
from lab_brain.cognition.evidence import EvidenceItem, EvidenceResearcher, StaticEvidenceCatalog
from lab_brain.cognition.llm import ModelSlot, PromptTemplate, ScientificLLM
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
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import LogicalSlot
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
from lab_brain.evidence.dense_index import EmbeddingSpace, hashing_embedder
from lab_brain.evidence.source_policy import SourcePolicyRegistry, default_source_policies
from lab_brain.ingestion.admission_gate import EvidenceAdmissionGate
from lab_brain.research.evidence import (
    DOCUMENT_STATEMENT_SCHEMA,
    AdmittedStatement,
    StatementAdmitter,
)
from lab_brain.research.literature import LiteratureRequest, LiteratureResult, run_literature_stage
from lab_brain.research.report import (
    ActionLine,
    BeliefLine,
    Conclusion,
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
class ResearchRequest:
    project_id: str
    actor_id: str
    goal: str
    documents: tuple[InputDocument, ...]
    #: (display name, bytes) of the pack's verification input, e.g. a device project.
    verification_input: tuple[str, bytes] | None = None
    literature: LiteratureRequest | None = None
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


@dataclass
class _Run:
    """What the stages produced, as the report is assembled from it."""

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


class ResearchEpisodeService:
    def __init__(
        self,
        *,
        connection: Any,
        artifact_store: Any,
        vertical_factory: VerticalFactory,
        clock: Callable[[], dt.datetime] = utc_now,
        mint: Callable[[str], str] = new_id,
    ) -> None:
        self._connection = connection
        self._store = artifact_store
        self._factory = vertical_factory
        self._clock = clock
        self._mint = mint
        self._service = IngestionService(
            connection=connection, artifact_store=artifact_store, clock=clock
        )

    # -- the episode --------------------------------------------------------------------------

    def run(self, request: ResearchRequest) -> EpisodeReport:
        c = self._connection
        # Authorization first and fatal: no episode, no rows, no report for a non-member.
        self._service.read_gate().require_project(
            actor_id=request.actor_id, project_id=request.project_id
        )
        started = self._clock()
        jobs = SqlJobStore(c)
        outputs = SqlRunOutputSink(connection=c, store=self._store, now=self._clock)
        vertical = self._factory(
            outputs=outputs, jobs=jobs, broker=PostgresResourceBroker(c), now=self._clock
        )
        self._register(vertical)
        episode = self._service.open_episode(
            project_id=request.project_id,
            goal=request.goal,
            trace_id=request.trace_id or new_id("trace"),
            episode_id=request.episode_id,
        )
        run = _Run()
        budget = BudgetPolicy(
            policy_id=BUDGET_POLICY_ID,
            policy_version="1.0.0",
            project_id=request.project_id,
            caps=BudgetCaps(
                token_count=request.token_budget, wall_clock_s=request.wall_clock_budget_s
            ),
        )
        self._ingest(request, episode.episode_id, episode.trace_id, run)
        self._verification_input(request, vertical, outputs, run)
        self._literature(request, vertical, run)
        debated = self._debate(request, vertical, episode.episode_id, episode.trace_id, budget, run)
        if debated is not None:
            self._verify(
                request, vertical, episode.episode_id, episode.trace_id, budget, *debated, run
            )
        report = self._report(request, vertical, episode.episode_id, episode.trace_id, started, run)
        return report

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
        if not request.documents:
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
        total = len(request.documents)
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
    ) -> tuple[HypothesisBrain, BeliefEpisode] | None:
        c = self._connection
        regs = vertical.registry.registries
        if not run.statements:
            run.stage("hypotheses", "SKIPPED", "no admitted evidence to debate over")
            run.stage("verification", "SKIPPED", "no hypotheses to verify")
            return None
        for slot in (*REASONING_SLOTS, LogicalSlot.EMBEDDING):
            contract = cost_contract_for(slot)
            if regs.capabilities.estimator(contract) is None:
                regs.capabilities.register_estimator(
                    contract, lambda params: CostVector(token_count=int(params["prompt_tokens"]))
                )
        reasoner = CatalogReasoner(vertical.catalog)
        prompts = [
            *core_prompts(),
            *(
                PromptTemplate(r.prompt_id, r.prompt_version, r.prompt_template)
                for r in regs.specialists.all()
            ),
        ]
        llm = ScientificLLM(
            slots=[*reasoner_slots(vertical.catalog, REASONING_SLOTS), EMBEDDING_SLOT],
            prompts=prompts,
            complete=reasoner,
            # Every slot is LOCAL: nothing leaves this machine, and no egress policy is declared
            # for model calls -- a slot that were EXTERNAL would be refused by this gate.
            runner=AuthorizedExternalRunner(
                gate=EgressGate(
                    policy_for=lambda _p: None, clearance_of=lambda _a, _p: frozenset()
                ),
                audit=EgressAuditLog(),
            ),
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
            router=ModelRouter([*REASONING_SLOTS, LogicalSlot.EMBEDDING]),
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
                minimum_hypotheses=len(vertical.catalog.mechanisms),
                max_rounds=2,
            ),
            mint=self._mint,
            now=self._clock,
        )
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
            f"{outcome.record.rounds} debate round(s) and an independent critique",
        )
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
                jobs=jobs,
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
            exclude=frozenset(result.executed),
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
            reasoner = (
                f"rules:{vertical.catalog.catalog_id}@{vertical.catalog.version} "
                "(local rule-based catalog reasoner; no language model)"
            )
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
            next_steps=self._next_steps(run, conclusion, human, request),
            provenance=self._provenance(run, episode_id, trace_id),
            deployment=(
                f"Reasoner: rules:{vertical.catalog.catalog_id}@{vertical.catalog.version}, a "
                "local rule-based reader of the pack's mechanism catalog (provider local-rules, "
                "reach LOCAL). No language model is configured or was called.",
                "Executable verification backends: "
                + ", ".join(f"`{k}` via {v}" for k, v in sorted(vertical.backends.items())),
                "Unavailable here: "
                + (
                    ", ".join(f"`{b.capability_id}` ({b.action_type})" for b in vertical.blocked)
                    or "none"
                ),
            ),
            not_performed=self._not_performed(run, vertical),
            notes=tuple(run.notes) + (tuple(loop.notes) if loop is not None else ()),
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
        run: _Run, conclusion: Conclusion, human: Sequence[str], request: ResearchRequest
    ) -> tuple[str, ...]:
        steps: list[str] = []
        for p in run.pending:
            if p.best_next:
                steps.append(
                    f"Run `{p.capability_id}` once {p.requires}; then resume this episode."
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
        if run.verification is None:
            steps.append("Provide the pack's verification input (a device project) to plan checks.")
        if request.literature is None:
            steps.append(
                "Optionally re-run with a literature provider and a query you declare public, so "
                "the Critic's inverted retrieval can search external literature."
            )
        return tuple(steps) or ("Nothing further is required.",)

    def _provenance(self, run: _Run, episode_id: str, trace_id: str) -> tuple[str, ...]:
        lines = [f"Episode `{episode_id}`, trace `{trace_id}`."]
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

    @staticmethod
    def _not_performed(run: _Run, vertical: ProductVertical) -> tuple[str, ...]:
        lines = [
            "no language model was called; every hypothesis, position and critique came from the "
            "local rule-based catalog reasoner, recorded as such in its InferenceProvenance",
        ]
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


__all__ = [
    "ADMISSION_POLICY",
    "InputDocument",
    "ResearchEpisodeService",
    "ResearchRequest",
    "UuidEpisodeIds",
]
