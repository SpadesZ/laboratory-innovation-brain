"""One test user standing in for two: the operator who owns the trust files, the service that runs.

`key_lifecycle` refuses interaction authorities the service user owns (it could rewrite the keys it
verifies against). A test creates every file as the one user running it, so outside root every
start-up would be refused. This fixture makes the authorities file and its directory read as the
operator's; the key file stays the service user's, as a deployment has it. A test that asks what
happens when the service DOES own them uses the real owners (`real_owners` marker).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from lab_brain.security import key_lifecycle

#: Not any user of the test machine: the operator in these tests.
OPERATOR_UID = 3_999_999


@pytest.fixture(autouse=True)
def operator_owns_the_trust_files(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    if request.node.get_closest_marker("real_owners") is None:
        monkeypatch.setattr(key_lifecycle, "_owner", lambda _path: OPERATOR_UID)
    yield
