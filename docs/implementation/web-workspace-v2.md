# Research workspace V2: navigation, language, and configurable language-model routes

Date: 2026-09-28
Scope: usability and configurable real-LLM operation over the accepted Product Vertical and Web
Workspace. **Not a milestone.** No Requirement or Test ID was added and no milestone status changed
(M0–M3 `DONE`; M4 `IN_PROGRESS`, paused on TST-001; M5 `IN_PROGRESS`). M6 was not started, no
simulation was implemented, and the research workflow is unchanged: with no LLM runtime active a run
is byte-for-byte the accepted one.

## 1. What a researcher sees

A stable header on every page: **Episodes · New research run · LLM settings · Runtime**, the actor,
and a language switch (**English / 繁體中文**).

**Language.** The switch is a CSRF-protected form that sets one per-browser cookie (`lb_locale`,
`HttpOnly`, `SameSite=Strict`) and returns to the same page (only ever a path of this workspace).
Only the interface is translated: headings, labels, buttons and the workspace's own sentences. A
report's statements, evidence excerpts, stage details, conclusions, the research service's refusals,
every identifier and every enum value are shown exactly as stored in either language, and the
Markdown export is identical in both. The interface language is not the research-output language:
reports are written in English (`i18n.RESEARCH_OUTPUT_LANGUAGE`) whatever the interface says. The
server's readiness sentences (below) are rule text: the pages compose localized statements from the
structured readiness and keep the server's own English sentences in the technical details (§5).

**LLM settings** follow one workflow, and each step is a server-side action:

```
Connection -> Fetch/declare model -> Capability test -> Lock -> Slot binding -> Runtime readiness -> Activate
```

| Step | What happens |
|---|---|
| Connection | an OpenAI-compatible endpoint (OpenAI, OpenRouter, vLLM, LM Studio, Ollama's `/v1`), its declared reach, and a credential REFERENCE. LOCAL may be declared only of 127.0.0.1 / localhost / [::1]; a URL with credentials, a query or a fragment is refused |
| Fetch / declare | `/models` is listed (and recorded as a health check), or a model name is declared |
| Capability test | fixed, synthetic probes -- no project data -- judged by code (below) |
| Lock | freezes exactly the capabilities whose latest probe PASSED, and a route fingerprint `lk:…` |
| Slot binding | a draft runtime binds LogicalSlots to locked models; each slot offers only models that proved what its roles need, and says why the others are not eligible |
| Runtime readiness | slot by slot: model, connection, reach, route, the roles the router sends there, blockers; the Critic's route; egress. "Check readiness now" runs live health checks first |
| Activate | only with no blocker, checked live; the previous active runtime is retired; **Deactivate** returns new research to the catalog reasoner |

**Runtime** shows the active runtime's readiness, or says plainly that none is active and the local
catalog reasoner serves every slot.

## 2. The contract that is not changed

`CognitiveRole -> LogicalSlot -> ModelSlot`. The role-to-slot table is the router's own
(`cognition.routing`); the settings page shows it read-only, derived through the router's public API
so it cannot drift, with the Critic's fallback to REASONING_PRIMARY. An operator configures only
which locked model serves each slot: REASONING_PRIMARY and FAST_UTILITY (M3's minimum route, with
EMBEDDING as the built-in local embedder), and optionally REASONING_ADVERSARIAL, PRIVATE_LOCAL (a
LOCAL connection only), CODE and VISION. Slots no role routes to in this version are shown as
"configured; no role routes to this slot".

## 3. One inference path

The research service gains one optional argument, `reasoning: ReasoningRuntime | None`
(`research/reasoning.py`). `ScientificLLM` is built from it or -- when it is `None` -- exactly as
before from the catalog reasoner (the explicit fallback):

| | no runtime (fallback) | active runtime |
|---|---|---|
| `ModelSlot`s | `rules:<catalog>`, provider `local-rules`, LOCAL | model name, route `lk:…` as `model_version`, provider = connection name, declared reach |
| `Completion` | `CatalogReasoner` | `RouteCompletion`: the slot's model over HTTP, with the role's response contract |
| `ModelRouter` | PRIMARY / FAST / EMBEDDING | the bound slots + EMBEDDING |
| budget gate | unchanged | unchanged (declared token counts, every call a span) |
| egress gate | no policy (every slot LOCAL) | the runtime's policy for its EXTERNAL providers and permitted labels, AND the actor's clearance; RESTRICTED_NDA never leaves |
| typed role parsers, admission, `InferenceProvenance` | unchanged | unchanged |

The report says which reasoned: the debate's reasoner line is read from the recorded
`InferenceProvenance` (so a continuation names the reasoner that produced its reused debate), and the
deployment section lists the runtime's routes, the Critic's route and the egress declaration.

**Response contracts** (`llm_runtime/contracts.py`). M3's role prompts end "Reply with JSON." -- not
enough for a general model to produce what the typed parsers accept. M3's prompts are hard-locked,
so a language-model route carries a fixed system message per role giving the JSON shape its parser
reads, generated from the parsers' own enums. It carries no project data; it is versioned and
hashed, and the hash is part of the lock fingerprint every inference records as `model_version`.
The role probes send the same contracts, so a model is bindable only if, so told, it actually
produces output the parsers accept.

**Capability probes** (`llm_runtime/probes.py`): CHAT (the word asked for), STRUCTURED_JSON (bare
JSON, exactly the object), ROLE_QUERY / ROLE_HYPOTHESIS / ROLE_SPECIALIST / ROLE_CRITIQUE (the real
M3 templates and rendered CONTEXT, judged by the real `parse_*` functions), CODE (parsed with `ast`,
never executed), VISION (a generated PNG). Each slot requires: PRIMARY -- CHAT, STRUCTURED_JSON,
ROLE_HYPOTHESIS, ROLE_SPECIALIST; FAST -- CHAT, STRUCTURED_JSON, ROLE_QUERY; ADVERSARIAL -- CHAT,
STRUCTURED_JSON, ROLE_CRITIQUE; PRIVATE_LOCAL -- CHAT, STRUCTURED_JSON; CODE -- CHAT, CODE; VISION --
CHAT, VISION. With ADVERSARIAL unbound, PRIMARY's model must also prove ROLE_CRITIQUE (the Critic
falls back to it). A probe stores its outcome, latency, a redacted reason and the SHA-256 of the
answer, not the answer.

**Honest routes.** An unbound REASONING_ADVERSARIAL is **FALLBACK** -- "the Adversarial Critic runs
on REASONING_PRIMARY (model). That is NOT model-route independence: the critique's independence
rests on the inverted evidence path alone". The runtime page and Runtime say so in the interface
language ("Uses primary reasoning", "NOT an independent model route" / 「改由主要推理執行」、「不是獨立的
模型路由」), with the server's sentence in the technical details; every report it reasons carries the
server's sentence; the critique's provenance records REASONING_PRIMARY. An ADVERSARIAL slot bound
to the same model as PRIMARY is shown as a separate slot but NOT an independent model route.

**Fail closed.** With a runtime active and unusable (a credential no longer readable), a new run is
refused with the reason before anything is written -- never silently reasoned by the fallback.

## 4. Credentials and configuration state

- **Never stored, never shown.** The database holds `secret_ref` (`env:NAME`, or
  `wincred:lab-brain/llm/<uuid>` -- Windows Credential Manager, protected by the OS per user) and a
  fingerprint `****abcd` (HMAC-SHA256 under a per-deployment salt; no character of the key). A key
  pasted as a reference is refused; a typed-in key is written only to the OS store and **fails
  closed** where there is none (any platform but Windows in this version) -- the operator is told to
  use an environment variable. Credential inputs are password fields never filled back in. Every
  provider message -- some echo the key they were sent -- is redacted before it is recorded or shown.
  The database refuses a reference that is not one, a URL with credentials, and a reference without a
  fingerprint.
- **Configuration is not health.** A connection's lifecycle (ENABLED / DISABLED / RETIRED) is what the
  operator decided; health (REACHABLE / AUTH_FAILED / UNREACHABLE / PROTOCOL_ERROR /
  SECRET_UNAVAILABLE) is an append-only log of what the endpoint answered, and never changes the
  lifecycle. Readiness requires the latest check of every bound connection to be REACHABLE.

## 5. Names researchers read (`interfaces/web/labels.py`)

The Runtime and LLM settings pages do not ask researchers to read routing identifiers. One mapping
gives every canonical ID a localized name and a one-line purpose:

| ID | English | 繁體中文 |
|---|---|---|
| `REASONING_PRIMARY` | Primary reasoning | 主要推理 |
| `FAST_UTILITY` | Fast assistance | 快速輔助 |
| `REASONING_ADVERSARIAL` | Independent critique | 獨立批判 |
| `PRIVATE_LOCAL` | Private local model | 本機私有模型 |
| `CODE` | Code and computation | 程式與運算 |
| `VISION` | Image understanding | 圖像理解 |
| `EMBEDDING` | Semantic embedding | 語意向量 |
| `SUPERVISOR` | Research orchestration | 研究流程統籌 |
| `HYPOTHESIS_ENGINE` | Hypothesis generation and comparison | 假說產生與比較 |
| `VERIFICATION_PLANNER` | Verification planning | 驗證規劃 |
| `NOVELTY_AUDITOR` | Novelty and prior-work check | 創新性／先前研究檢查 |
| `DOMAIN_SPECIALIST` | Domain specialists | 領域專家 |
| `EVIDENCE_RESEARCHER` | Evidence and data search | 證據與資料搜尋 |
| `ADVERSARIAL_CRITIC` | Adversarial review | 反方審查 |

and the capabilities as what a model must be able to do ("Proposes competing hypotheses in the
required form" / 「能以規定格式提出競爭假說」, "Returns structured data (JSON)" / 「能輸出結構化資料
（JSON）」, …), readiness states ("Uses primary reasoning" / 「改由主要推理執行」, …) and reach
("external service" / 「外部服務」). Nothing underneath is renamed: every name carries its raw ID as a
tooltip, and each table has a collapsed **Technical details (internal IDs)** block with the raw IDs,
route fingerprints and the server's own rule sentences. The Critic and egress statements are
composed per locale from the structured readiness (the server's sentences are in the details); rule
text that must be shown -- blockers, refusals -- has its unambiguous IDs replaced by their names
(`humanize`, escaped). The readiness table has three columns -- used for (with status), model, who
relies on it and what it must prove -- so long names no longer stack vertically.

## 6. The database (`012e_llm_runtime.sql`, 52 migrations)

`llm_connections`, `llm_connection_health`, `llm_models`, `llm_capability_probes`, `llm_runtimes`,
`llm_slot_bindings`, `llm_secret_salt`. Held against any writer: an endpoint is its identity (edit it
and it is a new connection); models are discovered, then tested (a probe on record), then locked (the
lock equals the latest passing probes and includes CHAT); probes and health are append-only; a locked
or retired model is not re-probed; a binding needs a LOCKED model proving the slot's requirements
(`llm_slot_requirements`, which a test compares with the code) on an ENABLED connection, and LOCAL for
PRIVATE_LOCAL; activation needs PRIMARY and FAST, locked models, enabled connections and -- with
ADVERSARIAL unbound -- PRIMARY proving ROLE_CRITIQUE; one ACTIVE runtime; an active runtime's
bindings are frozen, and a model or connection it depends on cannot be unlocked, retired or disabled;
external labels never include RESTRICTED_NDA.

## 7. Changes outside the new modules

- `research/service.py`: the optional `reasoning`, `_model_route`, the provenance-derived reasoner
  line, and runtime deployment/not-performed lines. With no runtime, every line is as before.
- `interfaces/web/pages.py`: the navigation, the language switch and the message catalog; English
  output unchanged. `app.py`: the settings and runtime routes, the locale cookie, runtime hookup.
- `interfaces/cli.py`: `lab-brain web --locale`. The command line NEVER reaches a language model
  (T-UX-006's structural guard: it imports nothing that could generate), so `research run`
  reasons only with the catalog reasoner -- and while an LLM runtime is ACTIVE it refuses (exit 2,
  nothing written), since a CLI run would otherwise be reasoned by something other than what is
  active. It reads only the active runtime's name (`research.reasoning.active_runtime_name`). An
  early draft of this work wired the runtime into the CLI; the M1 contract test
  `test_no_cli_path_can_reach_a_model` refused it, and it was withdrawn.
- `core/models/identifiers.py`: `llm_connection`, `llm_health_check`, `llm_model`, `llm_probe`,
  `llm_runtime`.
- `tests/postgres_fixtures.py`, `tests/wsgi_client.py` (a cookie jar).

## 8. Verification

End to end on PostgreSQL (`tests/e2e/test_web_llm_runtime_postgres.py`, 9) against an
OpenAI-compatible provider on 127.0.0.1 (`tests/fake_llm_provider.py`) over a real socket with a real
Bearer credential -- a test double the system under test does not know is one. Its `fake-reasoner`
and `fake-critic` pass every probe and answer research prompts from the SiPh mechanism catalog;
`fake-chatty` answers only in prose.

| Scenario | What is asserted |
|---|---|
| language | switching sets the cookie and returns; `lang="zh-TW"`, Chinese chrome; every stored value of the report still shown; the Markdown export and the stored report unchanged; unknown locales and off-site `next` refused |
| credentials | `env:` reference and fingerprint; a typed-in key only in the OS store; no store -> refused, nothing written; a pasted key refused; a wrong key echoed by the provider recorded and shown redacted; no key anywhere in the database dump or any page |
| lifecycle and invalid configuration | LOCAL for a LAN host, credentials in the URL, a non-HTTP scheme, a bad name, a duplicate name: refused, nothing written; fetched models DISCOVERED; lock before test refused; all 8 probes PASSED; LOCKED with `lk:…`; re-test while locked refused; unlock/relock; provider down -> UNREACHABLE while the connection stays ENABLED and the model LOCKED; disabled -> fetch refused; a non-researcher gets 403 |
| capability-based binding | `fake-chatty` (CHAT only) absent from PRIMARY's choices with "not proven: …"; forced binding refused; PRIVATE_LOCAL refused on EXTERNAL, accepted on LOCAL; activation without FAST refused; unlocking a bound model refused |
| real-LLM routing | activated with its own Critic; the new-run page names the runtime; the run's provenance is exactly {PRIMARY, FAST: fake-reasoner, ADVERSARIAL: fake-critic} with the lock fingerprints and provider; one provider call per recorded inference, each with its role contract; an LLM_CALL span per call; the report names the runtime; verification unchanged (SUSPENDED, no simulation Job) |
| egress | a runtime permitting PUBLIC only: INTERNAL evidence refused by the egress gate before the transport, no provenance |
| fallback | FALLBACK shown as not route-independent; same-model ADVERSARIAL shown as not independent; critiques recorded on REASONING_PRIMARY; deactivated -> catalog reasoner, no provider call; an unusable active runtime -> the run refused (409), nothing written, Runtime says so |
| restart | a new workspace: connection, lock, ACTIVE runtime and OS-stored credential persist, and the next run is reasoned by the runtime |

Also: the live Runtime page in zh-TW shows the researcher names with no routing ID in its main view
and every ID in its technical details, the bindings unchanged; and `lab-brain research run` exits 2
while a runtime is active, writing nothing and calling no model (11 end-to-end tests in all).
`tests/unit/test_web_labels.py` (6): the canonical IDs, the routing table and each slot's
requirements are exactly as before; zh-TW and English render the intended names; no raw ID in the
main view, all of them in tooltips and technical details; switching language changes every label
and no ID; rule text is humanized safely.

`tests/integration/test_llm_runtime_postgres.py` (7): `012e` written directly in SQL.
`tests/unit/test_llm_runtime.py` (15): probes judged by the real parsers and never executing code,
contracts, the router's table, references, fingerprints and redaction, fail-closed storage, the
Windows Credential Manager round trip (Windows only), the HTTP transport, the message catalog, the
zh-TW report. The workspace was also run live (`lab-brain web --locale zh-TW`) against a demo
database and the provider, and its settings and Runtime pages checked in a real browser.

| Gate | Result |
|---|---|
| ruff / format / mypy strict | clean / 412 files formatted / no issues in 229 source files |
| backend-free suite | 1636 passed, 762 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated (52 migrations, re-apply a no-op) | 2396 passed, 2 skipped (`lumerical`, `network`) -- the accepted 2357 plus 39 new |
| the accepted Product Vertical and Web Workspace tests | unchanged and passing (with no runtime active, the catalog path is byte-for-byte the accepted one) |
| M1's T-UX-006 (`test_no_cli_path_can_reach_a_model`) | passing: the CLI imports nothing that can generate |
| M4 root-cause benchmark `--check` (regression) | report current |
| coverage ratchet, obligation inventory, status, debate and segmentation benchmark reports | current; M0a-M3 enforced, M4 and M5 IN_PROGRESS |
| mutation battery (`scripts/mutation_battery.py`, PostgreSQL) | 288/288 killed -- the accepted 269 plus 19 new (15 runtime, 4 labels); no backup left |
| OS credential store after every run | no test credential left behind |
| GitHub Actions CI at `8f708d792e972026d015b868245f68a2dcf25a78` (commit hygiene, spec conformance, lint/types/full suite, PostgreSQL backend incl. the fresh 52-migration apply) | success, run 36418503706 |
