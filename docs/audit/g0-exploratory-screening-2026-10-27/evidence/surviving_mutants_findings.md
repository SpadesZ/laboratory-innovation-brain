# Mutation battery findings: two problem entries (REPORT.zh-TW.md §3.2)

Repository: /home/user/laboratory-innovation-brain, branch `g0-exploratory-screening`, HEAD `8a04c33`.
Database: `postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_mut` only.
Nothing committed; no file under `src/`, `migrations/` or `scripts/` edited.

Note on the working tree: while this audit ran, another agent was editing the same checkout
(`scripts/migrate.py`, `src/lab_brain/cognition/debate.py`, `roles.py`, `core/models/identifiers.py`, new
`migrations/012y_exploratory_screening.sql`, `src/lab_brain/**/screening.py`). For a few minutes the tree
did not import (`ModuleNotFoundError: lab_brain.cognition.overlap`), and one battery run there reported
both entries as `killed by ERROR tests/e2e/...` -- a **false kill** (collection error). The `_killed()`
helper counts any non-zero pytest exit, including collection errors, as a kill. To get clean results, the
final battery runs used an export of HEAD (`git archive HEAD`) in the scratchpad, with
`PYTHONPATH=<copy>/src:<copy>` and the shared `.venv`; `app.py` and `review_cli.py` in HEAD equal the working tree.

---

## 1. `workspace_episode_ignores_membership` (`src/lab_brain/interfaces/web/app.py`)

### What the guard protects
`Workspace._opened` (app.py ~L2219-2250) is the single gate for `GET /episodes/<id>`,
`POST /episodes/<id>/continue`, `GET .../runs/<n>/report.md` and `GET .../runs/<n>/summary.html`.
It has three layers:
1. SQL: `WHERE r.episode_id = %s AND r.ordinal = 1 AND r.actor_id = %s`. Only the **opener** ever gets a row.
2. The guarded check: `self._gate(c).authorize_project(actor_id, episode.project_id).allowed`
   (`can_access_project`: actor resolvable, `actors.active`, membership present and active).
3. Classification: the latest `research_runs.question_label` must be in `self._cleared(c, project)`.
   `ResearchData.clearance` (src/lab_brain/research/data.py L138-158) returns no labels when the
   membership row is missing or inactive, but it does **not** look at `actors.active`.

### Why the mutant survived
- An actor of another project, or a colleague who did not open the episode, is blocked by layer 1
  (the SQL). The guard is irrelevant to them, so the existing
  `test_another_actor_or_project_sees_nothing_and_writes_nothing` cannot detect it.
- The only existing "lapsed opener" assertion (same test, end) uses an episode whose question is
  classified INTERNAL. With the membership inactive, layer 3 returns `None` anyway. So the guard is never
  the deciding check in any test.

### Consequence if the guard were really absent (verified by experiment)
`scratchpad/probe_ws.py`, with `_opened`'s guard disabled in memory on the live class:

```
member, labelled:                      page 200 goal shown: True excerpt shown: True  | md 200 | summary 200
disabled actor, labelled:              page 200 goal shown: True excerpt shown: False withheld count: 38 | md 200 | summary 200
lapsed member, labelled:               page 404 ...                                 | md 404 | summary 404
lapsed member, unlabelled (pre-012q):  page 200 goal shown: True excerpt shown: False withheld count: 38 | md 200 | summary 200
membership row deleted, unlabelled:    page 200 goal shown: True excerpt shown: False withheld count: 38 | md 200 | summary 200
```
(Unmutated: every case after the first is 404 on all three routes.)

Who could read what: **only the episode's own opener**, and only when
(a) their actor is globally disabled (`actors.active = FALSE`) while the membership stays active (layer 3
still clears the label), or (b) the episode predates 012q (no recorded label) and their membership is
inactive or deleted. They would see the research question/goal, run history, hypotheses, conclusions and
the "recorded since" flags in the read model, plus the Markdown export and the summary document.

Defenses that still hold:
- Evidence excerpts stay withheld: `_authorized` re-checks every excerpt with `authorize_artifact`,
  which runs `can_access_project` first (38 `WITHHELD` markers, excerpt absent from page and Markdown).
- Other actors and other projects: blocked by the SQL opener filter (layer 1).
- Continuing the episode: the research service raises `ScientificReadRefused` and the route maps it to
  404 (code path in `_continue`; not exercised with the guard disabled: **unverified**).
- In accounts mode, `AccountService.suspend` sets `actors.active = FALSE` *and* revokes sessions, and
  `AccountService.session` rejects non-ACTIVE accounts. So case (a) only applies to the single-actor
  workspace (`Workspace(actor_id=...)` without accounts) or to an actor disabled directly in the
  database. Case (b), a membership removed while the account stays active, is reachable in accounts
  mode. There the guard is the only defense for pre-012q episodes.

Severity: **Low-to-Medium**. Disclosure is limited to the opener's own episode, with no evidence
excerpts. It does break revocation, though: a removed member keeps reading research records,
including flags recorded after their removal.

### Test change
`tests/e2e/test_web_workspace_postgres.py`: new
`test_the_opener_reads_their_episode_only_while_the_gate_admits_them`. The opener first reads the page,
report.md and summary.html (200). Then:
(a) actor disabled globally: all three routes 404, the goal does not appear, the 404 page says
"No research <id> for <actor>"; re-enabled: 200 again.
(b) question label nulled past the triggers (same technique as the existing excerpt test), membership
set inactive: all three 404. The DB census is unchanged.
With the guard disabled, the test fails on (a). With (a) skipped, (b) also fails (shown by the probe above).

### Proposed source patch (optional defense in depth; not applied, not tested)
Make the classification layer refuse whenever the gate refuses, so the guard has a second layer:
```diff
--- a/src/lab_brain/interfaces/web/app.py
+++ b/src/lab_brain/interfaces/web/app.py
@@ def _cleared(self, c: Any, project_id: str) -> frozenset[str]:
         """The labels this actor may declare -- and read -- in the project."""
+        if not self._gate(c).authorize_project(actor_id=self._actor, project_id=project_id).allowed:
+            return frozenset()
         held = self._research_data(c).clearance(project_id=project_id, actor_id=self._actor)
```
(or make `ResearchData.clearance` also require `actors.active`). With that patch the battery entry would
still be killed for case (b) (unlabelled episode), so the new test keeps its teeth.

---

## 2. `the_review_rivals_cross_projects` (`src/lab_brain/interfaces/review_cli.py`)

### What the guard is
In `_packet` (review_cli.py L204-214), the rivals query:
```sql
... WHERE p.project_id = %s AND h.hypothesis_set_id = (SELECT hypothesis_set_id
      FROM hypotheses WHERE project_id = %s AND hypothesis_id = %s) AND p.hypothesis_id <> %s
      AND p.observable_ref = %s
```
The mutant drops `project_id = %s` from the scalar subquery.

### Why it flips (root cause, verified)
1. Hypothesis ids are unique per project only. In the test's second phase, `prj:twin` holds the same ids,
   so the mutated subquery returns **2 rows**. The *only* way the mutant can be detected is PostgreSQL
   raising `CardinalityViolation: more than one row returned by a subquery used as an expression`.
2. In the test's fixture **no rival declares anything about the observed observable**: the packet
   prints `rivals       none declares anything about this observable`. The outer side has zero rows.
3. PostgreSQL evaluates a scalar subquery (InitPlan) lazily, only when a row needs it. Whether it is ever
   evaluated depends on the plan, and the plan depends on table statistics (autovacuum/ANALYZE state after
   the TRUNCATE/INSERT churn). Experiment against the post-test DB state:
   ```
   Incremental Sort ... InitPlan 1 (returns $0) -> Seq Scan on hypotheses ...
     -> Merge Join -> Sort -> Seq Scan on predictions p (Filter: hypothesis_id <> ... AND observable_ref = ...)
                   -> Sort -> Index Scan using hypotheses_set_idx on hypotheses h (Index Cond: hypothesis_set_id = $0)
   EXECUTE (real params)                  -> (0 rows), no error
   EXECUTE (outer side made non-empty)    -> ERROR: more than one row returned by a subquery used as an expression
   ```
   The merge join gets no rows from `predictions` and never reads the `hypotheses` side, so the subquery
   never runs. The first in-memory mutant run after a battery run raised `CardinalityViolation` (killed).
   The next 21 runs on the same DB all passed (survived). Three battery runs on unmodified HEAD:
   `[SURVIVED] the_review_rivals_cross_projects` each time. It is not a test-order issue. It is a
   PostgreSQL plan/statistics dependency. Which exact plan produced the kills was not captured (**unverified**).

### Security consequence if the guard were really absent
**No cross-project disclosure is possible.** The outer `p.project_id = %s` and the join
`h.project_id = p.project_id` keep every returned rival in the relation's own project. The subquery
always contains the relation's own hypothesis (the first query in `_packet` joins it in the same
project). So the mutated subquery either returns the own row only (identical output) or ≥2 rows (error).
The only effect is availability: `lab-brain review show` would crash for a relation whose hypothesis id
also exists in another project, provided a rival prediction exists on the observable. The entry's
`guards` text ("rivals are the relation's own project's") overstates the guard. The second layer is the
outer project filter. Severity: **Low** (DoS of one review packet; integrity/confidentiality intact).

### Test change
`tests/e2e/test_causal_warrant_counterexample_postgres.py::test_the_review_packet_reads_only_its_own_projects_records`:
the fixture's contact-discontinuity rival also declares the normalization falsifier
(`sp.normalization_basis = AGREES -> CONTRADICTS`, copied from the fixture). The observation is
`DISAGREES`, so it creates no relation and the single outstanding review is unchanged. The packet now has
a rival on the observable, so the outer side is non-empty under any plan and the ambiguous lookup must be
evaluated. A new assertion requires the line
`rival ... (access contact discontinuity): AGREES CONTRADICTS` in the packet, so the test cannot quietly
go vacuous again. Docstring extended to say why.
Unmutated: 3/3 pass. Mutated in memory: 6/6 fail with `CardinalityViolation`.

### Proposed source patch
None needed for security. Optionally, the battery's `guards` text could say "the rivals lookup is not
ambiguous across projects" rather than claim a cross-project disclosure (scripts/ not edited).

---

## Battery output

Before (shared tree, still clean at that time):
```
[SURVIVED] workspace_episode_ignores_membership
           SURVIVED — tests still pass with the guard disabled
[KILLED ] the_review_rivals_cross_projects
           killed by FAILED tests/e2e/test_causal_warrant_counterexample_postgres.py::test_the_review_packet_reads_only_i
1/2 killed
```
Before (HEAD export, 3 consecutive runs, identical each time):
```
[SURVIVED] workspace_episode_ignores_membership
           SURVIVED — tests still pass with the guard disabled
[SURVIVED] the_review_rivals_cross_projects
           SURVIVED — tests still pass with the guard disabled
```
After (HEAD export + the two edited test files; run 4 times, `2/2 killed` each time):
```
[KILLED ] workspace_episode_ignores_membership
           killed by FAILED tests/e2e/test_web_workspace_postgres.py::test_the_opener_reads_their_episode_only_while_the_
[KILLED ] the_review_rivals_cross_projects
           killed by FAILED tests/e2e/test_causal_warrant_counterexample_postgres.py::test_the_review_packet_reads_only_i
2/2 killed
```
Unmutated, both edited files in full: `36 passed` (shared tree and HEAD export).
`ruff check`: All checks passed. `ruff format --check`: 2 files already formatted.

## Side observation (battery harness, not changed)
`_killed()` treats any non-zero pytest exit (collection ERROR, exit 5 "no tests collected", DB errors)
as a kill, and a skipped test (`postgres_connection` skips if the DB connect times out after 5 s) as a
survival. Both make battery results depend on environment state. Suggest requiring a `FAILED` line for
a kill and treating `skipped`/`ERROR` as "NOT RUN".
