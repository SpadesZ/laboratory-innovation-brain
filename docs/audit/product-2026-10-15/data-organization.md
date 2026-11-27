# SiPh Lab: information architecture and data integrity audit (2026-10-15)

An independent reviewer audited how research material is organized: the schema, the storage and
the provenance links, and whether a researcher can answer the questions in §5. It worked on
`16a1560`, read-only on the code. It used its own disposable database (`lab_brain_ia_audit`, 63
migrations: 83 tables, 2 views, 191 foreign keys, 132 user triggers, no row-level security, one
database role), probed with synthetic rows inside rolled-back transactions, and dropped the
database afterwards. It did not touch the deployment's database or web app.

Below is its report, condensed as delivered. **[V]** means it ran it or read the cited line;
**[I]** means inferred. The "since" column says what changed after the audit, and where.

**Bottom line (reviewer).** The scientific core is project-scoped with composite foreign keys and
is append-only: hypotheses, predictions, decisions, belief events, reports, warrants. The weak
points are in the mutable layer around it: episodes, memberships, sensitivity labels,
attestations, relation validity, and references stored as text or text arrays.

## 1. Where research material actually lives [V]

- **Structured records:** PostgreSQL. In the product, volume `lab-brain-workspace_db`.
- **Raw bytes:** content-addressed at `<artifact-root>/objects/sha256/aa/bb/<digest>`, staged in
  `<artifact-root>/_staging/`. In the product, volume `artifacts`; when run natively, whatever
  `--artifact-root` names on each invocation.
- **Evidence units:** global `evidence_units`; their presence in a project is
  `evidence_unit_occurrences`.
- **Reports:** JSONB in `research_run_reports`, one per research run; no report files on disk.
- **Model keys:** volume `credentials`.
- **Empty `objects/` and `_staging/` in a checkout:** made by `tests/e2e/test_m1_vertical_postgres.py`,
  which built `LocalArtifactStore(".")` [I].
- **`docs/audit/**/evidence/`** holds direct dumps of deployment rows. `exports/` outside the
  repository was not opened.

## 2. Entity map (abridged)

| entity | table | scoping | provenance links | UI |
|---|---|---|---|---|
| project | `projects` | root; `archived_at` never set | | project picker; CLI `admin` |
| membership | `project_memberships` | project; overwritten in place, `granted_by` never written | | CLI only |
| artifact | `artifacts` | global; presence via `artifact_occurrences` (label row mutable) | `previous_artifact_id` unused; `uri` is the caller's URI, not the store location | `/data` |
| evidence unit | `evidence_units` | global, gated by occurrences | | `/data` counts |
| claim | `claims` | global, no project, no label | | excerpt text |
| observation | `observations` | project | artifact FK without an occurrence check; `run_id` soft | episode checks |
| attestation | `attestations` | project; mutable | `run_id` soft | report evidence |
| relation | `relation_judgments` | project | from/to soft; support list a soft array; `valid_to`/`actor_id` mutable | episode relations |
| episode / run / report | `research_episodes`, `research_runs`, `research_run_reports` | project | episode has no trigger; runs and reports append-only | `/episodes` (opener only) |
| hypothesis set / hypothesis / prediction | composite keys | project; immutable | | episode L1/L2 |
| decision / belief event | composite keys | project; append-only | | transitions |
| conflict, review, warrant, reviewer keys | composite keys | project; append-only | | CLI `review` |
| failure analysis / flag | `failure_analyses`, `failure_analysis_flags` | project; append-only, N per episode | arrays trigger-checked | episode L1/L3 |
| candidate heuristic | `candidate_heuristics` | project; status fixed `PENDING_REVIEW` | sources checked only for global existence | report text |
| registries | policies, outcome spaces, declaration sets | global, versioned | | none |

## 3. Findings

| # | sev. | finding (reviewer) | since |
|---|---|---|---|
| F-01 | HIGH | The question's sensitivity label is not stored; a web continuation that re-debates uses the default INTERNAL (`research/service.py:270, 611-617, 1200`) [V]. A CONFIDENTIAL or NDA question could go to a model under INTERNAL [I]. | Open: needs a migration (store the label) or an interim fail-closed rule. Owner decision. |
| F-02 | HIGH | A withdrawn relation can be reopened by UPDATE, and invalidation overwrites `actor_id` with the invalidator (probe P15) [V]. | Open: migration (`invalidated_by_actor_id`, no reopening). |
| F-03 | MED | Cross-project and dangling references accepted: attestation citing another project's artifact, relation support citing another project's attestation, bundle members, ghost run ids (P1–P5) [V]. | Partly: the gate's relation check now reads attestations and observations in the relation's project (`fa9e982`, V1.1 branch). Other tables: migration. |
| F-04 | MED | Hypothesis ids are unique per project, but two gate triggers looked them up by id alone (`012p:223`, `012o:347`) [V]. | **Fixed** on the V1.1 branch (`fa9e982`), with tests that failed before. |
| F-05 | MED | Episode lifecycle not enforced: a COMPLETED episode set back by UPDATE (P6); ABANDONED unreachable; no parent episode, no transition log [V]. | Open: migration. |
| F-06 | MED | Every loop run appends a failure analysis; nothing marks the current one (P8) [V]. | Open: migration or a derived "current" view. |
| F-07 | MED | The Markdown export renders the frozen report without the flags recorded since [V/I]. | **Fixed** on this branch: the export appends what was recorded since. |
| F-08 | MED | Every admission copies each evidence unit's text into a new global, unlabelled `claims` row [V]. | Open: owner decision (D7). |
| F-09 | MED | Membership and label history overwritten (P10, P12, P14) [V]. | Open: migration (event tables). |
| F-10 | MED | `archived_at` exists but nothing sets it, and a new episode was accepted in an archived project (P11) [V]. | Open: owner decision (D2). |
| F-11 | MED | Episodes are visible and continuable only by their opener; research data is project-wide; CLI-opened episodes without a research run never appear [V]. | Open: owner decision (D1). |
| F-12 | MED | The database does not record where raw bytes are stored; the README examples used a relative `.\artifacts`; those paths were not git-ignored; no backup procedure [V]. | **Partly fixed** on this branch: `.gitignore`, README examples under `var\artifacts`, the test no longer writes into the repository. Backup procedure: open. |
| F-13 | LOW–MED | Backend features with no web workflow: answering reviews, flagging, heuristic approval, SUPERSEDES, artifact revisions, archive, abandon, membership revoke [V]. | Open (UX proposals R1, R5, R6). |
| F-14 | LOW | Dead or unvalidated schema: `evidence_independence` unused; `budget_policies` no product writer; `jobs_episode_must_exist` NOT VALID [V]. | Open: owner decision (D11). |
| F-15 | LOW | Unenforced `episode_id` in spans, costs, conflicts, governance events, reviews, decisions; jobs carry no `research_run_id` [V]. | Open. |
| F-16 | LOW | Declaration-set supersession can fork [V]; Python refuses the mismatch, so it fails as a denial [I]. | Open: unique index (migration). |
| F-17 | LOW | Documentation drift: README structure table, requirement counts, stale risks R-7/R-11/R-12 and "Next Recommended Task" in IMPLEMENTATION_STATUS, spec §18 tree, ADR-0004/0009 citing `configs/*.yaml` [V]. | Open (documentation pass). |
| F-18 | LOW | Deployment rows dumped into `docs/audit/causal-warrant-gate-v1/evidence/` with no recorded classification [V]. | Open: owner decision (D10). |
| F-19 | INFO | The development PostgreSQL container publishes `0.0.0.0:5433` with the committed password; it was created from an older compose file; `compose.dev.yaml` now binds loopback only [V]. | Operator step: recreate it from `compose.dev.yaml` (the volume is kept). |
| F-20 | LOW | Confusing names: `runs` (tool executions) vs `research_runs` vs `/runs/new`; `research_runs.outcome` packs two values [V]. | Open (glossary). |
| F-21 | LOW | Missing indexes for the reverse questions: failure analyses and decisions by episode; "what cites attestation X?" [V]. | Open: migration. |

## 4. Probe log (rolled back)

P1–P5 cross-project or dangling references: accepted. P6 reopening a COMPLETED episode:
`UPDATE 1`. P7 the same hypothesis id in two projects: 2 rows. P8 two analyses for one episode.
P9 spans and costs naming ghost ids: accepted. P10 membership overwritten. P11 a new episode in an
archived project: accepted. P12–P14 a label updated, an attestation edited, an occurrence deleted
while cited: accepted. P15 an invalidated relation reopened: accepted. P16 deleting a project with
children: refused by FK. Declaration fork: three versions active.

## 5. Can a researcher answer these? (reviewer)

| question | answer |
|---|---|
| Which project does this result belong to? | Mostly: every scientific row has `project_id`. Gaps: claims, spans, array references (F-03), per-project hypothesis ids (F-04, fixed in the gate). |
| Which source and experiment produced it? | Partly: attestation → artifact / evidence unit; observation → run → job → episode. Gaps: store location (F-12), research-run attribution (F-15). |
| Which hypothesis does it support or contradict? | Yes within an episode. Gaps: reversible withdrawals (F-02), no reverse index (F-21), no project-wide view. |
| Which result is authoritative or superseded? | Weak: F-05, F-06, F-07 (fixed for exports), F-13, F-16. |
| Where should new research material be stored? | Clear in the product (`/data` → `artifacts` volume); unclear natively (F-12, partly fixed). |
| Can it be recovered, reused and audited without mixing projects? | Auditing the scientific core: good. Recovery weak (F-12); reuse weak (F-11, F-13); memberships and labels overwritten (F-09); archive inert (F-10). |

## 6. Owner decisions (reviewer)

D1 colleagues seeing or continuing each other's episodes; D2 what "archived" blocks; D3 lab-wide
reuse with clearance, or strict per-project memory; D4 heuristic approval (HEU-001); D5 adopt or
remove SUPERSEDES and artifact revisions; D6 one recorded artifact root per deployment; D7 the
claims layer; D8 spec §18; D9 must database invariants hold against any SQL writer (priority of
the migrations for F-02, F-03, F-05); D10 export policy for `docs/audit` evidence and `exports/`;
D11 the dead tables.

Read-only starter queries for an orphan and cross-project check are in the reviewer's notes (§9
of the delivered report); none was run against production.
