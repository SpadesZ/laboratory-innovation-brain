"""§17.20's PriorArtSearchRecord, and the novelty status that must cite one (SRC-003).

    SRC-003  任何 novelty status MUST 引用 PriorArtSearchRecord，記錄 sources、queries、date range
             與 limitations。無覆蓋率記錄的 novelty status MUST 被拒絕；internal novelty MUST NOT
             被當作 global novelty 呈現。
    §7.1     Novelty Auditor ... 沒搜到不能宣告全球唯一。

THE RECORD IS ABOUT COVERAGE, NOT RESULTS. "We found no prior art" is a statement about a search,
and it means nothing without the search: which sources, which queries, which dates, and what the
search could not see. A novelty status that cannot name its search is refused, and the refusal is a
type -- `NoveltyAssessment.search_id` is required and the database's foreign key makes it resolve.

INTERNAL IS NOT GLOBAL, AND THE DIFFERENCE IS DERIVED. Whether a search covered the world or only
the lab is read off `sources[]` -- each source declares the §6.5 trust classes it covers -- rather
than off anything the auditor asserts. A search over lab runs and lab measurements covers only
INTERNAL_* classes, and `assess_novelty` refuses a GLOBAL scope over it whatever the auditor said.
The strongest status there is is `NOVELTY_CANDIDATE`: §7.1 forbids "全球唯一", so no value here
means "novel", only "no prior art found within this coverage".
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import TrustClass

#: §6.5 source kinds that are the lab's own records. A search over only these is an internal search.
INTERNAL_TRUST_CLASSES: frozenset[TrustClass] = frozenset(
    {TrustClass.INTERNAL_RUN, TrustClass.INTERNAL_MEASUREMENT, TrustClass.EXPERT_HEURISTIC}
)


class NoveltyStatus(StrEnum):
    """§7.1's three answers. There is deliberately no `NOVEL`: 沒搜到不能宣告全球唯一."""

    KNOWN = "KNOWN"
    PARTIALLY_NOVEL = "PARTIALLY_NOVEL"
    NOVELTY_CANDIDATE = "NOVELTY_CANDIDATE"


class NoveltyScope(StrEnum):
    """Against what a novelty status was judged. The field SRC-003's second sentence is about."""

    INTERNAL = "INTERNAL"
    GLOBAL = "GLOBAL"


class PriorArtOverlap(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"


class PriorArtSource(CoreModel):
    """One source a search consulted, and the §6.5 source kinds it covers.

    Declared by the deployment that wires the provider, not inferred from results: a provider that
    returned nothing still covered its classes, and "no results" must not read as "not searched".
    """

    provider_id: str
    trust_classes: tuple[TrustClass, ...] = Field(min_length=1)

    @property
    def internal(self) -> bool:
        return frozenset(self.trust_classes) <= INTERNAL_TRUST_CLASSES


class DateRange(CoreModel):
    start: dt.date
    end: dt.date

    @model_validator(mode="after")
    def _forward(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"date range ends ({self.end}) before it starts ({self.start})")
        return self


class PriorArtSearchRecord(CoreModel):
    """§17.20, plus ``project_id``.

    ``project_id`` is not in §17.20's block, for the reason §17.4 and §17.16 omit it: the record
    reaches its project through ``episode_id``. SEC-002 scopes every read by project, so the row
    carries it and `schema_drift.UNBOUND` records the difference.

    ``date_range`` stays optional as §17.20 declares it, and SRC-003 still requires it: a record
    with no date range can exist -- a search is a search -- but it cannot be *cited* by a novelty
    status, because a claim of novelty with no date bound is a claim about all time.
    """

    search_id: str
    project_id: str
    episode_id: str
    intent: str
    sources: tuple[PriorArtSource, ...] = Field(min_length=1)
    queries: tuple[str, ...] = Field(min_length=1)
    date_range: DateRange | None = None
    retrieved_at: dt.datetime
    source_policy_version: str
    result_count: int = Field(ge=0)
    deduped_work_count: int = Field(ge=0)
    #: What this search could not see. Required and non-empty: every search has limitations, and a
    #: record claiming none is a record nobody examined.
    limitations: tuple[str, ...] = Field(min_length=1)
    coverage_notes: str
    #: The DISTINCT works found (one id per deduplicated work), so its length is
    #: `deduped_work_count`; `result_count` counts raw hits across all queries.
    external_source_record_ids: tuple[str, ...] = ()
    inference_provenance_id: str | None = None

    @model_validator(mode="after")
    def _a_search_record_is_internally_coherent(self) -> Self:
        if any(not q.strip() for q in self.queries):
            raise ValueError(f"prior-art search {self.search_id} records a blank query")
        if any(not note.strip() for note in self.limitations):
            raise ValueError(f"prior-art search {self.search_id} records a blank limitation")
        if self.deduped_work_count > self.result_count:
            raise ValueError(
                f"prior-art search {self.search_id} reports {self.deduped_work_count} deduplicated "
                f"works out of {self.result_count} results; deduplication cannot add works"
            )
        if len(set(self.external_source_record_ids)) != len(self.external_source_record_ids):
            raise ValueError(f"prior-art search {self.search_id} names a record twice")
        if len(self.external_source_record_ids) != self.deduped_work_count:
            raise ValueError(
                f"prior-art search {self.search_id} reports {self.deduped_work_count} distinct "
                f"works and names {len(self.external_source_record_ids)}; a count that does not "
                "match the records it names cannot be audited"
            )
        providers = [s.provider_id for s in self.sources]
        if len(set(providers)) != len(providers):
            raise ValueError(f"prior-art search {self.search_id} lists a source twice")
        return self

    @property
    def covered_trust_classes(self) -> frozenset[TrustClass]:
        return frozenset(c for source in self.sources for c in source.trust_classes)

    @property
    def internal_only(self) -> bool:
        return all(source.internal for source in self.sources)


class PriorArtMatch(CoreModel):
    """One row of §7.4's prior-art matrix."""

    record_id: str
    overlap: PriorArtOverlap
    note: str = ""


class NoveltyAssessment(CoreModel):
    """A novelty status, bound to the search it rests on (SRC-003).

    ``search_id`` is required. ``scope`` is checked against the search's coverage by
    `lab_brain.cognition.novelty.assess_novelty` and again by `002b`'s trigger, so an internal
    search cannot yield a GLOBAL status by any write path.
    """

    assessment_id: str
    project_id: str
    episode_id: str
    #: What the status is about -- a hypothesis or a design concept id.
    subject_id: str
    search_id: str
    status: NoveltyStatus
    scope: NoveltyScope
    #: The trust classes the governing NOVELTY_AUDIT policy required before a GLOBAL scope, copied
    #: at assessment time so the row is judged against the rule it was made under.
    global_coverage_required: tuple[TrustClass, ...] = ()
    prior_art_matrix: tuple[PriorArtMatch, ...] = ()
    inference_provenance_id: str | None = None
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_known_status_names_what_it_is_known_from(self) -> Self:
        if self.status is NoveltyStatus.KNOWN and not any(
            m.overlap is PriorArtOverlap.FULL for m in self.prior_art_matrix
        ):
            raise ValueError(
                f"novelty assessment {self.assessment_id} says KNOWN and names no fully "
                "overlapping prior art; a concept is known FROM something"
            )
        return self


def novelty_coverage_problems(
    record: PriorArtSearchRecord, assessment: NoveltyAssessment
) -> list[str]:
    """SRC-003's rules for a status resting on ``record``. Empty when it may stand.

    The one statement of the rule in Python, mirrored by `002b`'s trigger. Pure, so the gate that
    refuses an auditor's claim and the store that refuses a raw write cannot disagree.
    """
    problems: list[str] = []
    if record.search_id != assessment.search_id:
        problems.append(f"the assessment cites {assessment.search_id}, not {record.search_id}")
    if record.project_id != assessment.project_id:
        problems.append("the search belongs to another project")
    if record.date_range is None:
        problems.append(
            "the search records no date range; SRC-003 requires sources, queries, date range and "
            "limitations, and a novelty claim with no date bound is a claim about all time"
        )
    if assessment.scope is NoveltyScope.GLOBAL:
        required = frozenset(assessment.global_coverage_required)
        if not required or required & INTERNAL_TRUST_CLASSES:
            problems.append(
                f"GLOBAL scope is claimed under a coverage requirement {sorted(required)} that is "
                "empty or internal"
            )
        if record.internal_only:
            problems.append(
                f"GLOBAL scope is claimed from search {record.search_id}, which searched only "
                "internal sources. SRC-003: internal novelty MUST NOT be presented as global "
                "novelty"
            )
        uncovered = sorted(required - record.covered_trust_classes)
        if uncovered:
            problems.append(
                f"GLOBAL scope is claimed but search {record.search_id} did not cover {uncovered}; "
                "沒搜到不能宣告全球唯一 -- an uncovered class is not an absent one"
            )
    return problems


__all__ = [
    "INTERNAL_TRUST_CLASSES",
    "DateRange",
    "NoveltyAssessment",
    "NoveltyScope",
    "NoveltyStatus",
    "PriorArtMatch",
    "PriorArtOverlap",
    "PriorArtSearchRecord",
    "PriorArtSource",
    "novelty_coverage_problems",
]
