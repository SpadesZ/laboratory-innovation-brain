# Research episode page, human-readable view V1

Date: 2026-10-08
Scope: Product/UI only. **Not a milestone.** No Requirement or Test ID was added and no milestone
status changed. Hypothesis and Prediction semantics, falsifier authority, RelationJudgment
creation, TransitionPolicy, BeliefRevisionEvent, planning and ranking, EvidenceAdmission, model
contracts, prompts and probes, qualification, BudgetGate, transport and security are unchanged. No
migration; nothing new is stored. The Lumi Agent benchmark was not run.

## 1. The problem

The episode page showed the stored episode row, a runs table and then the whole `EpisodeReport`
rendered field by field: header, continuation, result, steps, inputs, evidence, literature,
competing hypotheses, debate and critique, belief, verification plans, checks completed, actions
awaiting a person, simulations waiting, next steps, provenance and what ran. It was complete and
auditable, but a researcher had to read most of it, past record ids, hashes and prefixes, to answer
four questions: what was asked, where it stands, what was tested and what that changed.

It also never said what an observed outcome *meant*. The blind episode `epi:08cf92c8...` observed
`sp.normalization_basis = AGREES`, while the normalization hypothesis had designated `DISAGREES ->
CONTRADICTS` as its falsifier. Nothing was related and nothing moved. The report listed the outcome
and the hypothesis states, but a reader had to work out for themselves that the two did not
connect.

## 2. The design

**Three disclosure layers, one page.**

| | before | after |
|---|---|---|
| top | goal, live state, continue form, runs table, technical details | **L1, open**: 1 Question -- 2 Result -- 3 Competing hypotheses -- 4 What was tested -- 5 What was learned -- 6 Next action (continue form here) |
| middle | the full report, every section open | **L2, collapsed**: Evidence and reasoning -- the recorded conclusion, observed facts, declared predictions (observed / not what was observed, naming the observed outcome, in the same OutcomeSpace / not comparable, naming both spaces / not observed yet), model interpretations (positions, critic, alternatives, objections, marked as critique-stage), verification candidates, evidence excerpts, what was not performed with the stage table, next steps as recorded |
| bottom | -- | **L3, collapsed**: Audit and provenance -- the runs table with report and Markdown links, the technical table, every record behind each executed check (with every decision that considered each relation, whether or not an event followed), and the full report exactly as before (`report_html`, unchanged) |

L1 shows no record identifier: capabilities and observables are given by name (`cap:sp.fourpoint_probe`
becomes "fourpoint probe (measurement)"), and each name keeps its id as a hover title. Mechanisms,
states and outcomes are shown as stored and are not translated. No confidence score is shown,
because none is recorded.

**What was learned comes from typed rows only.** `research/episode_view.py` is a read-only read
model. For each verification Run of the episode (the loop's own jobs, selected by the key
`prior_verification` reads, so document ingestion is not counted) it reads:

- the Observation and its Attestation (the outcome space is taken from the attestation's method);
- every typed Prediction the episode's certificates declared over that observable, whether it is
  comparable to the observed outcome (`verification.evidence.comparable`, the rule
  `evidence_from_run` applied), and whether its certificate designates it as the falsifier;
- the RelationJudgments the Observation instantiated;
- for each RelationJudgment, the governed BeliefRevisionEvents it triggered (genesis excluded) with
  their authorising decisions, and the transition decisions whose admitted relations include it.

From these the page says one of the following for each observed outcome:

| the rows say | the page says |
|---|---|
| a relation, and a governed event | "X = O matched M's declared prediction (O -> CONTRADICTS), its machine falsifier." then "M: ACTIVE -> CONTRADICTED, a governed transition (decision: ALLOW)." |
| a relation, a decision that refused | "M: its transition policy decided NEED_HUMAN_REVIEW; its state did not change." |
| a relation, no decision | "M: no governed transition is recorded for this relation." |
| a comparable prediction, no relation | "... is comparable to M's declared prediction, but no relation is recorded for it." |
| predictions over X, none comparable | "X = O matched no declared prediction, so it neither supports nor contradicts any hypothesis, and no belief could move." then each declared prediction, with its designation; one in another OutcomeSpace id or version, or against an observation that does not record its space, is marked "so not comparable" |
| no prediction over X | "No hypothesis declared a prediction about X; the result is on record and moves nothing." |
| no observation | "The stored records do not say what this result meant for the hypotheses." |

No relationship is inferred from an outcome's name or from report prose, and no report string is
parsed. The count "N governed belief change(s) happened in this run" is the number of governed
events this run's own checks caused. A relation is not counted, and neither is a genesis
admission or an earlier run's move.

**Per hypothesis** the card shows its designated typed falsifiers ("Would be refuted if X = O --
the machine falsifier verification adjudicates"). When the episode's certificates are not readable,
it shows the report's recorded rendering. When neither exists, as in episodes from before typed
falsifiers, it shows "No machine falsifier is recorded". Below that comes the author's prose,
labelled "not adjudicated". Critic objections are counted in L1 as critique, not belief changes,
and listed in L2.

**What was tested** separates four groups:

- checks executed in this run, from the report's `completed`, with the observed outcome;
- checks executed in earlier runs, shown as such and not repeated (a Run that started before the
  shown run began and is not one of its own);
- checks a plan chose that have no workflow, which are a person's act (the plan's typed `chosen`,
  minus completed and blocked);
- checks that cannot run in this deployment (`pending`).

**Next action** gives the best next check with its blocker and what it would decide, other blocked
checks, what a person can do now, and the continue form, or the read-only notice.

**History and continuation.** `HypothesisLine.machine_falsifiers` and the continuation section are
read only when present. A report without them renders without a substitute, and a run with no
recorded report says that what it tested is not known. A continued run says "Run n continued this
research from where it stopped; it did not start over", and links the other recorded runs.

**Unchanged.** `report_html`, `render_markdown`, the report store and its decoding, the
`/episodes/<id>/runs/<n>/report.md` export, project authorisation (the view is read in the
episode's own project after `_opened` has authorised the actor), the CSP and escaping (every value
passes through `h`/`e`), and both locales (every new message exists in English and 繁體中文).

## 3. Tests

- `tests/unit/test_episode_view_page.py` (synthetic report and read model): L1 order and closed
  layers; no identifier in L1, and every record plus the unchanged full report in L3; each row of
  the table above; designated and supporting predictions kept apart; executed, earlier,
  person-only and blocked checks separated; a historical report and no report; a continuation
  showing run 1's checks as earlier and counting nothing twice; i18n completeness and zh-TW
  headings; hostile strings escaped everywhere.
- `tests/e2e/test_web_episode_view_postgres.py` (real records, through the web workspace and
  PostgreSQL, with the model stand-in):
  - every executed check and every governed move on the page matches the rows, record for record;
    each card names exactly its designated falsifiers;
  - with the deployed local model's certificate shape (`FakeProvider(inverted_falsifier=True)`:
    only designated falsifiers, each on another outcome), AGREES matches nothing, nothing moves
    because of it, and the page says so;
  - a run without verification input says where it stopped;
  - a continuation shows run 1's checks as earlier ones and counts none of their moves.
- Existing web tests changed only where they pinned the old page surface:
  - the waiting reason in L1 names the check ("(mesh sensitivity)"), and the stored
    `awaiting simulator for cap:...` is still asserted in the technical details;
  - a withheld excerpt is now counted twice, once in L2 and once in the full report, and the
    excerpt itself still never appears;
  - the zh-TW vocabulary check treats the two collapsed layers as it already treated the technical
    details.

  "Research task" above the question and the "Research report -- run n" heading of the full
  report are kept, so those assertions are unchanged.
- Ten mutation entries: matching by observable only; document ingestion counted as a check; every
  prediction treated as designated, in the read model and on the card; a later run's checks listed
  as earlier; an executed check offered to a person; a relation counted as a belief change; a
  refused decision shown as none; "no root cause confirmed" dropped for an open question; a
  prediction a check observed otherwise shown as not observed yet. The
  genesis filter (`from_state IS NOT NULL`) has no entry: no stored genesis event carries a
  relation, so removing it changes nothing observable (an equivalent mutant). It stays as a
  fail-closed guard.

## 4. Verification

Code: `9f877a2` (the view) and `c38d5ff` (a prediction observed otherwise is no longer shown as
pending -- found on the deployed blind episode's L2). CI runs `37718648412` and `37721090716`:
commit hygiene, spec conformance, lint/types/full suite and the PostgreSQL backend profile, all
green. `src` changed only in `interfaces/web` (`pages`, `i18n`, `app`) and the new read-only
`research/episode_view.py`; no migration, and `verification`, `cognition`, `llm_runtime`, the
models, TransitionPolicy, planning, the report and its store are untouched.

| Run (at `c38d5ff`) | Passed | Skipped |
|---|---|---|
| local, Windows: `pytest -q` | 1757 | 848 backend-gated |
| local, fresh database (61 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2603 | 2: 1 Lumerical, 1 network |

ruff, ruff format and strict mypy (238 source files) clean; status, obligation inventory and
requirement coverage current; the evidence, debate and root-cause (`--disposable`) benchmark
reports current and unchanged. Mutation battery, every entry on a fresh database: **436/436
killed**, no anchor missing.

## 5. Deployed, and the real episodes

`docker compose -p lab-brain-workspace up --build -d` from `c38d5ff`; `local-models` changed
nothing ("an LLM runtime is ACTIVE"), `local-typed-falsifier` stayed applied, and the qualification
digest is unchanged, so nothing was re-tested. Each page below was read from
`http://127.0.0.1:8765/episodes/<id>`: no identifier in L1, and both layers closed.

- **`epi:08cf92c8...`** (latest blind episode, SUSPENDED):
  - Result: PROVISIONAL, no root cause confirmed, ACTIVE 5.
  - Each card shows its designated falsifier and the prose, labelled.
  - Tested: extraction consistency, executed, observed normalization basis = AGREES.
  - Learned: "matched no declared prediction, so it neither supports nor contradicts any
    hypothesis, and no belief could move", with NORMALIZATION_BASIS_ISSUE: DISAGREES -> CONTRADICTS,
    its machine falsifier. Then "No governed belief change happened in this run."
  - Next: charge ac sweep, simulation, cannot run here (no Lumerical seat), and what it would
    decide; charge dc sweep also blocked; "A person can act now: fourpoint probe (measurement)".
  - L2 shows the falsifier as "not what was observed: the check observed AGREES" and the other
    four as not observed yet.
- **`epi:4d4c9488...`** (`prj:lab`, SUSPENDED, from before typed falsifiers):
  - Learned:
    - extraction consistency AGREES matched length normalization error's declared prediction:
      ACTIVE -> CONTRADICTED (decision: ALLOW);
    - inspect contact connectivity CONTINUOUS matched access contact discontinuity's prediction:
      ACTIVE -> CONTRADICTED (decision: ALLOW);
    - "2 governed belief change(s)".
  - Cards: "No machine falsifier is recorded", nothing substituted.
  - Next: mesh sensitivity, blocked.
- **`epi:226036fa...`** (COMPLETED / NOT_REACHED): "Not reached -- the research stopped before
  verification", "It stopped at the hypotheses step (FAILED)", no hypothesis admitted, nothing
  executed, nothing could move, read-only.
- **`epi:500ca3b7...` run 2** (a continuation): "Run 2 continued this research from where it
  stopped; it did not start over", with a link to run 1. Nothing was executed in run 2.

The audit layer of `08cf92c8` and `4d4c9488` contains every run, observation, attestation,
relation and event id the database holds for their checks (3/3 and 10/10).

Viewing, rebuilding and `local-models` wrote no scientific row. Since the previous commit
(`32a4373`, 2026-10-07 18:39 UTC), the newest research episode, run, hypothesis, belief event,
observation, plan, job, Run and report all date from the blind run that ended at 18:34 UTC. The
counts:

| episodes | runs | hypotheses | relations | belief events | decisions | observations | attestations | plans | jobs | Runs | provenance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 9 | 10 | 30 | 2 | 32 | 2 | 5 | 166 | 10 | 8 | 8 | 48 |

Not a HARD-LOCK: independent review is required. READY_FOR_REAL_RESEARCH stays false.

## 6. Independent review follow-up

The review confirmed the commits, CI, the read-only architecture and the layers, and blocked on
two presentation-correctness findings. Both are fixed inside this slice. Nothing in the scientific
core, schema or persistence changed.

- **Every recorded decision is auditable.** L3 used to list a decision only through the event it
  authorised. A RelationJudgment the policy considered and refused (NEED_HUMAN_REVIEW, DENY, ...)
  therefore showed no decision. The records table now lists every decision that considered each
  relation -- id, result, policy, subject and states -- whether or not an event followed.
- **OutcomeSpace identity is respected.** L2 read every unmatched prediction as "another outcome
  was observed", but `comparable` also rejects another OutcomeSpace id or version. The read model
  now splits by `comparable` itself:
  - matched;
  - same space, another outcome: comparable were the observed outcome the predicted one;
  - not comparable: another space or version, or an observation that does not record its space.

  L2 names both spaces for a prediction that is not comparable and infers nothing; L1 marks it
  "not comparable"; "not observed yet" is kept for what no check observed. The latest blind
  episode's DISAGREES against an observed AGREES, in `os:sp.normalization_basis@1.0.0` on both
  sides, is the same-space case.

Tests:

- Unit:
  - a decision without a transition shown in full in L3;
  - the split over real typed predictions: the same outcome string in another version, another
    space, an unrecorded space, and the blind episode's AGREES against DISAGREES;
  - the L1 and L2 wording for a different and an unknown space.
- PostgreSQL, over a real web research run:
  - a refusal recorded through the governed path (`BeliefEpisode.attempt_transition` with the
    pack's comparators, the registered rejection policy asked about the hypothesis the run
    SUPPORTED) is a DENY with no event, and appears in full in L3; L1's count of belief changes is
    unchanged;
  - on the deployed model's certificate shape, the read model and L2 classify AGREES against
    DISAGREES as the same space, another outcome.
- Four mutation entries (another space read as another outcome; the L1 and L2 not-comparable
  readings dropped; a decision without a transition omitted from L3), all killed. The PostgreSQL
  regressions alone also kill the omission and the observable-only match. The observable-only entry
  moved with its code.

At this point: `pytest -q` 1760 passed and 848 skipped; on a fresh database 2606 passed and 2
skipped; ruff, ruff format and strict mypy clean. The three real episodes were rendered from the
deployed database with this code. Their L1 is unchanged; `08cf92c8`'s L2 still reads "not what was
observed: the check observed AGREES"; `4d4c9488`'s L3 lists both of its ALLOW decisions in full.
