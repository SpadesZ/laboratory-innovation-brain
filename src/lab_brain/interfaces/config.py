"""How a command-line process obtains a database connection (§24, AGT-007).

ONE SMALL EXPLICIT BOUNDARY, and everything it deliberately is not.

    read_settings(env)    a pure function over a mapping. No I/O, no defaults that connect
                          somewhere, no ambient `os.environ` read at import time.
    open_connection(s)    the only place psycopg is imported, and it is imported INSIDE the
                          function.

WHY THE DRIVER IMPORT IS NOT AT MODULE LEVEL. AGT-007 requires the whole suite to be verifiable
with no database and no driver installed. A top-level `import psycopg` would break collection
everywhere psycopg is absent -- which is the backend-free profile, which is most of CI. The
function-level import is the difference between "this command needs a database" and "importing
this package needs a database".

WHY NOTHING CONNECTS AT IMPORT TIME. A module that opens a connection when it is imported makes
`--help` require a running server, makes every test that imports the CLI a database test, and puts
the connection lifecycle somewhere no caller can see. `main()` opens one, uses it, closes it.

WHY THE SETTINGS ARE NOT READ FROM `os.environ` HERE. `read_settings` takes the mapping, so a test
supplies one without touching the process environment and without the leak-between-tests that
`monkeypatch.setenv` has when someone forgets to undo it. `main()` passes `os.environ`.

MISSING CONFIGURATION IS AN ERROR, NOT A DEFAULT. There is no fallback to `localhost`: a command
that silently connects somewhere plausible is one that will eventually read the wrong database and
report on it confidently. The message names the variable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: The one variable. A single DSN rather than five host/port/user/password/database variables:
#: psycopg already parses this form, and five variables is five places for an environment to be
#: half-configured.
DSN_VARIABLE = "LAB_BRAIN_DATABASE_URL"


class ConfigurationError(RuntimeError):
    """The process is not configured to reach a database.

    Its own type so `main` can turn it into an exit code and a sentence, rather than a traceback
    that tells a researcher about psycopg.
    """


@dataclass(frozen=True)
class Settings:
    """Everything a CLI process needs to reach the system. Currently one field."""

    dsn: str


def read_settings(env: Mapping[str, str]) -> Settings:
    """Read configuration from a mapping. Pure, and refuses rather than guessing."""
    dsn = env.get(DSN_VARIABLE, "").strip()
    if not dsn:
        raise ConfigurationError(
            f"{DSN_VARIABLE} is not set. This command reads durable records, and there is no "
            "default connection on purpose: a command that quietly connected to a plausible "
            "local database would eventually report on the wrong one"
        )
    return Settings(dsn=dsn)


def open_connection(settings: Settings) -> Any:
    """Open a psycopg connection. The ONLY place this package imports a driver.

    Imported inside the function, not at module level -- see the module docstring. Returns `Any`
    because the type lives in a package the rest of the codebase is built not to require.
    """
    try:
        import psycopg
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised by absence, not by a test
        raise ConfigurationError(
            "psycopg is not installed, so this command cannot reach a database. The library and "
            "the test suite do not require it (AGT-007); the CLI does"
        ) from exc
    return psycopg.connect(settings.dsn)


__all__ = [
    "DSN_VARIABLE",
    "ConfigurationError",
    "Settings",
    "open_connection",
    "read_settings",
]
