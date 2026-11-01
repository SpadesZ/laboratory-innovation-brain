"""The test servers on 127.0.0.1 are free: an explicit stand-in for the Owner's free declaration.

Since 011v a request with a body to this machine is admitted like any other -- reserved against a
budget, or exempt because the Owner declared that model free at that endpoint -- and with no guard
it is refused unsent. Tests of the transport itself (redirects, TLS, deadlines, schema fallback)
talk to throwaway HTTP servers on 127.0.0.1 that are not proxies to anything. A module that tests
the transport, not the spend ceiling, says so by using `free_test_servers`:

    from tests.free_test_endpoints import free_test_servers  # noqa: F401
    pytestmark = pytest.mark.usefixtures("free_test_servers")

The stand-in exists only under `tests/`; nothing in `src/` can declare an endpoint free. The spend
tests do not use it: they show what happens without a declaration.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.spend import Reservation, SpendRefused, SpendRequest

#: The hosts the throwaway servers are reached by (`tests/transport_endpoints.py`, the fakes, and
#: the Docker gateway name a transport test resolves to 127.0.0.1).
TEST_HOSTS = ("127.0.0.1", "localhost", "[::1]", "host.docker.internal")


class TestEndpointsFree:
    """Declares every model on a test server free; refuses (never sends) anything else."""

    __test__ = False  # not a test class

    def declared_free(self, endpoint_host: str, model: str) -> bool:
        host = (
            endpoint_host.rsplit(":", 1)[0]
            if not endpoint_host.startswith("[")
            else (endpoint_host.split("]", 1)[0] + "]")
        )
        return host in TEST_HOSTS

    def reserve(self, request: SpendRequest) -> Reservation:
        raise SpendRefused(f"{request.endpoint_host} is not a test server")

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        return "SETTLED"

    def retain(self, reservation: Reservation, reason: str) -> None:
        return


@pytest.fixture
def free_test_servers() -> Iterator[TestEndpointsFree]:
    guard = TestEndpointsFree()
    with spend.installed(guard):
        yield guard


__all__ = ["TEST_HOSTS", "TestEndpointsFree", "free_test_servers"]
