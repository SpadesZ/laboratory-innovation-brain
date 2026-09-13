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
    # P4 / M0b-1. Extends 002 by moving project scope off the global artifact row
    # (R-7, ADR-0010). Needs 001 for the `projects` and `actors` foreign keys.
    "002a_artifact_occurrences.sql",
    # Before 003: observations and attestations reference condition_schemas(schema_ref).
    "008_conditions.sql",
    "003_claims_observations_attestations.sql",
    "004_relations.sql",
    # After 003: bundle members reference attestations. `a` suffixes mark additions beyond
    # Appendix A's index, whose 001-012 numbers are reserved for the canonical migrations.
    "004a_evidence_bundles.sql",
    # After 004a: makes the bundle tables append-only. Separate from 004a because storability and
    # immutability are distinct guarantees, and 004a shipped without the second one.
    "004b_evidence_bundle_immutability.sql",
    # After 003: the EVI-005 payload triggers attach to observations and attestations.
    "008a_condition_payload_validation.sql",
)

#: Migrations renamed AFTER being applied somewhere, as ``{old filename: new filename}``.
#:
#: A rename is a real event and pretending it did not happen is how two environments end up with
#: different schemas while both report themselves up to date. Deleting the old ledger row would
#: make the renamed file look pending and re-run it -- here that means `CREATE TABLE
#: artifact_occurrences` against a database that already has it, so the run fails and the operator
#: is left to repair it by hand. Editing the row silently would leave no trace that the rename
#: occurred.
#:
#: So the carry-across is explicit, transactional, idempotent and logged. It runs before pending is
#: computed, updates `filename` and `checksum` in place, and keeps the original `applied_at` and
#: `apply_index` -- the migration really was applied then, in that position.
#:
#: Entries are permanent. Removing one would make the rename invisible to a database that has not
#: yet seen it, which is the same failure one release later.
RENAMED: dict[str, str] = {
    # P4 / M0b-1. `005` is reserved by Appendix A for epistemic events and transition policies;
    # artifact occurrences extend 002. Caught by tests/spec/test_migration_numbering.py, which now
    # fails on any bare-numbered migration whose slug disagrees with Appendix A.
    "005_artifact_occurrences.sql": "002a_artifact_occurrences.sql",
}

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


def _carry_renames(connection: object, migrations: tuple[Migration, ...]) -> list[str]:
    """Move ledger rows for migrations renamed after they were applied. See ``RENAMED``.

    Idempotent by construction: a row is only moved when the old name is present and the new one is
    not, so a second run does nothing. If both are somehow present the ledger is contradictory and
    this refuses rather than guessing which is authoritative.
    """
    by_name = {migration.filename: migration for migration in migrations}
    moved: list[str] = []
    for old_name, new_name in RENAMED.items():
        rows = connection.execute(  # type: ignore[attr-defined]
            "SELECT filename FROM schema_migrations WHERE filename IN (%s, %s)",
            (old_name, new_name),
        ).fetchall()
        present = {str(row[0]) for row in rows}
        if old_name not in present:
            continue
        if new_name in present:
            raise MigrationError(
                f"ledger holds both {old_name!r} and {new_name!r}; a rename left two rows for one "
                "migration and this cannot be resolved automatically"
            )
        migration = by_name.get(new_name)
        if migration is None:
            raise MigrationError(
                f"{old_name!r} was renamed to {new_name!r}, which is not in APPLY_ORDER"
            )
        connection.execute(  # type: ignore[attr-defined]
            "UPDATE schema_migrations SET filename = %s, checksum = %s WHERE filename = %s",
            (new_name, migration.checksum, old_name),
        )
        connection.commit()  # type: ignore[attr-defined]
        moved.append(f"{old_name} -> {new_name}")
    return moved


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

        carried = _carry_renames(connection, migrations)
        for line in carried:
            print(f"  renamed  {line}")

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
