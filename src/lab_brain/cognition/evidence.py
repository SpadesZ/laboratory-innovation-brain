"""The Evidence Researcher's retrieval: intent-aware, deterministic, always a stored bundle (§7.5).

    §7.5  SourceRouter 先過 privacy/rights/ACL，再依 research intent 選 SourcePolicy，最後做
          condition compatibility、source-work independence、authority/directness、semantic
          relevance、recency 與 retrieval cost。
          Always: ACL/privacy -> condition/schema compatibility -> source-work dedup
                  -> authority/directness -> relevance -> time/cost.

THE ORDER IS §7.5's, AND EACH STEP REMOVES SOMETHING BEFORE THE NEXT CAN RANK IT:

    project scope          only this project's evidence -- an item from another project is never
                           a candidate, not a low-ranked one (SEC-002)
    source class           the SourcePolicy's admitted §6.5 trust classes (primary) or its
                           declared inverted classes (the Critic's retrieval)
    domain                 a Domain Specialist reads only its DomainPack's evidence domains (§7.1)
    source-work dedup      one item per SourceWork, so a preprint and its journal version cannot
                           appear as two pieces of evidence in one bundle (EVI-004)
    relevance              lexical overlap with the query, M1's tokenizer, ties broken by the
                           policy's class preference and then by id

Condition compatibility is not a filter here: evidence reaches this catalog already admitted with a
registered condition schema (EVI-005), and interpreting conditions is TransitionPolicy's, on
ConditionMatch, at transition time -- a retriever that dropped items on its own reading of
conditions would be a second, unversioned condition comparator.

EVERY RETRIEVAL IS A STORED BUNDLE, INCLUDING AN EMPTY ONE. §17.14.1: "we looked under this policy
and found nothing" is a reproducible result. And SRC-002 requires the Critic's inverted bundle to be
SAVED, so the researcher writes every bundle through the `EvidenceBundleRepository` before returning
it -- a caller cannot hold a bundle that is not on record.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from lab_brain.core.models.enums import TrustClass
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.repositories.protocols import EvidenceBundleRepository
from lab_brain.evidence.retriever import tokenize
from lab_brain.evidence.source_policy import IntentSourcePolicy


@dataclass(frozen=True)
class EvidenceItem:
    """One admitted attestation, as retrieval sees it: its text, its kind and its domain."""

    attestation_id: str
    project_id: str
    text: str
    trust_class: TrustClass
    domain: str
    source_work_id: str | None = None


@runtime_checkable
class EvidenceCatalog(Protocol):
    def items(self, project_id: str) -> Sequence[EvidenceItem]: ...


class StaticEvidenceCatalog:
    """A catalog over a declared set of items. Used by tests, the benchmark and the vertical."""

    def __init__(self, items: Iterable[EvidenceItem]) -> None:
        self._items = tuple(items)
        ids = [i.attestation_id for i in self._items]
        if len(set(ids)) != len(ids):
            raise ValueError("an evidence catalog lists an attestation twice")

    def items(self, project_id: str) -> Sequence[EvidenceItem]:
        return tuple(i for i in self._items if i.project_id == project_id)


class EvidenceResearcher:
    """§7.1's Evidence Researcher: finds evidence, never writes any (它不能用自己生成文字補證據)."""

    def __init__(
        self,
        *,
        catalog: EvidenceCatalog,
        bundles: EvidenceBundleRepository,
        mint: Callable[[str], str],
        now: Callable[[], dt.datetime],
    ) -> None:
        self._catalog = catalog
        self._bundles = bundles
        self._mint = mint
        self._now = now

    def item(self, project_id: str, attestation_id: str) -> EvidenceItem | None:
        for item in self._catalog.items(project_id):
            if item.attestation_id == attestation_id:
                return item
        return None

    def seed(
        self,
        *,
        question: str,
        policy: IntentSourcePolicy,
        stakes: str,
        project_id: str,
        trace_id: str,
    ) -> EvidenceBundle:
        """A bundle with no evidence: the question under the policy, before anything is retrieved.

        The FAST_UTILITY query rewrite needs a bundle -- §17.14 requires one for every scientific
        call -- and at that moment nothing has been retrieved. An empty bundle is the honest record
        of that: it names the query and the policy and cites nothing.
        """
        return self._store(
            query_text=question,
            policy=policy,
            stakes=stakes,
            project_id=project_id,
            trace_id=trace_id,
            ids=(),
        )

    def retrieve(
        self,
        *,
        query_text: str,
        policy: IntentSourcePolicy,
        stakes: str,
        project_id: str,
        trace_id: str,
        inverted: bool = False,
        domains: Sequence[str] | None = None,
        exclude: Iterable[str] = (),
    ) -> EvidenceBundle:
        classes = policy.inverted_source_classes if inverted else policy.source_classes
        excluded = frozenset(exclude)
        query_tokens = frozenset(tokenize(query_text))
        scored: list[tuple[int, int, str, EvidenceItem]] = []
        for item in self._catalog.items(project_id):
            if item.project_id != project_id or item.attestation_id in excluded:
                continue
            if item.trust_class not in classes:
                continue
            if domains is not None and item.domain not in domains:
                continue
            overlap = len(query_tokens & frozenset(tokenize(item.text)))
            if overlap == 0:
                continue
            preference = classes.index(item.trust_class)
            scored.append((-overlap, preference, item.attestation_id, item))
        chosen: list[str] = []
        works: set[str] = set()
        for _, _, _, item in sorted(scored):
            if item.source_work_id is not None:
                if item.source_work_id in works:
                    continue
                works.add(item.source_work_id)
            chosen.append(item.attestation_id)
            if len(chosen) >= policy.max_items:
                break
        return self._store(
            query_text=query_text,
            policy=policy,
            stakes=stakes,
            project_id=project_id,
            trace_id=trace_id,
            ids=tuple(chosen),
        )

    def combined(
        self,
        bundles: Sequence[EvidenceBundle],
        *,
        query_text: str,
        policy: IntentSourcePolicy,
        stakes: str,
        project_id: str,
        trace_id: str,
    ) -> EvidenceBundle:
        """One bundle holding several retrievals' evidence, in order, each attestation once.

        The Critic cross-examines ALL the evidence the positions it attacks were formed from, plus
        its own inverted retrieval. Everything it is shown is in this bundle, so SEC-001 classifies
        exactly what is sent and the critique's provenance names exactly what it saw.
        """
        ids: list[str] = []
        for bundle in bundles:
            for attestation_id in bundle.ordered_attestation_ids:
                if attestation_id not in ids:
                    ids.append(attestation_id)
        return self._store(
            query_text=query_text,
            policy=policy,
            stakes=stakes,
            project_id=project_id,
            trace_id=trace_id,
            ids=tuple(ids),
        )

    def evidence_context(self, bundle: EvidenceBundle) -> list[dict[str, str]]:
        """The text of a bundle's attestations, in bundle order, for a role's prompt context."""
        out: list[dict[str, str]] = []
        for attestation_id in bundle.ordered_attestation_ids:
            item = self.item(bundle.project_id, attestation_id)
            if item is None:
                raise ValueError(
                    f"bundle {bundle.bundle_id} names {attestation_id}, which this catalog cannot "
                    "resolve in its project; a role may only be shown evidence that resolves"
                )
            out.append(
                {
                    "attestation_id": item.attestation_id,
                    "trust_class": item.trust_class.value,
                    "text": item.text,
                }
            )
        return out

    def _store(
        self,
        *,
        query_text: str,
        policy: IntentSourcePolicy,
        stakes: str,
        project_id: str,
        trace_id: str,
        ids: tuple[str, ...],
    ) -> EvidenceBundle:
        bundle = EvidenceBundle(
            bundle_id=self._mint("evidence_bundle"),
            research_intent=ResearchIntent(intent=policy.intent, stakes=stakes),
            query_text=query_text,
            source_policy_id=policy.policy_id,
            source_policy_version=policy.version,
            ordered_attestation_ids=ids,
            retrieval_trace_id=trace_id,
            project_id=project_id,
            created_at=self._now(),
        )
        return self._bundles.add(bundle)


__all__ = [
    "EvidenceCatalog",
    "EvidenceItem",
    "EvidenceResearcher",
    "StaticEvidenceCatalog",
]
