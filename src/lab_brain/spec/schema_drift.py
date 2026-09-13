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


#: The bindings this guard enforces. Completeness is enforced by
#: ``test_every_canonical_schema_is_bound_or_exempt``: every §17 block naming an exported core
#: model must appear here or in ``UNBOUND`` with a stated reason.
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


#: §17 schemas that name a core model but are NOT field-for-field bound, and why.
#:
#: Most §17 blocks are abbreviated sketches rather than complete schemas -- they name the fields the
#: chapter is making a point about and omit foreign keys, denormalised columns and audit fields the
#: implementation needs. Binding those by exact field equality would report a dozen "undeclared"
#: findings that are not drift, and a guard that cries wolf gets suppressed.
#:
#: §17.1 and §17.1.1 are bound because amendment v3.3-a8 rewrote them to be exact, which is what
#: made the Artifact drift detectable in the first place. The entries below are the honest statement
#: of how far this guard currently reaches. Each says what would have to change to bind it.
UNBOUND: dict[str, str] = {
    "Claim": "§17.2's block omits merged_into_claim_id, which the merge path needs. Bindable once "
    "§17.2 is amended to state it.",
    "Observation": "§17.2's block is a sketch: it omits the artifact/run/project links and the "
    "value+unit pair that make an Observation queryable.",
    "Attestation": "§17.2's block omits every foreign key (claim, observation, source work, "
    "artifact, run, project), which is most of the record.",
    "RelationJudgment": "§17.8's block omits project_id and invalidation_reason; the latter exists "
    "because RelationJudgment.invalidate() must record why.",
    "EvidenceBundle": "§17.14.1 declares canonical_hash and query_hash, which the model exposes as "
    "computed properties rather than stored fields, and omits project_id. Binding needs a rule for "
    "computed fields that this guard does not yet have.",
    "EvidenceField": "§17.9's block describes a value object embedded in Observation, not a table, "
    "so there is no DDL side to compare against.",
    "ConditionSchemaRegistration": "§17.19 describes the registration payload; the table stores it "
    "decomposed across condition_schemas.",
    "ConditionMatch": "§17.19's block is a return value, not stored state.",
    "Actor": "§17.15's block is not parseable as a standalone `Actor { ... }` schema; the section "
    "describes the ACL model in prose. Bindable once §17.15 states a schema block.",
    "ProjectMembership": "Same as Actor -- §17.15 has no standalone block.",
}


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


def canonical_schema_names(text: str | None = None) -> dict[str, str]:
    """Every ``Name {`` schema block inside §17, mapped to the section that declares it.

    Used by the completeness check. Scanning the document rather than a hand-kept list is the point:
    a schema added by an amendment has to be bound or exempted, not quietly ignored.
    """
    body = text if text is not None else spec_path().read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for heading in re.finditer(r"^#{1,4}\s+(17(?:\.\d+)*)[ .].*$", body, re.M):
        section = heading.group(1)
        following = re.search(r"^#{1,4}\s+\d", body[heading.end() :], re.M)
        window = body[heading.end() : heading.end() + (following.start() if following else 4000)]
        for block in re.finditer(r"^\s*([A-Z][A-Za-z0-9]*)\s*\{", window, re.M):
            found.setdefault(block.group(1), section)
    return found


def unbound_canonical_schemas(text: str | None = None) -> list[str]:
    """§17 schemas naming an exported core model that are neither bound nor exempted."""
    import lab_brain.core.models as core_models

    exported = {name for name in dir(core_models) if name[:1].isupper()}
    bound = {binding.schema_name for binding in BINDINGS}
    return sorted(
        f"§{section} {name}"
        for name, section in canonical_schema_names(text).items()
        if name in exported and name not in bound and name not in UNBOUND
    )


def stale_exemptions(text: str | None = None) -> list[str]:
    """``UNBOUND`` entries that no longer name a §17 schema, or that are now bound.

    Without this the exemption list rots into a permanent excuse: a schema deleted by an amendment,
    or one that was later bound properly, would keep an entry claiming it cannot be checked.
    """
    names = canonical_schema_names(text)
    bound = {binding.schema_name for binding in BINDINGS}
    problems = [f"{name}: no longer a §17 schema" for name in UNBOUND if name not in names]
    problems += [f"{name}: exempt but also bound" for name in UNBOUND if name in bound]
    problems += [
        f"{name}: exemption has no reason" for name, why in UNBOUND.items() if not why.strip()
    ]
    return sorted(problems)


__all__ = [
    "BINDINGS",
    "UNBOUND",
    "SchemaBinding",
    "SchemaDriftError",
    "all_drift",
    "canonical_fields",
    "canonical_schema_names",
    "drift",
    "effective_table_columns",
    "model_fields",
    "stale_exemptions",
    "table_columns",
    "unbound_canonical_schemas",
]
