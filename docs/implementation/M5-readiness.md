# M5 — External Evidence Expansion: readiness for independent review

Date: 2026-09-27
Milestone: **M5 — External Evidence Expansion**, `IN_PROGRESS` (was `DEFERRED`) — **READY FOR
INDEPENDENT REVIEW**. The review's P0 (project B consuming project A's access policy, allowlist
or credential) is repaired and accepted (§4.6); the two items the review left open are closed:
snapshots that predate the repair fail closed on upgrade (§4.7), and M5's gate profile is the
normative one, `[postgres]` (§5.7). The implementing agent does not sign off its own work; moving M5
to DONE is the maintainer's act on independent review.
M4: **`IN_PROGRESS`, paused** — externally blocked on TST-001's licensed Lumerical replay (attempted; the
environment has no Lumerical installation, `lumapi`, licence or licensed provider — see
M4-readiness.md §11). M5 was built on M4's final SHA `457252c` as a *provisional baseline*: no M4
file was changed and nothing in M4 was repaired or redesigned. §10 records what M5's work observed
about M4.
M3 and earlier: `DONE` / hard-locked — **no locked behaviour changed** (§6 lists every edit outside
the new modules; all additive).
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`. **No amendment, no ADR, no new Requirement or
Test ID, and no SPEC-ISSUE was raised.** Interpretations the text left open are stated in §5 where
they are made. M6 was not started.

**No external service was contacted.** Every GitHub and literature response in the recorded
verification comes from a deterministic fixture (`fixtures/external/`). The live-GitHub test is
optional -- marked `network`, deselected by default, evidence for no requirement -- and **was not
run**; nothing below claims it was.

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
| **GH-001** | `GitHubConnector.search` / `fetch` / `retrieve`; locator grammar; commit pinning; `PinnedContent` refuses a record whose hash is not the hash of the bytes; `ExternalSnapshotService`; `002c` `external_snapshots` | `unit/test_github_connector.py` (7), `unit/test_github_http_transport.py` (7, offline), `unit/test_external_snapshots.py`, `integration/test_external_snapshots_postgres.py` (T-GH-001), `e2e/test_external_evidence_postgres.py` (T-GH-001). T-GH-001 is fixture-based ("public fixture repo 可 search/fetch"); the optional live check `integration/test_github_network.py` carries no requirement marker and was not run (§5.7) |
| **GH-002** | `GitHubAccessPolicy` (authored, versioned, project-scoped, private label never PUBLIC); **one project's authorization serves no other** — `ExternalAccessScope`, project-scoped registration and lookup, project-bound routers, `retrieve(..., project_id=)` refused first by a connector of another project, credentials resolved per project, the record's scope re-checked before anything is kept, `002d` for every writer (§4.6); `_access` (a credential only for an allowlisted repository; allowlisted without a credential refused before any request); anonymous not-found and refused credentials audited by **locator digest and reason code only**; `ConnectorError.audited` so no caller re-logs the locator; discovery always anonymous; `max_sensitivity = PUBLIC` so SEC-001's gate refuses a restricted-context query before the transport; `002c` forbids a refusal row carrying a locator and any event detail carrying a query, text, content, token or credential | `security/test_github_private_access.py` (7, T-GH-002), `security/test_github_project_scope.py` (10, T-GH-002, cross-project), `integration/test_external_access_scopes_postgres.py` (4, T-GH-002), `integration/test_external_snapshot_quarantine_postgres.py` (3, T-GH-002, upgrade from a real pre-`002d` database), `integration/test_external_snapshots_postgres.py::test_a_refused_private_request_is_a_durable_audit_row_that_names_nothing_private` |
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

**4.6 One project's authorization serves no other (GH-002; the review's P0, repaired).** Before the
repair, a GitHub connector was built for one project's policy but registered deployment-wide, and
nothing bound a request to the project that asked: project B's `snapshot` of project A's allowlisted
private file was served by A's connector with A's token and stored in B under A's policy (reproduced
before the fix; egress approval is per requesting project and never asked whose authorization the
adapter carried). The substitution is now closed at every layer it could pass through, each before
the next step happens:

| Layer | What holds |
|---|---|
| declaration | an adapter that holds an allowlist or can resolve a credential declares an `ExternalAccessScope` (policy ref, project, provider, allowlist; never the secret) |
| registry | a scoped adapter is registered for its own project only — never deployment-wide, never for another project; lookup is by project: its own adapter, else a project-neutral one, never another project's |
| router | `registry.router(project_id=)` returns a `ProjectBoundRouter` (a subclass; M1's router is unchanged) that holds no other project's adapter, refuses to be given one, and refuses a search, fetch or authorization read for any other project |
| service, before egress | a provider present only under other projects' scopes is refused and audited **in the requesting project's log, by digest** (`NO_ACCESS_SCOPE_FOR_PROJECT`); a foreign-scoped adapter is refused even if a registry misroutes one |
| connector | `retrieve(locator, project_id=)` refuses any project but its own FIRST — before parsing, credential resolution or any request (`PROJECT_SCOPE_MISMATCH`, audited in the requesting project) |
| credentials | references resolve in the asking project's namespace only: project B's policy naming project A's reference resolves to nothing (`PRIVATE_ACCESS_WITHOUT_CREDENTIAL`, before any request) |
| M1 fetch path | `fetch(locator)` carries no project, so it is **anonymous only** and can never present a credential |
| service, before storage | the record must say it was read under this project's scope; material read under another scope, or private material from an adapter with no scope, is refused and nothing is kept (`ACCESS_SCOPE_MISMATCH`) |
| store | the scope is recorded before the snapshot naming it; a policy version is bound to one project and allowlist forever (re-pointing refused); the in-memory store refuses a snapshot whose scope is unrecorded or another project's |
| SQL (`002d`) | for every writer: a snapshot naming a scope is in that scope's project and provider; private material names a scope and its repository is on that scope's allowlist; scopes are append-only |

The valid half is tested as carefully as the refusals: two projects that each allowlist the same
private repository and each hold their own credential each read it with **their own token only**
(the fixture host records which token reached it), each snapshot lands in its own project under its
own scope, and neither is visible from, or a cache hit for, the other.

**4.7 Snapshots that predate the repair fail closed on upgrade (`002e`).** `002d` checks new writes
only. A database that ran the vulnerable code can hold rows read for one project under another
project's policy with no scope recorded anywhere, and such a row cannot be told from a legitimate
one by looking at it. So on upgrade every existing snapshot is checked by the **same rule `002d`
applies to new writes**, against the scopes recorded by then, and every row that cannot be proven
coherent is **quarantined** with its reason:

| Legacy row | Result |
|---|---|
| no scope named, PUBLIC material (e.g. a literature passage) | coherent — no authorization was involved |
| no scope named, private material | `PRIVATE_WITHOUT_SCOPE` |
| a scope named that was never recorded (every pre-`002d` GitHub row, until its project re-reads) | `SCOPE_NOT_RECORDED` |
| a scope of another project or provider (the P0 pattern) | `SCOPE_OF_ANOTHER_PROJECT` |
| private material off its scope's allowlist | `NOT_ON_ALLOWLIST` |

A quarantined row stays on record (it is provenance, append-only, re-readable), but it is no longer
trusted anywhere it could be used:

- **cache** — never a cache hit (in Python and SQL); a fresh read under the project's own scope
  supersedes it. The cache key moved from a UNIQUE constraint to a trigger — one TRUSTED row per
  (project, provider, pinned locator), serialised by an advisory lock — because a unique index
  cannot read the quarantine table.
- **admission** — nothing is admitted from it (`SNAPSHOT_QUARANTINED` in Python; a trigger on
  `attestations` for every writer).
- **use** — an attestation admitted from it before the upgrade cannot be cited by a new relation,
  evidence bundle or belief event (triggers on `relation_judgments`, `evidence_bundle_members`,
  `belief_revision_event_attestations`).
- **replay** — `external_quarantined_attestations` / `SqlExternalSourceStore.
  quarantined_attestation_ids` is the §6.18 quarantine selection, so belief events those
  attestations triggered before the upgrade are skipped when the projection is replayed, never kept
  by default.

Quarantine is append-only; any writer may add to it (the fail-safe direction, reason
`QUARANTINED_BY_OPERATOR`), nothing releases a row. The upgrade test builds a real database at the
pre-`002d` state, writes legacy rows the way the old code did (including the P0 pattern and an
attestation admitted from it), applies `002d` and `002e`, and checks all of the above.

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

**5.7 M5's gate profile is `[postgres]`, the normative one.** It was `[postgres, network]` from the
catalog's first version. SAI does not ask for that: T-GH-001 is "public fixture repo 可
search/fetch" and T-GH-002/003 are security and epistemic tests over the same fixtures (§26), and
AGT-007 requires CI to pass offline. A `network` gate the CI job never enables meant the ratchet
could never sign M5 off. The live check stays, optional and unmarked, so it is evidence for no
requirement. `spec/test_ci_workflow.py::test_every_declared_gate_profile_can_be_met_where_the_ratchet_runs`
now checks every milestone's profile — not only DONE ones — against the gates the ratchet's CI job
enables; against the old catalog it fails.

## 6. What changed outside the new modules (all additive)

- `core/models/identifiers.py`: id prefixes `xsn` (external snapshot) and `xev` (external source
  event).
- `scripts/migrate.py`: `002c`, `002d`, `002e` appended to `APPLY_ORDER`.
  `tests/postgres_fixtures.py`: the new tables in `_TABLES`.
- `scripts/mutation_battery.py`: 52 M5 entries appended (34 at `3361c77`, 13 for the P0 repair,
  5 for upgrade safety); no pre-M5 entry changed.
- `tests/spec/test_ci_workflow.py`: one added test (every declared gate profile must be meetable
  where the ratchet runs); nothing existing changed.
- `002e` adds BEFORE INSERT guards to four pre-M5 tables (`attestations`, `relation_judgments`,
  `evidence_bundle_members`, `belief_revision_event_attestations`). They refuse only rows citing
  quarantined external material, which no pre-M5 flow produces; every pre-M5 suite passes
  unchanged.
- `docs/milestones.yaml`: M5 `DEFERRED` → `IN_PROGRESS`, with the comment stating the mock
  boundary and, since the P0 repair, readiness for independent review. M4's entry gained a comment
  recording TST-001's external blocker; its status is unchanged.
- `docs/implementation/M4-readiness.md` §11: the TST-001 licensed-replay attempt and its blockers
  (documentation only; no M4 code changed).
- No M0–M4 source module, migration or test was modified. The P0 repair changed only M5 modules
  and M5 tests (the connector's `retrieve` and the registry's `register`/`adapter`/`router` now
  take the project; one existing `002c` test gives its forged private row a valid scope so the
  CHECK it exercises is still reached after `002d`'s trigger, and asserts the new refusal too).

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

`002d_external_access_scopes.sql` (after `002c`; the P0 repair, §4.6):

- `external_access_scopes` — policy ref (PK), project, provider, declaring actor, private
  allowlist; append-only; the credential is never stored.
- `external_snapshots` (additive trigger) — a snapshot naming a scope is in that scope's project
  and provider; private material names a scope and its repository is on the scope's allowlist. A
  trigger rather than a foreign key, so rows written before `002d` are not re-validated.

`002e_external_snapshot_quarantine.sql` (after `002d`; upgrade safety, §4.7):

- `external_snapshot_quarantine` — snapshot (PK), project (must be the snapshot's), reason code,
  time; append-only; populated at upgrade by `external_snapshot_scope_problem`, `002d`'s rule as a
  function of a row.
- `external_snapshots` — the UNIQUE cache key becomes a trigger admitting one trusted row per key
  (advisory-locked); an index keeps the lookup.
- `external_quarantined_attestations` (view) — the §6.18 selection.
- guards on `attestations`, `relation_judgments`, `evidence_bundle_members`,
  `belief_revision_event_attestations` (§4.7).

All apply cleanly on a fresh database (49 migrations) and are idempotent; `002e` is also exercised
as an upgrade of a database holding legacy rows.

## 8. Adversarial cases tested

- **upgrade**: legacy rows read for B under A's policy, under a scope never recorded, private with
  no scope, private off the allowlist, next to provable ones (a scopeless literature passage, A's
  own read, a row written after `002d`); an attestation admitted from a quarantined row; admitting,
  relating, bundling or triggering a belief event from it afterwards; re-snapshotting a quarantined
  key and duplicating a trusted one; deleting a quarantine; a quarantine naming another project or
  an unknown reason;
- **across projects (the P0)**: project B snapshotting project A's private and public files through
  A's connector; A's connector called directly for B (and with an unparsable locator); A's
  connector registered for B or deployment-wide; B's router given A's connector; A's router asked
  to search, fetch or authorize for B; B's policy naming A's credential reference; a registry that
  misroutes A's connector to B; an adapter that ignores the asked-for project, and one that strips
  the scope from a private record; SQL rows in B naming A's scope, private rows with no scope or
  off the allowlist, a scope re-pointed at another project, UPDATE/DELETE on scopes;
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

**At the closure commit `5876751150fd5120a9a6689830436cdbb43a1676`** — upgrade safety (§4.7) and
the normative gate profile (§5.7). Lineage: `6416adb` M3 hard-lock → `a0b9fcf` M3 sign-off, M4
begins → `241f546` M4 → `457252c` M4 verification record → `3361c77` M5 → `9cf5ba8` verification
record → `26ad26c` P0 repair + TST-001 blocker record → `e9c9dd0` verification record → `5876751`
closure.

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` (src, tests, scripts) | clean / 368 files formatted |
| `mypy` strict | no issues in 201 source files |
| backend-free suite | **1588 passed**, 709 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated database (49 migrations; re-applying is a no-op) | **2295 passed**, 2 skipped (`lumerical`, `network`) |
| `002e` as an upgrade | a database migrated to `002c` with legacy rows, then `002d` + `002e`: exactly the four unprovable rows quarantined, the provable ones kept, every use guard holding |
| M5's own tests | 80 collected across 14 files; 79 run (the optional `network` check is deselected) |
| M4 root-cause benchmark `--check` (regression; M4 untouched) | report current |
| mutation battery (PostgreSQL profile on) | **237/237 killed** — the 185 pre-M5 entries still killed; 52 M5 entries (5 new for upgrade safety, 2 of them killed only by the PostgreSQL upgrade test) |
| `check_requirement_coverage.py` (whole-suite PostgreSQL report) | DONE [M0a, M0b, M1, M2, M3] enforced; M4 and M5 IN_PROGRESS |
| gate profiles | every milestone's declared profile is meetable where the ratchet runs (new spec test; fails against the old catalog) |
| `rebuild_obligation_inventory.py --check`; segmentation and debate benchmark reports | 84 occurrences, in sync; both reports current |
| `update_status.py --check` | current |
| `check_commit_messages.py` | no AI attribution |
| GitHub Actions CI (commit hygiene, spec conformance, lint/types/full suite, PostgreSQL backend incl. the `002e` upgrade test) | success, run 36334962866 |
| live GitHub (`network` marker) | optional; **not run** — no external access was attempted |

Earlier records: `26ad26c` — backend-free 1585, PostgreSQL 2289 on 48 migrations, battery 232/232,
CI run 36330841315; `e9c9dd0` — CI run 36331109992; `3361c77` — backend-free 1574, PostgreSQL 2274
on 47 migrations, battery 219/219, CI run 36326456910.

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
- **Private GitHub access needs one connector per project.** A deployment registers each project's
  own connector (its own policy and credential namespace); a project with none gets public access
  only if a deployment-wide, credential-free connector is registered for it. M1's `fetch` path is
  anonymous only, so private material is read solely through the project-bound snapshot path.
- **Upgrade quarantine is conservative.** Every GitHub snapshot written before `002d` names a
  policy ref no scope row existed for, so it is quarantined unless its project's scope was recorded
  (by a read after `002d`) before `002e` ran. Such material is re-read under the project's own scope
  rather than trusted by default; nothing releases a quarantine.
- **§6.18 replay is where pre-upgrade belief events are excluded.** The quarantine selection is
  provided (`quarantined_attestation_ids`); belief events already in the log stay there (append-only)
  and are skipped by a replay given the selection, as §6.18 prescribes — `002e` does not rewrite
  the log.
- **A changed allowlist is a new policy version.** Scopes are immutable per policy ref, so editing
  an allowlist in place is refused once material has been read under it.
- **The deleted-public-repository rule rests on an inference**: an anonymous "not found" for
  material this project once read publicly is treated as a change at the source. A repository made
  private by its owner is therefore also marked SOURCE_UNAVAILABLE — which, for a conclusion that
  can no longer be re-checked publicly, is the intended outcome.

## 12. Governance

M5 is `IN_PROGRESS` in `docs/milestones.yaml`, gate profile `[postgres]`, and **ready for
independent review**; M4 remains `IN_PROGRESS`, paused and **externally blocked on TST-001**; the executed-coverage ratchet enforces neither.
M6 was not started. No commit carries AI authorship attribution
(`scripts/check_commit_messages.py`).
