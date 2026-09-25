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
STRUCTURAL_ONLY: dict[str, frozenset[str]] = {
    # §17.13's two triggering arrays are stored as join tables, not TEXT[] columns, so that a
    # trigger reference is a foreign key that resolves. §6.18's contamination rollback *is* the
    # query "which events were triggered by an Attestation from extractor version X", and an
    # array that can name a row which does not exist makes that rollback silently incomplete.
    # The model keeps them as tuples; the table spreads them across
    # `belief_revision_event_attestations` / `_relations`. Both are faithful, and declaring the
    # relationship lets the guard check the rest of the schema instead of being told to skip it.
    "BeliefRevisionEvent": frozenset({"triggering_attestation_ids", "triggering_relation_ids"}),
}


@dataclass(frozen=True)
class SchemaBinding:
    """One canonical §17 schema and the two implementations that must agree with it."""

    section: str
    schema_name: str
    model_path: str
    table: str
    migration: str
    #: Canonical fields the TABLE stores decomposed into one column per sub-field, mapped to the
    #: model that defines those sub-fields. §17.17's `cost` is a CostVector: the model keeps it as
    #: one nested object, the table spreads it across a column per §9.4 dimension because caps are
    #: compared dimension-by-dimension in SQL. Both are faithful; declaring the relationship lets
    #: the guard check it instead of being told to look away.
    decomposed: tuple[tuple[str, str], ...] = ()


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
    SchemaBinding(
        section="17.13",
        schema_name="BeliefRevisionEvent",
        model_path="lab_brain.core.models.belief_event:BeliefRevisionEvent",
        table="belief_revision_events",
        migration="005a_belief_revision_events.sql",
    ),
    SchemaBinding(
        section="17.19.1",
        schema_name="GovernanceEvent",
        model_path="lab_brain.core.models.governance_event:GovernanceEvent",
        table="governance_events",
        migration="011f_governance_event_closure.sql",
    ),
    SchemaBinding(
        section="17.17",
        schema_name="CostEntry",
        model_path="lab_brain.core.models.cost:CostEntry",
        table="cost_entries",
        migration="007a_cost_ledger.sql",
        decomposed=(("cost", "lab_brain.core.models.cost:CostVector"),),
    ),
    # M1-P1 / EVI-010. Bound field-for-field rather than exempted, because `v3.3-a17` wrote
    # §17.25's blocks to be exact for exactly this reason -- the same move `v3.3-a8` made for
    # §17.1. ADR-0011's guarantee is that no embedding field ever appears on the evidence side,
    # and a guard that could not read the canonical block would not be able to hold it.
    SchemaBinding(
        section="17.25",
        schema_name="EvidenceUnit",
        model_path="lab_brain.core.models.evidence_unit:EvidenceUnit",
        table="evidence_units",
        migration="003a_evidence_units.sql",
        decomposed=(
            (
                "provenance",
                "lab_brain.core.models.evidence_unit:SegmenterProvenance",
            ),
        ),
    ),
    SchemaBinding(
        section="17.25.1",
        schema_name="EvidenceUnitOccurrence",
        model_path="lab_brain.core.models.evidence_unit:EvidenceUnitOccurrence",
        table="evidence_unit_occurrences",
        migration="003b_evidence_unit_occurrences.sql",
    ),
    SchemaBinding(
        section="17.25",
        schema_name="RetrievalRepresentation",
        model_path="lab_brain.core.models.evidence_unit:RetrievalRepresentation",
        table="retrieval_representations",
        migration="009a_retrieval_representations.sql",
    ),
    # M2 / VER-002. Bound field-for-field rather than exempted, because §17.18's block is already
    # exact -- fifteen fields, no audit timestamp -- and the table was written to match it. That is
    # why `capabilities` has no `created_at`: see the migration header for why registration history
    # is `version` rather than a column.
    SchemaBinding(
        section="17.18",
        schema_name="Capability",
        model_path="lab_brain.core.models.capability:Capability",
        table="capabilities",
        migration="007c_capabilities.sql",
    ),
    # M3 / LLM-002, VER-004. Both §17.19.2 blocks are exact, and `010c` was written to match them
    # field for field -- which is what lets this guard hold the calibration fields of a hard gate
    # and the membership of a declared OutcomeSpace to the spec rather than to a reviewer.
    SchemaBinding(
        section="17.19.2",
        schema_name="OutcomeSpace",
        model_path="lab_brain.core.models.prediction:OutcomeSpace",
        table="outcome_spaces",
        migration="010c_outcome_spaces_benchmark_policies.sql",
    ),
    SchemaBinding(
        section="17.19.2",
        schema_name="BenchmarkPolicy",
        model_path="lab_brain.core.models.benchmark:BenchmarkPolicy",
        table="benchmark_policies",
        migration="010c_outcome_spaces_benchmark_policies.sql",
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
    "Hypothesis": "§17.5 declares `status_projection` and `belief_level_projection`, and the same "
    "block four lines later says status is rebuilt from BeliefRevisionEvent + TransitionPolicy. "
    "Neither the model nor `005e`'s `hypotheses` table stores them: a stored, writable status is "
    "the bypass T-SYS-001 requires be rejected, so the projection lives in "
    "EpistemicStateProjection where it is derived. Both also carry project_id, which §17.5 omits; "
    "the table stores `prediction_ids` as the `predictions` rows that reference it (so a reference "
    "always resolves) and adds `hypothesis_set_id`, `authored_by_actor_id` and `created_at`, which "
    "EPI-001's competing set and P12's human authorship need. Bindable once §17.5 states the two "
    "projections as derived references.",
    "Prediction": "§17.5.1's block omits project_id, which the model and `011i`'s table carry for "
    "the reason §17.8 omits it on RelationJudgment and every other scoped table adds it (SEC-002), "
    "and the table adds `created_at` as an audit field. Otherwise exact. Bindable once §17.5.1 "
    "states the scope key.",
    "Position": "§17.14.1's block reaches the project through `episode_id` and declares no audit "
    "time; the model and `005e`'s `positions` table add `project_id` (SEC-002 scopes every read "
    "by project) and `created_at`. Otherwise exact. Bindable once §17.14.1 states the scope key.",
    "CritiqueReport": "§17.14.1's block omits the scope keys (`project_id`, `episode_id`) and "
    "the two fields that make §7.6's independence checkable: `original_inference_id` (which "
    "inference was critiqued) and `differs_in` (the axes, derived from the two provenance rows and "
    "re-derived by `005e`). Without them a critique cannot exhibit independence, only claim it. "
    "Bindable once §17.14.1 states them.",
    "PriorArtSearchRecord": "§17.20's block reaches the project through `episode_id`; the model "
    "and `002b`'s table add `project_id` for SEC-002's project-scoped reads, and are otherwise "
    "exact. Bindable once §17.20 states the scope key.",
    "DisagreementMetric": "§17.19.2 writes `deterministic:true` as one token, which this parser "
    "cannot read as a field name, and the model adds `outcome_space_version` because a metric "
    "defined over one OutcomeSpace version is undefined on outcomes a later version adds. There "
    "is no DDL side: VER-008's §26 row is unit, and the registry tabulates the metric in memory.",
    "ResearchContract": "§17.14.1's block and the model agree field for field, and there is no DDL "
    "side: M3 carries the Supervisor's contract in memory for one debate, and it is persisted with "
    "§17.14.1's VerificationPlan in M4.",
    "ValidationReport": "§17.19.2 writes `status:PASS|WARN|FAIL|UNKNOWN` as one token, which this "
    "parser cannot read as a field name -- so the canonical set comes back as nine fields against "
    "an implementation of ten and `status` is reported as undeclared. The same shape as §17.16's "
    "`state:QUEUED|...` on Job. There is also no DDL side: M2 stores no report, because §26's "
    "VER-002 and DOM-SP-001 rows are `unit` and `domain` -- what they require is that a validator "
    "RETURNS this shape. Bindable once §17.19.2 states `status` as its own field and VER-004's "
    "planner-side plausibility check brings the table.",
    "RelationJudgmentTemplate": "§17.5.1's block describes a value object embedded in Prediction, "
    "not a table -- the same shape as EvidenceField.",
    "RetrievalCandidate": "§17.25's block describes a retrieval result, not stored state -- the "
    "same shape as ConditionMatch. It is deliberately the smallest object in the codebase: "
    "giving it a body field would let admission read evidence out of the retriever's output, "
    "which is what EVI-010 forbids, so there is nothing to persist and nothing to compare.",
    "ConditionSchemaRegistration": "§17.19 describes the registration payload; the table stores it "
    "decomposed across condition_schemas.",
    "ConditionMatch": "§17.19's block is a return value, not stored state.",
    "Actor": "§17.15's block is not parseable as a standalone `Actor { ... }` schema; the section "
    "describes the ACL model in prose. Bindable once §17.15 states a schema block.",
    "ProjectMembership": "Same as Actor -- §17.15 has no standalone block.",
    "ExecutionSpan": "§17.19.1 writes the subject reference as one slash alternation, "
    "`model_call_id?/job_id?/retrieval_id?`, which this parser cannot read as three field names: "
    "it would compare a canonical set of 11 fields against an implementation of 13 and report the "
    "three subjects as undeclared. The model and the DDL implement the literal reading (at most "
    "one of the three, matching `span_type`) and enforce it in both places. Bindable once §17.19.1 "
    "states them as separate optional fields.",
    "Job": "§17.16's block reaches the project transitively through `episode_id`, and §17.3's "
    "ResearchEpisode is not built -- nothing in M1's ingestion path creates one. A Job that could "
    "only be scoped through an episode could therefore not be scoped at all, while SEC-002 scopes "
    "every read by project membership and a Job surfaces through UX-001's IngestionItem and "
    "UX-003's error lookup, both project-scoped by requirement. So the model and the table carry "
    "`project_id` and the canonical block does not. `resume_stage` is the second addition, for "
    "UX-004's resume-at-the-failed-stage: §17.16 declares the retry policies but no field "
    "recording where a resumable job is parked. Bindable once §17.16 states both, or once "
    "Episodes exist and the transitive scope is real.",
    "Run": "§17.4 omits `project_id` for the same reason §17.16 does, and the same argument "
    "applies one table over: a Run that is not project-scoped cannot be read under SEC-002, and "
    "`runs_job_must_exist` refuses a Run scoped away from its Job. The block also omits "
    "`created_at`, which every other table here carries as an audit field.",
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
    # `IF NOT EXISTS` is optional because the repository uses both forms: the early migrations
    # create a table once, and the later ones are written to be re-appliable against an
    # already-migrated database. A guard that only recognised one spelling would report a bound
    # table as missing -- which is how `governance_events` first failed this check.
    block = re.search(
        rf"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?{re.escape(table)}\s*\((.*?)\n\);",
        sql,
        re.S | re.I,
    )
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
        rf"ALTER TABLE\s+{re.escape(table)}\s+ADD COLUMN"
        rf"\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
        sql,
        re.I,
    ):
        columns.add(altered.group(1))
    for dropped in re.finditer(
        rf"ALTER TABLE\s+{re.escape(table)}\s+DROP COLUMN"
        rf"\s+(?:IF\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
        sql,
        re.I,
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
            rf"ALTER TABLE\s+{re.escape(binding.table)}\s+ADD COLUMN"
            rf"\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
            sql,
            re.I,
        ):
            columns.add(altered.group(1))
        for dropped in re.finditer(
            rf"ALTER TABLE\s+{re.escape(binding.table)}\s+DROP COLUMN"
            rf"\s+(?:IF\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
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

    # A decomposed field is satisfied by the presence of its parts, and those parts are not
    # "undeclared" -- they are the declared field, spread out.
    expanded: set[str] = set()
    satisfied: set[str] = set()
    for parent, nested_path in binding.decomposed:
        parts = model_fields(nested_path)
        expanded |= set(parts)
        if parts <= table:
            satisfied.add(parent)
        else:
            findings_missing = sorted(parts - table)
            expanded -= set(findings_missing)

    findings: list[str] = []
    for label, implemented in (("model", model), ("table", table)):
        if label == "table":
            implemented = (implemented - expanded) | satisfied
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


#: The one canonical schema outside §17 that this guard binds, and the five places a cost dimension
#: has to appear for the system to actually govern it. See :func:`cost_dimension_drift`.
COST_VECTOR_SECTION = "9.4"
COST_TABLES: tuple[tuple[str, str, str], ...] = (
    # (table, column prefix, migration that creates the table)
    ("cost_entries", "", "007a_cost_ledger.sql"),
    ("budget_policies", "cap_", "007a_cost_ledger.sql"),
    ("budget_approvals", "overrun_", "007a_cost_ledger.sql"),
)


def cost_dimension_drift(text: str | None = None) -> list[str]:
    """§9.4's dimensions, the ``CostVector`` model, ``CAPPED_DIMENSIONS``, ``BudgetCaps`` and the
    three cost tables must describe the same set.

    WHY THIS IS SEPARATE FROM ``BINDINGS``.

    ``CostVector`` is a canonical schema that lives at §9.4, and the §17 machinery above cannot see
    it: ``canonical_schema_names`` scans §17 headings only. So amendment ``v3.3-a10`` could add
    ``token_count`` to the specification and the whole suite stayed green with no model field, no
    column and no cap -- which is precisely the ADR-0010 drift, one chapter to the left.

    It is also not a plain ``SchemaBinding``, because a cost dimension is not one field in one
    table. It has to exist in five places at once, and each absence fails differently:

        §9.4 block            the declaration. Absent -> the dimension is not in the contract.
        ``CostVector``        what an action costs. Absent -> unrecordable.
        ``cost_entries``      what was spent. Absent -> recordable in memory, lost on write.
        ``CAPPED_DIMENSIONS`` whether the gate looks at it. Absent -> recorded, never enforced.
        ``BudgetCaps`` +      whether a cap can be stated at all. Absent -> enforceable in Python
        ``cap_*`` columns     against a limit no policy row can hold.

    The fourth and fifth are the quiet ones: a dimension that is recorded but not cappable looks
    fully implemented in every test that only writes ledger rows.

    Qualifiers (``irreversible``, ``earliest_available_at``, ``dependency_risk``) are checked to be
    present in the model and the ledger and **absent** from the caps -- they are not quotas, and a
    cap on irreversibility would be a category error the gate would then have to interpret.
    """
    canonical = canonical_fields("CostVector", COST_VECTOR_SECTION, text)
    model = model_fields("lab_brain.core.models.cost:CostVector")
    from lab_brain.core.models.cost import CAPPED_DIMENSIONS

    capped = set(CAPPED_DIMENSIONS)
    caps_model = model_fields("lab_brain.core.models.cost:BudgetCaps")

    findings: list[str] = []
    if canonical != model:
        missing = sorted(canonical - model)
        extra = sorted(model - canonical)
        if missing:
            findings.append(
                f"§{COST_VECTOR_SECTION} CostVector: declared but absent from the model: "
                + ", ".join(missing)
            )
        if extra:
            findings.append(
                f"§{COST_VECTOR_SECTION} CostVector: present in the model but not declared in the "
                "spec: " + ", ".join(extra)
            )

    if not capped <= model:
        findings.append(
            "CAPPED_DIMENSIONS names dimensions CostVector does not have: "
            + ", ".join(sorted(capped - model))
        )
    if caps_model != capped:
        findings.append(
            "BudgetCaps and CAPPED_DIMENSIONS disagree; only in BudgetCaps: "
            f"{sorted(caps_model - capped)}, only in CAPPED_DIMENSIONS: "
            f"{sorted(capped - caps_model)}"
        )

    for table, prefix, migration in COST_TABLES:
        columns = effective_table_columns(
            SchemaBinding(
                section=COST_VECTOR_SECTION,
                schema_name="CostVector",
                model_path="lab_brain.core.models.cost:CostVector",
                table=table,
                migration=migration,
            )
        )
        # The ledger stores every dimension; the cap and overrun tables store the cappable ones.
        expected = model if prefix == "" else capped
        absent = sorted(
            dimension for dimension in expected if f"{prefix}{dimension}" not in columns
        )
        if absent:
            findings.append(
                f"{table} has no column for: "
                + ", ".join(f"{prefix}{dimension}" for dimension in absent)
            )
        if prefix != "":
            # A cap on a qualifier would be a category error, so catch it here rather than let the
            # gate decide what a capped `irreversible` means.
            uncappable = sorted(
                dimension for dimension in model - capped if f"{prefix}{dimension}" in columns
            )
            if uncappable:
                findings.append(
                    f"{table} caps dimensions that are qualifiers, not quotas: "
                    + ", ".join(f"{prefix}{dimension}" for dimension in uncappable)
                )
    return findings


def all_drift(text: str | None = None) -> list[str]:
    return [finding for binding in BINDINGS for finding in drift(binding, text)] + (
        cost_dimension_drift(text)
    )


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
    "COST_TABLES",
    "COST_VECTOR_SECTION",
    "UNBOUND",
    "SchemaBinding",
    "SchemaDriftError",
    "all_drift",
    "canonical_fields",
    "canonical_schema_names",
    "cost_dimension_drift",
    "drift",
    "effective_table_columns",
    "model_fields",
    "stale_exemptions",
    "table_columns",
    "unbound_canonical_schemas",
]
