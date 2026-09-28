# The research workspace: `lab-brain web`

Date: 2026-09-28
Scope: the first usable web interface over the accepted, hard-locked Product Vertical V1
(`product-vertical.md`). **Not a milestone.** No Requirement or Test ID was added and no milestone
status changed (M0–M3 `DONE`; M4 `IN_PROGRESS`, paused on TST-001; M5 `IN_PROGRESS`). M6 (the
Multi-physics Ring) was not started, no simulation was implemented, and the research workflow was
not changed. It is also not M7's Web Knowledge Inbox or System Health panel (§27.0, `DEFERRED`):
those are different surfaces over IngestionItem/ErrorRecord, and nothing here builds them.

## 1. What a researcher does

```
lab-brain web --actor act:rkuo --artifact-root .\artifacts        # http://127.0.0.1:8765/
```

| Page | What it is |
|---|---|
| `/` | the actor's active projects (as the read gate admits them now) and the episodes the actor opened, with each episode's stored state |
| `/runs/new` | the form: project, goal, measurement / run-record / note files (the trust class each declares, as the CLI flags do), optional verification input, optional literature corpus with a query the actor ticks as PUBLIC, optional symptom / expected / observed, classification |
| `/episodes/<id>` | the episode now (state, reason or outcome, from `research_episodes`), its runs (from `research_runs`), a **Continue** button unless it is COMPLETED or ABANDONED, and the report of the chosen run |
| `/episodes/<id>/runs/<n>/report.md` | that run's report as Markdown, by the CLI's own renderer |

A run is sent with the form and the page comes back when it has finished (seconds here: no model,
no simulator). The report shows every section the CLI prints: stages, inputs and ingestion state,
evidence and sources (internal statements, external literature with rights and status),
competing hypotheses with falsifiers and predictions, debate and critique, belief state with the
governed moves, verification plans, completed actions with Job, Run and outcomes, actions awaiting
a person, **blocked simulation actions** with what they would decide and what they need, the
conclusion, next steps, provenance, and what did not run. A SUSPENDED episode stays on the home
page; **Continue** re-enters it through the accepted continuation path.

## 2. Architecture

```
interfaces/web/app.py     Workspace: a WSGI application (standard library only)
interfaces/web/pages.py   HTML, escaped by construction; the report section renders EpisodeReport
interfaces/web/forms.py   multipart/form-data and urlencoded bodies, size-limited
interfaces/web/__init__   serve(): the standard library's threading WSGI server, loopback only
research/report_store.py  EpisodeReport <-> JSON, and the `012d` store
interfaces/cli.py         `lab-brain web` (a new subcommand; the others are unchanged)
```

**No new dependency and no JavaScript.** The spec prescribes no UI framework (§0.5); the smallest
thing that does the job is the standard library's WSGI server and `email` MIME parser. The browser
receives HTML and forms; the Content-Security-Policy forbids script outright.

**It calls the service; it decides nothing.** A new run is `ResearchEpisodeService.run` with the
request the form describes -- built with the CLI's own trust-class and media-type tables. A
continuation is the same call with `episode_id`, i.e. the accepted continuation path; its refusals
(finished, in progress, not yours) are the service's, shown in its words. The service is not
modified: the workspace learns which research run it made by passing the service a `mint` that
observes the one `research_run` id it mints, and the database checks the pairing (below).

**One account of a run, recorded as returned (`012d_research_run_reports.sql`, 51 migrations).**
The report a run returned is the service's account, assembled from the rows the authorities wrote.
The workspace records it, bound to its run, and shows an episode again from that record -- never
from a second account recomputed in the web layer. §27.1's rule holds: the web is a second renderer
of the same data. The page's report section renders the same `EpisodeReport` field by field (a unit
test walks every field of a fully populated report and finds each on the page), and the Markdown
export is `render_markdown` of it. `012d` refuses a report for a run that is still live, was
INTERRUPTED or FAILED; a report about another episode, project or actor; one whose conclusion is not
the outcome the ledger recorded for the run; one that does not name the run in its provenance; and
any edit or deletion. What an episode *is* now is always read live from the episode and ledger rows.
Runs made from the CLI are listed with their ledger outcome and marked "not recorded in the
workspace" (the CLI printed their report).

## 3. Who, and what they may see

- **One actor per workspace**, named when it is started -- the CLI's `--actor` trust model: whoever
  runs the process is that actor. The browser never names an actor. The server binds to loopback
  only and refuses any other host (`--host 0.0.0.0` exits 2): there is no login, so nothing off this
  machine may reach it. A shared deployment needs an authenticating front end, which this is not.
- **Authorization on every request, on the server.** Projects are those `ScientificReadGate`
  admits the actor to now. An episode is shown, exported or continued only if this actor opened it
  (`012c`'s opening run) and the gate still admits the actor to its project; an unknown id, another
  project's episode and a colleague's episode all get one 404 naming only the id asked for, and a
  lapsed membership hides the actor's own episodes. A stored report's evidence excerpts are
  re-authorized against the actor's **current** clearance each time they are shown (a report is
  kept; a clearance is not); an excerpt the actor may no longer read is withheld, on the page and in
  the Markdown export.
- **Forgery.** Every state-changing request is a POST carrying this process's CSRF token (a fresh
  secret each start) and, when the browser sends one, an Origin of this workspace; every request
  must name an allowed Host (loopback names on the bound port), which also defeats DNS rebinding.
  `Referrer-Policy: same-origin`: under `no-referrer` a browser sends `Origin: null` on the
  workspace's own form posts, which the check refuses -- found by driving the live server from a
  real browser, and fixed.
- **Escaping.** Every dynamic value -- goal, file name, document excerpt, report text -- is escaped
  when it is interpolated; markup exists only in this package's literal templates. Inline `code` and
  `**emphasis**` in report text are applied after escaping.

## 4. Changes outside the new modules

- `migrations/012d_research_run_reports.sql` (new) and its `APPLY_ORDER` entry.
- `interfaces/cli.py`: the `web` subcommand and `run_web`. `research run`, `episode open`, `inbox`
  and `explain` are unchanged.
- `tests/postgres_fixtures.py`: `research_run_reports` in the reset list.
- Nothing in `research/service.py`, `research/continuation.py`, `research/report.py`,
  `research/render.py` or any M0–M5 module changed.

## 5. Verification

End to end on PostgreSQL (`tests/e2e/test_web_workspace_postgres.py`), driven as a browser drives
it -- pages fetched, the CSRF token read from the form, files uploaded as multipart, redirects
followed -- with no simulator anywhere:

| Scenario | What is asserted |
|---|---|
| input -> output, then later | the form opens an episode; it is SUSPENDED on `cap:sp.mesh_sensitivity` with no simulation Job or Run; the page shows the recorded report (`report_html` of it, verbatim) with ingestion READY, the admitted statements, the literature (a RETRACTED paper), every hypothesis, the critique, two CONTRADICTED rivals, every plan, both executed checks with their Runs, the four-point probe awaiting a person, the mesh simulation BLOCKED, the conclusion and the run id in provenance; the Markdown export is `render_markdown` of it. A restarted workspace lists the episode, refuses the old token, shows the same report, and **Continue** makes run 2 of the same episode: continuation section, hypotheses RESUMED, no new hypothesis set, debate, Job or Run, both reports recorded, the episode SUSPENDED again, run 1's report still selectable |
| completed episode | CONFIRMED and COMPLETED; the page is read-only with no form; a continuation request anyway is refused with the service's words (409); nothing written |
| other actors and projects | a member of another project sees neither the project (her lapsed membership included) nor the episode; the episode, an unknown id, the export and a continuation get one 404; a run in the project she is not in is refused ("No research for ..."); a colleague in the same project gets the same 404s; the opener, once lapsed, sees the episode no more; nothing written |
| clearance lost | after the actor's clearance drops to PUBLIC, every INTERNAL excerpt is withheld on the page and in the export |
| hostile input | a file named `<img ...>.md` with `<script>` in its text and goal is shown escaped on every page |
| forged and undeclared | no token, a wrong token, a foreign Origin, a foreign Host; a literature query not declared public, a corpus without a query, an empty goal: refused, nothing written |

`tests/unit/test_web_workspace.py` (13, no database): the report codec round-trips a fully
populated report and refuses what is not one; the web report shows every field of that report; a
report carrying `<script>`/`<img onerror>` in every field produces no markup; forged, foreign-host,
cross-origin, oversized and non-GET/POST requests are refused before a database connection is
opened; the security headers; `lab-brain web` serves as its actor and refuses a non-loopback host.
`tests/integration/test_research_run_reports_postgres.py` (6): `012d` written directly in SQL.

The workspace was also started with `lab-brain web` and driven from a real browser against a demo
database: an episode opened with the CLI was listed, shown and continued from the page.

| Gate | Result |
|---|---|
| ruff / format / mypy strict | clean / 394 files formatted / no issues in 216 source files |
| backend-free suite | 1615 passed, 744 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated (51 migrations, re-apply a no-op) | 2357 passed, 2 skipped (`lumerical`, `network`) -- the accepted 2332 plus 25 new |
| the accepted Product Vertical tests (`test_research_episode_postgres.py`, `test_research_continuation_postgres.py`, `test_research_runs_postgres.py`) | unchanged and passing |
| M4 root-cause benchmark `--check` (regression) | report current |
| coverage ratchet, obligation inventory, status, debate and segmentation benchmark reports | current; M0a-M3 enforced, M4 and M5 IN_PROGRESS |
| mutation battery (PostgreSQL profile on) | **269/269 killed** (258 prior entries still killed; 11 new: host, CSRF and Origin checks, opener binding, lapsed membership, projects through the gate, excerpt re-authorization, the literature declaration, completed episodes read-only, escaping, the report dropping a section). `continuation_scope_ignores_project` now binds a typed parameter, so it is killed by the cross-project test and not by PostgreSQL failing to type `%s IS NOT NULL` |
| commit hygiene | no AI attribution |
