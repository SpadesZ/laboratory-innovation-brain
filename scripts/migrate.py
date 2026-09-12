"""Apply versioned SQL migrations.

AGT-004 forbids silent schema drift, so this runner is deliberately strict:

**Order is declared, not alphabetical.** ``008_conditions.sql`` must run before
``003_claims_observations_attestations.sql``, because attestations carry a foreign key to a
registered condition schema version. Appendix A's numbering is an index, not an apply order, so
the order lives in ``APPLY_ORDER`` below where it can be read and reviewed.

**Applied migrations are checksummed.** If a file changes after it has been applied, the run
fails. Editing an applied migration is the most common way two environments end up with
divergent schemas while both believing they are up to date.

Usage:
    python scripts/migrate.py                 # apply pending
    python scripts/migrate.py --status        # report without changing anything
    python scripts/migrate.py --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_brain.spec import repo_root

#: Apply order. Numbers follow Appendix A; the sequence here reflects real dependencies.
APPLY_ORDER: tuple[str, ...] = (
    "001_actors_projects.sql",
    "002_artifacts_sourceworks.sql",
    # Before 003: observations and attestations reference condition_schemas(schema_ref).
    "008_conditions.sql",
    "003_claims_observations_attestations.sql",
    "004_relations.sql",
    # After 003: the EVI-005 payload triggers attach to observations and attestations. The `a`
    # suffix marks an amendment to 008 rather than a new canonical Appendix A migration, whose
    # 001-012 numbers are reserved.
    "008a_condition_payload_validation.sql",
)

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    apply_index INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class Migration:
    filename: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


class MigrationError(RuntimeError):
    pass


def migrations_dir() -> Path:
    return repo_root() / "migrations"


def load_migrations() -> tuple[Migration, ...]:
    directory = migrations_dir()
    on_disk = {path.name for path in directory.glob("*.sql")}
    declared = set(APPLY_ORDER)

    undeclared = sorted(on_disk - declared)
    if undeclared:
        raise MigrationError(
            f"migration files exist but are not in APPLY_ORDER: {undeclared}. "
            "Dependency order must be explicit -- add them deliberately."
        )
    missing = sorted(declared - on_disk)
    if missing:
        raise MigrationError(f"APPLY_ORDER names missing files: {missing}")

    return tuple(
        Migration(
            filename=name,
            path=directory / name,
            sql=(directory / name).read_text(encoding="utf-8"),
        )
        for name in APPLY_ORDER
    )


def database_url(explicit: str | None) -> str:
    url = explicit or os.environ.get("LAB_BRAIN_DATABASE_URL")
    if not url:
        raise MigrationError(
            "no database URL. Pass --database-url or set LAB_BRAIN_DATABASE_URL (see .env.example)."
        )
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument(
        "--status", action="store_true", help="report state without applying anything"
    )
    args = parser.parse_args()

    try:
        migrations = load_migrations()
        url = database_url(args.database_url)
    except MigrationError as exc:
        print(f"FAIL  {exc}")
        return 1

    try:
        import psycopg
    except ImportError:
        print("FAIL  psycopg is not installed; install with the 'postgres' extra")
        return 1

    with psycopg.connect(url, autocommit=False) as connection:
        connection.execute(_BOOTSTRAP)
        connection.commit()

        applied = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT filename, checksum FROM schema_migrations"
            ).fetchall()
        }

        # A changed checksum means an applied migration was edited. Two environments would now
        # have different schemas while both reporting themselves up to date (AGT-004).
        drifted = [
            migration.filename
            for migration in migrations
            if migration.filename in applied and applied[migration.filename] != migration.checksum
        ]
        if drifted:
            print(
                "FAIL  applied migrations have been modified on disk: "
                f"{drifted}\n      Write a new migration instead of editing an applied one."
            )
            return 1

        pending = [m for m in migrations if m.filename not in applied]

        print(f"database : {url.rsplit('@', 1)[-1]}")
        print(f"declared : {len(migrations)}")
        print(f"applied  : {len(applied)}")
        print(f"pending  : {len(pending)}")

        if args.status:
            for migration in migrations:
                mark = "applied" if migration.filename in applied else "PENDING"
                print(f"  {mark:>7}  {migration.filename}")
            return 0

        for index, migration in enumerate(migrations):
            if migration.filename in applied:
                continue
            try:
                connection.execute(migration.sql)  # type: ignore[arg-type]
                connection.execute(
                    "INSERT INTO schema_migrations (filename, checksum, apply_index) "
                    "VALUES (%s, %s, %s)",
                    (migration.filename, migration.checksum, index),
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                print(f"FAIL  {migration.filename}: {exc}")
                return 1
            print(f"  applied  {migration.filename}")

    print("migrations up to date" if not pending else f"applied {len(pending)} migration(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
