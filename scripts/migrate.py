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
    # M1-P2 / OPS-001. Appendix A's whole `006` slot, both halves, which is why this takes the
    # bare number rather than a suffix. After 001 for the `projects` foreign key and nothing
    # else: Jobs and Runs are execution records, not scientific ones, and a dependency on the
    # evidence tables would be a coupling neither §17.16 nor §17.4 declares. Placed here rather
    # than at numeric position because `010a`'s header records that its `job_id` carries no
    # foreign key *because this migration did not exist*; it exists now, and the ordering makes
    # that legible.
    "006_jobs_runs.sql",
    # M1-P4 / OPS-001 repair. Two audit findings against `006`: `job_complete` persisted a
    # SUBSET of §17.4 (seven fields silently replaced by column defaults, so the two stores
    # disagreed about what a Run is), and `add_run` was a second, weaker completion path that
    # permitted a durable Run whose Job did not resolve to it. Separate from `006` because
    # `006` is applied and an applied migration is checksummed.
    "006a_run_completion_integrity.sql",
    # M1 final / OPS-001. The minimum §17.3 ResearchEpisode the exit gate's "delayed mock
    # job resumes EPISODE" needs. Extends 006 because `jobs.episode_id` is the reference it
    # resolves, and turns that column into a checked foreign key. After 006.
    "006b_research_episodes.sql",
    # P6 / M0b-3. The observability third of Appendix A's 010 slot (OPS-003); the review and
    # benchmark halves land with OPS-002 and §17.19.2. After 007a/007b: span cost refs are a
    # foreign key into `cost_entries`.
    "010a_execution_spans.sql",
    # P6-fix. Makes closing a span atomic with its cost refs, and requires a parent span to be in
    # the same trace. Separate from 010a because 010a is applied.
    "010b_execution_span_close_atomicity.sql",
    # P11 / EPI-006. Appendix A's `011_predictions_conflicts.sql` slot, conflict half only --
    # Prediction is a later migration. After 005c: `conflicts.resolution_event_id` is a composite
    # foreign key into `belief_revision_events (event_id, project_id)`, and that UNIQUE came from
    # 005c. After 001: `project_id` references `projects`.
    "011a_conflicts.sql",
    # P11 / EPI-004. §26's M0b row lists "ReviewItem minimum schema" in this range. After 011a:
    # it turns `conflicts.review_id` into a checked composite foreign key and adds the trigger
    # that makes an AUTHORITY_CONFLICT review name a conflict in the same project. A shared
    # foundation with UX-005, which it does NOT discharge -- see the migration header.
    "011b_review_items.sql",
    # P12 / `v3.3-a14`. The P11 audit's P0: a review had to actually resolve before its conflict
    # could close. Adds `review_resolutions` (what §17.19.1's `decision_ref` points at), makes
    # `conflict_close` consult the linked review, and adds the atomic resolve-and-close path.
    # Also completes 011a's immutability and makes 011b's escalation idempotent. After 011b:
    # `decision_ref` becomes a deferred composite foreign key into the new table.
    "011c_review_resolutions.sql",
    # P13 / `v3.3-a14`. The P12 audit's P0: every guard `011c` added lives inside a function, and a
    # writer can decline to call one -- so raw SQL could still commit a terminal review beside an
    # unresolved conflict, or a closed conflict behind a QUEUED review. Moves the whole cross-table
    # invariant to the COMMIT boundary with deferred constraint triggers, which is what lets the one
    # valid operation pass through its necessary intermediate half-state. After 011c: it reads
    # `review_resolutions` and the `decision_ref` reference that migration created.
    "011d_review_conflict_commit_invariant.sql",
    # M0b closure / OPS-002. §14.4's ReviewQueue: capacity, stakes and an SLA/expiry policy, so an
    # uncertain item cannot park in PENDING forever. `011b` shipped `review_items` as a minimum
    # schema with nullable `due_at`/`expires_at` and nothing setting them, and said so. After 011c:
    # it replaces `authority_conflict_escalate` again to price the item from the declared policy,
    # preserving that version's idempotence and one-winner concurrency guarantees unchanged.
    "011e_review_queue_policy.sql",
    # M0b gate / `v3.3-a15` (SPEC-ISSUE-012). An automatically expired ReviewItem had no
    # closure event anyone could author: `v3.3-a14` routes every closure through a
    # BeliefRevisionEvent, and a timeout is not a belief transition. Adds `governance_events`,
    # generalises the closure reference to a typed (kind, id) pair on both
    # `review_resolutions` and `conflicts`, and adds the atomic `review_expire`. After 011e:
    # the GovernanceEvent cites the exact queue policy version the item was priced by.
    "011f_governance_event_closure.sql",
    # M0b gate / `v3.3-a16`. `011f` checks that the Conflict and the ReviewResolution agree on
    # (kind, id); it never loads the referenced GovernanceEvent to ask whether that event was
    # written for *this* review. So a genuine REVIEW_EXPIRY event for review A could be presented
    # as closure proof for review B in the same project -- the `v3.3-a14` substitution, one
    # indirection further out. Binds the event to the exact review, conflict, queue-policy version,
    # policy declarer and executor, requires `declared_by_actor_id` on a REVIEW_EXPIRY, and refuses
    # an inactive executor. After 011f: it extends that migration's commit-boundary invariant
    # rather than adding a second notion of closure validity.
    "011g_governance_event_chain_binding.sql",
    # M1 / UX-005. Adds EXTRACTION_UNCERTAINTY to `review_items.subject_type`. An extension
    # of the vocabulary, not a change to M0b semantics: UX-005 forbids a parallel review
    # surface because ReviewQueue depth is what prices human attention in §14.4.1, so a
    # second queue would consume the same reviewers while being invisible to the planner.
    "011h_review_subject_extraction.sql",
    # M1 final / UX-001, UX-002, UX-003. Appendix A's 012 slot, with its exact slug.
    # `ingestion_items` has NO state column -- §17.22 derives it. After 006b (stage results
    # reference jobs), 010a (spans), 002/002a (artifacts) and 011h (review items).
    "012_ingestion_items_errors.sql",
    # M1 second audit / UX-001, ART-001. Drops one CHECK from 012 that content addressing makes
    # unsatisfiable: identical bytes are the SAME artifact, so a duplicate item's
    # `duplicate_of_artifact_id` necessarily equals its `raw_artifact_id`. Forward-only, because
    # editing an applied file is what the checksum guard exists to catch.
    "012a_duplicate_is_content_identity.sql",
    # M1 third audit / UX-003, §17.24. The row `error_records.technical_detail_ref` points at.
    # A separate table rather than columns, because the default payload is built FROM the error
    # record -- a detail column would put restricted material into the object the untrusted tier
    # is rendered from. After 012 (error_records) and 001 (projects).
    "012b_technical_details.sql",
    # M1-P1 / EVI-010 (`v3.3-a17`). The canonical evidence body. Extends 003 rather than taking
    # Appendix A's 012, which is reserved for `ingestion_items_errors` (UX-001, a later slice).
    # After 002 and 003: foreign keys into `artifacts` and `source_works`, and it is what an
    # Attestation is made from.
    "003a_evidence_units.sql",
    # M1-P1 / EVI-010, ADR-0011. What an index holds about a unit. A SEPARATE migration on
    # purpose: dropping every row for an `index_id` must be expressible without touching
    # `evidence_units`, which is the schema-level form of "rebuilding an index changes no
    # scientific evidence identity". The 'a' extension of Appendix A's 009 `vectors` slot, where
    # EVI-007's dense index will later add columns -- nowhere near 003a. After 003a: the foreign
    # key points from the index to the evidence, never the reverse.
    "009a_retrieval_representations.sql",
    # M1-P1 repair / `v3.3-a18` (SPEC-ISSUE-014, SPEC-ISSUE-015). Splits project scope off the
    # content-derived evidence identity -- the ADR-0010 move one layer down -- and adds the
    # segmentation witness. After 003a and 002a: it backfills occurrences from the column it then
    # drops, and its occurrence trigger checks `artifact_occurrences`.
    "003b_evidence_unit_occurrences.sql",
    # M1-P1 repair / `v3.3-a18`. Consequence of the split: 009a's UNIQUE (unit, index) permitted
    # only one project to index evidence that several may now hold, and its trigger read the
    # column 003b drops. Must run after 003b for both reasons.
    "009b_representation_project_scope.sql",
    # M1-P1 repair / `v3.3-a18`. §17.25's durable-reference clause: the Attestation->EvidenceUnit
    # link existed only as an admission-call parameter, so a reloaded attestation could not name
    # the passage it read. After 003b: the column references `evidence_units` and its trigger
    # reads `evidence_unit_occurrences`.
    "003c_attestation_evidence_unit.sql",
    # M1 final / LLM-001. §17.14 InferenceProvenance, durable and append-only. Extends 003
    # because §17.2's Attestation carries `inference_provenance_id`. After 001 for the
    # project foreign key.
    "003d_inference_provenance.sql",
    # M2 / VER-002, §9.5, §17.18, §10.7. The capabilities half of Appendix A's `007` slot, which
    # `007a`'s header reserved for this milestone. Also carries the license/seat pool the M2 exit
    # gate's "license/resource queue mock" needs, because a seat ceiling enforced in Python is
    # correct for one scheduler and wrong for two -- the same argument `006` makes about duplicate
    # callbacks. After 008 (`conditions_schema_version` is a foreign key into `condition_schemas`)
    # and after 006 (`resource_leases.job_id` references `jobs`).
    "007c_capabilities.sql",
    # M3 / §7.3. `003d` constrained `logical_slot` to M1's function labels, so §7.3's own route
    # slots were unrecordable. Widens the CHECK additively; M1's rows and code are unchanged.
    "003e_model_route_slots.sql",
    # M3 / LLM-002, VER-004/008. The benchmark half of Appendix A's 010 slot: OutcomeSpace and
    # BenchmarkPolicy, both bound field-for-field to §17.19.2. No dependencies beyond 001.
    "010c_outcome_spaces_benchmark_policies.sql",
    # M3 / EPI-001, SRC-002, LLM-002. The Hypothesis certificate, competing sets, Position,
    # CritiqueReport and the debate record. After 006b (episodes), 004a (bundles), 003d
    # (inference provenance): every one of them is referenced by a foreign key.
    "005e_hypotheses_and_debate.sql",
    # M3 / EPI-001, VER-006, SRC-002. The Prediction half of Appendix A's 011 slot, and the
    # belief-revision guard for certificates admitted through M3's gate. After 010c (outcome
    # spaces), 005e (hypotheses, critiques) and 005a (the events it guards).
    "011i_predictions.sql",
    # M3 / SRC-003. PriorArtSearchRecord and NoveltyAssessment. After 006b (episodes) and 005e,
    # whose episode-in-project trigger function it reuses.
    "002b_prior_art_search.sql",
    # M3 / EPI-001 -- closes R-12. Re-keys `hypotheses` on (project_id, hypothesis_id), M0b's
    # identity for a history, and makes every belief event name an admitted hypothesis of its own
    # project. After 011i, whose two functions it replaces with project-scoped lookups.
    "011j_belief_event_targets.sql",
    # M4 / VER-001, VER-005. SelectionPolicy and VerificationPlan (§9.6, §17.14.1). After 006b
    # (episodes) and 005e, whose episode-in-project trigger function it reuses.
    "011k_verification_plans.sql",
    # M4 / EPI-002. FailureAnalysis and CandidateHeuristic, with the Run/Artifact trace in SQL.
    # After 011j (hypotheses keyed on the pair), 006 (runs), 003 (observations, attestations),
    # 004 and 005a (relations and the events that cite them).
    "011l_failure_analyses.sql",
    # M5 / GH-001, GH-002, GH-003. External snapshots and their lifecycle, and GH-003's guards on
    # attestations and source works. In Appendix A's 002 slot (artifacts / source works); applied
    # last because its attestation guard reads source_works and it references actors, projects and
    # artifacts only.
    "002c_external_snapshots.sql",
    # M5 / GH-002. Access scopes, and the guard that a snapshot was read under its own project's
    # scope. After 002c, whose table it guards and whose append-only function it reuses.
    "002d_external_access_scopes.sql",
    # M5 / GH-002, upgrade safety. Quarantines every pre-existing snapshot whose project and access
    # scope cannot be proven coherent, and keeps quarantined material out of use. After 002d, whose
    # scope table it reads, and after 003/004/004a/005a, whose tables it guards.
    "002e_external_snapshot_quarantine.sql",
    # Product vertical / episode continuation. The research runs of an episode: the opener
    # binding, one live run, one reasoning history. After 006b (episodes), 005e (hypothesis sets
    # and `m3_episode_is_in_project`), 001 (actors, projects) and 002 (artifacts).
    "012c_research_runs.sql",
    # Research workspace (web). The report each finished research run returned, bound to its
    # run. After 012c (research_runs) and 006b/001 (episodes, projects).
    "012d_research_run_reports.sql",
    # Research workspace V2. Model connections (credential references only), health, models,
    # capability probes, locks, runtimes and slot bindings. After 001 (actors).
    "012e_llm_runtime.sql",
    # Research workspace V2, closure. Deployment LLM administration apart from project egress
    # authorization; LOCAL may name the Docker host. After 012e (llm_*) and 001 (actors,
    # projects, memberships).
    "012f_llm_authority.sql",
    # Research data intake: the material kind a researcher declared for a file added outside a
    # research run, bound to its ingestion item. After 012 (ingestion_items) and 001.
    "012g_research_data_declarations.sql",
    # A pasted model-provider key kept in this deployment's credential directory: the reference
    # `file:lab-brain/llm/<uuid>` beside env: and wincred:. After 012e (llm_connections).
    "012h_llm_credential_directory.sql",
    # An ENABLED model connection reaches another host over https:// only; plaintext http:// only
    # on this machine (NOT VALID: older rows are refused where they are used). After 012f (the
    # this-machine host list it repeats).
    "012i_llm_transport.sql",
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
