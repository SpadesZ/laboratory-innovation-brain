"""Belief transition is a versioned policy decision, not an LLM vote (EPI-005, §8.2.1).

    TransitionPolicy 是版本化、可測試的 deterministic-first policy。LLM 可以產生
    RelationJudgment 或解釋 rationale，但**不得**直接把 ACTIVE 改成 SUPPORTED/REJECTED。

THE SIGNATURE IS NORMATIVE. §8.2.1 says so in as many words:

    # This signature is normative (EPI-005).
    # No other name or arity may appear elsewhere in this specification.

    TransitionPolicy.evaluate(hypothesis, admitted_relations, authority_policy,
                              condition_matches, independence_summary,
                              candidate_to_state) -> TransitionDecision

So :meth:`TransitionPolicy.evaluate` has exactly that name and exactly those six parameters. There
is deliberately no ``should_transition``, no ``can_promote`` and no ``decide``: `T-EPI-005` requires
that only ``evaluate`` exists in the codebase, and a second entry point is how a caller ends up
using the one that skips a check.

DETERMINISTIC MEANS REPLAYABLE, WHICH IS WHY IT IS PURE. §8.2.1:

    Deterministic: identical inputs + identical policy_version MUST return
    identical TransitionDecision.

This function reads no clock, no random source and no ambient state, and every collection it
returns is ordered. That is not tidiness: EPI-003 requires a past belief revision to be
re-derivable, and a policy that consulted the time would give a different answer on the day
somebody audited it. Anything derived from a set is sorted before it reaches the decision, because
set iteration order is not stable across processes.

WHAT REFUSING LOOKS LIKE, and why there are four outcomes rather than a boolean:

    ALLOW                the policy is satisfied
    DENY                 the policy is violated -- more evidence would not help
    NEED_MORE_EVIDENCE   the thresholds are not met yet; the planner can act on this
    NEED_HUMAN_REVIEW    the policy cannot decide honestly and must not guess

The last one is the load-bearing one. §10.5.1's INCOMPARABLE, §6.17's un-modelled independence
bases and a blocking conflict all land there, because in each case the alternative is to invent a
fact: an ordering that does not exist, an independence that has not been established, or a
resolution nobody made.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, Self

from pydantic import Field, model_validator

if TYPE_CHECKING:
    # Annotation-only, and that is what breaks a cycle rather than merely surviving it.
    # `lab_brain.core.authority` imports `models.enums`, which executes `models/__init__`,
    # which imports this module -- so a runtime import here made the whole cycle depend on
    # which side was imported first. `import lab_brain.core.authority` failed outright while
    # `import lab_brain.core.models` worked, which is the kind of latent breakage that only
    # shows up when someone imports the module you did not expect. EPI-004 added a registry
    # to `authority`, tests import it directly, and that is when it showed up.
    from lab_brain.core.authority import AuthorityPolicy
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.conflict import Conflict, ConflictType
from lab_brain.core.models.enums import (
    IMPLEMENTED_INDEPENDENCE_BASES,
    AuthorityComparison,
    ConditionMatchState,
    IndependenceBasis,
    IndependenceRelation,
    RelationType,
)
from lab_brain.core.models.relation import RelationJudgment

#: The declared §17.19.3 vocabulary, as the strings `blocking_conflict_policy` carries.
_CONFLICT_TYPE_VALUES: Final[frozenset[str]] = frozenset(kind.value for kind in ConflictType)

#: The relation types that move a belief, and so the ones a diagnostic warrant gates. PREDICTS
#: and TESTS never count toward a transition (`PREDICTION_EFFECT_MEANINGS`).
_GATED_TYPES: Final[frozenset[RelationType]] = frozenset(
    {RelationType.SUPPORTS, RelationType.CONTRADICTS}
)


class TransitionOutcome(StrEnum):
    """§8.2.1's four outcomes. See the module docstring for why NEED_HUMAN_REVIEW exists."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    NEED_MORE_EVIDENCE = "NEED_MORE_EVIDENCE"
    NEED_HUMAN_REVIEW = "NEED_HUMAN_REVIEW"


class TransitionReason(StrEnum):
    """Why the policy answered as it did.

    §8.2.1 declares ``reason_code`` without enumerating it, so these are derived from the checks
    the section's own fields require rather than invented: one member per way a declared policy
    field can fail to be satisfied, plus ``POLICY_SATISFIED``. A reason code is what makes a
    refusal actionable -- "denied" tells a planner nothing about what to do next.
    """

    POLICY_SATISFIED = "POLICY_SATISFIED"
    #: The policy does not govern this from/to pair at all.
    TRANSITION_NOT_GOVERNED = "TRANSITION_NOT_GOVERNED"
    #: §23.4: a blocking Conflict prevents ALLOW and appears in `blocking_conflict_ids`.
    BLOCKING_CONFLICT = "BLOCKING_CONFLICT"
    #: §6.17 / FIX-6: a basis above WORK is not modelled, and pretending otherwise is forbidden.
    INDEPENDENCE_BASIS_NOT_MODELLED = "INDEPENDENCE_BASIS_NOT_MODELLED"
    MISSING_REQUIRED_RELATION_TYPE = "MISSING_REQUIRED_RELATION_TYPE"
    CONDITION_MATCH_MISSING = "CONDITION_MATCH_MISSING"
    CONDITION_MATCH_UNACCEPTABLE = "CONDITION_MATCH_UNACCEPTABLE"
    #: §17.19: "we cannot tell whether these are comparable" is not "they are not comparable".
    CONDITION_MATCH_UNKNOWN = "CONDITION_MATCH_UNKNOWN"
    #: §10.5.1: INCOMPARABLE must not be coerced into an ordering.
    AUTHORITY_INCOMPARABLE = "AUTHORITY_INCOMPARABLE"
    AUTHORITY_INSUFFICIENT = "AUTHORITY_INSUFFICIENT"
    #: EVI-004: DEPENDENCE_UNKNOWN contributes 0, and the shortfall must not be guessed away.
    INSUFFICIENT_INDEPENDENT_ATTESTATIONS = "INSUFFICIENT_INDEPENDENT_ATTESTATIONS"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"
    #: A belief-moving relation is present and a warrant for its link would decide the
    #: transition, but nobody accountable has warranted that its outcome diagnoses this
    #: hypothesis's mechanism. Unknown, not refuted: a person decides.
    DIAGNOSTIC_WARRANT_MISSING = "DIAGNOSTIC_WARRANT_MISSING"
    #: Every gated relation present had its warrant refused on review; none counts.
    DIAGNOSTIC_WARRANT_REFUSED = "DIAGNOSTIC_WARRANT_REFUSED"


class ReviewItemSpec(CoreModel):
    """What review the policy says is needed -- **not** a created ReviewItem.

    §8.2.1's `TransitionDecision.review_item_spec?` is a description the policy returns; creating
    the ReviewItem, feeding ReviewQueue capacity and honouring SLA/expiry is `OPS-002`'s job, and
    the INCOMPARABLE auto-creation flow is `EPI-004`'s. Keeping this a spec is what lets the policy
    stay pure: a function that created rows could not be replayed.
    """

    subject_type: str
    subject_id: str
    stakes: str
    reason: TransitionReason


class IndependenceSummary(CoreModel):
    """The resolved EvidenceIndependence rollup §8.2.1 passes to ``evaluate`` (§6.17).

    ``unknown_count`` is carried separately and **not** added to the independent count. EVI-004:

        DEPENDENCE_UNKNOWN 對 independent-attestation count 的貢獻固定為 0。
        ...若因此無法達到門檻，TransitionPolicy MUST 回傳 NEED_MORE_EVIDENCE 或
        NEED_HUMAN_REVIEW，不得猜測為獨立。

    Keeping it visible rather than dropping it is the difference between "we have two independent
    attestations" and "we have two, and three more we could not classify" -- the second is what a
    reviewer needs in order to go and classify them.
    """

    basis: IndependenceBasis = IndependenceBasis.WORK
    independent_count: int = Field(default=0, ge=0)
    unknown_count: int = Field(default=0, ge=0)

    def relation_counts_as_independent(self, relation: IndependenceRelation) -> bool:
        """Only ``INDEPENDENT`` does. Kept as a method so the rule has one home."""
        return relation is IndependenceRelation.INDEPENDENT


class WarrantBasis(StrEnum):
    """Who vouches that an observed outcome diagnoses a hypothesis's mechanism.

    Never the hypothesis's author. A declared effect is the author's claim that the outcome
    bears on the mechanism -- for SUPPORTS, that the mechanism produces it and the rivals do not;
    for CONTRADICTS, that the mechanism cannot. A warrant is an accountable source agreeing.
    """

    #: The DomainPack's versioned diagnostic declarations name this exact link.
    DOMAIN = "DOMAIN"
    #: A person resolved a DIAGNOSTIC_WARRANT review for this exact relation as warranted.
    REVIEW = "REVIEW"


class RelationEvidence(CoreModel):
    """One admitted SUPPORTS or CONTRADICTS relation, as a warrant-gated policy counts it.

    Resolved by the caller (`core.warrant`) because every field is a repository read, and carried
    per relation so the pure policy can evaluate condition, authority and independence over the
    relations that are warranted rather than over everything admitted -- otherwise an unwarranted
    proxy observation could still supply the authority or the independent line a warranted one
    lacks. The read path re-resolves each record against its sources before a stored ALLOW may
    change a belief.

    `warrant_ref` is `dds:<set>@<version>#<class>` for DOMAIN and the grant id for REVIEW.
    `evidence_line` identifies the execution behind the relation -- capability, backend, input
    artefacts and parameters -- so a replicate of one computation is one line, not two.
    """

    relation_id: str
    relation_type: RelationType
    prediction_id: str | None = None
    authority_classes: tuple[str, ...] = ()
    evidence_line: str | None = None
    warrant: WarrantBasis | None = None
    warrant_ref: str | None = None
    #: A reviewer refused the warrant: terminal for this relation, which never counts again.
    refused: bool = False
    #: The declared class a reviewer said this hypothesis IS (`dds:` ref), when they said so and
    #: the observed outcome is that class's signature. Read by the confirmation rule, not here.
    identifies: str | None = None

    @model_validator(mode="after")
    def _a_warrant_names_its_source(self) -> Self:
        if (self.warrant is None) != (self.warrant_ref is None):
            raise ValueError(
                f"relation evidence for {self.relation_id} must carry a warrant and its source "
                "together; a basis without a source cannot be re-checked"
            )
        if self.warrant is not None and self.refused:
            raise ValueError(f"relation {self.relation_id} cannot be both warranted and refused")
        if self.relation_type not in _GATED_TYPES:
            raise ValueError(
                f"relation {self.relation_id} is {self.relation_type.value}; only SUPPORTS and "
                "CONTRADICTS move a belief, so only they are warranted"
            )
        return self

    @property
    def warranted(self) -> bool:
        return self.warrant is not None


class HypothesisView(CoreModel):
    """The part of a Hypothesis ``evaluate`` actually reads.

    A view rather than the §8.1 entity because `Hypothesis` is `EPI-001` in M3, and evaluating a
    transition needs only its identity, its current state, its stakes and whatever blocking
    conflicts are attached. Passing a narrow, frozen view also keeps the determinism claim
    checkable: there is no lazily-loaded field that could differ between two calls.
    """

    hypothesis_id: str
    project_id: str
    current_state: BeliefState
    #: §17.19.1's ReviewItem needs stakes, and §8.2.1 passes `hypothesis.stakes` straight through.
    stakes: str = "NORMAL"
    #: §17.19.3 `Conflict` records attached to this hypothesis (EPI-006).
    #:
    #: WHAT CHANGED AND WHY IT MATTERED. This was `blocking_conflict_ids: tuple[str, ...]` -- a
    #: list of opaque ids the *caller* had already decided were blocking, matched against nothing.
    #: So `blocking_conflict_policy` declared `conflict_type` values that no code compared, and a
    #: caller who forgot to populate the ids got an ALLOW. §17.19.3 forbids exactly that
    #: arrangement: a conflict must not be "只以字串或散落旗標表示". Now the policy matches
    #: declared types against typed records and decides for itself.
    #:
    #: Passed in rather than loaded, like `independence_summary`: resolving a project's conflicts
    #: is a repository read, and a pure policy that performed one would stop being replayable.
    conflicts: tuple[Conflict, ...] = ()

    #: Authority classes of the evidence admitted for this hypothesis, resolved by the caller.
    #:
    #: WHY THEY ARE HERE AND NOT ON THE RELATIONS. §8.2.1's signature is normative and passes
    #: `admitted_relations` -- but `authority_class` lives on `Attestation` (§17.2), and a
    #: `RelationJudgment` carries only `supporting_attestation_ids`. Resolving those ids to
    #: attestations is a repository read, and a pure policy must not perform one or it stops being
    #: replayable. So the caller resolves them while assembling this view, exactly as §8.2.1 has it
    #: pass a *resolved* `independence_summary` rather than raw EvidenceIndependence rows.
    #:
    #: Recorded as a candidate spec clarification rather than a blocker: the signature admits a
    #: faithful implementation, it just does not say where the authority classes come in.
    admitted_authority_classes: tuple[str, ...] = ()

    #: Per-relation facts and warrants for this hypothesis's admitted SUPPORTS and CONTRADICTS
    #: relations, resolved by the caller from the domain's declarations and durable review
    #: grants -- never from who authored anything. Here rather than as a seventh `evaluate`
    #: argument for the reason the authority classes are: §8.2.1 fixes the arity, and resolving
    #: them is a repository read.
    #:
    #: Left out of the decision snapshot's canonical form while empty, so every snapshot recorded
    #: before it existed still hashes to what was stored (`decision.py`).
    relation_evidence: tuple[RelationEvidence, ...] = ()


class TransitionDecision(CoreModel):
    """§8.2.1's structured verdict.

    Named fields rather than a boolean because §8.2.1 requires the *decision* to be recordable and
    comparable: `T-EPI-005` compares two decisions under canonical serialization, which is only
    meaningful if everything the policy concluded is in the object.
    """

    outcome: TransitionOutcome
    reason_code: TransitionReason
    policy_id: str
    policy_version: str
    blocking_conflict_ids: tuple[str, ...] = ()
    required_authority_gap: str | None = None
    #: EVI-004: DEPENDENCE_UNKNOWN contributes 0 to this.
    independent_attestation_count: int = Field(default=0, ge=0)
    review_item_spec: ReviewItemSpec | None = None

    @property
    def permits_transition(self) -> bool:
        """``ALLOW`` only.

        Named this rather than ``allowed`` for the reason `BudgetDecision.budget_permits` is:
        several gates answer several questions, and a caller must not read one as all of them. A
        budget approval does not clear this policy and this policy does not clear SEC-002.
        """
        return self.outcome is TransitionOutcome.ALLOW


class _Decide(Protocol):
    """`_decide`'s local constructor for a verdict, passed to the steps split out of it."""

    def __call__(
        self,
        outcome: TransitionOutcome,
        reason: TransitionReason,
        *,
        conflicts: tuple[str, ...] = (),
        gap: str | None = None,
        review: bool = False,
        counted: int | None = None,
    ) -> TransitionDecision: ...


class TransitionPolicy(CoreModel):
    """§8.2.1's versioned policy, and the only thing that may authorise a belief transition.

    ``effective_from`` and ``supersedes`` are recorded but deliberately **not** consulted by
    ``evaluate``: selecting which policy version applies to a moment is the caller's job, and a
    policy that filtered itself by comparing ``effective_from`` against the current time would read
    a clock and stop being replayable. The version that decided is recorded on the event
    (`v3.3-a11`), so a replay re-runs that version rather than today's.
    """

    policy_id: str
    version: str
    domain: str | None = None
    from_state: BeliefState
    candidate_to_state: BeliefState
    required_relation_types: tuple[RelationType, ...] = ()
    required_authority_rule: str | None = None
    #: Acceptable `ConditionMatch.state` values. Empty means conditions are not gated by this
    #: policy -- distinct from "any state is acceptable", which would be written out in full.
    required_condition_match: tuple[ConditionMatchState, ...] = ()
    min_independent_attestations: int | None = Field(default=None, ge=0)
    independence_basis: IndependenceBasis | None = None
    #: §17.19.3 `conflict_type` values this policy treats as blocking (EPI-006).
    #:
    #: VALIDATED HERE, AND THE COMMENT THAT SAID OTHERWISE WAS WRONG. An earlier version of this
    #: field carried a docstring claiming a `blocking_conflict_policy_is_known_vocabulary()`
    #: helper existed to catch typos. **It did not exist.** The P10 audit caught the claim, and it
    #: was the worst kind of error in this codebase: a comment asserting a guard that was never
    #: written, which is more dangerous than no comment at all because it stops the next reader
    #: looking.
    #:
    #: The consequence was real. `evaluate` matches against `ConflictType.value`, so
    #: `"SIM_TO_REAL_CONFLIC"` matched nothing and the policy silently declared *no* blocking
    #: types -- a fail-open typo, discovered at the moment a belief was promoted rather than when
    #: the policy was written. It is now rejected at construction.
    blocking_conflict_policy: tuple[str, ...] = ()
    human_gate: bool = False
    #: Whether a required SUPPORTS or CONTRADICTS counts only when warranted (Causal Warrant Gate).
    #:
    #: A relation's type is the effect its prediction's author declared, so without a warrant it
    #: is the author's claim that the outcome diagnoses the mechanism. When set, steps 5-7 are
    #: evaluated over the warranted relations only. False reproduces every policy version
    #: registered before the gate exactly, which is what lets their stored decisions re-derive.
    diagnostic_warrant_required: bool = False
    #: TRUE for a §8 Hypothesis-Admission policy, which backs only a target's *first* event.
    #:
    #: Not a §8.2.1 field. It exists because §17.13 makes `from_state?` optional for a target's
    #: first record while every transition policy declares a `from_state` -- so without the
    #: distinction, a genesis event could cite any policy and nothing could tell an admission from
    #: a transition that had quietly dropped its predecessor. `admit_hypothesis` requires it,
    #: `evaluate`-driven `record_transition` refuses it, and migration 005c enforces the pairing in
    #: the database. Recorded here rather than inferred per event so it is registered once and
    #: reviewable.
    is_admission: bool = False
    effective_from: dt.datetime | None = None
    supersedes: str | None = None

    @model_validator(mode="after")
    def _blocking_conflict_policy_is_known_vocabulary(self) -> Self:
        """Every declared blocking type must be a §17.19.3 `conflict_type`.

        Fail closed at construction, which is the only point where the mistake is cheap. A typo
        here produces a policy that blocks nothing, and "blocks nothing" is indistinguishable from
        a policy that deliberately ignores conflicts -- so the failure surfaces as an unexpected
        ALLOW on a hypothesis with an open blocking conflict, long after the typo.

        The field stays `tuple[str, ...]` rather than `tuple[ConflictType, ...]` because §8.2.1
        declares it as `conflict_type[]` and a DomainPack may load policies from configuration;
        what matters is that an unknown value is refused, not which type the field has.
        """
        unknown = sorted(
            declared
            for declared in self.blocking_conflict_policy
            if declared not in _CONFLICT_TYPE_VALUES
        )
        if unknown:
            raise ValueError(
                f"policy {self.policy_id}@{self.version} declares blocking conflict type(s) "
                f"{unknown}, which are not §17.19.3 conflict_type values. Known values: "
                f"{sorted(_CONFLICT_TYPE_VALUES)}. An unknown type matches no conflict, so the "
                "policy would silently block nothing -- a fail-open typo"
            )
        return self

    def evaluate(
        self,
        hypothesis: HypothesisView,
        admitted_relations: tuple[RelationJudgment, ...],
        authority_policy: AuthorityPolicy | None,
        condition_matches: tuple[ConditionMatch, ...],
        independence_summary: IndependenceSummary,
        candidate_to_state: BeliefState,
    ) -> TransitionDecision:
        """§8.2.1's canonical operator. Name and arity are normative -- see the module docstring.

        Pure: no clock, no randomness, no I/O, and nothing derived from an unordered iteration
        reaches the result. Identical inputs and an identical ``version`` therefore produce an
        identical decision, which is what makes a recorded revision re-derivable (EPI-003).

        The order of the checks below affects only ``reason_code``, never the verdict -- every
        branch refuses. It is ordered so the most decisive and least recoverable reasons come
        first: a transition this policy does not govern, then a conflict a human must resolve, then
        an independence basis nobody has modelled, and only then the thresholds a planner could
        actually go and satisfy.
        """
        verdict = self._decide(
            hypothesis,
            admitted_relations,
            authority_policy,
            condition_matches,
            independence_summary,
            candidate_to_state,
        )
        return verdict

    def evaluate_hypothetical(
        self,
        hypothesis: HypothesisView,
        admitted_relations: tuple[RelationJudgment, ...],
        hypothetical_relations: tuple[RelationJudgment, ...],
        authority_policy: AuthorityPolicy | None,
        condition_matches: tuple[ConditionMatch, ...],
        independence_summary: IndependenceSummary,
        candidate_to_state: BeliefState,
    ) -> TransitionDecision:
        """§17.5.1's side-effect-free "what if", used by §9.1's sufficiency (VER-006).

            §17.5.1  evaluate_hypothetical MUST be side-effect free: it MUST NOT persist
                     RelationJudgment, MUST NOT emit BeliefRevisionEvent, and MUST NOT mutate any
                     projection.
                     hypothetical_relations MUST be instantiated from declared Predictions, never
                     invented by the planner or by an LLM at planning time.

        IT IS SIDE-EFFECT FREE BY CONSTRUCTION, NOT BY DISCIPLINE, and that distinction is the
        reason this lives on the model. `TransitionPolicy` holds no repository, no connection and
        no store; it is a frozen Pydantic object whose only capability is arithmetic over its
        arguments. There is no `self._events` to append to and no session to flush. A planner that
        wanted to persist the hypothetical relations would have to go and find a store itself,
        which is a line in a diff rather than an accident.

        NOT A SECOND TRANSITION OPERATOR. `evaluate` remains the only thing that can authorise a
        belief revision -- §26's T-EPI-005 requires that only its signature exists, and nothing
        downstream accepts a `TransitionDecision` produced here: `authorize_transition` computes
        its own from the six real inputs and `record_transition` re-derives before minting. This
        answers "would it change the answer", which is a planning question, and §17.5.1 gives it
        its own name for exactly that reason.

        THE UNION IS ORDERED, WHICH MATTERS MORE THAN IT LOOKS. The two sequences are concatenated
        admitted-first and then sorted on `relation_id`, so the same prediction evaluated twice
        produces an identical `TransitionDecision` -- §26 requires that, and `evaluate` reaches
        into `admitted_relations` for the required relation types, where an unstable order would
        change nothing today and change `blocking_conflict_ids` ordering the moment it does.

        A hypothetical relation is **not** counted as an independent attestation. `sufficiency` is
        about whether an outcome would change the verdict, and inflating the independence count
        would answer a different question -- one where the evidence has already been gathered.
        `independence_summary` is passed through untouched; a caller modelling the independence a
        new measurement would add says so by passing a different summary.
        """
        combined = tuple(
            sorted(
                (*admitted_relations, *hypothetical_relations),
                key=lambda relation: relation.relation_id,
            )
        )
        return self._decide(
            hypothesis,
            combined,
            authority_policy,
            condition_matches,
            independence_summary,
            candidate_to_state,
        )

    # ---------------------------------------------------------------------------------------
    # The body is split out only so `evaluate` keeps §8.2.1's signature visible and unpolluted.
    # ---------------------------------------------------------------------------------------

    def _decide(
        self,
        hypothesis: HypothesisView,
        admitted_relations: tuple[RelationJudgment, ...],
        authority_policy: AuthorityPolicy | None,
        condition_matches: tuple[ConditionMatch, ...],
        independence_summary: IndependenceSummary,
        candidate_to_state: BeliefState,
    ) -> TransitionDecision:
        independent = independence_summary.independent_count

        def decide(
            outcome: TransitionOutcome,
            reason: TransitionReason,
            *,
            conflicts: tuple[str, ...] = (),
            gap: str | None = None,
            review: bool = False,
            counted: int | None = None,
        ) -> TransitionDecision:
            return TransitionDecision(
                outcome=outcome,
                reason_code=reason,
                policy_id=self.policy_id,
                policy_version=self.version,
                blocking_conflict_ids=conflicts,
                required_authority_gap=gap,
                independent_attestation_count=independent if counted is None else counted,
                review_item_spec=(
                    ReviewItemSpec(
                        subject_type=_REVIEW_SUBJECT_FOR.get(reason, reason.value),
                        subject_id=hypothesis.hypothesis_id,
                        stakes=hypothesis.stakes,
                        reason=reason,
                    )
                    if review
                    else None
                ),
            )

        # 1. Does this policy govern the transition being asked about at all?
        if (
            hypothesis.current_state is not self.from_state
            or candidate_to_state is not self.candidate_to_state
        ):
            return decide(TransitionOutcome.DENY, TransitionReason.TRANSITION_NOT_GOVERNED)

        # 2. A blocking conflict prevents ALLOW and appears in the decision (§23.4, §17.19.3).
        #    Human review rather than DENY: the conflict is resolvable, and resolving it is a
        #    human act.
        #
        #    Matched on `conflict_type` against this policy's declared `blocking_conflict_policy`,
        #    and on the conflict's own `blocking` flag and resolution status -- not on ids the
        #    caller pre-selected. A resolved blocking conflict is history and an unresolved
        #    non-blocking one is a recorded disagreement the domain has said does not gate belief;
        #    only the intersection stops a transition.
        blocking_types = frozenset(self.blocking_conflict_policy)
        if blocking_types:
            matching = tuple(
                sorted(
                    conflict.conflict_id
                    for conflict in hypothesis.conflicts
                    if conflict.blocks_transitions
                    and conflict.conflict_type.value in blocking_types
                )
            )
            if matching:
                return decide(
                    TransitionOutcome.NEED_HUMAN_REVIEW,
                    TransitionReason.BLOCKING_CONFLICT,
                    conflicts=matching,
                    review=True,
                )

        # 3. §6.17 / FIX-6: a declared basis above WORK MUST yield NEED_HUMAN_REVIEW rather than
        #    pretend to be satisfied. Checked before the thresholds, because the count computed
        #    under an unmodelled basis is not a number anyone should act on.
        basis = self.independence_basis
        if basis is not None and basis not in IMPLEMENTED_INDEPENDENCE_BASES:
            return decide(
                TransitionOutcome.NEED_HUMAN_REVIEW,
                TransitionReason.INDEPENDENCE_BASIS_NOT_MODELLED,
                review=True,
            )
        if basis is not None and independence_summary.basis is not basis:
            return decide(
                TransitionOutcome.NEED_HUMAN_REVIEW,
                TransitionReason.INDEPENDENCE_BASIS_NOT_MODELLED,
                review=True,
            )

        # 4. Required relation types. Sorted before use: `required_relation_types` is a tuple, but
        #    the set difference below would otherwise iterate in an unstable order.
        present = {relation.relation_type for relation in admitted_relations}
        if any(required not in present for required in self.required_relation_types):
            return decide(
                TransitionOutcome.NEED_MORE_EVIDENCE,
                TransitionReason.MISSING_REQUIRED_RELATION_TYPE,
            )

        # 4b. Causal Warrant Gate: a required SUPPORTS or CONTRADICTS counts only when an
        #     accountable source warrants its link, and steps 5-7 then read only those relations.
        gated = tuple(t for t in self.required_relation_types if t in _GATED_TYPES)
        if self.diagnostic_warrant_required and gated:
            # Each gated type the policy requires must stand on its own warranted relations; a
            # warranted SUPPORTS does not stand in for an unwarranted CONTRADICTS, or the reverse.
            verdict = None
            for kind in sorted(set(gated), key=lambda t: t.value):
                verdict = self._decide_warranted(
                    decide,
                    hypothesis,
                    admitted_relations,
                    authority_policy,
                    condition_matches,
                    (kind,),
                )
                if verdict.outcome is not TransitionOutcome.ALLOW:
                    return verdict
            assert verdict is not None
            return verdict

        verdict = self._thresholds(
            decide,
            authority_policy,
            condition_matches,
            tuple(sorted(set(hypothesis.admitted_authority_classes))),
            independent,
        )
        if verdict is not None:
            return verdict

        return self._last_word(decide)

    def _last_word(self, decide: _Decide, counted: int | None = None) -> TransitionDecision:
        # 8. An explicit human gate is the last word, so a policy cannot be configured to require
        #    review and then satisfy itself.
        if self.human_gate:
            return decide(
                TransitionOutcome.NEED_HUMAN_REVIEW,
                TransitionReason.HUMAN_GATE_REQUIRED,
                review=True,
                counted=counted,
            )

        return decide(TransitionOutcome.ALLOW, TransitionReason.POLICY_SATISFIED, counted=counted)

    def _thresholds(
        self,
        decide: _Decide,
        authority_policy: AuthorityPolicy | None,
        condition_matches: tuple[ConditionMatch, ...],
        classes: tuple[str, ...],
        independent: int,
        counted: int | None = None,
    ) -> TransitionDecision | None:
        """Steps 5-7 over the given inputs; None when all three are met.

        The bodies are the ones `_decide` always had, moved here unchanged so an ungated policy
        decides exactly as before and the gated path asks the same questions of fewer relations.
        """
        # 5. Condition matches.
        if self.required_condition_match:
            if not condition_matches:
                return decide(
                    TransitionOutcome.NEED_MORE_EVIDENCE,
                    TransitionReason.CONDITION_MATCH_MISSING,
                    counted=counted,
                )
            acceptable = set(self.required_condition_match)
            for match in condition_matches:
                if match.state is ConditionMatchState.UNKNOWN:
                    # §17.19: UNKNOWN is deliberately distinct from INCOMPATIBLE. "We cannot tell"
                    # is not a verdict, so it escalates instead of being read as either answer.
                    return decide(
                        TransitionOutcome.NEED_HUMAN_REVIEW,
                        TransitionReason.CONDITION_MATCH_UNKNOWN,
                        review=True,
                        counted=counted,
                    )
                if match.state not in acceptable:
                    return decide(
                        TransitionOutcome.DENY,
                        TransitionReason.CONDITION_MATCH_UNACCEPTABLE,
                        counted=counted,
                    )

        # 6. Authority. INCOMPARABLE first, because it is the one result that must never be
        #    resolved into an ordering (§10.5.1).
        if self.required_authority_rule is not None:
            if authority_policy is None:
                return decide(
                    TransitionOutcome.NEED_HUMAN_REVIEW,
                    TransitionReason.AUTHORITY_INCOMPARABLE,
                    gap=self.required_authority_rule,
                    review=True,
                    counted=counted,
                )
            if not classes:
                # A rule with nothing to test it against cannot be satisfied, and must not be
                # treated as satisfied. Escalates rather than DENYing, because the usual cause is
                # that the caller has not resolved the authority classes yet.
                return decide(
                    TransitionOutcome.NEED_HUMAN_REVIEW,
                    TransitionReason.AUTHORITY_INCOMPARABLE,
                    gap=self.required_authority_rule,
                    review=True,
                    counted=counted,
                )
            for candidate in classes:
                if (
                    authority_policy.compare(candidate, self.required_authority_rule)
                    is AuthorityComparison.INCOMPARABLE
                ):
                    return decide(
                        TransitionOutcome.NEED_HUMAN_REVIEW,
                        TransitionReason.AUTHORITY_INCOMPARABLE,
                        gap=self.required_authority_rule,
                        review=True,
                        counted=counted,
                    )
            if not any(
                authority_policy.meets(self.required_authority_rule, candidate)
                for candidate in classes
            ):
                return decide(
                    TransitionOutcome.DENY,
                    TransitionReason.AUTHORITY_INSUFFICIENT,
                    gap=self.required_authority_rule,
                    counted=counted,
                )

        # 7. Independent attestations. The unknown ones contribute 0 and the shortfall is reported
        #    rather than guessed away (EVI-004).
        if (
            self.min_independent_attestations is not None
            and independent < self.min_independent_attestations
        ):
            return decide(
                TransitionOutcome.NEED_MORE_EVIDENCE,
                TransitionReason.INSUFFICIENT_INDEPENDENT_ATTESTATIONS,
                counted=counted,
            )
        return None

    def _decide_warranted(
        self,
        decide: _Decide,
        hypothesis: HypothesisView,
        admitted_relations: tuple[RelationJudgment, ...],
        authority_policy: AuthorityPolicy | None,
        condition_matches: tuple[ConditionMatch, ...],
        gated: tuple[RelationType, ...],
    ) -> TransitionDecision:
        """Steps 5-8 over warranted relations; a person only where a warrant would decide.

        A relation's facts count only when its record names it exactly -- same id, same type,
        same prediction -- so a record cannot lend a warrant to a relation it does not describe.
        Unwarranted relations go to review only when warranting them would change the verdict:
        one that would fail on authority or conditions anyway is answered as that failure, and a
        person is never asked a question whose answer cannot matter.
        """
        relations = {r.relation_id: r for r in admitted_relations if r.relation_type in gated}
        facts: dict[str, RelationEvidence] = {}
        for record in hypothesis.relation_evidence:
            relation = relations.get(record.relation_id)
            if (
                relation is None
                or record.relation_type is not relation.relation_type
                or record.prediction_id != relation.attributes.get("prediction_id")
            ):
                continue
            facts[record.relation_id] = record
        ordered = sorted(relations)
        warranted = [i for i in ordered if i in facts and facts[i].warranted]
        open_ = [
            i for i in ordered if not (i in facts and (facts[i].warranted or facts[i].refused))
        ]

        def lines(ids: list[str]) -> int:
            return len(
                {facts[i].evidence_line for i in ids if i in facts and facts[i].evidence_line}
            )

        def thresholds(ids: list[str]) -> TransitionDecision | None:
            refs = {relations[i].condition_match_ref for i in ids}
            matches = tuple(m for m in condition_matches if m.condition_match_id in refs)
            classes = sorted({c for i in ids if i in facts for c in facts[i].authority_classes})
            counted = lines(ids)
            return self._thresholds(
                decide, authority_policy, matches, tuple(classes), counted, counted=counted
            )

        def ask() -> TransitionDecision:
            return decide(
                TransitionOutcome.NEED_HUMAN_REVIEW,
                TransitionReason.DIAGNOSTIC_WARRANT_MISSING,
                review=True,
                counted=lines(warranted),
            )

        # A relation nobody resolved facts for cannot be weighed at all, so it can only be asked
        # about -- never counted, and never read as an authority or condition failure it may not be.
        known = [i for i in open_ if i in facts]
        unknown = [i for i in open_ if i not in facts]
        if warranted:
            verdict = thresholds(warranted)
            if verdict is None:
                return self._last_word(decide, counted=lines(warranted))
            if unknown or (known and thresholds(warranted + known) is None):
                return ask()
            return verdict
        if known:
            verdict = thresholds(known)
            if verdict is None or unknown:
                return ask()
            return verdict
        if unknown:
            return ask()
        return decide(
            TransitionOutcome.NEED_MORE_EVIDENCE,
            TransitionReason.DIAGNOSTIC_WARRANT_REFUSED,
            counted=0,
        )


#: The review subject a reason asks for, where it is not the reason's own name. Every other reason
#: keeps the value it always had, so no stored decision's `review_item_spec` changes.
_REVIEW_SUBJECT_FOR: Final[dict[TransitionReason, str]] = {
    TransitionReason.AUTHORITY_INCOMPARABLE: "AUTHORITY_CONFLICT",
    TransitionReason.DIAGNOSTIC_WARRANT_MISSING: "DIAGNOSTIC_WARRANT",
}


__all__ = [
    "HypothesisView",
    "IndependenceSummary",
    "RelationEvidence",
    "ReviewItemSpec",
    "TransitionDecision",
    "TransitionOutcome",
    "TransitionPolicy",
    "TransitionReason",
    "WarrantBasis",
]
