# Scientific Causal Warrant Gate V1.1 — hardening

Status: **implemented on branch `causal-warrant-gate-v1`, not merged, not deployed.** V1 is
`134c07b` (code) / `dc4fc12` (docs). The protected baseline is `41b3cec`.
`READY_FOR_REAL_RESEARCH` stays false. No database outside the development container was written;
the deployment's database was not read for this work. The audit package is
`docs/audit/causal-warrant-gate-v1.1/`; its report names the final commit and every result.
Sections 13-16 were added in the completion pass (2026-10-15): performance, least-privilege
database access, runner identity, and the disputed declaration links.

V1 is described in [`causal-warrant-gate-v1.md`](causal-warrant-gate-v1.md). This record covers
what V1.1 changes and why; where it does not mention something, V1 holds.

---

## 1. What V1 left open

The V1 auditor's verdict was CONDITIONAL PASS, not approved for merge or deployment. V1.1 takes up
the gaps that need no owner decision to close safely:

| # | V1 gap (audit reference) | V1.1 |
|---|---|---|
| G1 | The answering actor was a parameter (`--actor`, `diagnostic_warrant_resolve(…, actor, …)`): anyone with database access answered as the PI (review 8, A2) | answers are signed; §2 |
| G2 | A CONFIRMED row written directly was checked for its trace and warrant references, not for the confirmation rule (review 8, finding 3) | the rule is evaluated in SQL for every writer; §3 |
| G3 | No product path declared a review-queue policy; nothing ran the expiry sweep (review 8, finding 1; V1 §9) | a command, a bootstrap default, and a sweep in every research run; §4 |
| G4 | `fan:30d9407f` stayed CONFIRMED on record, unmarked beyond its derived exclusion | an append-only flag bound to its content; §5 |

Deferred, as the mission requires: DISCRIMINATION reviews, multi-cause conclusions, and showing
declared class names to models. They stay owner decisions (§11).

---

## 2. Who answered: reviewer identity

### 2.1 Why a signature

Every process in this deployment reaches PostgreSQL with one superuser credential
(`compose.yaml`; `deployment.py`: "the operator is whoever holds the database credentials"). The web
workspace has no login. So nothing a database row says about who wrote it can be trusted. Per-person
database roles do not help either: a superuser connection can assume any role.

What can be trusted is a secret the person holds. So an answer is a statement the reviewer signs
with an Ed25519 private key, and it is checked against a public key that a review **authority**
enrolled for that person in that project. The authority's own public key is pinned **outside the
database**, in the file `LAB_BRAIN_REVIEW_AUTHORITIES` names. Whoever can write the database can
write an enrolment row or an answer row. Without the authority's or the reviewer's private key,
neither row verifies.

### 2.2 The records

| record | signed by | over (`core/models/reviewer.py`) | stored in (`012p`) |
|---|---|---|---|
| enrolment | an authority | project, reviewer, reviewer public key, scope, time, authority and its key id | `warrant_reviewer_enrolments` |
| revocation | an authority | enrolment, project, `effective_at`, reason, authority | `warrant_reviewer_revocations` |
| answer (grant) | the reviewer | every field of the grant: review, relation, type, hypothesis, prediction, verdict, reviewer, time, rationale, rivals considered, identity statement, enrolment | `diagnostic_warrant_grants.enrolment_id`, `.signature` |

- Each statement is canonical JSON (the repository's JCS profile) with a domain-separation tag, so
  a signature over one kind of statement never verifies as another.
- An answer cannot be moved onto another link, edited into another answer, or replayed onto
  another review: all of those are inside what was signed.
- Replay, field by field (`tests/unit/test_reviewer_identity.py`):
  - project: inside the statement, and bound again through the enrolment, whose id is inside
    it. A test holds the same person's same key in two projects, also under a store whose
    enrolment ids are per project; the moved answer does not verify;
  - review, grant id, relation, relation type, hypothesis, prediction, verdict, rationale,
    rivals, identity statement, time: inside the statement;
  - kind of statement: the domain-separation tag. The same content signed under another tag
    (a future kind of review) does not verify;
  - authorization scope: the enrolment's scope is authority-signed, the model and `012p` admit
    only `DIAGNOSTIC_WARRANT`, and `verify_grant` refuses any other scope explicitly, so a key
    enrolled for another kind of review, once one exists, never answers a warrant review.
  - decisions: an answer is about one relation. Every stored decision that rests on it
    re-checks it on read (`WarrantResolver.verify`); there is no decision-level signature to
    replay.

### 2.3 Where it is checked

- **On every read that counts an answer** (Python, `security/reviewer_identity.py`):
  - `WarrantResolver._counted`, for new resolutions;
  - `WarrantResolver.verify`, which re-checks a stored decision before it may move a belief;
  - `confirmation_verifier`, before case memory or the miner relies on a conclusion (§3.5).

  An answer that does not verify is **no answer**: it neither warrants nor refuses. The loop notes
  it ("the answer recorded on … counts as no answer: …").
- **At write, the frame** (SQL, `012p`):
  - every new grant carries an enrolment and a signature-shaped value;
  - the enrolment is the answering person's, in that project, and was not revoked;
  - the answer is dated after the enrolment and after the question.

  The unsigned V1 `diagnostic_warrant_resolve` signature is dropped. SQL cannot verify Ed25519, so
  this frame is necessary, not sufficient; the cryptographic check is the Python one.

### 2.4 Independent authorization

- An authority never enrols itself: a CHECK constraint, the model validator, and `verify_enrolment`.
- One key belongs to one person, everywhere.
- An authority key is never a reviewer key.
- A revoked key is never enrolled again.
- V1's separations still hold: the person who ran the episode and the hypothesis's author cannot
  answer.
- **Which role may answer is now whoever an authority enrolled.** That is the owner's choice (V1
  decision 1), made explicit and recorded.

### 2.5 Revocation

`effective_at` is chosen by the authority, at or before the suspected compromise.
- An answer signed at or after it does not verify.
- Once the revocation is recorded, SQL accepts no further answer from that enrolment, whatever
  time the answer claims.
- A conclusion that rested on a now-revoked answer re-checks to unverified and stops being relied on
  (§3.5). The test `test_revoking_a_key_from_before_its_answer_withdraws_the_answer` covers this.

### 2.6 Fail closed

| situation | result |
|---|---|
| no authority configured (the committed `review-authorities.example`) | no answer verifies; DOMAIN warrants still count; anything needing a person waits |
| an answer recorded before 012p (unsigned) | counts as no answer; the deployment holds none (V1 was never deployed) |
| a malformed authorities file | refused at start, not silently treated as "no authority" |

### 2.7 Commands

```
lab-brain review keygen --out pi.key                       # reviewer or authority, own machine
lab-brain review enrol --project P --actor act:authority --reviewer act:pi \
    --public-key <b64> --authority-key authority.key       # authority
lab-brain review resolve RVW --project P --actor act:pi --key pi.key --outcome ... --rationale ...
lab-brain review revoke ENR --project P --actor act:authority --authority-key authority.key --reason ...
lab-brain review keys --project P --actor act:pi           # which enrolments verify here
```

`resolve` refuses before writing anything when the key is not enrolled for `--actor`, is revoked,
or its enrolment does not verify. An encrypted key's passphrase comes from
`LAB_BRAIN_REVIEW_KEY_PASSPHRASE`.

### 2.8 What it does not cover

- **The trust root is the deployment's.** The holder of an authority key can enrol anyone. Whoever
  controls the deployment configuration chooses the authorities. Both are outside a database
  writer's reach, and neither is anything V1.1 can remove.
- **A reviewer's own key is theirs to misuse.** Their answers are attributable, not correct.
- **The episode runner's identity is still self-asserted** (`--actor`, the workspace's single
  actor). An enrolled reviewer who ran an episode under another name could then answer for it. The
  answer would still be signed by them, so this is attributable misconduct, not impersonation.
- **Backdating with a stolen key, before its revocation is recorded**, is possible within the
  window the authority's `effective_at` leaves.
- **`until=` is for routine rotation, not for a compromised authority key.** `enrolled_at` is
  signed by the same key, so whoever holds a retired key can date an enrolment before
  `until`. A compromised authority's line is removed, which withdraws every enrolment it signed.
- **The trust anchor is read per command and per research run** (the CLI before it connects;
  the workspace for each run and each page). A changed authorities file takes effect at the
  next one; no verdict about an answer is cached between reads.

---

## 3. The confirmation rule for every writer

### 3.1 Why in SQL

Every input of the loop's rule (`VerificationLoop.standing`, V1 §2 I6) is recorded:
- belief events and their decisions;
- relations, attestations, observations, runs and jobs;
- grants, enrolments and revocations;
- conflicts;
- the domain's declarations, once they are registered.

So the database can evaluate the rule itself, rather than trust a writer's claim that it held.
`confirmation_rule_breaches(project, episode, candidate)` returns what a CONFIRMED conclusion would
breach. The trigger `failure_analyses_with_the_confirmation_rule_trg` refuses the row unless the
list is empty. Per clause:

| loop (`standing`, `WarrantResolver`) | SQL (`012p`) |
|---|---|
| member state = projected current state | `cwg_state`: the latest event, ordered as `history` |
| DOMAIN warrant: bound class (exact mechanism + whole declaration), outcome's declared effect = relation type | `cwg_bound_class`, `cwg_binds`, `cwg_relation_warrant` |
| REVIEW warrant / refusal; refusal outranks DOMAIN | `cwg_counted_grant` (signed, enrolled, unrevoked at its time), `cwg_relation_warrant` |
| attestations must record the claimed outcome of that observation | `cwg_relation_agrees` |
| class key: bound class, or one person's identity statement on that class's signature | `cwg_member_key` |
| competing support across classes | "competing support" |
| candidate = first SUPPORTED member of the family | "the rule's candidate is …" |
| family holds a warranted refutation | "the candidate's own class hold a warranted refutation" |
| support nobody accountable warranted | "SUPPORTED on support nobody accountable warranted" |
| another declared class's observed signature, predicted or not | "the observed … is the declared signature of …" |
| an outcome the candidate's own class cannot produce | "… an outcome the declared class … cannot produce" |
| a rival affirming the supporting observation (invalidated relations included), unless excluded | "affirm the observation supporting … and nothing warranted excludes them" |
| an unsettled relation that could overturn the conclusion | "a person's answer on … could change whether …" |
| a rival's warranted support held only by a blocking conflict | "hold warranted support blocked only by an open conflict review" |

The trigger also refuses a CONFIRMED row that:
- omits a member of its set from `candidate_causes`;
- cites a warrant that is not a current warrant of the cause's support;
- records a member of a declared class under anything but the class's canonical name.

Every lookup is in the record's project (fixed in the completion pass). `hypotheses` is keyed on
(project_id, hypothesis_id), so another project may hold the same id. The grant trigger's author
check, `cwg_binds`, `cwg_bound_class` and the prediction reads used to look up by id alone;
`012p` now scopes them and restates `012o`'s `relation_judgments_describe_their_observation` the
same way. Two tests failed before the change: a colliding hypothesis elsewhere unbound this
project's hypothesis in SQL (SQL and the loop disagreed), and another blocked this project's run
outright.

### 3.2 The declarations, as the code has them

The rule needs the domain's declarations, and those are code: digest-pinned and reviewed.
`diagnostic_declaration_sets` stores the versions a composition root registers. It is append-only,
and well-formedness and supersession are checked in SQL. `SqlDeclarationSetStore.ensure` is exact:
- a stored version must carry the code's digest;
- a version of one of the code's sets that the code does not declare stops the run.

So a declaration set written into the database by hand never decides what SQL accepts. The research
service and the test harness register before anything is concluded.

### 3.3 Holding two statements to one rule

The rule now has two statements, Python and SQL, and two statements drift. In the PostgreSQL suite
`tests/vertical_fixtures.CheckedLoop` checks, after **every** loop run, that for every member SQL
finds no breach exactly when the loop would confirm that member. This covers:
- the ten benchmark cases under both strategies;
- every counterexample and control in the V1 and V1.1 suites;
- every resumption.

Python changed in one place to match SQL exactly. `_observed_signatures` now reads every declared
signature an observation records, not only the first.

If the database still refuses a confirmation the loop reached, the loop records an OPEN analysis and
says why. It does not crash and it does not conclude more than the record supports.

### 3.4 What SQL cannot check

SQL counts a signed-shaped answer under a matching enrolment; it cannot verify the signature.
- A writer with database access and no keys could write such an answer and then a CONFIRMED row
  that SQL accepts.
- So the readers that rely on a conclusion re-check it (§3.5). The loop itself never counts such
  an answer: the resolver verifies.

### 3.5 Who relies on a conclusion

`FailureStore.trusted_confirmations` is the only source for case memory (`similar_failures`, the
planner's precedents) and for the miner. A CONFIRMED analysis is trusted when:
- it names its warrants (V1);
- it carries no flag (§5);
- every reviewer answer recorded anywhere in its cause's hypothesis set verifies
  (`confirmation_verifier`).

Without a verifier, a conclusion resting on any reviewer answer is not trusted. The episode page
shows each confirmation with its flags and, when nothing relies on it, why not.

Case memory (`similar_failures`) matches the symptom before it re-derives a conclusion: the same
precedents, without re-deriving every confirmation of the project at every planning step (§13).
Every call still re-derives; nothing is cached.

---

## 4. Operations

- **Review queue.** `lab-brain admin review-queue <project> --declared-by <member>` declares a new
  version and deactivates the one it replaces, so items already queued keep their deadlines.
  Defaults:
  - capacity 50;
  - due after 3 days;
  - expires after 14 days;
  - 60 reviewer-minutes per day.

  `declared-by` must be an active person in the project: expiry is their standing decision
  (`v3.3-a15`). `--if-absent` leaves an existing policy alone. The container bootstrap declares one
  for its project, declared by the researcher it configures.
- **Expiry.** Every research run, new or continued, sweeps its project's overdue reviews through
  OPS-002's `ReviewExpiryProcessor` before it verifies. It records a stage when it closed anything.
  An expired warrant question is asked again in the same run. `lab-brain review expire` remains for
  doing it by hand.
- **Deployment.** `compose.yaml` mounts the file `LAB_BRAIN_REVIEW_AUTHORITIES_FILE` names, read-only,
  into every application service. The default is the committed example, which pins no authority.

---

## 5. The recorded false confirmation

`fan:30d9407f-f7ad-4b40-af4c-290edd5cc296` (`epi:7b56877f`) is CONFIRMED on record and wrong (V1 §1).
It is append-only, so it is not edited. `012p` adds `failure_analysis_flags`:
- append-only;
- one flag per kind per analysis;
- each flag bound to the analysis's content digest (`failure_analysis_digest`), so it cannot be
  moved to another row;
- recorded by a person (`act:…`) or a migration carrying an audit finding.

`flag_known_false_confirmations()` runs in the migration. It writes one FALSE_CONFIRMATION flag only
where that exact row exists:
- same id, project, episode and cause;
- same failure class;
- CONFIRMED, with no warrant references.

The statement names the true cause and cites the audit. A deployment without the row gets nothing,
and running it again writes nothing.

A flagged analysis is never trusted (§3.5). The episode page shows the flag beside it.
`lab-brain admin flag-analysis` records further flags.

---

## 6. Behaviour before and after

| situation | V1 | V1.1 |
|---|---|---|
| `diagnostic_warrant_resolve(…, 'act:pi', …)` from any connection | counted: the proxy was confirmed with `--is-class` | the unsigned call does not exist. A row signed with any key but the PI's enrolled one is written and counts as no answer; nothing is promoted or confirmed |
| an enrolment row written without the authority's key | n/a | enrols nobody; `review keys` shows DOES NOT VERIFY |
| two faults, no queue; a CONFIRMED row citing the cause's real warrant | accepted, became a precedent | refused: "the observed DISAGREES is the declared signature of 'length normalization error'" |
| shared PREDICTS, untestable rival; direct CONFIRMED | accepted | refused: "affirm the observation supporting … nothing warranted excludes them" |
| direct CONFIRMED omitting rivals, or renaming a class member | accepted | refused |
| an overdue warrant review | blocked until someone ran `review expire` | closed by the next research run and asked again |
| a project with no queue policy | nobody could be asked | declared by command; the container bootstrap declares one |
| `fan:30d9407f` | CONFIRMED, excluded from reuse by `warrant_refs = '{}'` | additionally flagged FALSE_CONFIRMATION, bound to its content, shown beside it |
| the catalog mechanism on its own check | CONFIRMED (DOMAIN) | unchanged |
| an uncatalogued account, identified by the PI's signed answer | CONFIRMED | unchanged, and trusted for reuse only where the answer verifies |
| ten benchmark cases | 10/10 | unchanged (§8) |

---

## 7. Threats added to V1 §5

| # | threat | V1.1 |
|---|---|---|
| T24 | answering as another person | signature under an authority-enrolled key, verified on every read |
| T25 | minting an enrolment or an authority from the database | authority keys pinned outside the database; enrolments signed |
| T26 | self-authorization, shared keys, authority key as reviewer key | refused in SQL and in verification |
| T27 | a compromised reviewer key | revocation from `effective_at`; no answer accepted once recorded |
| T28 | a CONFIRMED row the record does not support | `confirmation_rule_breaches` for every writer |
| T29 | declarations rewritten in the database | `ensure` refuses rows the code does not declare |
| T30 | a conclusion reused that rests on an answer nobody can verify | `trusted_confirmations` |
| T31 | a stored conclusion known to be wrong | append-only flag bound to its content |
| T32 | a question nobody answers before its deadline | expired by the next research run, asked again |

---

## 8. Migration, compatibility, history

- `012p` is forward-only. No existing row changes, and 63 migrations are declared.
- Upgrade paths, applied to copies of V1 development databases that hold data:
  - 012o → 012p;
  - 012n → 012o → 012p.

  A V1 unsigned grant and the CONFIRMED analysis that rested on it stayed as written. The grant now
  counts as no answer, and the analysis is not trusted for reuse.
- Repeated at the final code (`evidence/migration_upgrade_*.txt`): on copies of the two
  databases, every pre-existing table's rows fingerprint the same before and after, except the
  migrations ledger; a second run applies nothing; the V1 conclusion that rested on the unsigned
  grant is not trusted.
- `012p` changed after review (project scoping, §3.1). It is not deployed; a development
  database that applied an earlier text is recreated, not repaired (its checksum differs).
- The six decisions stored in the deployment still re-derive byte-exact
  (`tests/unit/test_pre_gate_history.py`).
- Prompts, contracts, probes, qualification, BudgetGate and egress are untouched.
- The new runtime dependency is `cryptography` (Ed25519).

---

## 9. Verification

Numbers and logs are in the audit package.
- `tests/unit/test_reviewer_identity.py`: keys, the trust anchor, enrolment, every field of an
  answer, impersonation, revocation, dates, and the resolver.
- `tests/e2e/test_causal_warrant_v1_1_postgres.py`:
  - impersonation (the recorded A2) and forged enrolments;
  - SQL refusals of self-enrolment, shared keys, mislabelled key ids, non-members, edits;
  - revocation, including withdrawal of an earlier answer;
  - the signed control, trusted only where it verifies;
  - direct CONFIRMED rows for each blocking clause, and the accepted control;
  - the queue command, and the expiry sweep in a research run;
  - declaration registry exactness and well-formedness, and `cwg_binds`;
  - the flag: replica, idempotence, exactness, display, exclusion, digest binding, the command.
- The V1 suites run unchanged in substance. Their answers are now signed, and the harness checks
  SQL against the loop after every run.
- The mutation battery now mutates SQL too. A migration entry is applied to a clone of a template
  database, never to the file.
- Completion pass:
  - replay across projects, scopes and statement kinds (§2.2);
  - reuse of a conclusion whose stored history was edited past the triggers (the battery's one
    survivor, now killed);
  - colliding hypothesis ids across projects (§3.1);
  - least-privilege roles (§14), `tests/integration/test_least_privilege_postgres.py`;
  - a randomized differential check of the two rules over 80 multi-fault devices
    (`evidence/rule_agreement_fuzz_*.txt`; implementer-run).

---

## 10. Limitations and residual risks

- Everything in V1 §9 that V1.1 does not name here still holds:
  - the closed world;
  - an untestable PREDICTS rival parks the episode;
  - declarations are trusted;
  - the converse failure is unrepaired;
  - planning follows declared effects;
  - co-occurring causes;
  - no quarantine in the outcome scan;
  - measured falsifiers cannot exclude a rival;
  - invalidated affirmations count.
- §2.8: the trust root, a reviewer's own misuse, the self-asserted runner, backdating within a
  revocation's window.
- SQL counts a signed-shaped answer it cannot verify (§3.4). The loop does not count it, and readers
  re-check.
- **A superuser, or a table's owner, can still disable triggers.** `lab-brain admin db-roles`
  (§14) gives the services a role that cannot; until the deployment connects its services as
  that role, every process still holds the superuser credential. Signatures still do not
  verify for such a writer.
- Case memory re-derives every same-symptom conclusion at every planning step: about 144 ms each
  on the development machine (§13).
- The disputed declaration links stand as declared (§16).
- The Python and SQL rules are held together by the differential check over the scenarios the suite
  runs. A divergence outside those scenarios fails safe in one direction: SQL refuses and the loop
  records OPEN. In the other direction SQL accepts what Python refused, and only `trusted_confirmations`
  and the loop stand between that row and reuse.
- Single-person projects still cannot get a REVIEW warrant. The runner cannot answer, and an
  authority cannot enrol itself. The minimum is now two people: an authority who runs episodes,
  and a reviewer.

## 11. Independent reviews

See the audit package (`docs/audit/causal-warrant-gate-v1.1/reviews/`). Three delegated
executable attacks were stopped by an automated safety check before running anything (reviews
01, 02 and 05); the executable adversarial tests are the implementer's own.

## 12. Decisions for the owner

The audit report (§10 there) keeps the current list. As of this record:

1. Which people hold authority keys, and where the authorities file lives in each deployment.
2. Whether to accept the residual risks in §10.
3. Merge and deployment. Deploying applies `012p`, which flags `fan:30d9407f` in the deployment's
   database.
4. Still open from V1:
   - DISCRIMINATION review;
   - multi-cause conclusion;
   - showing declared class names to models;
   - re-running the governed Gemini cases.

---

## 13. Performance

The completion pass was handed a report that the V1.1 PostgreSQL suites had become about 15x
slower. Measured under matched conditions, they have not (`evidence/performance.txt`):

| measurement | V1 | V1.1 |
|---|---|---|
| CI, whole PostgreSQL profile | 2709 tests, 296.7 s | 2760 tests, 312.5 s (+3.4 % per test) |
| local, benchmark + counterexample + provenance (36 tests) | 182.6 s | 189.5 s |
| local, research-service files (36 tests) | 280.5 s | 298.9 s |
| local, whole suite, both at once | 2712 tests, 1527.8 s | 2770 tests, 1571.6 s |

The 2.6 h run behind the report was not reproduced, and its cause was not established.

What does scale with history is case memory. `similar_failures` runs at every planning step, and
re-deriving one stored conclusion (`research.confirmation`) costs about 144 ms on the development
machine. Before the completion pass it re-derived every confirmation of the project at every
step. It now matches the symptom first (`507770f`), which returns the same precedents. Conclusions
of the SAME symptom are still re-derived each time.

A cache would remove that cost, and none was added, because its key must change whenever any input
of the verdict does:
- the cause's set's belief events and decisions;
- relations of its members, with their attestations, observations and runs;
- grants on those relations, with their enrolments and revocations;
- conflicts and review items of its members;
- flags of the analysis;
- the registered declaration sets;
- the trust anchor and the clock.

A key that misses one of these trusts a revoked answer until the process ends. That is a weakening,
so it waits for a design that can be tested input by input.

## 14. Least-privilege database access

The owner does not approve a production superuser. `lab-brain admin db-roles --app-role
lab_brain_app --reader-role lab_brain_reader`, run as the migrator:
- grants the services' role SELECT, INSERT, UPDATE and DELETE on rows;
- keeps `schema_migrations` read-only for it;
- sets default privileges for tables later migrations create;
- grants the auditors' role SELECT;
- grants no TRUNCATE (it fires no row trigger), no ownership, and no CREATE on `public`.

It refuses a role that could undo this:
- a superuser;
- one that can create roles or databases, replicate, bypass row security, or set
  `session_replication_role`;
- one that owns, or is a member of a role that owns, an object in the database.

`tests/integration/test_least_privilege_postgres.py` creates throwaway login roles and shows:
- a whole diagnosis episode runs as the services' role, with SQL and the loop agreeing;
- every escape is refused: `session_replication_role`, `DISABLE TRIGGER`, `DROP TRIGGER`,
  `TRUNCATE`, new objects, replacing a gate function, the migrations ledger, `SET ROLE`, granting
  itself more;
- the append-only triggers still fire;
- the auditor writes nothing.

Not done, and the deployment's decision:
- creating the roles and their passwords (outside version control);
- connecting `web` and `local-models` as the services' role, with migrations and `admin` kept on
  the migrator credential;
- the compose wiring. It was not changed: testing it would rebuild the shared image tag the running
  deployment uses.

## 15. Who ran an episode (design; not implemented)

The runner is still self-asserted: the workspace's single `--actor`. The separation "the runner
does not warrant" therefore compares labels. The approved signing infrastructure would extend to
it:
- a runner key, enrolled by an authority like a reviewer key;
- a run's statement (episode, ordinal, question digest, inputs, actor, time) signed at start, and
  checked where the separation is checked (`relation.actor_id`).

It needs authentication in the workspace, which has no login today. Until then the separation
holds against honest labels only.

## 16. Disputed declaration links (measured; not applied)

Review 04 disputed several SP declarations. Three of the disputes are about category, not
threshold: the check cannot observe what the link claims.
- `contact_discontinuity` CONTRADICTS: a drawn-layout reading cannot see a fabricated defect.
- `dopant_compensation` CONTRADICTS: a design-file solve cannot see process compensation.
- `mesh_artifact` SUPPORTS: a solver mesh is not the cause of a measured anomaly. The benchmark's
  anomaly is an `INTERNAL_MEASUREMENT`.

`evidence/disputed_links_experiment.txt` withdraws the automatic DOMAIN authority of exactly these
three links, leaving them to a person, and runs the benchmark. Python only; the SQL mirror was not
patched.
- All six legitimate automatic confirmations under `least_cost` stand.
- `mesh-coarse-access` no longer confirms the mesh artefact. It waits for the four-point probe.
- `probe-lab-closed` asks for a fabricated split lot instead of reporting no sufficient action.

Applying it is a declaration version and a benchmark version, with these two expected outcomes
changed. Both need scientific justification, which is the owner's and the domain expert's (the
owner's rule). The other disputes are thresholds or statements: normalization's direction and
size, and "dominates" from a rule-level overlap flag. They need domain knowledge this work does not
invent.
