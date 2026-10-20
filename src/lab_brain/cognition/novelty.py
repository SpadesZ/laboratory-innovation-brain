"""§7.1's Novelty Auditor: a prior-art search that records its coverage, and a status bound to it.

    SRC-003  任何 novelty status MUST 引用 PriorArtSearchRecord，記錄 sources、queries、
             date range 與 limitations。無覆蓋率記錄的 novelty status MUST 被拒絕；
             internal novelty MUST NOT 被當作 global novelty 呈現。
    §7.1     Novelty Auditor 預設不看 private raw data；沒搜到不能宣告全球唯一。
    §7.4     Sanitized surviving concept -> Prior-art matrix + novelty status +
             PriorArtSearchRecord

COVERAGE IS WHAT WAS ACTUALLY SEARCHED, NOT WHAT WAS CONFIGURED. `SourceRouter.search` skips a
provider that is unreachable or that this actor may not reach with this material, and returns what
the others found -- which is right for a researcher's query and would be wrong for a coverage
record: "no prior art in the patent corpus" and "the patent corpus was not searched" would read the
same. So before searching, the search asks the router which declared providers are reachable AND
authorized, records only those as `sources`, and writes every declared provider it could NOT search
into `limitations`. A global-scope claim then fails against a record that honestly lacks the class.

THE CONCEPT IS SANITIZED BY A PERSON. §7.1's auditor sees a "sanitized concept", never raw data.
Deciding that a concept is safe to send is a human act (P12), recorded as
`SanitizedConcept.sanitized_by_actor_id` with the label the person declared -- and that label is
what SEC-001's egress gate judges, so a concept declared INTERNAL cannot reach a provider the
project's egress policy does not open to INTERNAL.

THE AUDITOR'S STATUS IS CHECKED AGAINST THE RECORD, NOT TRUSTED. A model reply claiming GLOBAL scope
over an internal-only search is refused (`NoveltyRefused`) and nothing is stored: the system does
not quietly rewrite a scientific claim into a weaker one, and it does not store the stronger one.
`002b` refuses the same row for any writer of SQL.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lab_brain.cognition.budgeted import BudgetedInferenceDispatcher, InferenceCall
from lab_brain.cognition.evidence import EvidenceCatalog
from lab_brain.cognition.roles import NOVELTY_AUDITOR, parse_novelty, require_input
from lab_brain.cognition.routing import CognitiveRole, ModelRouter
from lab_brain.core.budget import BudgetPolicy
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.models.prior_art import (
    INTERNAL_TRUST_CLASSES,
    DateRange,
    NoveltyAssessment,
    NoveltyScope,
    PriorArtSearchRecord,
    PriorArtSource,
    novelty_coverage_problems,
)
from lab_brain.core.repositories.prior_art import PriorArtStore
from lab_brain.core.repositories.protocols import EvidenceBundleRepository
from lab_brain.evidence.retriever import tokenize
from lab_brain.evidence.source_policy import IntentSourcePolicy
from lab_brain.sources.adapter import SourceQuery, SourceRouter

#: The internal corpus's source identity in a coverage record.
INTERNAL_SOURCE_ID = "internal:lab-records"


class NoveltyRefused(RuntimeError):
    """A novelty status was refused: its search does not cover what the status claims."""


@dataclass(frozen=True)
class SanitizedConcept:
    """What the auditor may see and send: a concept a person declared safe, and at what label."""

    subject_id: str
    text: str
    declared_label: SensitivityLabel
    sanitized_by_actor_id: str

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.sanitized_by_actor_id.strip():
            raise ValueError(
                "a sanitized concept names its text and the person who sanitized it (§7.1, P12)"
            )


@dataclass(frozen=True)
class PriorArtSourceBinding:
    """The deployment's declaration of which §6.5 classes an external provider covers."""

    provider_id: str
    trust_classes: tuple[TrustClass, ...]


@dataclass(frozen=True)
class PriorArtHit:
    record_id: str
    title: str
    source_type: str
    trust_class: str


class PriorArtSearch:
    """Run a coverage-recorded prior-art search and store its PriorArtSearchRecord."""

    def __init__(
        self,
        *,
        router: SourceRouter,
        bindings: Sequence[PriorArtSourceBinding],
        internal: EvidenceCatalog | None,
        store: PriorArtStore,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._router = router
        self._bindings = tuple(bindings)
        self._internal = internal
        self._store = store
        self._mint = mint
        self._now = now

    def search(
        self,
        *,
        concept: SanitizedConcept,
        queries: Sequence[str],
        date_range: DateRange | None,
        policy: IntentSourcePolicy,
        project_id: str,
        episode_id: str,
        actor_id: str,
        include_internal: bool = True,
    ) -> tuple[PriorArtSearchRecord, tuple[PriorArtHit, ...]]:
        if not queries:
            raise ValueError("a prior-art search needs at least one query")
        escalate = frozenset({concept.declared_label})
        reachable = {r.provider_id for r in self._router.health() if r.reachable}
        registered = set(self._router.providers)
        authorized = set(
            self._router.authorized_providers(
                project_id=project_id, actor_id=actor_id, escalate=escalate
            )
        )
        sources: list[PriorArtSource] = []
        limitations: list[str] = [
            "only the sources listed were searched; the absence of a match is not evidence that no "
            "prior art exists (沒搜到不能宣告全球唯一)",
            "matching is lexical over titles and indexed text; a differently worded disclosure of "
            "the same idea may not match",
        ]
        if date_range is not None:
            limitations.append(
                f"publications outside {date_range.start.isoformat()}.."
                f"{date_range.end.isoformat()} were not considered"
            )
        for binding in sorted(self._bindings, key=lambda b: b.provider_id):
            if binding.provider_id not in registered:
                limitations.append(f"{binding.provider_id} is declared but not registered")
            elif binding.provider_id not in reachable:
                limitations.append(f"{binding.provider_id} was unreachable and was not searched")
            elif binding.provider_id not in authorized:
                limitations.append(
                    f"{binding.provider_id} may not receive material labelled "
                    f"{concept.declared_label.value} and was not searched (SEC-001)"
                )
            else:
                sources.append(
                    PriorArtSource(
                        provider_id=binding.provider_id, trust_classes=binding.trust_classes
                    )
                )

        hits: dict[str, PriorArtHit] = {}
        raw = 0
        searched = {s.provider_id for s in sources}
        since = (
            dt.datetime.combine(date_range.start, dt.time(), tzinfo=dt.UTC)
            if date_range is not None
            else None
        )
        for query in queries:
            for found in self._router.search(
                SourceQuery(text=query, since=since),
                project_id=project_id,
                actor_id=actor_id,
                escalate=escalate,
            ):
                if found.provider not in searched:
                    continue
                raw += 1
                hits.setdefault(
                    found.canonical_locator,
                    PriorArtHit(
                        record_id=found.canonical_locator,
                        title=found.title or "",
                        source_type=found.source_type,
                        trust_class=found.trust_class.value,
                    ),
                )
        if include_internal and self._internal is not None:
            sources.append(
                PriorArtSource(
                    provider_id=INTERNAL_SOURCE_ID,
                    trust_classes=tuple(sorted(INTERNAL_TRUST_CLASSES)),
                )
            )
            for query in queries:
                terms = frozenset(tokenize(query))
                for item in self._internal.items(project_id):
                    if item.trust_class not in INTERNAL_TRUST_CLASSES:
                        continue
                    if terms & frozenset(tokenize(item.text)):
                        raw += 1
                        hits.setdefault(
                            item.attestation_id,
                            PriorArtHit(
                                record_id=item.attestation_id,
                                title=item.text[:80],
                                source_type="internal_attestation",
                                trust_class=item.trust_class.value,
                            ),
                        )
        if not sources:
            raise NoveltyRefused(
                "no source could be searched for this concept, so no coverage record can be "
                f"written; limitations: {limitations}"
            )
        ordered = tuple(hits[k] for k in sorted(hits))
        covered = sorted({c.value for s in sources for c in s.trust_classes})
        record = PriorArtSearchRecord(
            search_id=self._mint("prior_art_search"),
            project_id=project_id,
            episode_id=episode_id,
            intent=policy.intent,
            sources=tuple(sources),
            queries=tuple(queries),
            date_range=date_range,
            retrieved_at=self._now(),
            source_policy_version=policy.version,
            result_count=raw,
            deduped_work_count=len(ordered),
            limitations=tuple(limitations),
            coverage_notes=f"covered trust classes: {covered}",
            external_source_record_ids=tuple(h.record_id for h in ordered),
        )
        return self._store.add_search(record), ordered


class NoveltyAuditor:
    """The Novelty Auditor role: a durable, budgeted judgment, checked against its search."""

    def __init__(
        self,
        *,
        router: ModelRouter,
        dispatcher: BudgetedInferenceDispatcher,
        bundles: EvidenceBundleRepository,
        store: PriorArtStore,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._router = router
        self._dispatcher = dispatcher
        self._bundles = bundles
        self._store = store
        self._mint = mint
        self._now = now

    def assess(
        self,
        *,
        concept: SanitizedConcept,
        record: PriorArtSearchRecord,
        hits: Sequence[PriorArtHit],
        policy: IntentSourcePolicy,
        stakes: str,
        trace_id: str,
        actor_id: str,
        budget_policy: BudgetPolicy | None,
    ) -> NoveltyAssessment:
        # The bundle names the prior-art records it was built over (`source_snapshot_refs`), so the
        # judgment's provenance says exactly which search results it saw.
        bundle = self._bundles.add(
            EvidenceBundle(
                bundle_id=self._mint("evidence_bundle"),
                research_intent=ResearchIntent(intent=policy.intent, stakes=stakes),
                query_text=concept.text,
                source_policy_id=policy.policy_id,
                source_policy_version=policy.version,
                source_snapshot_refs=tuple(h.record_id for h in hits),
                retrieval_trace_id=trace_id,
                project_id=record.project_id,
                created_at=self._now(),
            )
        )
        context = {
            "concept": concept.text,
            "records": [
                {
                    "record_id": h.record_id,
                    "title": h.title,
                    "source_type": h.source_type,
                    "trust_class": h.trust_class,
                }
                for h in hits
            ],
            "coverage": {
                "internal_only": record.internal_only,
                "covered_trust_classes": sorted(c.value for c in record.covered_trust_classes),
                "required_for_global": sorted(c.value for c in policy.global_novelty_requires),
                "limitations": list(record.limitations),
            },
        }
        require_input(NOVELTY_AUDITOR.role.value, NOVELTY_AUDITOR.requires, context)
        result = self._dispatcher.infer(
            InferenceCall(
                slot=self._router.route(CognitiveRole.NOVELTY_AUDITOR),
                role=CognitiveRole.NOVELTY_AUDITOR.value,
                prompt_id=NOVELTY_AUDITOR.prompt.prompt_id,
                prompt_text=NOVELTY_AUDITOR.prompt.template,
                bundle=bundle,
                context=context,
                project_id=record.project_id,
                episode_id=record.episode_id,
                trace_id=trace_id,
                actor_id=actor_id,
                action_ref=f"{record.search_id}:novelty",
                span_id=self._mint("execution_span"),
                estimate_entry_id=f"cst:{record.search_id}:novelty:est",
                actual_entry_id=f"cst:{record.search_id}:novelty:act",
                inference_id=self._mint("inference"),
                escalate=frozenset({concept.declared_label}),
            ),
            policy=budget_policy,
        )
        draft = parse_novelty(
            result.inference.text,
            record_ids=[h.record_id for h in hits],
            inference_id=result.inference.inference_id,
        )
        assessment = NoveltyAssessment(
            assessment_id=self._mint("novelty_assessment"),
            project_id=record.project_id,
            episode_id=record.episode_id,
            subject_id=concept.subject_id,
            search_id=record.search_id,
            status=draft.status,
            scope=draft.scope,
            global_coverage_required=tuple(sorted(policy.global_novelty_requires)),
            prior_art_matrix=draft.matrix,
            inference_provenance_id=result.inference.inference_id,
            created_at=self._now(),
        )
        problems = novelty_coverage_problems(record, assessment)
        if problems:
            raise NoveltyRefused(
                f"the auditor's status ({draft.status.value}, {draft.scope.value}) is refused and "
                f"nothing is stored: {'; '.join(problems)}"
            )
        return self._store.add_assessment(assessment)


def present(assessment: NoveltyAssessment, record: PriorArtSearchRecord) -> str:
    """How a novelty status may be shown to a person: with its scope, coverage and limitations.

    SRC-003's second sentence is about PRESENTATION, so the one sanctioned rendering always states
    the scope in words and never uses "novel" without it.
    """
    scope = (
        "within the lab's internal records only -- NOT a global novelty claim"
        if assessment.scope is NoveltyScope.INTERNAL
        else "against the external coverage recorded below"
    )
    classes = ", ".join(sorted(c.value for c in record.covered_trust_classes))
    return (
        f"{assessment.status.value} {scope}. Search {record.search_id}: "
        f"{len(record.queries)} queries, sources [{classes}], "
        f"{record.deduped_work_count} distinct works. Limitations: "
        + " | ".join(record.limitations)
    )


__all__ = [
    "INTERNAL_SOURCE_ID",
    "NoveltyAuditor",
    "NoveltyRefused",
    "PriorArtHit",
    "PriorArtSearch",
    "PriorArtSourceBinding",
    "SanitizedConcept",
    "present",
]
