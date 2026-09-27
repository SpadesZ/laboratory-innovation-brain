"""The PaperQA-style literature adapter: passage-level, version-pinned, rights and status reported."""

from __future__ import annotations

import hashlib

import pytest

from lab_brain.core.models.enums import LicenseClass, TrustClass
from lab_brain.sources.adapter import SourceQuery
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.tool_providers.literature.corpus import license_class_for
from tests.external_fixtures import build


def test_retrieval_returns_citable_passages_ranked_by_relevance():
    adapter = build().literature
    found = adapter.search(SourceQuery(text="open contact via series resistance reverse bias"))
    assert found[0].canonical_locator == "doi:10.5555/sp.2019.041@vor#p5"
    for record in found:
        assert record.source_type == "paper_passage"
        assert (
            record.version_ref is not None and f"@{record.version_ref}#" in record.canonical_locator
        )
        assert record.metadata["section"] and record.metadata["page"]
    scores = [int(r.metadata["score"]) for r in found]
    assert scores == sorted(scores, reverse=True)


def test_a_passage_is_pinned_hashed_and_carries_its_rights_and_status():
    adapter = build().literature
    pinned = adapter.retrieve("doi:10.5555/sp.2018.007#p1")
    assert pinned.record.canonical_locator == "doi:10.5555/sp.2018.007@vor#p1"
    assert pinned.record.content_hash == "sha256:" + hashlib.sha256(pinned.content).hexdigest()
    assert pinned.record.metadata["status"] == "RETRACTED"
    assert pinned.record.license_class is LicenseClass.UNKNOWN
    assert pinned.record.trust_class is TrustClass.PEER_REVIEWED
    preprint = adapter.retrieve("doi:10.5555/sp.2021.113#p2").record
    assert preprint.trust_class is TrustClass.PREPRINT


def test_licences_map_to_sec_004_classes_and_unknowns_are_refused_not_guessed():
    assert license_class_for("CC-BY-4.0") is LicenseClass.PERMISSIVE
    assert license_class_for("CC0-1.0") is LicenseClass.PERMISSIVE
    assert license_class_for("CC-BY-SA-4.0") is LicenseClass.COPYLEFT
    assert license_class_for("All-rights-reserved") is LicenseClass.UNKNOWN
    assert license_class_for(None) is LicenseClass.UNKNOWN
    adapter = build().literature
    for locator, kind in (
        ("doi:10.5555/nope#p1", ConnectorErrorKind.NOT_FOUND),
        ("doi:10.5555/sp.2019.041#p99", ConnectorErrorKind.NOT_FOUND),
        ("isbn:123", ConnectorErrorKind.NOT_FOUND),
        ("doi:10.5555/sp.2019.041@am#p3", ConnectorErrorKind.REF_DRIFT),
    ):
        with pytest.raises(ConnectorError) as failed:
            adapter.retrieve(locator)
        assert failed.value.kind is kind
