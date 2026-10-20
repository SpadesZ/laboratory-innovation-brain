"""Generate the database passwords once, into their volumes (compose.yaml, service `secrets`).

One file per argument: the migrator's password in the `secrets` volume, and the services' role's
password in `app-secrets`. An existing password is never replaced: the database was initialised
with the first, and the services' role was given the second. Each file is readable by the
processes that mount its volume; each volume is mounted only where its password is needed.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def ensure_secret(target: str) -> str:
    path = Path(target)
    if path.exists():
        return f"{path.name} in {path.parent}: kept"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "w") as out:
        out.write(secrets.token_hex(24))
    os.chmod(path, 0o444)
    return f"{path.name} in {path.parent}: generated"


def main(targets: list[str]) -> int:
    if not targets:
        print("usage: make_secret.py PATH [PATH ...]", file=sys.stderr)
        return 2
    for target in targets:
        print(f"database password {ensure_secret(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
