"""An OPTIONAL live check against the real api.github.com -- marked `network`, deselected unless
`LAB_BRAIN_TEST_NETWORK=1`. Nothing in this repository's recorded verification claims this ran.

Not evidence for any requirement, and deliberately carrying no requirement marker: GH-001's
normative test T-GH-001 is fixture-based ("public fixture repo 可 search/fetch", §26) and is
discharged by the fixture tests, and M5's gate profile is `[postgres]` so offline CI (AGT-007) can
validate it. This check exists for an operator who wants to see the same contract hold against the
live host.

When enabled, it performs anonymous, read-only requests against a well-known public repository and
checks the same contract the fixture tests check: a ref resolves to a 40-hex commit, the pinned
locator names it, and the content hash is the hash of the bytes returned.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest

from lab_brain.sources.external import InMemoryConnectorAudit
from lab_brain.tool_providers.github import (
    GitHubAccessPolicy,
    GitHubConnector,
    HttpGitHubTransport,
    StaticCredentials,
)


@pytest.mark.network
def test_a_public_file_on_github_pins_to_a_commit_and_hashes_what_was_read():
    connector = GitHubConnector(
        transport=HttpGitHubTransport(),
        policy=GitHubAccessPolicy(
            policy_id="ghp:live",
            version="1.0.0",
            project_id="prj:live",
            declared_by_actor_id="act:pi",
        ),
        credentials=StaticCredentials({"prj:live": {}}),
        audit=InMemoryConnectorAudit(),
        now=lambda: dt.datetime.now(dt.UTC),
    )
    pinned = connector.retrieve("github:octocat/Hello-World@master:README", project_id="prj:live")
    commit = pinned.record.version_ref
    assert commit is not None and len(commit) == 40
    assert pinned.record.canonical_locator == f"github:octocat/Hello-World@{commit}:README"
    assert pinned.record.content_hash == "sha256:" + hashlib.sha256(pinned.content).hexdigest()
