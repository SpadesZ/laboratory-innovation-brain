# The product vertical: `lab-brain research run`

Date: 2026-09-28
Scope: the first usable input-to-output Laboratory Innovation Brain workflow, built from
capabilities already implemented. **Not a milestone.** No Requirement or Test ID was added, no
milestone status changed (M0–M3 `DONE`/hard-locked; M4 `IN_PROGRESS`, paused on TST-001; M5
`IN_PROGRESS`, implementation approved), and M6 was not started. The real Lumerical environment
was not touched.

## 1. What a user does, and what comes back

```
lab-brain research run --project P --actor A --goal "..." \
    --measurement report.md [--run-record F] [--note F] \
    [--verification-input device.json] \
    [--literature-corpus corpus.json --literature-query "a query you declare public"] \
    --artifact-root DIR [--report report.md]
```

One Markdown report, printed and optionally written, with: the result (CONFIRMED / PROVISIONAL /
INCONCLUSIVE / NOT_REACHED), stage-by-stage status, input status, evidence and sources (internal
statements and external literature with rights and status), the competing hypotheses with their
falsifiers and typed predictions, the debate and critique, the governed belief state of every
rival, the verification plans, the completed actions (Job, Run, outcome, output artifact), the
**pending simulation actions** (blocked, with why and what would unblock them), the actions awaiting
a person, next steps, provenance ids, and an explicit list of what did **not** run.

## 2. Architecture

```
interfaces/cli.py  research run            parse args, open the connection, select the domain's
                                           vertical BY NAME (entry point), print the report
research/service.py ResearchEpisodeService  composes the existing authorities; decides nothing
research/evidence.py StatementAdmitter      verbatim REPORTED statements through M1's admission gate
research/literature.py                      M5's registry + snapshot service + admission, unchanged
research/report.py, render.py               plain data, Markdown presentation
research/vertical.py ProductVertical        what a DomainPack supplies (domain-agnostic contract)
cognition/catalog_reasoner.py               a LOCAL rule-based reasoner behind the model slots
domains/silicon_photonics/product.py        the §25.1 mechanism catalog; the pack as THIS
                                           deployment can run it
```

| Stage | Authority it calls, unchanged |
|---|---|
| authorize | `ScientificReadGate.require_project` — non-members get nothing |
| episode | `IngestionService.open_episode` (§17.3), under an id the service mints |
| continue (`--episode`) | `research.continuation` + `SqlEpisodeStore.resume` (`006b`'s `episode_resume`) + `012c`'s `research_runs` (§8) |
| ingest | `IngestionService.submit` + `ingest` — raw bytes hashed and stored before parsing, one Job and Run per file, Knowledge Inbox item |
| evidence | M1 `admission_gate` — ACL, EVI-010 re-derivation from stored bytes, canonical body; statements are verbatim units, REPORTED, trust class as the user declared |
| external | M5 `ConnectorRegistry`, `ExternalSnapshotService`, `ExternalEvidenceAdmission`; only with a query the actor declares PUBLIC, under an egress policy the actor declares for the run |
| hypotheses | M3 `StructuredDebate` (intent-aware retrieval, positions, the Critic's inverted retrieval over the literature, §8 admission, typed predictions) |
| verification | M4 `VerificationLoop` (least-cost planning, typed tools, Jobs/Runs, evidence admission, governed belief moves, failure analysis) |
| pending | M4 `LeastCostPlanner`, asked over the loop's own final state with the pack's DECLARED descriptors: "what would you choose if every capability could run here?" — reported, never executed, never stored |

**Selecting the pack.** §24.2 forbids orchestration from importing a DomainPack (TID251 enforces
it). The pack exposes `product_vertical`, named in `pyproject.toml` under the
`lab_brain.domain_verticals` entry-point group; `--domain` selects it by name. `research/` imports
no pack and no provider (`tests/unit/test_research_vertical.py`).

## 3. No simulator, and no pretending

`product_vertical` wires a backend for every capability this deployment can execute — the two
solver-free design readers — and marks every SIMULATION capability UNAVAILABLE with the reason
(no licensed Lumerical provider, installation or seat; TST-001, risk R-1). This is §17.24's existing
rule: the planner never selects an UNAVAILABLE capability, so nothing unexecutable is attempted and
nothing is mocked. Cheap checks run normally. When the planner, over the declared descriptors, would
choose a simulation next, the report lists it as **BLOCKED** with what it would decide, its
estimated cost and what would unblock it; the episode is **SUSPENDED** with that reason, so it is
resumed as the same episode when a simulator exists. Measurement and fabrication have no workflow:
the loop stops for a person and the report says which action.

## 4. No language model, and no pretending

No model slot is configured in this deployment. The debate's slots are served by
`CatalogReasoner`: a deterministic reader of the pack's declared mechanism catalog (statements,
falsifiers, typed predictions, and the words that point at or against each mechanism). Its
`ModelSlot` is `rules:sp.rs_anomaly_mechanisms@1.0.0`, provider `local-rules`, reach LOCAL; every
InferenceProvenance row it produces carries that identity and the report states it. It cannot
invent a mechanism the catalog does not declare. The debate gate is reported as advisory because no
calibrated BenchmarkPolicy is active.

## 5. Changes outside the new modules

- `composition.IngestionService.classifier(*, artifact_of_cited_work=None)` — optional, default
  behaviour unchanged. M5's external attestations cite a SourceWork; the fallback resolves them to
  their snapshot artifact so the Critic may be shown literature. The label still comes from the
  read gate's own occurrence loader. Without it classification refused every such bundle.
- `core/repositories/external_sources.SqlExternalSourceStore.snapshot_artifact_of_attestation` —
  the resolver above; never resolves a quarantined snapshot.
- `verification/loop.VerificationLoop.planning_inputs` — a read-only accessor returning the states
  and projected ConditionMatch the loop itself plans from.
- `core/models/identifiers`: `"episode": "epi"`. **A latent defect found by this work:**
  `open_episode` without an explicit id minted the unregistered kind `episode`, so
  `lab-brain episode open` without `--episode` raised. Covered by
  `test_episode_open_mints_its_own_id_when_none_is_given`.
- `interfaces/cli.py`: `--artifact-root` is resolved to an absolute path. **Second latent defect:**
  the local artifact store builds file URIs, which a relative path cannot express, so both
  `episode open` and `research run` failed with a relative artifact root.
- `pyproject.toml`: the `lab_brain.domain_verticals` entry point.
- `scripts/mutation_battery.py`: 7 entries.

## 6. Verification

End to end on PostgreSQL through `cli.main` (`tests/e2e/test_research_episode_postgres.py`): the
coarse-mesh device with a measurement report and the literature corpus — two checks executed as
Jobs with Runs, two rivals CONTRADICTED through authorised TransitionPolicy decisions, no simulation
Job or Run anywhere, `cap:sp.mesh_sensitivity` reported BLOCKED as the best next action, the
four-point probe awaiting a person, the episode SUSPENDED, literature pinned and admitted (a
RETRACTED paper reported as such); the open-via device — CONFIRMED by a cheap check with its Run
and artifact trace, episode COMPLETED; no verification input — the debate still reports,
NOT_REACHED; a non-member — exit 1, no rows; a literature corpus without a declared query — exit 2,
nothing sent. Unit: the reasoner, the SiPh vertical (every simulation blocked with its reason, the
catalog bound to declared outcome spaces), the renderer, the import boundary.

| Gate | Result |
|---|---|
| ruff / format / mypy strict | clean / 381 files formatted / no issues in 210 source files |
| backend-free suite | 1601 passed, 715 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated (49 migrations, re-apply a no-op) | 2314 passed, 2 skipped (`lumerical`, `network`) |
| M4 root-cause benchmark `--check` (regression) | report current |
| mutation battery (PostgreSQL profile on) | **244/244 killed** (237 prior entries still killed; 7 new product entries) |
| coverage ratchet, obligation inventory, status, benchmark reports | current; M0a-M3 enforced, M4 and M5 IN_PROGRESS |
| commit hygiene | no AI attribution |
| GitHub Actions CI at `f81b1492a52e7f81099208ef0c0902f7413382fb` (commit hygiene, spec conformance, lint/types/full suite, PostgreSQL backend) | success, run 36345691524 |

## 7. Limits

- The reasoner is catalog-bound and lexical: good for the declared mechanism classes, blind to any
  other. A language model behind the same slots changes nothing else.
- Statements are verbatim units; nothing extracts quantities or conditions from them, so they
  inform the debate and never move belief — belief moves only on Run-derived evidence.
- External literature here is a local corpus file; the connectors for live providers exist (M5)
  and are not configured.
- One domain (Silicon Photonics, the Rs anomaly class) supplies a vertical today.

## 8. Continuing an episode (`research run --episode`)

Independent review accepted the vertical except for one path: `--episode E` reached
`IngestionService.open_episode`, which is idempotent on the id. A caller could name any existing
episode -- another project's included -- and the run treated it as a fresh episode with that id,
debating again into it. Closed fail-closed as follows.

**A new run always opens a new episode**, under an id the service mints. `--episode` no longer
opens anything: it means *continue*, through `research/continuation.py`, and every refusal below
happens before the first write.

| Rule | Where it is decided | Answer |
|---|---|---|
| a continuation carries no documents, verification input, literature, framing or sensitivity | CLI (exit 2) and the service, before any read | refused |
| the episode must be in the requesting project and opened by the requesting actor | one scoped read of `research_runs` (ordinal 1 is the opener) | an unknown id, another project's episode, a colleague's episode and an episode no research run opened all get **one** sentence (`No episode E to continue for A in P.`), exit 1, nothing written; a non-member gets the project's own `No research for A in P.` |
| a finished episode receives no new run | the service, then `012c`'s trigger | `Episode E is COMPLETED (...)`, exit 1, nothing written |
| one live run per episode | a session advisory lock held for the whole run; `012c`'s partial unique index | `has a research run in progress`, exit 1 |
| a suspended episode resumes through the authoritative lifecycle | `SqlEpisodeStore.resume` (`006b`'s `episode_resume`, row-locked, refuses finished episodes); `012c` refuses a run on an episode that is not gathering evidence, so the resume cannot be skipped | SUSPENDED -> EVIDENCE_GATHERING |
| one reasoning history | the opening run records its hypothesis set once; a continuation loads that debate from the durable record (set, certificates, positions, critiques, bundles) and never debates; `012c` refuses a continuation over another set and a second hypothesis set under the episode | `hypotheses: RESUMED` |
| goal, trace, framing and verification input are the episode's | the opener's row; a differing `--goal`/`--trace` is refused; the input is read back from the artifact store (a different `--artifact-root` is refused before any write) | reused |

**Retry and idempotency.** A run's lease is a PostgreSQL session advisory lock, so it dies with the
process that holds it: the next continuation finds the run still marked live, records it
`INTERRUPTED`, marks any job it left `RUNNING` `FAILED` (`RESEARCH_RUN_INTERRUPTED`: no Run, outcome
unknown, never resumed) and carries on; `episode_resume`'s idempotence on its target state is
exactly this case. Verification jobs keep their meaning across runs: a check an earlier run executed
is excluded from planning (the stored plan names it "executed earlier in this episode"), because a
second Run of it would count as a second independent source; a job an earlier finished run parked
(QUEUED behind a budget, WAITING_RESOURCE behind a seat) is `CANCELLED` as
`SUPERSEDED_BY_CONTINUATION`; and every job a continuation submits is keyed
`vs:<episode>:run<n>:<step>:<capability>`, so no key an earlier run used is returned for a new
submission. Within one run the loop's keys are unchanged -- a retried submission is still the same
job -- and the opening run's keys are exactly the accepted flow's.

**Three defects the adversarial tests found and this change fixes.**

- *Re-dispatching a parked job collides with its own history.* The first design resumed a job an
  earlier run had parked behind a budget as the same job. Its dispatch attempt was already recorded
  under span and cost ids derived from that job, so the retry failed on `execution_spans_pkey`. The
  job is now superseded and the check resubmitted under the continuation's key.
- *A verification error finished the episode.* An exception in the verification loop closed the
  episode `NOT_REACHED`, which made a transient failure final and forbade the retry. The episode is
  now SUSPENDED with the reason, and a continuation retries it (same episode, same hypotheses).
- *M1's `episode open --episode E` handed out another project's episode.* The same idempotent
  `open_episode` returned whatever episode had the id and printed its trace and project before any
  write was refused. `open_episode` now returns an existing episode only for a retry of the same
  open (same project, trace and goal) and otherwise refuses, naming only the id the caller chose.

**Changes.** `migrations/012c_research_runs.sql` (new; 50 migrations) and its `APPLY_ORDER` entry;
`research/continuation.py` (new); `research/service.py` (open vs continue, the ledger, the lease,
the resumed debate, run-scoped jobs, verification errors parked); `research/report.py` and
`render.py` (a Continuation section: which run, resumed from what, over which reasoning, what earlier
runs did); `interfaces/cli.py` (`--goal` required only to open; `--episode` continues; new inputs
with `--episode` exit 2; `episode open` refuses a taken id); `composition.IngestionService
.open_episode` (the retry-only idempotence above); `core/models/identifiers` (`research_run`:
`rrn`). M4's loop, M3's debate and `006b`'s lifecycle are called unchanged.

**Verification.** `tests/integration/test_research_runs_postgres.py` (10) writes `012c`'s rows
directly, as a caller that bypasses the service would, and shows each shortcut refused: another
actor continuing, a run on an episode not resumed through `episode_resume`, a run on a finished
episode, two live runs, a gap in the ordinals, a continuation over another set, a second
hypothesis set under the episode, a run naming another project's episode, a set that is not the
episode's, and any rewrite or delete of the ledger. `tests/e2e/test_research_continuation_postgres.py`
(7) drives `cli.main` and the service, comparing a census of 24 tables before and after every
refusal:

| Scenario | What is asserted |
|---|---|
| foreign and unknown ids | another project's episode (from a member of that other project, and from the opener naming the wrong project), an unknown id, a colleague's episode, an episode M1 opened: one sentence each, identical up to the id; a non-member gets the project's refusal; M1's `episode open` with the foreign id is refused and prints none of it; the census and the episode row unchanged |
| suspended continuation | the same episode id, trace, goal and start; resumed from SUSPENDED through `episode_resume` and parked again on `cap:sp.mesh_sensitivity`; hypothesis sets, hypotheses, positions, critiques, debate records, bundles, inference provenance, belief events, attestations and ingestion items unchanged; no job or Run added; the new plans do not list the two executed checks as candidates and name them "executed earlier in this episode"; a failure analysis appended; the ledger shows runs 1 and 2 by the opener over one set and one input; a third continuation works the same way |
| completed-episode reuse | a CONFIRMED episode and a NOT_REACHED one: exit 1 with the state and outcome, nothing written, one run in the ledger; the service raises `EpisodeFinished` for any caller |
| no new inputs | `--measurement` and `--symptom` with `--episode` exit 2; a different `--goal` or `--trace` is refused; the service refuses documents from a non-CLI caller; nothing written |
| live and interrupted runs | a held lease refuses the continuation; a run that resumed the episode, recorded itself and left a job RUNNING, then lost its connection, is recorded INTERRUPTED and its job FAILED (`RESEARCH_RUN_INTERRUPTED`) by the next continuation, which runs as run 3 |
| parked check | a first run with no wall-clock budget parks its first check (QUEUED) and suspends; the continuation cancels that job as `SUPERSEDED_BY_CONTINUATION`, executes the cheap checks under `vs:<episode>:run2:` keys and CONFIRMS the cause; failure analyses OPEN then CONFIRMED; one hypothesis set |
| verification error | the loop raising parks the episode (SUSPENDED, `verification failed`), and the continuation retries it to CONFIRMED on the same episode and hypotheses |

| Gate | Result |
|---|---|
| ruff / format / mypy strict | clean / 384 files formatted / no issues in 211 source files |
| backend-free suite | 1602 passed, 732 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated (50 migrations, re-apply a no-op) | 2332 passed, 2 skipped (`lumerical`, `network`) -- the 2314 of the accepted vertical plus 18 new |
| the accepted first-run flow | `tests/e2e/test_research_episode_postgres.py` unchanged and passing |
| M4 root-cause benchmark `--check` (regression) | report current |
| coverage ratchet, obligation inventory, status, debate and segmentation benchmark reports | current; M0a-M3 enforced, M4 and M5 IN_PROGRESS |
| mutation battery (PostgreSQL profile on) | **258/258 killed** (244 prior entries still killed; 14 new: project scope, opener binding, lifecycle resume, finished episode, re-debate, executed checks excluded from the loop and from the pending question, run-scoped job keys, parked jobs superseded, interrupted runs recorded, the live-run lease, no new inputs, `open_episode` handing out another episode, a verification error parking the episode) |
| commit hygiene | no AI attribution |
