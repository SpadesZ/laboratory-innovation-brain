"""A rename moves a filename. It must not overwrite what the ledger says was applied.

THE HOLE THIS CLOSES. The first `_carry_renames()` wrote the *current* file's checksum into the
ledger row. It ran before the drift check, so renaming a migration and editing it in the same commit
laundered the edit straight past the one guard that exists to catch it: the ledger would agree with
the edited file, and "applied migrations have been modified on disk" would never fire.

The fix is that `RENAMED` declares `expected_old_checksum` -- what the file hashed to when it was
applied under the old name -- and the carry refuses unless the ledger matches exactly, then moves
the filename and leaves the checksum alone. An edited file therefore still fails drift afterwards,
which is the correct outcome.

These run inside the transactional `db` fixture, so each inserts its own ledger rows and rolls them
back. No throwaway database, and no dependence on what this developer's ledger happens to hold.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys

import pytest

from lab_brain.spec import repo_root

pytestmark = pytest.mark.postgres

OLD = "005_artifact_occurrences.sql"
NEW = "002a_artifact_occurrences.sql"


def _migrate():
    name = "lab_brain_migrate_script"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, repo_root() / "scripts" / "migrate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ledger(db):  # type: ignore[no-untyped-def]
    """The real `schema_migrations` table, emptied for the duration of one rolled-back test."""
    db.execute("DELETE FROM schema_migrations")
    return db


def _insert(db, filename: str, checksum: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO schema_migrations (filename, checksum, apply_index) VALUES (%s, %s, %s)",
        (filename, checksum, 1),
    )


def _rows(db) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {
        str(r[0]): str(r[1])
        for r in db.execute("SELECT filename, checksum FROM schema_migrations").fetchall()
    }


def test_the_declared_checksum_is_what_the_file_actually_hashes_to():
    """A pure rename: the file on disk is byte-identical to what was applied under the old name.

    If these ever diverge the rename stopped being a rename, and the carry below would move a
    filename onto content that never ran under it.
    """
    module = _migrate()
    rename = module.RENAMED[OLD]
    text = (repo_root() / "migrations" / rename.new_filename).read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == rename.expected_old_checksum


def test_a_matching_ledger_is_carried_across(ledger):
    """The upgrade path: a database that applied the old name ends up on the new one."""
    module = _migrate()
    rename = module.RENAMED[OLD]
    _insert(ledger, OLD, rename.expected_old_checksum)

    moved = module._carry_renames(ledger, module.load_migrations())

    assert moved == [f"{OLD} -> {NEW}"]
    rows = _rows(ledger)
    assert OLD not in rows
    assert rows[NEW] == rename.expected_old_checksum, (
        "the carry must preserve the recorded checksum, not restamp it from the file"
    )


def test_the_carry_is_idempotent(ledger):
    """A second pass does nothing, so re-running the migrator is safe."""
    module = _migrate()
    rename = module.RENAMED[OLD]
    _insert(ledger, OLD, rename.expected_old_checksum)

    module._carry_renames(ledger, module.load_migrations())
    before = _rows(ledger)
    assert module._carry_renames(ledger, module.load_migrations()) == []
    assert _rows(ledger) == before


def test_an_unexpected_old_checksum_is_refused(ledger):
    """The negative fixture. This is the laundering path, and it must fail closed.

    A ledger recording something other than what the rename declares means the migration was edited
    after it was applied, or this database ran a different version of it. Either way the carry
    cannot know what is authoritative, so it refuses rather than choosing.
    """
    module = _migrate()
    _insert(ledger, OLD, "0" * 64)

    with pytest.raises(module.MigrationError, match="refusing to carry"):
        module._carry_renames(ledger, module.load_migrations())

    assert _rows(ledger) == {OLD: "0" * 64}, "a refused carry must change nothing"


def test_a_refused_carry_does_not_restamp_the_checksum(ledger):
    """The specific regression: the old implementation would have written the file's checksum here.

    Asserted separately from the raise, because a carry that refused *and* mutated would still be
    the bug -- the exception is not the guarantee, the unchanged row is.
    """
    module = _migrate()
    rename = module.RENAMED[OLD]
    _insert(ledger, OLD, "0" * 64)

    with pytest.raises(module.MigrationError):
        module._carry_renames(ledger, module.load_migrations())

    rows = _rows(ledger)
    assert rows[OLD] == "0" * 64
    assert rename.expected_old_checksum not in rows.values()


def test_both_names_present_is_refused(ledger):
    """Two rows for one migration is a contradiction, not something to resolve by guessing."""
    module = _migrate()
    rename = module.RENAMED[OLD]
    _insert(ledger, OLD, rename.expected_old_checksum)
    _insert(ledger, NEW, rename.expected_old_checksum)

    with pytest.raises(module.MigrationError, match="holds both"):
        module._carry_renames(ledger, module.load_migrations())


def test_a_ledger_without_the_old_name_is_untouched(ledger):
    """A fresh database has never seen the old name, so the carry is a no-op."""
    module = _migrate()
    rename = module.RENAMED[OLD]
    _insert(ledger, NEW, rename.expected_old_checksum)

    assert module._carry_renames(ledger, module.load_migrations()) == []
    assert _rows(ledger) == {NEW: rename.expected_old_checksum}


def test_a_renamed_and_edited_migration_still_fails_drift(ledger):
    """End to end: the carry succeeds, and the edit is still caught immediately after.

    Simulated by carrying a ledger whose declared checksum matches, then comparing against a
    *different* file body -- which is what `migrate.py` does on the next line.
    """
    module = _migrate()
    rename = module.RENAMED[OLD]
    _insert(ledger, OLD, rename.expected_old_checksum)
    module._carry_renames(ledger, module.load_migrations())

    edited_checksum = hashlib.sha256(
        b"-- an edit made after this migration was applied"
    ).hexdigest()
    recorded = _rows(ledger)[NEW]
    assert recorded != edited_checksum, (
        "the carry preserved the applied checksum, so an edited file is still detectable as drift"
    )
