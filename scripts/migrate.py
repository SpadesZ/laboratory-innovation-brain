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
    # P7 / M0b-4. The events half of Appendix A's 005 slot (EPI-003); the transition-policy half
    # lands as 005b. After 003/004: a triggering reference is a foreign key into `attestations`
    # and `relation_judgments`, so those tables must exist first.
    "005a_belief_revision_events.sql",
    # P7 / Phase B. The transition-policy half of the 005 slot (EPI-005). After 005a: it adds the
    # foreign key that makes an event cite a *registered* policy version.
    "005b_transition_policies.sql",
    # P7-fix. Governance hardening found by audit: an admission is a separate path, an event must
    # record the transition its policy governs, a cross-project trigger reference becomes
    # unrepresentable, and an orphan event cannot be written by raw SQL. After 005b: the policy
    # governance trigger reads `transition_policies`.
    "005c_belief_event_governance.sql",
    # P8 / `v3.3-a12`. SPEC-ISSUE-011: the §17.14.1 Decision that authorised a transition, stored
    # with the six §8.2.1 inputs that produced it, plus the event's required back-reference. After
    # 005c: the linkage trigger is named to fire *after* 005c's policy trigger, so a policy
    # mismatch is still reported by the guard that owns it.
    "005d_belief_transition_decisions.sql",
    # After 003: bundle members reference attestations. `a` suffixes mark additions beyond
    # Appendix A's index, whose 001-012 numbers are reserved for the canonical migrations.
    "004a_evidence_bundles.sql",
    # After 004a: makes the bundle tables append-only. Separate from 004a because storability and
    # immutability are distinct guarantees, and 004a shipped without the second one.
    "004b_evidence_bundle_immutability.sql",
    # After 003: the EVI-005 payload triggers attach to observations and attestations.
    "008a_condition_payload_validation.sql",
    # P5 / M0b-2. The cost half of Appendix A's 007 slot (COST-001); the capabilities
    # half lands with VER-002 in M2. Needs 001 for the project and actor foreign keys.
    "007a_cost_ledger.sql",
    # P5-fix / v3.3-a10. Adds §9.4's `token_count` to the three cost tables. Separate from 007a
    # because 007a is applied: an applied migration is checksummed and must not be edited.
    "007b_cost_token_dimension.sql",
    # P6 / M0b-3. The observability third of Appendix A's 010 slot (OPS-003); the review and
    # benchmark halves land with OPS-002 and §17.19.2. After 007a/007b: span cost refs are a
    # foreign key into `cost_entries`.
    "010a_execution_spans.sql",
    # P6-fix. Makes closing a span atomic with its cost refs, and requires a parent span to be in
    # the same trace. Separate from 010a because 010a is applied.
    "010b_execution_span_close_atomicity.sql",
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
class RenamedMigration:
    """Where an applied migration moved to, and what its ledger row must already say.

    ``expected_old_checksum`` is what the file hashed to **when it was applied under the old
    name**. It is written out literally rather than computed from the file on disk: computing it
    would make the check tautological, since the whole point is to detect a file that no longer
    matches what ran.
    """

    new_filename: str
    expected_old_checksum: str


@dataclass(frozen=True)
class Migration:
    filename: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


#: Migrations renamed AFTER being applied somewhere.
#:
#: A rename is a real event and pretending it did not happen is how two environments end up with
#: different schemas while both report themselves up to date. Deleting the old ledger row would make
#: the renamed file look pending and re-run it -- here that means `CREATE TABLE
#: artifact_occurrences` against a database that already has it. Editing the row silently would
#: leave no trace that the rename occurred.
#:
#: A RENAME MOVES THE FILENAME AND NOTHING ELSE. `expected_old_checksum` is the checksum of the file
#: **as it was applied under the old name**, and the carry refuses unless the ledger matches it
#: exactly. The first version of this took the *current* file's checksum and wrote that into the
#: ledger, which meant a rename that also edited the migration would launder the edit past the
#: drift check -- the one guard that exists to catch exactly that. The carry now preserves the
#: recorded checksum, so an edited file still fails drift afterwards, as it should.
#:
#: Entries are permanent. Removing one would make the rename invisible to a database that has not
#: yet seen it, which is the same failure one release later.
RENAMED: dict[str, RenamedMigration] = {
    # P4 / M0b-1. `005` is reserved by Appendix A for epistemic events and transition policies;
    # artifact occurrences extend 002. Caught by tests/spec/test_migration_numbering.py, which now
    # fails on any bare-numbered migration whose slug disagrees with Appendix A.
    #
    # The file is byte-identical to what was applied under the old name -- deliberately, so this is
    # a pure rename. The explanation of *why* it was renamed lives in ADR-0010 and in the numbering
    # test, not in the migration, because editing an applied migration to document its own rename is
    # the thing this mechanism must not normalise.
    "005_artifact_occurrences.sql": RenamedMigration(
        new_filename="002a_artifact_occurrences.sql",
        expected_old_checksum=("7e47e2fd8cf75a7aaab30de8c220f3bb9b5dcfb422ec77af6e4c384da2b91030"),
    ),
}


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

    Moves the filename and **preserves the recorded checksum**, so a rename cannot launder an edit
    to an applied migration past the drift check that runs immediately after.

    Fails closed on anything unexpected: a ledger checksum that does not match what was declared to
    have been applied, both names present at once, or a target missing from APPLY_ORDER. Idempotent
    -- a row is only moved when the old name is present and the new one is not.
    """
    by_name = {migration.filename: migration for migration in migrations}
    moved: list[str] = []
    for old_name, rename in RENAMED.items():
        new_name = rename.new_filename
        rows = connection.execute(  # type: ignore[attr-defined]
            "SELECT filename, checksum FROM schema_migrations WHERE filename IN (%s, %s)",
            (old_name, new_name),
        ).fetchall()
        recorded = {str(row[0]): str(row[1]) for row in rows}
        if old_name not in recorded:
            continue
        if new_name in recorded:
            raise MigrationError(
                f"ledger holds both {old_name!r} and {new_name!r}; a rename left two rows for one "
                "migration and this cannot be resolved automatically"
            )
        if new_name not in by_name:
            raise MigrationError(
                f"{old_name!r} was renamed to {new_name!r}, which is not in APPLY_ORDER"
            )
        actual = recorded[old_name]
        if actual != rename.expected_old_checksum:
            raise MigrationError(
                f"refusing to carry {old_name!r} -> {new_name!r}: the ledger records checksum "
                f"{actual}, but the rename declares {rename.expected_old_checksum}. Either the "
                "migration was edited after it was applied, or this database ran a different "
                "version of it. A rename moves a filename; it must not overwrite history."
            )
        connection.execute(  # type: ignore[attr-defined]
            "UPDATE schema_migrations SET filename = %s WHERE filename = %s",
            (new_name, old_name),
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
