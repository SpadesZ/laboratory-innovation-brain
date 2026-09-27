# M5 — External Evidence Expansion: readiness for independent review

Date: 2026-09-27
Milestone: **M5 — External Evidence Expansion**, `IN_PROGRESS` (was `DEFERRED`). The implementing
agent does not sign off its own work; moving M5 to DONE is the maintainer's act on independent
review.
M4: **`IN_PROGRESS`, not signed off.** M5 was built on M4's final SHA `457252c` as a *provisional
baseline*: no M4 file was changed, nothing in M4 was repaired or redesigned, and M4 stays
`IN_PROGRESS` pending its own review. §10 records what M5's work observed about M4.
M3 and earlier: `DONE` / hard-locked — **no locked behaviour changed** (§6 lists every edit outside
the new modules; all additive).
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`. **No amendment, no ADR, no new Requirement or
Test ID, and no SPEC-ISSUE was raised.** Interpretations the text left open are stated in §5 where
they are made. M6 was not started.

**No external service was contacted.** Every GitHub and literature response in the recorded
verification comes from a deterministic fixture (`fixtures/external/`). The live-GitHub test is
marked `network`, is deselected by default, and **was not run**; nothing below claims it was.

## 1. The exit gate, clause by clause

> external evidence enters with source/condition/rights/provenance metadata; GitHub source traces to
> repo + resolved commit/ref; removing the GitHub provider does not affect core cognition.

| Clause | Where it is demonstrated |
|---|---|
| **enters with source metadata** | Admission (`sources/admission.py`) turns a durable snapshot into a SourceWork (work type, identifier — `github-repository` numeric id or `doi` — trust class, retraction/status check), a Claim and a REPORTED Attestation whose locator is the pinned locator plus fragment. One work per identity (EVI-004). `e2e/test_external_evidence_postgres.py::test_external_evidence_enters_with_source_condition_rights_and_provenance` reads it back from the rows. |
| **condition metadata** | `conditions` + `conditions_schema_version` are required arguments of every admission; the database validates the payload against the registered schema for every writer (EVI-005, unchanged). Same test. |
| **rights metadata** | Every snapshot records `license_class` (SEC-004 vocabulary), licence identifier, rights status and the **retention rule that decided what was kept** (`rtn:external@1.0.0:<rule>`); the kept artifact carries `RightsMetadata`; the attestation's `method` repeats licence class, rights status and retention. |
| **provenance metadata** | Snapshot row (`002c`): requested and canonical locator, requested and resolved ref, repository identity, content hash, artifact id, retrieval time, access-policy reference; the attestation's `method` names snapshot id, artifact id, content hash, resolved ref and retrieval time. The kept bytes are an `EXTERNAL_CONNECTOR` artifact present in the project. |
| **GitHub traces to repo + resolved commit/ref** | `retrieve` resolves any ref to a 40-hex commit, reads the file **at that commit**, and names it in the canonical locator `github:owner/repo@<sha>:<path>`; the record carries the repository's immutable numeric id, requested ref and resolved commit (§22 *GitHub Provenance*). The model and `002c` refuse a code snapshot that is not commit-pinned, whose locator does not name its commit, or that has no repository identity. `integration/test_external_snapshots_postgres.py::test_a_public_repo_is_searched_fetched_pinned_and_its_hash_and_locator_are_stored`. |
| **removing the GitHub provider does not affect core cognition** | `contract/test_external_provider_removal.py`: with GitHub removed the novelty audit still runs and its coverage record says the TECHNICAL_ARTIFACT class was not searched, so a GLOBAL novelty claim needing it is refused by SRC-003's existing rule; the M3 debate runs with no provider at all. `contract/test_external_source_registry.py` holds on the import graph that no `core`, `cognition`, `verification`, `evidence`, `sources` or `ingestion` module imports a provider package, and `unit/test_extension_boundary.py` (unchanged) forbids `core → tool_providers`. |

## 2. §26.1's scope list, item by item

| §26.1 item | Implementation |
|---|---|
| ExternalSourceAdapter registry | `sources/external.py::ConnectorRegistry` — registration checks the adapter against its declaration (provider id, capabilities, `can_snapshot` ⇒ can retrieve, a non-empty trust ceiling, no scientific ceiling for a technical provider, no internal/heuristic ceiling for any external one); `clamp` refuses any record above its provider's ceiling; `router()` returns M1's `SourceRouter`, unchanged, over whatever is registered now. |
| PaperQA-style literature adapter | `tool_providers/literature/corpus.py` — passage-level retrieval ranked by relevance; each record is a citable passage `doi:<doi>@<version>#<passage>` with section, page, venue, year and publication status; PEER_REVIEWED only for peer-reviewed versions, else PREPRINT; licences mapped to SEC-004 classes, unknown never guessed; a version the corpus does not hold is REF_DRIFT, never a substitute. Backed by a fixture corpus. |
| GitHubConnector (public + policy-gated private) | `tool_providers/github/connector.py` over a `GitHubTransport` protocol (`FixtureGitHubTransport` for every recorded test; `HttpGitHubTransport` for the unrun `network` test). Public discovery is always anonymous; private access requires the project's allowlist **and** a resolvable credential (GH-002, §3). |
| progressive enrichment | Discover (metadata only; DISCOVERED events) → snapshot (pinned, rights-governed retention; SNAPSHOTTED / CACHE_HIT / REF_DRIFT) → admit (a separate act; ADMITTED). Each is authorized and recorded. The §6.4 stage an admission may claim is **bounded by what the snapshot kept** — METADATA_ONLY ⇒ Stage A, EXCERPT ⇒ at most B, FULL_CONTENT ⇒ at most C; Stage D is never claimed on admission — in Python and, for rows naming their snapshot, in `002c`. |
| novelty audit boundary | GitHub is prior art for M3's `PriorArtSearch` as a TECHNICAL_ARTIFACT source binding, and nothing else; the audit's coverage record names what was and was not searched, and SRC-003 refuses GLOBAL novelty over an unsearched required class. The novelty auditor reaches providers only through the router, so restricted context is refused by SEC-001's gate before any transport (§22 *Private GitHub Security*). |
| ref-pinned snapshot/cache | `sources/snapshots.py::ExternalSnapshotService` — the pinned locator is the cache key (a second read is a CACHE_HIT, never a copy; a pinned version that re-hashes differently is refused rather than replaced); a moved branch is a new snapshot and a REF_DRIFT event, the old snapshot and its bytes stay re-readable; append-only in SQL. |

## 3. Requirement-by-requirement readiness

| Req | Where it is implemented | Where it is proven |
|---|---|---|
| **GH-001** | `GitHubConnector.search` / `fetch` / `retrieve`; locator grammar; commit pinning; `PinnedContent` refuses a record whose hash is not the hash of the bytes; `ExternalSnapshotService`; `002c` `external_snapshots` | `unit/test_github_connector.py` (7), `unit/test_github_http_transport.py` (7, offline), `unit/test_external_snapshots.py`, `integration/test_external_snapshots_postgres.py` (T-GH-001), `e2e/test_external_evidence_postgres.py` (T-GH-001); `integration/test_github_network.py` — **deselected, not run** |
| **GH-002** | `GitHubAccessPolicy` (authored, versioned, project-scoped, private label never PUBLIC); `_access` (a credential only for an allowlisted repository; allowlisted without a credential refused before any request); anonymous not-found and refused credentials audited by **locator digest and reason code only**; `ConnectorError.audited` so no caller re-logs the locator; discovery always anonymous; `max_sensitivity = PUBLIC` so SEC-001's gate refuses a restricted-context query before the transport; `002c` forbids a refusal row carrying a locator and any event detail carrying a query, text, content, token or credential | `security/test_github_private_access.py` (7, T-GH-002), `integration/test_external_snapshots_postgres.py::test_a_refused_private_request_is_a_durable_audit_row_that_names_nothing_private` |
| **GH-003** | GitHub records are TECHNICAL_ARTIFACT, whatever the repository claims; the registry refuses a scientific ceiling for a technical provider and clamps every record; the snapshot model, `002c` CHECKs and the admission refuse promotion; `002c` refuses a non-REPORTED/INFERRED attestation citing a TECHNICAL_ARTIFACT work or an external snapshot's artifact, and a SOFTWARE_REPOSITORY work labelled PEER_REVIEWED or internal; repo, ref and commit are kept on the snapshot and the attestation | `contract/test_external_source_registry.py`, `unit/test_external_admission.py`, `unit/test_external_snapshots.py`, `e2e/test_external_evidence_postgres.py::test_a_github_record_is_technical_and_cannot_pose_as_measured_or_peer_reviewed` (T-GH-003) |

Normative text M5 also had to honour, without owning the requirement: §6.16's connector failure
policy (structured `ConnectorError` kinds, nothing guessed, SOURCE_UNAVAILABLE with the snapshot
kept — §4.5 below); §17.21's adapter contract (`snapshot(locator_or_record, ref?, policy) ->
ArtifactRef` — §5.1); SEC-001 egress; SEC-003 secret scanning of external bytes; SEC-004's licence
class and its code-generation gate (`snapshots.code_artifact` feeds the existing
`may_enter_generation_context`); EVI-004 one work per identity; EVI-008 status recorded, including
SOURCE_UNAVAILABLE; AGT-008 / SRC-001 provider independence; the §20 risk-register row
*Copyright/rights* (rights metadata + source-specific retention, no blanket fair-use assumption).

## 4. Behaviour worth reading before review

**4.1 What is kept follows the rights, and the row says which rule decided.** `RetentionPolicy`
(`rtn:external@1.0.0`): authorized private material and PERMISSIVE material are kept whole;
COPYLEFT is kept whole for provenance (SEC-004's gate, not retention, keeps it out of
code-generation context); a text source with no reuse licence keeps a 280-character excerpt; code
with no reuse licence keeps **metadata only** — the pinned locator and the hash still identify
exactly what was read. Material failing the secret scan is never stored; the snapshot drops to
METADATA_ONLY with rule `secret-scan-refused`.

**4.2 Private access fails closed, and a refusal names nothing.** A repository is read with a
credential only when the project allowlisted it *and* the credential resolves; a credential is
never presented for anything else, so a deployment token cannot widen what a project reaches.
Every refusal is an ACCESS_REFUSED event with a sha256 of the locator and a reason code
(`NOT_VISIBLE_WITHOUT_AUTHORIZATION`, `PRIVATE_ACCESS_WITHOUT_CREDENTIAL`, `CREDENTIAL_REFUSED`).

**4.3 A provider cannot promote its own records.** Trust ceilings are declared at registration and
enforced on every record by the registry, before storage; the snapshot model and `002c` enforce the
same classes independently. No external provider may declare INTERNAL_RUN, INTERNAL_MEASUREMENT or
EXPERT_HEURISTIC (§6.5; P16 for heuristics).

**4.4 External material is REPORTED.** MEASURED, SIMULATED and OBSERVED are refused for every
external snapshot, with a GH-003 reason for technical material; admission reads the snapshot from
the durable record and refuses a caller-assembled one (`SNAPSHOT_NOT_ON_RECORD`).

**4.5 "Gone" is decided narrowly (§6.16), because SOURCE_UNAVAILABLE sends every conclusion on it
to review.** SOURCE_REMOVED marks every earlier snapshot of the request; a NOT_FOUND at a resolved
version marks only snapshots pinned at that version (a path missing from a branch's new head does
not unmake the commit an earlier snapshot pinned); a NOT_FOUND the connector audited as a refusal
marks earlier *public* snapshots (a deleted public repository is, to an anonymous caller,
indistinguishable from a private one — the change is at the source) but not snapshots read under
authorization (a withdrawn allowlist is the project's decision, not a removal). Marking is by
event; rows and bytes are untouched. **Every SourceWork admitted from a now-unavailable snapshot has
SOURCE_UNAVAILABLE recorded at once**, which `evidence.source_status` maps to NEEDS_HUMAN_REVIEW
for a major revision (EVI-008). A later admission from a kept snapshot of vanished material is
still possible and records the same status.

## 5. Architectural decisions and the interpretations they rest on

**5.1 §17.21's `snapshot` is split into a provider half and a storage half.** `RetrievingAdapter.
retrieve(locator) -> PinnedContent` is the provider's: resolve, pin, read, hash — no storage, no
rights decision, no knowledge of projects beyond its access policy. `ExternalSnapshotService.
snapshot(provider, locator, …) -> ExternalSnapshot` is the platform's: SEC-001 authorization of the
egress, the registry clamp, the cache, the retention decision, the content-addressed artifact, the
provenance row and the lifecycle events. The spec's single signature returns an `ArtifactRef`; the
snapshot record here carries the artifact id plus the provenance §22 requires, so the ref is one
field of a richer answer rather than a different contract. A provider cannot decide what the lab
may keep, and the lab's storage must not depend on which provider is present.

**5.2 The registry wraps M1's router instead of replacing it.** `SourceRouter` (M1, hard-locked) is
unchanged; the registry adds what M5 needs around it — declarations, clamping, removal — and hands
the router the adapters registered at that moment.

**5.3 Placement: `tool_providers/github` and `tool_providers/literature`.** §18's tree lists
`integrations/external_sources/{literature,github}` as the long-term layout; this repository already
places adapters under `tool_providers/` (Lumerical) and M1's router under `sources/`, and the
existing §24.2 boundary tests already forbid `core → tool_providers`. A new top-level package would
have needed a second set of boundary rules for the same property. §18 is informative about layout;
nothing normative depends on the directory name.

**5.4 Patent and web connectors are not built.** §16's narrative roadmap row reads
"GitHub/Literature/Patent/Web 等 connector 擴張", but §16 states it is not a gate and that the formal
exit gate is §26.1 alone, whose M5 row names the literature adapter and the GitHubConnector; §18
marks `patents/` and `web/` as deferred. The registry, retention policy and admission are
provider-neutral — PATENT and WEB trust classes map to their work types — so either is an adapter
and a declaration, with no core change.

**5.5 Literature status is recorded, not decided by the adapter.** The corpus reports a paper's
publication status (e.g. RETRACTED) in record metadata; the admission records the retraction check
it is given (EVI-008) and `evidence.source_status` (M1, unchanged) decides what a status permits.

**5.6 The HTTP transport exists, is tested offline, and was not run live.** Its response mapping
(404/401/403-rate-limit/429/451/URL errors, base64 content, token in the header only) is tested with
`urlopen` stubbed; the live test is `network`-marked and deselected.

## 6. What changed outside the new modules (all additive)

- `core/models/identifiers.py`: id prefixes `xsn` (external snapshot) and `xev` (external source
  event).
- `scripts/migrate.py`: `002c_external_snapshots.sql` appended to `APPLY_ORDER`.
  `tests/postgres_fixtures.py`: the two new tables in `_TABLES`.
- `scripts/mutation_battery.py`: 34 M5 entries appended; no existing entry changed.
- `docs/milestones.yaml`: M5 `DEFERRED` → `IN_PROGRESS`, with the comment stating the mock
  boundary. M4's entry is untouched.
- No M0–M4 source module, migration or test was modified.

New modules: `sources/{errors,external,snapshots,admission}.py`,
`core/models/external_source.py`, `core/repositories/{external_sources,source_works}.py`,
`storage/postgres/external_artifacts.py`, `tool_providers/github/{connector,transport}.py`,
`tool_providers/literature/corpus.py`; fixtures `fixtures/external/{github_fixture,
literature_corpus}.json`.

## 7. Migration

`002c_external_snapshots.sql` (appended last in apply order; in Appendix A's 002 slot because a
snapshot is the provenance of an artifact and the manifestation of a SourceWork):

- `external_snapshots` — cache key UNIQUE (project, provider, canonical locator); CHECKs: sha256
  hash, commit-pinned code with repository identity, technical ⇒ TECHNICAL_ARTIFACT, external trust
  classes only, private ⇒ not PUBLIC; trigger: the kept artifact came from an external connector,
  is present in the project, and equals the recorded hash when the whole content was kept;
  append-only.
- `external_source_events` — ACCESS_REFUSED carries no locator; no detail key carries a payload;
  a named snapshot is in the event's project; append-only.
- `attestations` (additive trigger) — an attestation citing a TECHNICAL_ARTIFACT work or an
  external snapshot's artifact is REPORTED or INFERRED ("GH-003"); an attestation naming its
  snapshot is in that snapshot's project and claims no deeper §6.4 stage than the snapshot kept.
- `source_works` (additive trigger) — a SOFTWARE_REPOSITORY is never PEER_REVIEWED or internal.

Applies cleanly on a fresh database (47 migrations) and is idempotent.

## 8. Adversarial cases tested

- a private repository with no allowlist, allowlisted with no credential, with a refused credential,
  with a working deployment token but no allowlist entry; a withdrawn allowlist after an authorized
  read; a restricted-context query to public code search (refused by SEC-001 before the transport);
  a refusal row carrying a locator; an event detail carrying a query or token;
- a pinned commit that no longer resolves, a ref resolving to a non-commit, a branch moved under a
  cached snapshot, a pinned version that re-hashes differently, a literature version not held;
- a deleted repository (410/451-style), a deleted public repository answering "not found", a file
  missing at a branch's new head; rate limit and network loss (structured, retry-classified, no
  content);
- a file carrying a cloud credential (SEC-003, in memory and through the production scanner);
  unlicensed code, copyleft code, an all-rights-reserved paper;
- a provider declaring a scientific or internal trust ceiling, a provider labelling a record above
  its ceiling, a `can_snapshot` adapter that cannot retrieve, duplicate registration;
- admission as MEASURED / SIMULATED / OBSERVED, from a caller-edited snapshot, without a
  proposition, at a stage the retention cannot support, into a work already on record under
  another trust class; SQL writers forging each of these.

## 9. Verification

At the M5 implementation commit `3361c77c3f3ffe1e4b3864029fd7e1b92f109423` (lineage: `6416adb` M3
hard-lock → `a0b9fcf` M3 sign-off, M4 begins → `241f546` M4 → `457252c` M4 verification record →
`3361c77` M5):

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` (src, tests, scripts) | clean / 365 files formatted |
| `mypy` strict | no issues in 201 source files |
| backend-free suite | 1574 passed, 702 skipped (backend-gated) |
| PostgreSQL suite, freshly migrated database (47 migrations; re-applying is a no-op) | **2274 passed**, 2 skipped (`lumerical`, `network`) |
| M5's own tests | 59 collected across 11 files; 58 run (the `network` one is deselected) |
| M4 root-cause benchmark `--check` (regression, PostgreSQL) | report current |
| mutation battery (PostgreSQL profile on) | **219/219 killed** — the 185 pre-M5 entries still killed; 34 new M5 entries, 1 of them (`sql_sink_secret_scan_skipped`) killed only by a PostgreSQL-gated test |
| `check_requirement_coverage.py` (whole-suite PostgreSQL report) | DONE [M0a, M0b, M1, M2, M3] enforced; M4 and M5 IN_PROGRESS |
| `rebuild_obligation_inventory.py --check` | 84 occurrences, in sync |
| `update_status.py --check` | current; GH-001/002/003 IN_PROGRESS with test files |
| segmentation and debate benchmark reports | current |
| `check_commit_messages.py` | no AI attribution |
| GitHub Actions CI (commit hygiene, spec conformance, lint/types/full suite, PostgreSQL backend) | success, run 36326456910 |
| live GitHub (`network` marker) | **not run** — no external access was attempted |

## 10. M4, observed from M5 (M4 is a provisional baseline here)

**No material M4 defect was discovered.** M5 reuses M4 only at one seam — the e2e test borrows
`SqlEvidenceSink.load_artifact` for the M1 admission gate — and changed no M4 file. The M4 suite,
M4's 31 mutation entries and the M4 benchmark `--check` were re-run as regression at the M5 commit
(§9). The limitations M4's own readiness record discloses (TST-001's licensed replay not performed,
mock backends, a catalog-driven mock model, one rival per check, exact-symptom case memory, no
automatic escalation of INCOMPARABLE authority) are unchanged and are not M5's to repair.

## 11. Remaining risks and deliberately deferred work

- **Every external provider is a fixture.** The connector's behaviour against the real GitHub API
  (pagination, secondary rate limits, large files, the contents API's size limit, LFS, submodules)
  is unexercised; `HttpGitHubTransport` is tested only against stubbed responses.
- **The literature adapter is PaperQA-*style*, not PaperQA.** Ranking is term overlap over a fixture
  corpus; there is no embedding retrieval, no full-text acquisition and no retraction-registry
  lookup — the corpus reports status and the admission records what it is given.
- **Retention is one versioned policy for every project.** A project-specific retention policy
  (e.g. a publisher agreement) would be a new version, not a new mechanism.
- **The §6.4 stage bound in SQL applies to rows that name their snapshot** in `method.snapshot_id`,
  as the admission path writes them; a hand-written attestation that omits the name is bounded
  only by the other `002c` rules.
- **Patent and web connectors are not built** (§5.4).
- **The deleted-public-repository rule rests on an inference**: an anonymous "not found" for
  material this project once read publicly is treated as a change at the source. A repository made
  private by its owner is therefore also marked SOURCE_UNAVAILABLE — which, for a conclusion that
  can no longer be re-checked publicly, is the intended outcome.

## 12. Governance

M5 is `IN_PROGRESS` in `docs/milestones.yaml`; M4 remains `IN_PROGRESS`; the executed-coverage
ratchet enforces neither. M6 was not started. No commit carries AI authorship attribution
(`scripts/check_commit_messages.py`).
