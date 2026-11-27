"""Equal-scoring evidence is ordered by its content, never by the id an admission happened to mint.

Attestation ids are minted fresh at every admission -- each research run admits its statements
again, in each project -- so a tie broken by id gave the same evidence a different order (and, at
the `max_items` cut, a different selection) every time. The same statements admitted under other
ids must now yield the same bundle content in the same order.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import itertools

from lab_brain.cognition.evidence import EvidenceItem, EvidenceResearcher, StaticEvidenceCatalog
from lab_brain.core.models.enums import TrustClass
from lab_brain.core.repositories.memory import InMemoryEvidenceBundleRepository
from lab_brain.evidence.source_policy import ResearchIntentKind, default_source_policies

PROJECT = "prj:tie-order"
POLICY = next(p for p in default_source_policies() if p.intent is ResearchIntentKind.DIAGNOSIS)
QUERY = "series resistance contact"
#: Each names all three query terms once and has the same trust class: they tie on relevance.
TIED = (
    "Series resistance and contact resistance were both logged.",
    "A contact on split B shows a higher series resistance.",
    "The series resistance includes the contact term.",
    "Contact quality limits the series resistance here.",
)


def _item(attestation_id: str, text: str) -> EvidenceItem:
    return EvidenceItem(
        attestation_id=attestation_id,
        project_id=PROJECT,
        text=text,
        trust_class=TrustClass.INTERNAL_MEASUREMENT,
        domain="toy",
    )


def _texts(items: list[EvidenceItem], query: str = QUERY, max_items: int = 8) -> list[str]:
    counter = itertools.count()
    researcher = EvidenceResearcher(
        catalog=StaticEvidenceCatalog(items),
        bundles=InMemoryEvidenceBundleRepository(),
        mint=lambda kind: f"{kind}:{next(counter)}",
        now=lambda: dt.datetime(2026, 10, 8, tzinfo=dt.UTC),
    )
    bundle = researcher.retrieve(
        query_text=query,
        policy=dataclasses.replace(POLICY, max_items=max_items),
        stakes="NORMAL",
        project_id=PROJECT,
        trace_id="trc:tie-order",
    )
    by_id = {i.attestation_id: i.text for i in items}
    return [by_id[a] for a in bundle.ordered_attestation_ids]


def _admitted(ids: list[str]) -> list[EvidenceItem]:
    return [_item(a, t) for a, t in zip(ids, TIED, strict=True)]


def test_tied_statements_come_in_the_order_of_their_text_whatever_ids_were_minted():
    orders = [
        _texts(_admitted(ids))
        for ids in (
            ["att:4", "att:3", "att:2", "att:1"],
            ["att:a", "att:c", "att:b", "att:d"],
            ["att:f00", "att:0ff", "att:777", "att:123"],
        )
    ]
    assert orders[0] == orders[1] == orders[2] == sorted(TIED)


def test_the_max_items_cut_keeps_the_same_statements_whatever_ids_were_minted():
    kept = {
        tuple(_texts(_admitted(list(ids)), max_items=2))
        for ids in itertools.permutations(["att:1", "att:2", "att:3", "att:4"])
    }
    assert kept == {tuple(sorted(TIED)[:2])}


def test_relevance_still_decides_before_the_text_does():
    best = _item("att:9", "zz series resistance contact")
    order = _texts([*_admitted(["att:1", "att:2", "att:3", "att:4"]), best], query=QUERY + " zz")
    assert order == [best.text, *sorted(TIED)]
