"""PostgreSQL fixtures for integration tests.

The fixtures themselves moved to ``tests/postgres_fixtures.py`` in P6 and are registered by the
root ``tests/conftest.py``, so every suite sees them: T-OPS-003 is declared ``e2e`` in §26, and a
fixture defined here is invisible to ``tests/e2e/``.

``database_url`` is re-exported because integration tests import it by name to open a *second*
connection -- the two-session approval race and the durability fixtures need a session of their
own, and deriving the URL twice is how they end up pointed at different databases.
"""

from __future__ import annotations

from tests.postgres_fixtures import DEFAULT_URL, database_url

__all__ = ["DEFAULT_URL", "database_url"]
