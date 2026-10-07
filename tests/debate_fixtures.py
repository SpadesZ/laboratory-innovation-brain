"""M3 test infrastructure: the fixed debate fixture, a deterministic mock scientist, and a world.

THE MOCK SCIENTIST NEVER SEES THE ANSWER. Its replies are a function of the rendered prompt only --
the role's template and the CONTEXT block `ScientificLLM` appends -- and of the fixture's mechanism
CATALOG, which is domain knowledge (what each §25.1 mechanism predicts, what would falsify it, which
words in a record point at it). A case's `truth` field is read by the benchmark's scorer and by
nothing here. So when a debate finds the true mechanism and the baseline does not, it is because the
Critic's inverted retrieval put different evidence in front of the same deterministic reasoner --
which is the claim LLM-002 asks the benchmark to be able to refute.

It is deliberately a mediocre scientist: the Hypothesis Engine proposes the two best-supported
mechanisms in the evidence it is shown and stops there. That is the groupthink the debate protocol
exists to break, reproduced mechanically so it can be measured.

`MockScientist` flags turn one role into an adversary for the refusal tests: a critic that cites
evidence it was not shown, an engine that proposes a single cause, an auditor that claims global
novelty from an internal search. Each flag produces exactly the reply a misbehaving model would.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lab_brain.cognition.brain import HypothesisBrain, set_divergence_gate
from lab_brain.cognition.budgeted import BudgetedInferenceDispatcher, cost_contract_for
from lab_brain.cognition.debate import (
    DebateOutcome,
    DebatePolicy,
    DebateRequest,
    StructuredDebate,
)
from lab_brain.cognition.debate_benchmark import CONDITION_POLICIES, Condition, RunCase
from lab_brain.cognition.debate_metrics import DebateGate
from lab_brain.cognition.evidence import EvidenceItem, EvidenceResearcher, StaticEvidenceCatalog
from lab_brain.cognition.inference import ScientificInferenceService
from lab_brain.cognition.llm import ModelSlot, PromptTemplate, ScientificLLM
from lab_brain.cognition.novelty import NoveltyAuditor, PriorArtSearch, PriorArtSourceBinding
from lab_brain.cognition.roles import core_prompts
from lab_brain.cognition.routing import ModelRouter
from lab_brain.core.belief import replay, verified_history
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.hypothesis_admission import HypothesisAdmissionService
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.cost import BudgetCaps, CostVector
from lab_brain.core.models.enums import EpistemicType, RelationType, SensitivityLabel, TrustClass
from lab_brain.core.models.hypothesis import Hypothesis
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.models.prediction import OutcomeSpace, Prediction, RelationJudgmentTemplate
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.repositories.belief_events import (
    InMemoryBeliefEventStore,
    SqlBeliefEventStore,
    SqlBeliefTransitionDecisionStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.benchmark import InMemoryBenchmarkStore, SqlBenchmarkStore
from lab_brain.core.repositories.budget import (
    InMemoryBudgetApprovalClaims,
    InMemoryCostLedger,
    SqlBudgetApprovalClaims,
    SqlCostLedger,
)
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.debate import InMemoryDebateStore, SqlDebateStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.evidence_bundles import SqlEvidenceBundleRepository
from lab_brain.core.repositories.hypotheses import InMemoryHypothesisStore, SqlHypothesisStore
from lab_brain.core.repositories.inference import (
    InMemoryInferenceProvenanceStore,
    SqlInferenceProvenanceStore,
)
from lab_brain.core.repositories.memory import InMemoryEvidenceBundleRepository
from lab_brain.core.repositories.observability import (
    InMemorySpanRepository,
    SqlSpanRepository,
)
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.revision_gate import HypothesisRevisionGate
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics.plugin import DEBATE_BENCHMARK_ID
from lab_brain.domains.silicon_photonics.product import mechanism_catalog
from lab_brain.domains.silicon_photonics.tools import INPUT_DEVICE_PROJECT
from lab_brain.evidence.dense_index import EmbeddingSpace, hashing_embedder
from lab_brain.evidence.source_policy import SourcePolicyRegistry, default_source_policies
from lab_brain.security.egress import EgressAuditLog, EgressGate, EgressPolicy, PrivacyMode
from lab_brain.security.external import AuthorizedExternalRunner, ExternalReach
from lab_brain.sources.adapter import (
    ExternalSourceRecord,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
    SourceRouter,
    SourceVisibility,
)
from tests.classification_fixtures import labelled
from tests.conftest_fixtures import TOY_COMPARATOR_VERSION, make_artifact, make_attestation

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "debate" / "sp_rs_anomaly_debate.json"
#: The fixture is LOCKED. A benchmark is only fixed if its cases cannot drift silently; editing the
#: file changes this digest and `test_the_benchmark_fixture_is_locked` fails until it is updated
#: here -- in the same commit, where a reviewer sees both.
FIXTURE_SHA256 = "5127022e20e583bdd66169fca660394b2ef21188476d18c0bf4366122fca2d68"

PROJECT = "prj:m3"
EPISODE = "epi:m3"
TRACE = "trc:m3"
ACTOR = "act:researcher"
DOMAIN = "silicon_photonics"
EMBED_SPACE = EmbeddingSpace(model="hashing-embedder", version="1.0.0", dimensions=64)
T0 = dt.datetime(2026, 9, 26, 9, 0, tzinfo=dt.UTC)

ADMISSION_POLICY = TransitionPolicy(
    policy_id="tp:m3.admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fixture_digest() -> str:
    """Over LF-normalised bytes, so a checkout's line endings cannot move the benchmark's identity."""
    return hashlib.sha256(FIXTURE_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class SequentialIds:
    """Deterministic ids, `<prefix>:<kind>-<n>`. A benchmark whose ids were uuid4 would not repeat."""

    def __init__(self, scope: str = "t") -> None:
        self._counts: dict[str, int] = {}
        self._scope = scope

    def __call__(self, kind: str) -> str:
        prefix = new_id(kind).split(":", 1)[0]
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return f"{prefix}:{self._scope}-{kind}-{self._counts[kind]:04d}"


class TickingClock:
    """Each read is one second later: records ordered by time are ordered by what happened."""

    def __init__(self, start: dt.datetime = T0) -> None:
        self._now = start

    def __call__(self) -> dt.datetime:
        self._now = self._now + dt.timedelta(seconds=1)
        return self._now


def _context(material: str) -> dict[str, Any]:
    marker = "\n\nCONTEXT:\n"
    if marker not in material:
        return {}
    return json.loads(material.split(marker, 1)[1])


def _tokens(text: str) -> list[str]:
    return [t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if t]


def _typed_prefix(key: str) -> str:
    """How `typed_falsifier_text` begins for mechanism `key`'s designated falsifier; a string no
    rendering starts with when the pack's catalog does not declare the mechanism."""
    if key not in {m.key for m in mechanism_catalog().mechanisms}:
        return "\0"
    f = fixture_falsifier(key)
    return f"{f['observable_ref']} = {f['expected_outcome']} in "


@dataclass
class MockScientist:
    """The transport `ScientificLLM` calls. Deterministic, evidence-driven, answer-blind."""

    mechanisms: Mapping[str, Mapping[str, Any]]
    primary_terms: Sequence[str]
    outcome_space: Mapping[str, str]
    #: Adversarial switches, one per refusal test.
    single_cause: bool = False
    invent_citation: bool = False
    claim_global_novelty: bool = False
    #: A yes-man Critic: it reads everything and objects to nothing. The benchmark's refutation
    #: test runs the debate with it and expects REFUTED.
    passive_critic: bool = False
    prompts_seen: list[str] = field(default_factory=list)

    def __call__(self, material: str, slot: ModelSlot) -> str:
        self.prompts_seen.append(material)
        ctx = _context(material)
        if material.startswith("You are the Hypothesis Engine"):
            return json.dumps(self._engine(ctx))
        if material.startswith("You are the Adversarial Critic"):
            return json.dumps(self._critic(ctx))
        if material.startswith("You are the Evidence Researcher"):
            return json.dumps(self._rewrite(ctx))
        if material.startswith("You are the Novelty Auditor"):
            return json.dumps(self._novelty(ctx))
        if "specialist" in material.split(".", 1)[0]:
            return json.dumps(self._specialist(ctx))
        raise AssertionError(f"the mock scientist does not know this prompt: {material[:60]!r}")

    # -- roles --------------------------------------------------------------------------------

    def _mechanism_of(self, text: str) -> str | None:
        for key, m in self.mechanisms.items():
            if m["mechanism"] == text:
                return key
        return None

    def _score(self, texts: Sequence[str]) -> dict[str, int]:
        corpus = " ".join(texts).lower()
        return {key: sum(corpus.count(c) for c in m["cues"]) for key, m in self.mechanisms.items()}

    def _certificate(self, key: str) -> dict[str, Any]:
        m = self.mechanisms[key]
        return {
            "key": key,
            "statement": m["statement"],
            "mechanism": m["mechanism"],
            "assumptions": list(m["assumptions"]),
            "falsifier": m["falsifier"],
            "falsifier_prediction_keys": ["falsifier"],
            "confounders": list(m["confounders"]),
            "minimal_test_ref": m["minimal_test_ref"],
            "predictions": [
                {
                    "key": "supports",
                    "observable_ref": self.outcome_space["observable_ref"],
                    "outcome_space_id": self.outcome_space["outcome_space_id"],
                    "outcome_space_version": self.outcome_space["outcome_space_version"],
                    "expected_outcome": m["expected_outcome"],
                    "relation_effect": "SUPPORTS",
                },
                {"key": "falsifier", **fixture_falsifier(key), "relation_effect": "CONTRADICTS"},
            ],
        }

    def _engine(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        order = list(self.mechanisms)
        if ctx.get("alternatives_to_certify"):
            wanted = set(ctx["alternatives_to_certify"])
            existing = set(ctx.get("existing_mechanisms", []))
            keys = [
                k
                for k in order
                if self.mechanisms[k]["mechanism"] in wanted
                and self.mechanisms[k]["mechanism"] not in existing
            ]
        else:
            scores = self._score([e["text"] for e in ctx["evidence"]])
            ranked = sorted(order, key=lambda k: (-scores[k], order.index(k)))
            limit = 1 if self.single_cause else max(2, int(ctx["minimum_hypotheses"]))
            keys = ranked[:limit]
        hypotheses = [self._certificate(k) for k in keys]
        lead = self.mechanisms[keys[0]]["mechanism"] if keys else "none"
        return {
            "hypotheses": hypotheses,
            "position": {
                "mechanism_view": f"the evidence shown favours {lead}",
                "uncertainties": ["bias sweep resolution"],
                "confounders": ["measurement temperature"],
            },
        }

    def _specialist(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        texts = [e["text"] for e in ctx["evidence"]]
        scores = self._score(texts)
        favoured = [
            h["hypothesis_id"]
            for h in ctx["hypotheses"]
            if (key := self._mechanism_of(h["mechanism"])) is not None and scores[key] > 0
        ]
        names = sorted(
            self.mechanisms[k]["mechanism"] for k in self.mechanisms if scores[k] > 0
        ) or ["no listed mechanism"]
        return {
            "mechanism_view": f"{ctx['specialist']} reads the domain evidence as {', '.join(names)}",
            "favoured_hypothesis_ids": favoured,
            "uncertainties": ["domain evidence coverage"],
            "confounders": [],
            "proposed_predictions": [],
        }

    def _rewrite(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        """Inverted search terms for the typed falsifiers shown, phrased as a model would phrase
        them: in the words of the mechanism the falsifier belongs to, which the stand-in knows from
        its own catalog -- an unknown falsifier is searched for in its own words."""
        if ctx["mode"] == "PRIMARY":
            return {"terms": list(self.primary_terms)}
        terms: list[str] = []
        for falsifier in ctx.get("falsifiers", []):
            known = next(
                (
                    m["falsifier"]
                    for k, m in self.mechanisms.items()
                    if falsifier.startswith(_typed_prefix(k))
                ),
                falsifier,
            )
            for token in _tokens(known):
                if token not in terms:
                    terms.append(token)
        return {"terms": terms or ["counterevidence"]}

    def _critic(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        if self.passive_critic:
            return {"objections": [], "alternative_mechanisms": [], "falsifier_challenges": []}
        inverted = set(ctx.get("inverted_attestation_ids", []))
        evidence = ctx["evidence"]
        objections: list[dict[str, Any]] = []
        present = set()
        for h in ctx["hypotheses"]:
            key = self._mechanism_of(h["mechanism"])
            if key is None:
                continue
            present.add(key)
            for e in evidence:
                if e["attestation_id"] not in inverted:
                    continue
                if any(c in e["text"].lower() for c in self.mechanisms[key]["counter_cues"]):
                    objections.append(
                        {
                            "target_id": h["hypothesis_id"],
                            "kind": "COUNTEREXAMPLE",
                            "severity": "CONTRADICTS",
                            "text": f"{e['attestation_id']} reports what falsifies {h['mechanism']}",
                            "evidence_attestation_ids": [e["attestation_id"]],
                        }
                    )
        if ctx["hypotheses"]:
            first = ctx["hypotheses"][0]["hypothesis_id"]
            objections.append(
                {
                    "target_id": first,
                    "kind": "MISSING_CONTROL",
                    "severity": "CHALLENGES",
                    "text": "the sweep temperature was not reported",
                    "evidence_attestation_ids": [],
                }
            )
            if self.invent_citation:
                objections.append(
                    {
                        "target_id": first,
                        "kind": "COUNTEREXAMPLE",
                        "severity": "CONTRADICTS",
                        "text": "a paper I recall contradicts this",
                        "evidence_attestation_ids": ["att:never-shown"],
                    }
                )
        scores = self._score([e["text"] for e in evidence])
        alternatives = [
            self.mechanisms[k]["mechanism"]
            for k in self.mechanisms
            if k not in present and scores[k] > 0
        ]
        return {
            "objections": objections,
            "alternative_mechanisms": alternatives,
            "falsifier_challenges": [],
        }

    def _novelty(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        concept = set(_tokens(ctx["concept"]))
        matrix = []
        for r in ctx["records"]:
            shared = concept & set(_tokens(r["title"]))
            overlap = "FULL" if len(shared) >= 4 else ("PARTIAL" if shared else "NONE")
            matrix.append({"record_id": r["record_id"], "overlap": overlap, "note": ""})
        overlaps = {m["overlap"] for m in matrix}
        status = (
            "KNOWN"
            if "FULL" in overlaps
            else ("PARTIALLY_NOVEL" if "PARTIAL" in overlaps else "NOVELTY_CANDIDATE")
        )
        internal_only = ctx["coverage"]["internal_only"]
        scope = "GLOBAL" if (self.claim_global_novelty or not internal_only) else "INTERNAL"
        return {"matrix": matrix, "status": status, "scope": scope}


def artifact_for(attestation_id: str) -> str:
    """A content-addressed artifact id for a fixture attestation (ART-001's `art:sha256:` form)."""
    return "art:sha256:" + hashlib.sha256(attestation_id.encode("utf-8")).hexdigest()


def evidence_items(case: Mapping[str, Any], project_id: str = PROJECT) -> tuple[EvidenceItem, ...]:
    return tuple(
        EvidenceItem(
            attestation_id=e["attestation_id"],
            project_id=project_id,
            text=e["text"],
            trust_class=TrustClass(e["trust_class"]),
            domain=DOMAIN,
            source_work_id=e.get("source_work_id"),
        )
        for e in case["evidence"]
    )


#: How each §6.5 source kind witnessed what it says (EVI-003). An expert's heuristic is REPORTED --
#: a person said it -- not INFERRED, which is reserved for a model's interpretation.
EPISTEMIC_TYPE_OF: Mapping[TrustClass, EpistemicType] = {
    TrustClass.INTERNAL_MEASUREMENT: EpistemicType.MEASURED,
    TrustClass.INTERNAL_RUN: EpistemicType.SIMULATED,
    TrustClass.PEER_REVIEWED: EpistemicType.REPORTED,
    TrustClass.PREPRINT: EpistemicType.REPORTED,
    TrustClass.PATENT: EpistemicType.REPORTED,
    TrustClass.TECHNICAL_ARTIFACT: EpistemicType.REPORTED,
    TrustClass.WEB: EpistemicType.REPORTED,
    TrustClass.EXPERT_HEURISTIC: EpistemicType.REPORTED,
}


def attestation_for(item: EvidenceItem) -> Attestation:
    """The admitted Attestation behind a catalog item: its id, project, kind and artifact source."""
    return make_attestation(
        attestation_id=item.attestation_id,
        project_id=item.project_id,
        epistemic_type=EPISTEMIC_TYPE_OF[item.trust_class],
        source_work_id=None,
        source_artifact_id=artifact_for(item.attestation_id),
        locator=f"fixture {item.attestation_id}",
    )


class _NoTransaction:
    def transaction(self) -> AbstractContextManager[Any]:
        return nullcontext()


def permissive_runner(project_id: str = PROJECT) -> AuthorizedExternalRunner:
    labels = frozenset({SensitivityLabel.PUBLIC, SensitivityLabel.INTERNAL})
    return AuthorizedExternalRunner(
        gate=EgressGate(
            policy_for=lambda _p: EgressPolicy(
                policy_id="egp:m3",
                version="1.0.0",
                project_id=project_id,
                mode=PrivacyMode.RESEARCH,
                declared_by_actor_id="act:pi",
                permitted_labels=labels,
                approved_providers=frozenset({"local", "src:literature", "src:patents"}),
            ),
            clearance_of=lambda _a, _p: labels,
        ),
        audit=EgressAuditLog(),
    )


def budget_policy(project_id: str = PROJECT, tokens: int | None = None) -> BudgetPolicy:
    return BudgetPolicy(
        policy_id="bp:m3",
        policy_version="1.0.0",
        project_id=project_id,
        caps=BudgetCaps(token_count=tokens),
    )


@dataclass
class World:
    """Every M3 collaborator, wired the way the composition wires them.

    In memory by default. With a PostgreSQL connection every durable M3 object -- bundles,
    provenance, certificates, predictions, genesis events, positions, critiques, debate records,
    benchmark policies, spans and ledger rows -- goes to its real table, and `brain` is the
    Hypothesis Brain over M1's governed `BeliefEpisode`.
    """

    debate: StructuredDebate
    scientist: MockScientist
    router: ModelRouter
    registries: Any
    bundles: Any
    provenance: Any
    hypotheses: Any
    debates: Any
    benchmarks: Any
    events: Any
    spans: Any
    ledger: Any
    claims: Any
    attestations: dict[str, Attestation]
    #: (project_id, attestation_id) -> the admitted attestation, from the world's store.
    find_attestation: Callable[[str, str], Attestation | None]
    researcher: EvidenceResearcher
    catalog: StaticEvidenceCatalog
    llm_dispatcher: BudgetedInferenceDispatcher
    admission: HypothesisAdmissionService
    source_policies: SourcePolicyRegistry
    gate: DebateGate
    revision_gate: HypothesisRevisionGate
    mint: Callable[[str], str]
    now: Callable[[], dt.datetime]
    fixture: Mapping[str, Any]
    connection: Any = None
    brain: HypothesisBrain | None = None
    episode: BeliefEpisode | None = None

    def request(
        self,
        case: Mapping[str, Any] | None = None,
        *,
        stakes: str | None = None,
        tokens: int | None = None,
        **overrides: Any,
    ) -> DebateRequest:
        fx = self.fixture
        values: dict[str, Any] = {
            "project_id": PROJECT,
            "episode_id": EPISODE,
            "trace_id": TRACE,
            "actor_id": ACTOR,
            "question": (case or fx["cases"][0])["question"],
            "intent": fx["intent"],
            "stakes": stakes or fx["stakes"],
            "domain": DOMAIN,
            "admission_policy": ADMISSION_POLICY,
            "budget_policy": budget_policy(tokens=tokens),
            "question_label": SensitivityLabel.INTERNAL,
            # The lab holds the device project, so Stage C can plan the CHARGE AC sweep (VER-002's
            # `requires` half); without it no verification action is plannable at all.
            "available_inputs": frozenset({INPUT_DEVICE_PROJECT}),
        }
        values.update(overrides)
        return DebateRequest(**values)


class CountingIds:
    """`BeliefEpisode`'s id source: deterministic, one counter per kind."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def _next(self, prefix: str) -> str:
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        return f"{prefix}:m3-{self._counts[prefix]:04d}"

    def decision_id(self) -> str:
        return self._next("dec")

    def event_id(self) -> str:
        return self._next("bre")

    def conflict_id(self) -> str:
        return self._next("cfl")

    def review_id(self) -> str:
        return self._next("rvw")


def seed_postgres(
    connection: Any,
    items: Sequence[EvidenceItem],
    spaces: Sequence[OutcomeSpace],
    *,
    policies: Sequence[TransitionPolicy] = (),
    attestations_by_id: Mapping[str, Attestation] | None = None,
) -> None:
    """The rows an M3 debate stands on: project, actors, episode, admitted evidence, spaces.

    The evidence is admitted as real `attestations` rows (with their artifacts), because a genesis
    event cites its basis and `005a` resolves every cited attestation by foreign key.
    """
    connection.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'M3 Hypothesis Brain')"
        " ON CONFLICT DO NOTHING",
        (PROJECT,),
    )
    for actor in (ACTOR, "act:pi"):
        connection.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
            " ON CONFLICT DO NOTHING",
            (actor, actor),
        )
    connection.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, start_time)"
        " VALUES (%s, %s, %s, 'diagnose the Rs anomaly', %s) ON CONFLICT DO NOTHING",
        (EPISODE, PROJECT, TRACE, T0),
    )
    connection.execute(
        "INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:test', 'rs anomaly')"
        " ON CONFLICT DO NOTHING"
    )
    connection.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('toy', 'basic', '1.0.0', %s::jsonb, %s)"
        " ON CONFLICT DO NOTHING",
        (
            '{"type": "object", "properties": {"setting": {"type": "string"}}}',
            TOY_COMPARATOR_VERSION,
        ),
    )
    attestations = SqlAttestationStore(connection)
    for item in items:
        artifact = make_artifact(item.attestation_id.encode("utf-8"))
        assert artifact.artifact_id == artifact_for(item.attestation_id)
        connection.execute(
            "INSERT INTO artifacts (artifact_id, content_hash, uri, media_type, source_origin,"
            " lineage_id, lineage_revision) VALUES (%s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (
                artifact.artifact_id,
                artifact.content_hash,
                artifact.uri,
                artifact.media_type,
                artifact.source_origin.value,
                artifact.lineage_id,
                artifact.lineage_revision,
            ),
        )
        if attestations.get(item.project_id, item.attestation_id) is None:
            attestations.add(
                attestations_by_id[item.attestation_id]
                if attestations_by_id is not None
                else attestation_for(item)
            )
    store = SqlTransitionPolicyStore(connection)
    for policy in (ADMISSION_POLICY, *policies):
        if store.get(policy.policy_id, policy.version) is None:
            store.register(policy)
    benchmarks = SqlBenchmarkStore(connection)
    for space in spaces:
        if benchmarks.outcome_space(space.outcome_space_id, space.version) is None:
            benchmarks.add_outcome_space(space)


def build_world(
    case: Mapping[str, Any] | None = None,
    *,
    policy: DebatePolicy | None = None,
    adversarial_slot: bool = True,
    scientist: MockScientist | None = None,
    items: Sequence[EvidenceItem] | None = None,
    scope: str = "t",
    connection: Any = None,
    transition_policies: Sequence[TransitionPolicy] = (),
    epistemic_overrides: Mapping[str, EpistemicType] | None = None,
) -> World:
    """``epistemic_overrides`` admits named attestations under another EVI-003 type -- the
    adversarial worlds where the evidence a Critic finds is a model's INFERRED note."""
    fx = load_fixture()
    case = case or fx["cases"][0]
    catalog_items = tuple(items) if items is not None else evidence_items(case)
    mint = SequentialIds(scope)
    now = TickingClock()
    registry = DomainPackRegistry()
    registry.install(
        SiliconPhotonicsPack(runner=lambda _r: None, conditions=registry.registries.conditions)  # type: ignore[arg-type,return-value]
    )
    regs = registry.registries
    route_slots = [LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY, LogicalSlot.EMBEDDING]
    if adversarial_slot:
        route_slots.append(LogicalSlot.REASONING_ADVERSARIAL)
    for slot in route_slots:
        regs.capabilities.register_estimator(
            cost_contract_for(slot),
            lambda params: CostVector(token_count=int(params["prompt_tokens"]) + 400),
        )
    doctor = scientist or MockScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space=fx["outcome_space"],
    )
    prompts = [
        *core_prompts(),
        *(
            PromptTemplate(r.prompt_id, r.prompt_version, r.prompt_template)
            for r in regs.specialists.all()
        ),
    ]
    classifier = labelled(
        {artifact_for(i.attestation_id): SensitivityLabel.INTERNAL for i in catalog_items},
        project_id=PROJECT,
        attestations={i.attestation_id: artifact_for(i.attestation_id) for i in catalog_items},
    )
    llm = ScientificLLM(
        slots=[
            ModelSlot(
                slot,
                f"mock-{slot.value.lower()}",
                "1.0.0",
                provider="local",
                reach=ExternalReach.LOCAL,
            )
            for slot in route_slots
        ],
        prompts=prompts,
        complete=doctor,
        runner=permissive_runner(),
        classifier=classifier,
        source_policy_version="srcpol@1.0.0",
    )
    attestations = {i.attestation_id: attestation_for(i) for i in catalog_items}
    for attestation_id, kind in (epistemic_overrides or {}).items():
        attestations[attestation_id] = attestations[attestation_id].model_copy(
            update={"epistemic_type": kind}
        )
    stores: dict[str, Any]
    if connection is None:
        provenance: Any = InMemoryInferenceProvenanceStore()
        ledger: Any = InMemoryCostLedger()
        bundles: Any = InMemoryEvidenceBundleRepository()
        hypotheses: Any = InMemoryHypothesisStore(
            outcome_space=regs.disagreement_metrics.outcome_space
        )

        def exists(project_id: str, hypothesis_id: str) -> bool:
            return hypotheses.get_certificate(project_id, hypothesis_id) is not None

        stores = {
            "provenance": provenance,
            "commit": _NoTransaction(),
            "ledger": ledger,
            "spans": InMemorySpanRepository(ledger),
            "claims": InMemoryBudgetApprovalClaims(),
            "bundles": bundles,
            "hypotheses": hypotheses,
            "events": InMemoryBeliefEventStore(
                known_attestation_ids=attestations, known_hypotheses=exists
            ),
            "debates": InMemoryDebateStore(
                bundle=bundles.get, provenance=provenance.get, hypothesis_exists=exists
            ),
            "benchmarks": InMemoryBenchmarkStore(),
            "atomic": None,
            "attestation": lambda project_id, attestation_id: (
                found
                if (found := attestations.get(attestation_id)) is not None
                and found.project_id == project_id
                else None
            ),
        }
    else:
        seed_postgres(
            connection,
            catalog_items,
            regs.disagreement_metrics.declared_spaces(),
            policies=transition_policies,
            attestations_by_id=attestations,
        )
        sql_attestations = SqlAttestationStore(connection)
        stores = {
            "provenance": SqlInferenceProvenanceStore(connection),
            "commit": connection,
            "ledger": SqlCostLedger(connection),
            "spans": SqlSpanRepository(connection),
            "claims": SqlBudgetApprovalClaims(connection),
            "bundles": SqlEvidenceBundleRepository(connection),
            "hypotheses": SqlHypothesisStore(connection),
            "events": SqlBeliefEventStore(connection),
            "debates": SqlDebateStore(connection),
            "benchmarks": SqlBenchmarkStore(connection),
            "atomic": connection.transaction,
            "attestation": sql_attestations.get,
        }
    service = ScientificInferenceService(
        llm=llm, store=stores["provenance"], commit=stores["commit"]
    )
    dispatcher = BudgetedInferenceDispatcher(
        service=service,
        estimators=regs.capabilities,
        spans=stores["spans"],
        ledger=stores["ledger"],
        claims=stores["claims"],
        now=now,
    )
    catalog = StaticEvidenceCatalog(catalog_items)
    researcher = EvidenceResearcher(catalog=catalog, bundles=stores["bundles"], mint=mint, now=now)
    admission = HypothesisAdmissionService(
        store=stores["hypotheses"],
        append=stores["events"].append,
        outcome_space=regs.disagreement_metrics.outcome_space,
        provenance=stores["provenance"].get,
        attestations=stores["attestation"],
        atomic=stores["atomic"],
    )
    router = ModelRouter(route_slots)
    source_policies = SourcePolicyRegistry(default_source_policies())
    gate = DebateGate(stores["benchmarks"], domain=DOMAIN, benchmark_set_id=DEBATE_BENCHMARK_ID)
    debate = StructuredDebate(
        router=router,
        dispatcher=dispatcher,
        researcher=researcher,
        source_policies=source_policies,
        admission=admission,
        hypotheses=stores["hypotheses"],
        debates=stores["debates"],
        specialists=regs.specialists,
        metrics=regs.disagreement_metrics,
        capabilities=regs.capabilities,
        gate=gate,
        embed=hashing_embedder(EMBED_SPACE),
        embedding_space=EMBED_SPACE,
        policy=policy or DebatePolicy(),
        mint=mint,
        now=now,
    )
    revision_gate = HypothesisRevisionGate(
        hypotheses=stores["hypotheses"],
        critiques=stores["debates"],
        history=stores["events"].history,
        divergence_gate=set_divergence_gate(stores["debates"], gate),
    )
    brain: HypothesisBrain | None = None
    episode: BeliefEpisode | None = None
    if connection is not None:
        # M1's governed path, unchanged. The brain runs M3's preconditions in front of it; a test
        # that calls `episode` directly is a writer that skipped them, and meets `011i` instead.
        episode = BeliefEpisode(
            policies=SqlTransitionPolicyStore(connection),
            decisions=SqlBeliefTransitionDecisionStore(connection),
            events=SqlBeliefEventStore(connection),
            relations=SqlRelationStore(connection),
            authority_classes=SqlAttestationStore(connection),
            conflicts=SqlConflictStore(connection),
            reviews=SqlReviewItemStore(connection),
            ids=CountingIds(),
        )
        brain = HypothesisBrain(
            debate=debate,
            hypotheses=stores["hypotheses"],
            revision_gate=revision_gate,
            episode=episode,
            attestations=stores["attestation"],
        )
    return World(
        debate=debate,
        scientist=doctor,
        router=router,
        registries=regs,
        bundles=stores["bundles"],
        provenance=stores["provenance"],
        hypotheses=stores["hypotheses"],
        debates=stores["debates"],
        benchmarks=stores["benchmarks"],
        events=stores["events"],
        spans=stores["spans"],
        ledger=stores["ledger"],
        claims=stores["claims"],
        attestations=attestations,
        find_attestation=stores["attestation"],
        researcher=researcher,
        catalog=catalog,
        llm_dispatcher=dispatcher,
        admission=admission,
        source_policies=source_policies,
        gate=gate,
        revision_gate=revision_gate,
        mint=mint,
        now=now,
        fixture=fx,
        connection=connection,
        brain=brain,
        episode=episode,
    )


class _StaticPolicies:
    def __init__(self, *policies: TransitionPolicy) -> None:
        self._by_key = {(p.policy_id, p.version): p for p in policies}

    def get(self, policy_id: str, version: str) -> TransitionPolicy | None:
        return self._by_key.get((policy_id, version))


class _NoDecisions:
    def get(self, decision_id: str) -> None:
        return None


def state_of(world: World, hypothesis_id: str, project_id: str = PROJECT) -> BeliefState | None:
    """The verified projection of an ADMISSION-only history (in memory; PG tests use the episode)."""
    revisions = verified_history(
        project_id=project_id,
        target_id=hypothesis_id,
        events=world.events.history(project_id, hypothesis_id),
        decisions=_NoDecisions(),  # type: ignore[arg-type]
        policies=_StaticPolicies(ADMISSION_POLICY),  # type: ignore[arg-type]
    )
    return replay(project_id, hypothesis_id, revisions).current_state


# -- builders for the admission / revision / storage tests ------------------------------------


def make_set(
    set_id: str = "hst:unit",
    *,
    project_id: str = PROJECT,
    episode_id: str = EPISODE,
    stakes: str = "HIGH",
    root_cause: bool = True,
    inverted_retrieval_required: bool = True,
    intent: str = "DIAGNOSIS",
) -> HypothesisSet:
    return HypothesisSet(
        set_id=set_id,
        project_id=project_id,
        episode_id=episode_id,
        question="Why is Rs extremely high and weakly bias dependent?",
        research_intent=intent,
        stakes=stakes,
        root_cause=root_cause,
        source_policy_id="srcpol:diagnosis",
        source_policy_version="1.0.0",
        inverted_retrieval_required=inverted_retrieval_required,
        created_at=T0,
    )


def make_certificate(
    key: str,
    hypothesis_set: HypothesisSet,
    *,
    mechanism: str | None = None,
    expected_outcome: str | None = None,
    outcome_space_version: str | None = None,
    predictions: bool = True,
    typed_falsifier: bool = True,
    author: str | None = ACTOR,
    inference_provenance_id: str | None = None,
    **hypothesis_overrides: Any,
) -> HypothesisCertificate:
    """A certificate from the fixture's mechanism catalog, human-authored unless told otherwise.

    ``typed_falsifier=False`` leaves the falsifier in prose only: no CONTRADICTS prediction and no
    designation."""
    fx = load_fixture()
    m = fx["mechanisms"][key]
    space = fx["outcome_space"]
    hypothesis_id = f"hyp:{hypothesis_set.set_id.split(':', 1)[1]}.{key}"
    prediction = Prediction(
        prediction_id=f"prd:{hypothesis_set.set_id.split(':', 1)[1]}.{key}",
        hypothesis_id=hypothesis_id,
        project_id=hypothesis_set.project_id,
        observable_ref=space["observable_ref"],
        outcome_space_id=space["outcome_space_id"],
        outcome_space_version=outcome_space_version or space["outcome_space_version"],
        expected_outcome=expected_outcome or m["expected_outcome"],
        relation_effect_if_observed=(
            RelationJudgmentTemplate(
                relation_type=RelationType.SUPPORTS, to_entity_id=hypothesis_id
            ),
        ),
    )
    carried = (prediction,)
    if typed_falsifier:
        carried += (
            Prediction(
                prediction_id=f"{prediction.prediction_id}.falsifier",
                hypothesis_id=hypothesis_id,
                project_id=hypothesis_set.project_id,
                **fixture_falsifier(key),
                relation_effect_if_observed=(
                    RelationJudgmentTemplate(
                        relation_type=RelationType.CONTRADICTS, to_entity_id=hypothesis_id
                    ),
                ),
            ),
        )
    carried = carried if predictions else ()
    fields: dict[str, Any] = {
        "hypothesis_id": hypothesis_id,
        "project_id": hypothesis_set.project_id,
        "statement": m["statement"],
        "mechanism": mechanism or m["mechanism"],
        "assumptions": tuple(m["assumptions"]),
        "prediction_ids": tuple(c.prediction_id for c in carried),
        "falsifier": m["falsifier"],
        "confounders": tuple(m["confounders"]),
        "minimal_test_ref": m["minimal_test_ref"],
        "created_in_episode": hypothesis_set.episode_id,
        "inference_provenance_id": inference_provenance_id,
    }
    fields.update(hypothesis_overrides)
    return HypothesisCertificate(
        hypothesis=Hypothesis(**fields),
        hypothesis_set_id=hypothesis_set.set_id,
        predictions=carried,
        falsifier_prediction_ids=tuple(
            c.prediction_id for c in carried if c.prediction_id.endswith(".falsifier")
        ),
        authored_by_actor_id=author,
        created_at=T0,
    )


def fixture_falsifier(key: str) -> dict[str, str]:
    """Fixture mechanism `key`'s typed falsifier: the CONTRADICTS prediction the silicon-photonics
    pack's catalog designates for the same mechanism.

    The locked debate fixture states each falsifier in prose only ("normalization crosschecked
    against drawn length"); the pack's catalog types the same check ("sp.normalization_basis =
    AGREES contradicts"). Taken from that declaration, never derived from the fixture's SUPPORTS
    outcome -- an outcome that merely differs from it is not a falsifier.
    """
    mechanism = next(m for m in mechanism_catalog().mechanisms if m.key == key)
    (falsifier,) = (
        p for p in mechanism.predictions if p.key in mechanism.falsifier_prediction_keys
    )
    return {
        "observable_ref": falsifier.observable_ref,
        "outcome_space_id": falsifier.outcome_space_id,
        "outcome_space_version": falsifier.outcome_space_version,
        "expected_outcome": falsifier.expected_outcome,
    }


# -- prior-art fixtures (SRC-003) ----------------------------------------------------------------


@dataclass(frozen=True)
class CorpusAdapter:
    """A deterministic prior-art provider over a declared corpus. No network, no provider SDK.

    Returns every record whose title shares a token with the query -- lexical, like the internal
    search -- so what a search finds is a function of the corpus and the queries alone.
    """

    provider: str
    trust_class: TrustClass
    corpus: tuple[tuple[str, str], ...]
    reachable: bool = True

    def provider_id(self) -> str:
        return self.provider

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            provider_id=self.provider,
            max_sensitivity=SensitivityLabel.INTERNAL,
            reach=ExternalReach.LOCAL,
        )

    def healthcheck(self) -> SourceHealthReport:
        return SourceHealthReport(provider_id=self.provider, reachable=self.reachable)

    def search(self, query: SourceQuery) -> Sequence[ExternalSourceRecord]:
        terms = set(_tokens(query.text))
        return [
            ExternalSourceRecord(
                provider=self.provider,
                source_type="PATENT"
                if self.trust_class is TrustClass.PATENT
                else "JOURNAL_ARTICLE",
                canonical_locator=locator,
                retrieved_at=T0,
                visibility=SourceVisibility.PUBLIC,
                trust_class=self.trust_class,
                sensitivity=SensitivityLabel.PUBLIC,
                title=title,
            )
            for locator, title in self.corpus
            if terms & set(_tokens(title))
        ]

    def fetch(self, locator: str) -> ExternalSourceRecord | None:
        return None


LITERATURE = CorpusAdapter(
    "src:literature",
    TrustClass.PEER_REVIEWED,
    (
        ("doi:10.1000/rib.1", "dopant compensation raises series resistance in rib modulators"),
        ("doi:10.1000/rib.2", "contact via resistance in silicon photonic modulators"),
    ),
)
PATENTS = CorpusAdapter(
    "src:patents",
    TrustClass.PATENT,
    (("pat:US-1", "graded dopant compensation layer for a rib phase shifter"),),
)


def novelty_tools(
    world: World,
    adapters: Sequence[CorpusAdapter],
    store: Any,
    *,
    internal: bool = True,
) -> tuple[PriorArtSearch, NoveltyAuditor]:
    """The SRC-003 pair over a world's router, dispatcher and bundles, with `adapters` wired."""
    router = SourceRouter(
        list(adapters),
        runner=permissive_runner(),
        classifier=labelled({}, project_id=PROJECT),
    )
    search = PriorArtSearch(
        router=router,
        bindings=[PriorArtSourceBinding(a.provider, (a.trust_class,)) for a in adapters],
        internal=world.catalog if internal else None,
        store=store,
        mint=world.mint,
        now=world.now,
    )
    auditor = NoveltyAuditor(
        router=world.router,
        dispatcher=world.llm_dispatcher,
        bundles=world.bundles,
        store=store,
        mint=world.mint,
        now=world.now,
    )
    return search, auditor


#: The calibration's identity. The date is when this calibration was established, recorded so the
#: generated report is reproducible; a changed fixture or metric version is a NEW calibration with
#: a new version and date, never an edit of this one.
CALIBRATION_POLICY_ID = "bp:sp.debate.critic_divergence"
CALIBRATION_VERSION = "1.0.0"
CALIBRATED_AT = dt.datetime(2026, 9, 26, tzinfo=dt.UTC)


def benchmark_runner(
    *, scientist_flags: Mapping[str, bool] | None = None, human_requested_rounds: int = 0
) -> RunCase:
    """T-LLM-002's case runner: a fresh world per case and condition, the condition's policy.

    `scientist_flags` turns the reasoner into an adversary for the refutation test; a
    `human_requested_rounds` at the policy's maximum reproduces the always-max implementation the
    round-count check must fail.
    """
    fx = load_fixture()

    def run(case: Mapping[str, Any], condition: Condition) -> DebateOutcome:
        doctor = MockScientist(
            mechanisms=fx["mechanisms"],
            primary_terms=fx["primary_terms"],
            outcome_space=fx["outcome_space"],
            **dict(scientist_flags or {}),
        )
        world = build_world(
            case,
            policy=CONDITION_POLICIES[condition],
            scientist=doctor,
            scope=f"{case['case_id']}.{condition.value.lower()}",
        )
        return world.debate.run(world.request(case, human_requested_rounds=human_requested_rounds))

    return run


__all__ = [
    "ACTOR",
    "ADMISSION_POLICY",
    "CALIBRATED_AT",
    "CALIBRATION_POLICY_ID",
    "CALIBRATION_VERSION",
    "DOMAIN",
    "EMBED_SPACE",
    "EPISODE",
    "EPISTEMIC_TYPE_OF",
    "FIXTURE_PATH",
    "FIXTURE_SHA256",
    "LITERATURE",
    "PATENTS",
    "PROJECT",
    "T0",
    "TRACE",
    "CorpusAdapter",
    "CountingIds",
    "MockScientist",
    "SequentialIds",
    "TickingClock",
    "World",
    "artifact_for",
    "attestation_for",
    "benchmark_runner",
    "budget_policy",
    "build_world",
    "evidence_items",
    "fixture_digest",
    "load_fixture",
    "make_certificate",
    "make_set",
    "novelty_tools",
    "permissive_runner",
    "seed_postgres",
    "state_of",
]
