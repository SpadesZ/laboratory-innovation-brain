"""Migration filenames must not collide with Appendix A's reserved numbering.

P4 shipped `005_artifact_occurrences.sql`. Appendix A reserves 005 for
`005_epistemic_events_transition_policies.sql`. Nothing objected, because the runner only cares that
APPLY_ORDER and the directory agree with each other -- neither reads the spec. The collision would
have surfaced at P5, when the real 005 arrived and had nowhere to go, against a database where the
wrong 005 was already recorded as applied.

The repository's own convention already had the answer: 004a, 004b and 008a are suffixed extensions
of the migration they build on. Artifact occurrences extend 002, so the correct name is 002a.

Deliberately unmarked: this validates the schema-delivery harness, not a Requirement.
"""

from __future__ import annotations

import re

import pytest

from lab_brain.spec import repo_root, spec_path

#: `002a_artifact_occurrences.sql` -> ("002", "a", "artifact_occurrences")
_FILENAME = re.compile(r"^(\d{3})([a-z]?)_([a-z0-9_]+)\.sql$")


def _reserved_numbers() -> dict[str, str]:
    """Appendix A's canonical migration list, parsed from the specification.

    Derived rather than transcribed: an amendment that renumbers Appendix A must take effect here
    without anyone remembering to mirror it, or the guard drifts from the thing it guards.
    """
    text = spec_path().read_text(encoding="utf-8")
    index = text.find("Appendix A")
    assert index != -1, "Appendix A not found; this guard cannot read the reserved numbering"
    window = text[index : index + 4000]
    reserved = {
        match.group(1): match.group(2)
        for match in re.finditer(r"^(\d{3})_([a-z0-9_]+)\.sql\s*$", window, re.M)
    }
    assert len(reserved) >= 5, (
        f"only {len(reserved)} reserved numbers parsed; format likely changed"
    )
    return reserved


def _migrate_module():
    """Load `scripts/migrate.py` as a module.

    Registered in ``sys.modules`` before execution because the module defines a dataclass, and
    dataclasses resolve their annotations through ``sys.modules[cls.__module__]`` -- an unregistered
    module makes that lookup return None.
    """
    import importlib.util
    import sys

    name = "lab_brain_migrate_script"
    if name in sys.modules:
        return sys.modules[name]
    spec_obj = importlib.util.spec_from_file_location(name, repo_root() / "scripts" / "migrate.py")
    assert spec_obj and spec_obj.loader
    module = importlib.util.module_from_spec(spec_obj)
    sys.modules[name] = module
    spec_obj.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reserved() -> dict[str, str]:
    return _reserved_numbers()


@pytest.fixture(scope="module")
def migration_files() -> list[str]:
    files = sorted(path.name for path in (repo_root() / "migrations").glob("*.sql"))
    assert files, "no migrations found; this guard is comparing nothing"
    return files


def test_every_migration_filename_is_well_formed(migration_files):
    """`NNN[letter]_slug.sql`. A name the guard cannot parse is a name it cannot check."""
    malformed = [name for name in migration_files if not _FILENAME.match(name)]
    assert not malformed, f"migration filenames must match NNN[a-z]_slug.sql: {malformed}"


def test_no_bare_numbered_migration_takes_a_number_reserved_for_something_else(
    migration_files, reserved
):
    """The guard that would have caught P4's collision.

    A bare-numbered migration claims one of Appendix A's slots outright, so its slug must be the
    one Appendix A assigns. `005_artifact_occurrences.sql` claimed the slot reserved for
    `005_epistemic_events_transition_policies.sql`, which P5 is about to need.
    """
    collisions = []
    for name in migration_files:
        match = _FILENAME.match(name)
        assert match is not None
        number, suffix, slug = match.groups()
        if suffix:
            continue
        expected = reserved.get(number)
        if expected is not None and expected != slug:
            collisions.append(f"{name} takes {number}, which Appendix A reserves for {expected}")
    assert not collisions, (
        "migration numbering collides with SAI 3.3 Appendix A: "
        + "; ".join(collisions)
        + ". Extend the migration you build on with a letter suffix (002a) instead of taking a "
        "reserved number."
    )


def test_a_suffixed_migration_extends_a_number_that_exists(migration_files, reserved):
    """`002a` is meaningful only if 002 is a real migration. `099z` extends nothing."""
    orphans = [
        name
        for name in migration_files
        if (match := _FILENAME.match(name)) and match.group(2) and match.group(1) not in reserved
    ]
    assert not orphans, f"suffixed migrations extending an unreserved number: {orphans}"


def test_no_two_migrations_share_a_number_and_suffix(migration_files):
    """Two files claiming `002a` would apply in an order the filesystem decides."""
    seen: dict[tuple[str, str], str] = {}
    for name in migration_files:
        match = _FILENAME.match(name)
        assert match is not None
        key = (match.group(1), match.group(2))
        assert key not in seen, f"{name} and {seen[key]} share the same number and suffix"
        seen[key] = name


def test_renamed_migrations_are_declared_and_resolvable():
    """A rename must be recorded, and must point at a migration that exists.

    `RENAMED` carries an already-applied ledger row across a rename. An entry whose target is not
    in APPLY_ORDER would leave the ledger pointing at nothing; an entry whose source is still on
    disk means the rename never happened.
    """
    module = _migrate_module()

    on_disk = {path.name for path in (repo_root() / "migrations").glob("*.sql")}
    for old_name, rename in module.RENAMED.items():
        new_name = rename.new_filename
        assert old_name not in on_disk, (
            f"{old_name} is declared renamed but still exists; the ledger carry-across would "
            "collide with the file"
        )
        assert new_name in module.APPLY_ORDER, (
            f"{old_name} was renamed to {new_name}, which is not in APPLY_ORDER"
        )
        assert new_name in on_disk, f"rename target {new_name} does not exist"
        # A rename moves a filename. If the declared checksum does not match the file, the rename
        # also changed the content, and carrying the ledger across would attach an applied-at
        # record to bytes that never ran under either name.
        assert len(rename.expected_old_checksum) == 64, (
            f"{old_name}: expected_old_checksum is not a sha256 digest"
        )


def test_apply_order_matches_the_directory():
    """Every file is declared and every declaration exists -- no silent skips in either direction."""
    module = _migrate_module()

    on_disk = {path.name for path in (repo_root() / "migrations").glob("*.sql")}
    declared = set(module.APPLY_ORDER)
    assert declared == on_disk, (
        f"undeclared on disk: {sorted(on_disk - declared)}; "
        f"declared but missing: {sorted(declared - on_disk)}"
    )
