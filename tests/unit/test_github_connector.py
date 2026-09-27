"""GH-001's connector half: public discovery, ref/commit pinning, normalized provenance, and
§6.16's structured connector failures -- all against the fixture code host, no network."""

from __future__ import annotations

import hashlib

import pytest

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.sources.adapter import SourceQuery, SourceVisibility
from lab_brain.sources.errors import ConnectorError, ConnectorErrorKind
from lab_brain.tool_providers.github.connector import Locator, license_class_for
from tests.external_fixtures import (
    MAIN_COMMIT,
    PUBLIC_REPO,
    REMOVABLE_REPO,
    V10_COMMIT,
    build,
    file_locator,
)


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_public_repositories_are_discoverable_and_every_record_is_technical():
    world = build()
    found = world.github.search(SourceQuery(text="series resistance", limit=10))
    names = [r.canonical_locator for r in found]
    assert f"github:{PUBLIC_REPO}" in names
    assert "github:photonics-lab/calibration-private" not in names, "search never sees private"
    for record in found:
        assert record.trust_class is TrustClass.TECHNICAL_ARTIFACT
        assert record.source_type == "repository"
        assert record.version_ref is None, "a discovery result is not yet pinned"
    # Discovery is anonymous even when the connector holds a credential.
    assert all(not token for op, _, token in world.transport.calls if op == "search")


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_a_requested_ref_resolves_to_a_fixed_commit_and_the_record_pins_it():
    world = build()
    pinned = world.github.retrieve(file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py"))
    record = pinned.record
    assert record.version_ref == MAIN_COMMIT
    assert record.canonical_locator == (
        f"github:{PUBLIC_REPO}@{MAIN_COMMIT}:extract/rs_extraction.py"
    )
    assert record.content_hash == "sha256:" + hashlib.sha256(pinned.content).hexdigest()
    assert record.metadata["requested_ref"] == "main"
    assert record.metadata["resolved_commit"] == MAIN_COMMIT
    assert record.metadata["repository_id"] == "7001"
    assert record.metadata["repository"] == PUBLIC_REPO
    assert record.license_class is LicenseClass.PERMISSIVE
    assert record.visibility is SourceVisibility.PUBLIC
    assert record.sensitivity is SensitivityLabel.PUBLIC
    # A tag pins to its own commit and returns that commit's bytes.
    tagged = world.github.retrieve(file_locator(PUBLIC_REPO, "v1.0", "extract/rs_extraction.py"))
    assert tagged.record.version_ref == V10_COMMIT
    assert tagged.content != pinned.content
    # Asking for the commit itself is idempotent.
    again = world.github.retrieve(
        file_locator(PUBLIC_REPO, MAIN_COMMIT, "extract/rs_extraction.py")
    )
    assert again.record.canonical_locator == record.canonical_locator
    assert again.content == pinned.content


@pytest.mark.requirement("GH-001")
@pytest.mark.spec_test("T-GH-001")
def test_a_pinned_commit_that_no_longer_resolves_is_ref_drift_not_a_silent_substitute():
    world = build()
    missing = "f" * 40
    with pytest.raises(ConnectorError) as drift:
        world.github.retrieve(file_locator(PUBLIC_REPO, missing, "extract/rs_extraction.py"))
    assert drift.value.kind is ConnectorErrorKind.REF_DRIFT
    assert drift.value.error_class == "EXTERNAL_SERVICE_ERROR"


@pytest.mark.parametrize(
    ("setup", "kind", "error_class", "retryable"),
    [
        ("rate", ConnectorErrorKind.RATE_LIMITED, "EXTERNAL_SERVICE_ERROR", True),
        ("network", ConnectorErrorKind.NETWORK_UNAVAILABLE, "EXTERNAL_SERVICE_ERROR", True),
        ("removed", ConnectorErrorKind.SOURCE_REMOVED, "EXTERNAL_SERVICE_ERROR", False),
    ],
)
def test_every_connector_failure_is_structured_and_carries_no_guessed_content(
    setup, kind, error_class, retryable
):  # type: ignore[no-untyped-def]
    world = build()
    if setup == "rate":
        world.transport.rate_limited = True
    elif setup == "network":
        world.transport.network_down = True
    else:
        world.transport.remove(REMOVABLE_REPO)
    with pytest.raises(ConnectorError) as failed:
        world.github.retrieve(file_locator(REMOVABLE_REPO, "main", "mesh.py"))
    assert failed.value.kind is kind
    assert failed.value.error_class == error_class
    assert failed.value.retryable is retryable
    if setup == "rate":
        assert failed.value.retry_after_s == 60
    health = world.github.healthcheck()
    assert health.reachable is (setup == "removed")


def test_locators_and_licences_are_parsed_strictly():
    assert Locator.parse("github:o/r@feature/x:src/a.py") == Locator(
        "o", "r", "feature/x", "src/a.py"
    )
    assert Locator.parse("github:o/r") == Locator("o", "r")
    for bad in ("github:o", "gitlab:o/r", "github:o/r@main", "github:-o/r"):
        with pytest.raises(ConnectorError):
            Locator.parse(bad)
    assert license_class_for("MIT", private=False) is LicenseClass.PERMISSIVE
    assert license_class_for("GPL-3.0-only", private=False) is LicenseClass.COPYLEFT
    assert license_class_for(None, private=False) is LicenseClass.UNKNOWN
    assert license_class_for(None, private=True) is LicenseClass.PROPRIETARY
    assert license_class_for("WTFPL", private=False) is LicenseClass.UNKNOWN
