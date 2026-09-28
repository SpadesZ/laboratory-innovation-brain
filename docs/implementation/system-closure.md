# System closure: LLM authority, the local Docker product, local model routes, benchmark preparation

Date: 2026-09-28
Scope: closing the open P0 in Research workspace V2, making the existing product runnable as a local
Docker deployment, using the host's Ollama for lightweight routes, and preparing (not running) a
blind research benchmark. **Not a milestone.** No Requirement or Test ID was added and no milestone
status changed (M0–M3 `DONE`; M4 `IN_PROGRESS`, paused on TST-001; M5 `IN_PROGRESS`). M6 was not
started and no simulation was implemented. The Product Vertical and the Web Workspace behave as
accepted; with no LLM runtime active a run is byte-for-byte the accepted one.

## 1. P0/P1 audit

Method: an independent reading of the V2 control plane and of the path input -> reasoning ->
evidence -> verification -> report/resume, with each suspicion either reproduced or checked against
the code that would have to be wrong for it to be real.

| # | Finding | Class | Resolution |
|---|---|---|---|
| 1 | **Deployment-global LLM control plane.** Any active member of ANY project administered the one global runtime (`_require_researcher` = "a member of something"). The active runtime then manufactured ONE egress policy for EVERY project -- `EgressPolicy(project_id=<any>, mode=RESEARCH, declared_by=<activator>)` -- ignoring the project's own `privacy_mode`. An actor of project A could activate an external route and thereby let project B's evidence leave. Reproduced by the accepted V2 routing test itself: its project is created in the default PRIVATE mode, and its INTERNAL evidence reached an EXTERNAL route. | **P0** | Fixed (section 2). |
| 2 | Configuration writes whose rows name no actor (health checks, probes, unlock, retire, unbind, lifecycle, credential replacement) had no authority check beneath the web gate. | P1 (part of 1) | Every `LLMSettings` step now refuses a non-administrator before anything is written or sent; the database enforces it on every row that names an actor. |
| 3 | The literature stage builds a per-run, PUBLIC-only, single-provider policy in RESEARCH mode regardless of the project's privacy mode. | observation | Not P0/P1: the only literature connector the product can use is a local corpus file ("no network"), so nothing leaves the machine. Recorded; to be revisited if a network provider is ever wired. |
| 4 | The development database was published on every interface (`5433:5432`) with the test suite's public password. | hardening | `compose.dev.yaml` binds it to the host's loopback. |
| 5 | A deployment could be set up only by hand-written SQL (no way to create an actor, project or membership). | product gap | `lab-brain admin ...` (section 3). |
| 6 | Out-of-scope goals: the only installed product vertical diagnoses SiPh series-resistance anomalies; its hypothesis space is that pack's five mechanisms and every hypothesis must predict an outcome in the pack's outcome spaces. A goal outside it is reported honestly (`NOT_REACHED`, the reason in Stages), and with a single short document and no distinct critic model the debate is refused (`CRITIQUE_ROUTE_UNCHANGED`, §7.6). | scope, not a defect | Recorded; it bears directly on the benchmark (`benchmarks/lumi_agent/README.md`). |

Checked and sound: what leaves with a model call is classified from the bundle's own occurrence
rows plus the question's label (no caller can understate it); only a LOCAL-declared route bypasses
the gate, and declaring LOCAL is now administration; stored reports re-authorize every excerpt
against current clearance; the continuation path is unchanged; credentials are references only.

## 2. Two authorities (`012f_llm_authority`)

**Deployment LLM administration.** `llm_administrators`: granted by the operator (`lab-brain admin
llm-admin`) to an active HUMAN actor; revoked, never deleted or rewritten; `llm_is_administrator`
also requires the actor to be active. A trigger on every configuration write that names its actor --
a connection created, a model locked, a slot bound, a runtime created or activated -- refuses anyone
else, whatever wrote the row. `LLMSettings` refuses a non-administrator at every step, including those
whose rows name no actor. The workspace's LLM settings pages answer 403 to anyone else; project
membership grants none of it.

**Project egress authorization.** `project_llm_egress_policies`: a project's OWN versioned,
append-only declaration of which EXTERNAL connections may receive its evidence and under which
labels. Declared only by an active HUMAN member of that project holding the `LLM_EGRESS` approval
scope (a named scope, as `BUDGET_OVERRUN` is), for labels that member is cleared for, never
RESTRICTED_NDA, never in Private Mode, only ENABLED EXTERNAL connections; a withdrawal is a new
version. The workspace page is `/projects/<id>/egress`, answered only to an actor the read gate
admits to the project (others get the unknown-page 404).

**What the gate applies.** For each call, the policy of the project the evidence belongs to, read
when the gate asks: that project's own declaration and privacy mode, narrowed to the routes the
active runtime serves and to the runtime's `external_labels` (the most the administrator lets ANY
project send). No declaration: no policy, and the gate refuses every external call of that project.
Each report states the project egress it was held to (policy id and version, or its absence).

**Upgrade.** A runtime ACTIVE under `012e` was activated under the withdrawn rule: `012f` retires
it. An administrator activates one again.

**LOCAL.** May also be declared of `host.docker.internal` -- in the database, and in the application
only when the workspace is started as the container deployment (`--host-gateway`). Such an endpoint
is always reached directly, never through an environment proxy.

## 3. The local product (`compose.yaml`)

```
docker compose up --build        start; open http://127.0.0.1:8765/
docker compose down              stop; every volume is kept
docker compose down -v           reset: delete the database, artifacts and generated password
```

| Service | What it does |
|---|---|
| `secrets` | once: generates the database password into the `secrets` volume |
| `db` | PostgreSQL 17 + pgvector, internal network only, health-checked |
| `init` | every start: all migrations, then the operator bootstrap (`deployment/docker/bootstrap.sh`): the researcher (HUMAN), their project (created PRIVATE), their membership (configured clearance + `LLM_EGRESS`), their LLM administration -- all through `lab-brain admin`, idempotent |
| `web` | the workspace: `lab-brain web --in-container` listening on the container's interface, published on the HOST's loopback only; `/healthz` health check (Host-checked); `host.docker.internal` mapped to the host gateway |
| `local-models` | every start: `python -m lab_brain.llm_runtime.local_setup` (section 4) |

Security properties kept: no login, so loopback only (`--in-container` is refused wherever a
container runtime has not marked the process); the Host allowlist is the loopback names with the
published port; CSRF and Origin checks unchanged. No secret in any image or committed file: the
image is built from an allowlisted context; the database password is generated per deployment; API
keys come from the git-ignored `deployment/docker/llm-keys.env` and are referenced as `env:NAME`; a
typed-in key is refused (a container has no OS credential store). Persistent data: the named volumes
`lab-brain-workspace_db`, `lab-brain-workspace_artifacts`, `lab-brain-workspace_secrets`.

Operator commands run through the image's entrypoint (which assembles the database URL):
`docker compose run --rm --no-deps init lab-brain admin show|actor|project|member|llm-admin ...`.

## 4. Local model routes (`llm_runtime.local_setup`)

The host's Ollama is one more OpenAI-compatible endpoint (`/v1`): a LOCAL connection named `ollama`,
its models fetched, every untested model probed with the fixed capability probes judged by the typed
parsers, every model that proved CHAT locked with exactly what it proved. No Ollama-specific code, no
second inference path.

Binding policy, deterministic: only the lightweight slots FAST_UTILITY and PRIVATE_LOCAL, in a DRAFT
runtime `local-first`; a slot is bound only when EXACTLY ONE local model proved its requirements --
with several there is no meaningful basis to choose and they are listed for the researcher.
REASONING_PRIMARY and REASONING_ADVERSARIAL are never bound by it (a small local model passing the
role probes is not a reason to reason with it); nothing is activated.

On this machine (Ollama 0.34.4, models on CPU), probed from inside the `local-models` container
through `host.docker.internal` (health REACHABLE, 4 models listed):

| Model | Proved | Not proven | Result |
|---|---|---|---|
| `qwen2.5:7b` | CHAT, STRUCTURED_JSON, ROLE_QUERY, ROLE_HYPOTHESIS, ROLE_SPECIALIST, ROLE_CRITIQUE | CODE (FAILED), VISION (ERROR) | LOCKED |
| `qwen2.5-coder:7b` | CHAT, STRUCTURED_JSON, ROLE_QUERY, ROLE_HYPOTHESIS, ROLE_SPECIALIST, ROLE_CRITIQUE, CODE | VISION (ERROR) | LOCKED |
| `qwen2.5-coder:1.5b-base` | nothing (CHAT timed out; JSON and role probes FAILED) | all | TESTED, not lockable |
| `nomic-embed-text:latest` | nothing (an embedding model: every chat probe ERROR) | all | TESTED, not lockable |

Both 7B models proved FAST_UTILITY's and PRIVATE_LOCAL's requirements, on the slot's own probes
within seconds of each other (CHAT 21.4 s / 22.6 s, STRUCTURED_JSON 8.4 s / 9.9 s, ROLE_QUERY 26.8 s
/ 28.9 s), with the same family, size and quantisation. No meaningful basis to choose: neither is
bound; the draft runtime `local-first` lists both, and the researcher chooses. Both also passed the
role probes a reasoning slot needs -- the workspace offers them for REASONING_PRIMARY, and binding
one there stays the researcher's decision (a hypothesis call took 3-4 minutes on this CPU).

## 5. Benchmark preparation

`benchmarks/lumi_agent/` -- the holdout record, the Phase A problem statement, the Phase B corpus
bootstrap with its search log and snapshots, and the run protocol. See its README.

## 6. Verification

New tests:

| Test | What is asserted |
|---|---|
| `tests/e2e/test_web_llm_authority_postgres.py` (2) | a member who is not an LLM administrator is refused every LLM settings page and action (403) and nothing is written; administrator A of project A activates an EXTERNAL route and authorizes A -- B's run reaches no model (refused by the gate, recorded, said so in B's report), A cannot declare B's egress (404, nothing written), B's member without `LLM_EGRESS` may read and not declare (409, the database's rule), B with the scope declares and only then B's evidence uses the route; B switched to Private Mode by the operator -> refused again at the next call; withdrawn -> refused, the history kept as versions |
| `tests/integration/test_llm_authority_postgres.py` (7) | `012f` held against direct writers: only a current administrator creates a connection, locks, binds, creates or activates (revocation and re-grant; a deactivated person administers nothing); grants only to active persons, revoked once, never deleted; LOCAL of loopback or `host.docker.internal` only; a project declares its own egress and nobody else's, within clearance, only ENABLED EXTERNAL connections, versions in order, append-only, never RESTRICTED_NDA, never in Private Mode (a withdrawal always); every `LLMSettings` step refuses a non-administrator before it writes or sends; `lab-brain admin` idempotent, refusing unknown scopes and labels and a non-person administrator |
| `tests/unit/test_container_deployment.py` (4) | loopback, or 0.0.0.0 only inside a marked container; `host.docker.internal` is this machine only where the deployment says so; the CLI refuses the container flags outside a container; `/healthz` answers only an allowed Host |
| V2 end-to-end and SQL tests | now configure routes as a granted administrator, and declare project egress before sending evidence to an EXTERNAL route; the assertions on routing, provenance, fallback, restart and credentials are unchanged |

Also exercised live: `docker compose up --build` on this machine -- all services up, `web` healthy
on 127.0.0.1:8765 only, an unknown Host refused, the operator bootstrap recorded, the host's Ollama
reached from inside the deployment and probed (section 4), and the LLM settings, draft runtime and
project egress pages checked in a browser.

| Gate | Result |
|---|---|
| ruff / format / mypy strict (CI's scope) | clean / 419 files formatted / no issues in 233 source files |
| backend-free suite | 1640 passed, 771 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated (53 migrations) | 2409 passed, 2 skipped (`lumerical`, `network`) -- the accepted 2396 plus 13 new |
| mutation battery (`scripts/mutation_battery.py`, PostgreSQL) | 293/293 killed -- the accepted 288, 4 re-anchored to the new code, 5 added (project-scoped policy, the project's own privacy mode, every settings step administrative, the container listening rule, the host gateway as LOCAL); no backup left |
| coverage ratchet, obligation inventory, status, root-cause / debate / segmentation benchmark reports | current; M0a-M3 enforced, M4 and M5 IN_PROGRESS |
| M1's T-UX-006 (`test_no_cli_path_can_reach_a_model`) | passing: the operator commands import nothing that can generate |
