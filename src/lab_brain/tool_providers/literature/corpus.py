"""A PaperQA-style literature adapter over a local corpus (§26.1 M5). **Not a live literature API.**

WHAT "PAPERQA-STYLE" MEANS HERE. Retrieval returns PASSAGES, not papers: each record is one citable
span -- a section and page of one version of one DOI -- with a relevance score, so what a claim is
admitted from is the passage that says it, and the citation can be re-read. The locator names the
version: `doi:<doi>@<version>#<passage>`. A request without a version (`doi:<doi>#<passage>`) is
pinned to the version the corpus currently holds, and the record says which.

WHAT IT IS NOT. There is no network, no publisher API and no full-text licence negotiation: the
corpus is a JSON fixture of a few SiPh papers written for the M5 tests, and the adapter's name says
so. It proves the contract a real literature provider must meet -- normalized passage records with
licence, version and retraction status -- behind the same `ExternalSourceAdapter` boundary as
GitHub. A real provider replaces it without a change to the router, the snapshot service or
cognition (SRC-001, AGT-008).

RIGHTS ARE REPORTED, NOT ASSUMED. A paper's licence maps to SEC-004's classes (CC-BY / CC0
permissive, CC-BY-SA copyleft, anything else UNKNOWN); the snapshot service's retention policy, not
this adapter, decides that an UNKNOWN-licence passage is kept as a bounded excerpt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.security.external import ExternalReach
from lab_brain.sources.adapter import (
    ExternalSourceRecord,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
    SourceVisibility,
)
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.sources.external import ConnectorDeclaration, PinnedContent

PROVIDER_ID = "literature"
_LOCATOR = re.compile(r"^doi:(?P<doi>10\.[^@#\s]+)(?:@(?P<version>[^#\s]+))?#(?P<passage>[\w.-]+)$")
_WORD = re.compile(r"[a-z0-9]+")


def license_class_for(licence: str | None) -> LicenseClass:
    if licence is None:
        return LicenseClass.UNKNOWN
    if licence.startswith("CC-BY-SA"):
        return LicenseClass.COPYLEFT
    if licence.startswith(("CC-BY", "CC0")):
        return LicenseClass.PERMISSIVE
    return LicenseClass.UNKNOWN


def declaration() -> ConnectorDeclaration:
    return ConnectorDeclaration(
        provider_id=PROVIDER_ID,
        trust_ceiling=(TrustClass.PEER_REVIEWED, TrustClass.PREPRINT),
    )


class LiteratureCorpusAdapter:
    name = "literature-corpus (local fixture, no network)"

    def __init__(self, papers: Sequence[dict[str, Any]], *, now: Callable[[], dt.datetime]) -> None:
        self._papers = {str(p["doi"]): p for p in papers}
        self._now = now

    @classmethod
    def from_file(cls, path: Path, *, now: Callable[[], dt.datetime]) -> LiteratureCorpusAdapter:
        return cls(json.loads(path.read_text(encoding="utf-8"))["papers"], now=now)

    def provider_id(self) -> str:
        return PROVIDER_ID

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            provider_id=PROVIDER_ID,
            can_search=True,
            can_fetch=True,
            can_snapshot=True,
            max_sensitivity=SensitivityLabel.PUBLIC,
            reach=ExternalReach.EXTERNAL,
        )

    def healthcheck(self) -> SourceHealthReport:
        return SourceHealthReport(PROVIDER_ID, True, self.name)

    def _record(
        self, paper: dict[str, Any], passage: dict[str, Any], score: int
    ) -> ExternalSourceRecord:
        text = str(passage["text"])
        doi, version = str(paper["doi"]), str(paper["version"])
        return ExternalSourceRecord(
            provider=PROVIDER_ID,
            source_type="paper_passage",
            canonical_locator=f"doi:{doi}@{version}#{passage['id']}",
            retrieved_at=self._now(),
            visibility=SourceVisibility.PUBLIC,
            trust_class=TrustClass.PEER_REVIEWED if paper["peer_reviewed"] else TrustClass.PREPRINT,
            sensitivity=SensitivityLabel.PUBLIC,
            title=str(paper["title"]),
            owner=", ".join(paper.get("authors", ())),
            version_ref=version,
            content_hash="sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
            rights_status=f"licence:{paper['license']}" if paper.get("license") else "no-licence",
            license_class=license_class_for(paper.get("license")),
            license_identifier=paper.get("license"),
            metadata={
                "doi": doi,
                "section": str(passage["section"]),
                "page": str(passage["page"]),
                "venue": str(paper.get("venue", "")),
                "year": str(paper.get("year", "")),
                "status": str(paper.get("status", "UNKNOWN")),
                "score": str(score),
            },
        )

    def search(self, query: SourceQuery) -> Sequence[ExternalSourceRecord]:
        terms = set(_WORD.findall(query.text.lower()))
        scored: list[tuple[int, str, ExternalSourceRecord]] = []
        for paper in self._papers.values():
            for passage in paper["passages"]:
                score = len(terms & set(_WORD.findall(str(passage["text"]).lower())))
                if score:
                    record = self._record(paper, passage, score)
                    scored.append((-score, record.canonical_locator, record))
        return tuple(record for _, _, record in sorted(scored)[: query.limit])

    def _locate(self, locator: str) -> tuple[dict[str, Any], dict[str, Any]]:
        match = _LOCATOR.match(locator)
        if match is None:
            raise ConnectorError(
                ConnectorErrorKind.NOT_FOUND,
                provider_id=PROVIDER_ID,
                detail="not a passage locator (doi:<doi>[@<version>]#<passage>)",
            )
        paper = self._papers.get(match["doi"])
        if paper is None or paper.get("withdrawn_from_corpus"):
            raise ConnectorError(
                ConnectorErrorKind.NOT_FOUND, provider_id=PROVIDER_ID, detail="no such DOI"
            )
        if match["version"] is not None and match["version"] != paper["version"]:
            raise ConnectorError(
                ConnectorErrorKind.REF_DRIFT,
                provider_id=PROVIDER_ID,
                detail="the requested version is not the one the corpus holds; none is substituted",
            )
        passage = next((p for p in paper["passages"] if p["id"] == match["passage"]), None)
        if passage is None:
            raise ConnectorError(
                ConnectorErrorKind.NOT_FOUND,
                provider_id=PROVIDER_ID,
                detail="no such passage",
                pinned_ref=str(paper["version"]),
            )
        return paper, passage

    def fetch(self, locator: str) -> ExternalSourceRecord | None:
        return self._retrieve(locator).record

    def retrieve(self, locator: str, *, project_id: str) -> PinnedContent:
        """Project-neutral: the corpus holds no allowlist and no credential, so it declares no
        access scope and reads the same public passage for any project."""
        del project_id
        return self._retrieve(locator)

    def _retrieve(self, locator: str) -> PinnedContent:
        paper, passage = self._locate(locator)
        record = self._record(paper, passage, 0)
        match = _LOCATOR.match(locator)
        return PinnedContent(
            record=record,
            content=str(passage["text"]).encode("utf-8"),
            media_type="text/plain",
            requested_ref=None if match is None else match["version"],
        )


__all__ = ["PROVIDER_ID", "LiteratureCorpusAdapter", "declaration", "license_class_for"]
