# G0 reliability and authenticity closure: design

Branch `g0-reliability-authenticity-closure`, from `g0-owner-boundary-closure` @ `58c68be`.
Engineering only. No paid call, no licensed solver, no real model, no deployment. G0 is NOT PASSED;
`READY_FOR_REAL_RESEARCH` stays false.

Each defect below was reproduced by a test written before the fix; the failing runs are in
`evidence/`.

## 1. The unmetered local proxy (migration `011v`)

### Defect

With no spend ceiling configured, `OpenAICompatibleClient` sent a request to this machine
unmetered: with no guard at all, and with a database but no budget (`meter_this_machine` was false
unless `LAB_BRAIN_LLM_SPEND_METER_LOCAL=1`). A LiteLLM-style proxy on localhost forwarding to a paid
provider was an unmetered paid path (the 011t residual, Owner decision A3). Two further gaps were in
the Owner's own exemption: a declaration naming `*` freed every model at an endpoint (a proxy routes
by model name), and nothing noticed when a "free" endpoint answered like a paid one.
Evidence: `evidence/local_proxy_before.log` (10 of 14 tests failed on 58c68be).

### Change

| layer | rule |
|---|---|
| transport (`provider._reserve`) | a request with a body to this machine is admitted like a remote one: reserved, or exempt only by the Owner's declaration of that exact model at that endpoint; with no guard it is refused unsent. No guard attribute exempts this machine any more. |
| environment guard (`spend.resolve`) | a database without a budget gives a guard that meters this machine; `LAB_BRAIN_LLM_SPEND_METER_LOCAL` is retired (not read) |
| SQL (`011v`) | `llm_spend_declare_free` refuses `*`; `llm_spend_endpoint_is_free` reads only exact-model declarations (old `*` rows free nothing) and is false while paid-proxy evidence names the current declaration |
| paid-proxy evidence (`011v`) | a declared-free answer carrying a billing header (`x-litellm-*`, `openai-organization`, provider rate-limit headers...) or a cost in its usage is reported (`llm_spend_report_paid_proxy`, callable by the services because it can only withdraw an exemption) and the call is refused; the evidence is append-only, holds signal names only, and is cleared only by the Owner declaring the endpoint free again |
| evaluation (`free_endpoints_from_env`) | a free endpoint names one model |

### Residual (SPEC-ISSUE-017)

A proxy that strips every billing sign is indistinguishable from a model server. The Owner's exact
declaration is the cost trust root. Declarations do not expire and do not bind the model digest.

### Test servers

Tests drive throwaway model servers on 127.0.0.1. `tests/free_test_endpoints.py` declares those free
for tests only (nothing in `src/` can). Transport tests opt in per module; PostgreSQL tests get it
from `tests/conftest.py` unless marked `real_spend_guard` -- every spend-ceiling test is.

## 2. Signed verification authorizations (migration `011w`)

### Defect

A verification authorization (011s) proved nothing about a person: `actor_id` was a string, and
every service connects with the same role. Evidence: `evidence/unsigned_authorization_before_011w.log`
-- an unsigned authorization in a real member's name is accepted on a database without 011w.

### Change

The Causal Warrant Gate's design (012p) reused, in tables of its own:

- `verification_authorizer_enrolments` / `_revocations`: an authority-signed enrolment of a person's
  Ed25519 key, scope `VERIFICATION_AUTHORIZATION` (the scope is inside the authority's signature,
  so a warrant enrolment is never one). Active human member; one key one person across both kinds
  of enrolment; a revoked key never again; an authority key never a person's key; append-only.
- `verification_authorizations.{enrolment_id, signature, signed_at}`: the person's signature over
  `core.models.reviewer.authorization_statement` -- id, project, episode, hypothesis, predictions,
  capability, declaration hash, person, rationale, time, enrolment, under its own domain tag.

| where | what is checked |
|---|---|
| write (trigger) | signed; under an unrevoked enrolment of the person named, in that project; after the enrolment; not in the future; after the hypothesis (2-minute clock skew) |
| admission (rule (l), `prospective_authorization_problem`, replaced by 011w) | the same frame on the rows as they are now: an unsigned row (pre-011w), another person's enrolment, a revocation effective at or before the signature, license nothing |
| every read that counts it (Python) | `ReviewerTrust.verify_authorization`: the authority's signature on the enrolment, the person's on the authorization, scope, revocation timing. Used by `support_problem` / `ProspectiveEvidenceSink` (a SUPPORTS whose authorization does not verify is recorded as CITES) and by the evaluation collector (`unverified_authorization`, required false by scorer 2.3.0) |

SQL cannot verify Ed25519, so SQL holds the frame and Python the signature, exactly as for warrant
answers. Evidence admission is not weakened: every 011s rule still applies; the signature is one
more condition.

### Residual (SPEC-ISSUE-018)

The trust root is the pinned authority file and whoever controls the deployment configuration. A
person's own key is theirs to misuse. The warrant gate's separations of duty (not the episode's
runner, not the hypothesis's author) are not applied to authorizations yet.

## 3. Blind-evaluation input freezing and environment drift

### Defects (`evidence/blind_freezing_before.log`, 19 of 19 failed on 58c68be)

- The runner hashed only the generator package, never the evidence files the manifest froze: an
  evidence file edited after the freeze was fed to the run.
- The package was hashed, then read again from disk to be parsed: a file swapped in between ran.
- The outputs carried whatever `environment_sha256` string the caller passed; nothing checked the
  environment before the first case or after the last.
- `verify` ignored a dirty tree, the endpoint (only its locality), the platform, the LAB_BRAIN_*
  settings, the schema applied to the database, and whether the digest was measured.
- The model digest was only ever declared: a model replaced under the same tag was not noticed.

### Change

- `run_blind` reads every frozen file once, checks it, and parses the package and its evidence
  from those bytes (`load_generator_package(read=...)`); an input the manifest did not freeze is
  refused.
- `run_blind(environment=..., observe_environment=...)`: refuses to start on drift; checks again
  after the last case and writes `drift_after`; the scorer refuses a run whose environment changed,
  and reports `environment.verified`. A bare hash is no longer accepted.
- The environment manifest also pins the clean flag, endpoint, platform, settings (secrets only as
  set), applied migrations (`--database-url`), and `digest_source` (served by the local Ollama
  server and matching, or only declared). A served digest that contradicts the declared one is
  refused. Remote endpoints are never asked.

### Residual (SPEC-ISSUE-019)

Every recorded difference invalidates a run (the strictest reading); whether some may be allowed,
and whether a declared-only digest is acceptable for an acceptance run, is the Owner's decision.

## 4. Follow-up (auditor finding): the forged-authorization read path

### Defect

A verification authorization with a forged signature passes 011w's SQL frame (SQL cannot verify
Ed25519), and a SUPPORTS relation resting on it is admitted by the database. The evaluation
collector rejected it, but the collector only scores. `evidence/forged_authorization_read_path_before.log`
(3 of 4 tests failed on f41758c) shows that both rows can be written by the deployment's
least-privilege SERVICES role, and that the forged support was then returned by
`SqlRelationStore.admitted_for_subject` -- the one function every belief decision reads: the
transition authorization's decision inputs (`core.episode`), the verification loop's confirmation
rule (through `SqlEvidenceSink`), and the confirmation re-check a conclusion must pass before it is
reused (`research.confirmation`).

### Change

| reader | rule |
|---|---|
| `SqlRelationStore.admitted_for_subject` | for a hypothesis with a screening conditioning record, a SUPPORTS is admitted only when the store's `support_verifier` finds no problem; with no verifier it is never admitted (fail closed: a reader built without one loses post-screening support, it never gains a forged one) |
| `prospective_support_verifier(connection, trust)` | `support_problem`: 011s's SQL rules on the rows as they are now, then the signatures of the authorization the basis runs are bound to, under the pinned review authorities |
| research service, confirmation re-check | every relation reader they decide from is built with the verifier (a structural test checks each construction site) |
| episode view | a recorded post-screening SUPPORTS that does not verify (or that the view could not check) is shown as "recorded as support, but not counted" in both languages |
| `from_observation` | unchanged on purpose: the confirmation rule uses it to find rival affirmations, so an extra relation there can only block a confirmation, never grant one |

### Residual

A writer holding the services' role can still write any row SQL's frames admit -- a belief event
or a decision row included. Those are re-derived and verified on read where the product relies on
them (the projection, the confirmation re-check); the general boundary is the A12 deployment
boundary (separate roles for the services, the migrator and the Owner), not a property any SQL
frame can supply. SQL cannot verify Ed25519; a database extension that can (for example pgsodium)
would move the signature check into the admission trigger and is an Owner/deployment decision.

## 5. Follow-up: acceptance scores need an independently verified environment

On f41758c every score was the same kind of score. Now `score_run(purpose=...)`:

- `ACCEPTANCE` refuses unless the runner verified the environment before the first case and after
  the last, AND the evaluator's own verification record (`g0_eval_environment.py verify --verifier
  <id> --out verification.json`, `environment.verification_record`) is of that same environment,
  found no difference, saw a clean tree and a model digest the local server measured, names its
  verifier and hashes to itself.
- `DIAGNOSTIC` (the default) scores whatever ran and its `standing` says it is not an acceptance
  result -- and, when so, that its environment was not independently verified.

Residual: `verifier_id` is asserted, not signed. Whether an acceptance verification must be signed
with an enrolled evaluator key is an Owner decision (SPEC-ISSUE-019).
