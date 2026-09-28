"""Generate the database password once, into the `secrets` volume (compose.yaml, service `secrets`).

An existing password is never replaced: the database was initialised with it. The file is readable
by the database and workspace processes that mount the volume; nothing else mounts it.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def main(target: str) -> int:
    path = Path(target)
    if path.exists():
        print("database password: kept")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "w") as out:
        out.write(secrets.token_hex(24))
    os.chmod(path, 0o444)
    print("database password: generated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
