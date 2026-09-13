"""Compare §17's canonical schemas against the Pydantic models and the migration DDL.

WHY THIS EXISTS.

P4 moved ``project_id`` and ``sensitivity_label`` off the global ``artifacts`` table, which was the
right fix for risk R-7. It updated the SQL and the access gate and left §17.1 and the Pydantic
``Artifact`` declaring both fields. Three things then disagreed about what an Artifact *is*, the
whole suite stayed green, and the drift survived a review round before a human noticed.

Nothing could have caught it. The spec's schemas are fenced code blocks; the models are Python; the
tables are SQL. No check read more than one of the three.

So this module reads all three and compares them. The canonical §17 block is the authority -- it is
what a maintainer amends -- and the model and the table must match it exactly, in both directions:

    missing_from_model / missing_from_table   the spec declares a field nobody implements
    extra_in_model / extra_in_table           an implementation grew a field the spec never declared

The second direction matters as much as the first. A field that exists in code and not in the spec
is how ``project_id`` got onto ``artifacts`` in the first place.

WHAT IS NOT COMPARED. Types. The spec's blocks are field sketches -- ``lineage_revision?`` carries
no type at all -- so a type comparison would be inventing a contract the spec does not state, and
the guard would then be asserting this module's opinion rather than the document's. Names and
presence are exactly what the canonical block does specify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lab_brain.spec.parser import repo_root, spec_path

#: Fields a schema block may declare that no column or model field corresponds to, because they are
#: expressed structurally instead. Kept explicit and tiny: every entry is a place the guard is
#: deliberately blind, so it has to be argued for rather than discovered.
STRUCTURAL_ONLY: dict[str, frozenset[str]] = {}


@dataclass(frozen=True)
class SchemaBinding:
    """One canonical §17 schema and the two implementations that must agree with it."""

    section: str
    schema_name: str
    model_path: str
    table: str
    migration: str


#: The bindings this guard enforces. Adding a model without adding it here is itself caught, by
#: ``test_every_core_model_with_a_canonical_schema_is_bound``.
BINDINGS: tuple[SchemaBinding, ...] = (
    SchemaBinding(
        section="17.1",
        schema_name="Artifact",
        model_path="lab_brain.core.models.artifact:Artifact",
        table="artifacts",
        migration="002_artifacts_sourceworks.sql",
    ),
    SchemaBinding(
        section="17.1.1",
        schema_name="ArtifactOccurrence",
        model_path="lab_brain.core.models.access:ArtifactOccurrence",
        table="artifact_occurrences",
        migration="002a_artifact_occurrences.sql",
    ),
)


class SchemaDriftError(RuntimeError):
    """A canonical schema could not be located or parsed."""


def canonical_fields(schema_name: str, section: str, text: str | None = None) -> frozenset[str]:
    """Field names declared by ``<schema_name> { ... }`` inside the §``section`` code block.

    Parsed from the document rather than transcribed, so an amendment to §17 takes effect here
    without anyone remembering to mirror it.
    """
    body = text if text is not None else spec_path().read_text(encoding="utf-8")
    heading = re.search(rf"^#{{1,4}}\s+{re.escape(section)}[ .].*$", body, re.M)
    if heading is None:
        raise SchemaDriftError(f"§{section} not found in the specification")
    following = re.search(r"^#{1,4}\s+\d", body[heading.end() :], re.M)
    window = body[heading.end() : heading.end() + (following.start() if following else 4000)]

    block = re.search(rf"{re.escape(schema_name)}\s*\{{(.*?)\n\}}", window, re.S)
    if block is None:
        raise SchemaDriftError(
            f"§{section} contains no `{schema_name} {{ ... }}` block; the canonical schema cannot "
            "be read, so this guard would silently compare nothing"
        )

    fields: set[str] = set()
    for line in block.group(1).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for token in line.split(","):
            name = token.strip().rstrip("?").strip()
            # `derived_from_artifact_ids[]` and `metadata{}` declare shape, not extra fields.
            name = name.removesuffix("[]").removesuffix("{}")
            if re.fullmatch(r"[a-z_][a-z0-9_]*", name):
                fields.add(name)
    if not fields:
        raise SchemaDriftError(f"§{section}'s `{schema_name}` block parsed to zero fields")
    return frozenset(fields)


def model_fields(model_path: str) -> frozenset[str]:
    """Pydantic field names for ``module:ClassName``."""
    module_name, _, class_name = model_path.partition(":")
    module = __import__(module_name, fromlist=[class_name])
    model = getattr(module, class_name)
    return frozenset(model.model_fields)


def table_columns(migration: str, table: str) -> frozenset[str]:
    """Column names for ``table``, read from the migration that creates it.

    Reads the DDL rather than a live database on purpose: the guard has to run in the
    backend-free CI job too, and a schema the migrations do not produce is not a schema.
    """
    path = repo_root() / "migrations" / migration
    if not path.is_file():
        raise SchemaDriftError(f"migration {migration} not found")
    sql = path.read_text(encoding="utf-8")
    block = re.search(rf"CREATE TABLE\s+{re.escape(table)}\s*\((.*?)\n\);", sql, re.S | re.I)
    if block is None:
        raise SchemaDriftError(f"{migration} contains no `CREATE TABLE {table}`")

    columns: set[str] = set()
    depth = 0
    for raw in block.group(1).splitlines():
        line = raw.split("--", 1)[0].strip()
        if not line:
            continue
        if depth == 0:
            match = re.match(r"([a-z_][a-z0-9_]*)\s+[A-Za-z]", line)
            if match and match.group(1).upper() not in {
                "CONSTRAINT",
                "PRIMARY",
                "FOREIGN",
                "UNIQUE",
                "CHECK",
                "EXCLUDE",
            }:
                columns.add(match.group(1))
        depth += line.count("(") - line.count(")")

    # Columns the migration adds later with ALTER TABLE -- `project_memberships.active` is one.
    for altered in re.finditer(
        rf"ALTER TABLE\s+{re.escape(table)}\s+ADD COLUMN\s+([a-z_][a-z0-9_]*)", sql, re.I
    ):
        columns.add(altered.group(1))
    for dropped in re.finditer(
        rf"ALTER TABLE\s+{re.escape(table)}\s+DROP COLUMN\s+([a-z_][a-z0-9_]*)", sql, re.I
    ):
        columns.discard(dropped.group(1))

    if not columns:
        raise SchemaDriftError(f"{migration}: `CREATE TABLE {table}` parsed to zero columns")
    return frozenset(columns)


def effective_table_columns(binding: SchemaBinding) -> frozenset[str]:
    """Columns after every migration that touches the table, not only the one that created it.

    ``artifacts`` is created by 002 and altered by 002a. Reading only the creating migration would
    have reported the dropped columns as still present -- which is precisely the drift this guard
    exists to catch, so it must not be blind to it.
    """
    columns = set(table_columns(binding.migration, binding.table))
    directory = repo_root() / "migrations"
    for path in sorted(directory.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for altered in re.finditer(
            rf"ALTER TABLE\s+{re.escape(binding.table)}\s+ADD COLUMN\s+([a-z_][a-z0-9_]*)",
            sql,
            re.I,
        ):
            columns.add(altered.group(1))
        for dropped in re.finditer(
            rf"ALTER TABLE\s+{re.escape(binding.table)}\s+DROP COLUMN\s+([a-z_][a-z0-9_]*)",
            sql,
            re.I,
        ):
            columns.discard(dropped.group(1))
    return frozenset(columns)


def drift(binding: SchemaBinding, text: str | None = None) -> list[str]:
    """Every disagreement between the canonical schema, the model and the table."""
    canonical = canonical_fields(binding.schema_name, binding.section, text)
    allowed = STRUCTURAL_ONLY.get(binding.schema_name, frozenset())
    model = model_fields(binding.model_path)
    table = effective_table_columns(binding)

    findings: list[str] = []
    for label, implemented in (("model", model), ("table", table)):
        missing = sorted(canonical - implemented - allowed)
        extra = sorted(implemented - canonical)
        if missing:
            findings.append(
                f"§{binding.section} {binding.schema_name}: declared but absent from the "
                f"{label}: {', '.join(missing)}"
            )
        if extra:
            findings.append(
                f"§{binding.section} {binding.schema_name}: present in the {label} but not "
                f"declared in the spec: {', '.join(extra)}"
            )
    return findings


def all_drift(text: str | None = None) -> list[str]:
    return [finding for binding in BINDINGS for finding in drift(binding, text)]


__all__ = [
    "BINDINGS",
    "SchemaBinding",
    "SchemaDriftError",
    "all_drift",
    "canonical_fields",
    "drift",
    "effective_table_columns",
    "model_fields",
    "table_columns",
]
