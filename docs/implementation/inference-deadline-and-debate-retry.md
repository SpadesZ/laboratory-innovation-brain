# One inference deadline, and a debate that failed before it began

Date: 2026-10-05
Scope: an operational follow-up to the first real LOCAL smoke (qwen2.5:7b on CPU). **Not a
milestone.** No Requirement or Test ID was added and no milestone status changed. Scientific
reasoning, routing, CognitiveRole/LogicalSlot contracts, capability requirements, credentials,
transport locality, the redirect policy, egress and provenance are unchanged. The Lumi Agent
benchmark was not run.

## 1. What the smoke exposed

- **P1-A, two deadlines.** `local_setup` probed models with a 300 s timeout, so qwen2.5:7b's
  ROLE_HYPOTHESIS probe passed in 194 s and the model was locked; the active runtime called models
  with its own 180 s; the web workspace never set either. Readiness declared READY a configuration
  whose required capability was already recorded slower than the runtime's deadline -- and the
  research call timed out.
- **P1-B, a terminal non-answer.** `_debate()` recorded the failure and skipped verification, and
  finalization CLOSED the episode `COMPLETED / NOT_REACHED`. A continuation of an episode without a
  hypothesis set refused to debate, so a transient timeout ended the episode before anything was
  reasoned.
- **P2.** The timeout was reported as `UNREACHABLE`, though the endpoint had answered the previous
  call 30 s earlier.

## 2. One deadline per deployment

`lab-brain web --inference-deadline SECONDS` (compose: `LAB_BRAIN_INFERENCE_DEADLINE`, default 180;
`local_setup --inference-deadline`, the same variable) is the longest one model call may wait for its
answer. It reaches every place that decides by it, explicitly:

| Where | Uses |
|---|---|
| `LLMSettings.test_model` -- the capability probes that qualify a model | the deadline |
| `load_active_runtime(..., inference_deadline=)` -- every route's client | the deadline (required argument) |
| `Workspace` | passes its deadline to both, from one field |
| `LLMSettings` model discovery and health checks | `DISCOVERY_TIMEOUT_S` (20 s): an operational question, not inference |

**Readiness reads the evidence against it.** `readiness.deadline_problem` takes, for each capability
a bound slot requires, the model's latest recorded probe -- for a locked model, the one its lock
counted -- and if it passed slower than the deadline in force NOW, the slot is blocked: "model
qwen2.5:7b's recorded ROLE_HYPOTHESIS probe took 194 s, longer than this deployment's inference
deadline (180 s)". Activation needs readiness, and `load_active_runtime` refuses the same route
before reading its credential, so research never starts on a configuration already known to time
out. Nothing is re-probed or rewritten: raising the deadline makes the same evidence acceptable.
This is the deployment's operability, not a capability -- locks and slot requirements are untouched,
and the guide tells the operator to raise the deadline or bind a faster model.

The client timeout is urllib's: how long each wait for the provider may last. A non-streaming
completion arrives at once when it is done, so for a model call it is the call's deadline.

## 3. TIMEOUT is not UNREACHABLE

`ProviderFailure.TIMEOUT`: the request was sent and the answer did not arrive in time ("the endpoint
accepted the call and did not answer within N s"). `UNREACHABLE` stays for a connection that could
not be made (refused, unresolvable, or not accepted in time). `012j` admits TIMEOUT as a health
outcome; the page says 回應逾時. Redaction, credential handling, the https/locality rule and the
no-redirect policy in `provider.py` are unchanged.

## 4. A debate that failed before it began is retried in the same episode

- **The invariant.** An operational or reasoning failure (provider timeout, unavailable route, a
  reply no typed parser accepted) BEFORE a durable HypothesisSet exists concluded nothing: the
  episode is `SUSPENDED / NOT_REACHED` with the reason ("the debate failed before a hypothesis set
  existed (…); continue the episode to retry it"), never closed.
- **What the retry reasons over.** The opening run records what it admitted, by reference, before it
  debates (`012k`'s `research_run_statements`: attestation, trust class, source name, in order;
  append-only, only while the run is live). A continuation of an episode with no hypothesis set
  rebuilds exactly those statements from their attestations and claims -- nothing ingested,
  admitted or copied again -- and debates.
- **One reasoning history.** `012c` let only the opening run record the set; `012k` lets the run that
  debated record it, still once per episode, and every later run carries it. The backstop refusing a
  second set in the episode is unchanged. A debate that failed AFTER admitting a set leaves it
  unrecorded, and that episode is still refused (an incomplete history is neither continued nor
  replaced) -- the scope of this fix is a debate that never produced a set.
- **Provenance.** Every attempt stays on the record: each run in `research_runs` with its outcome,
  its stages in its report, the BudgetGate's estimate for the call that failed. A failed call writes
  no InferenceProvenance; the retry's successful calls write their own.
- **History is kept.** The 2026-10-05 smoke episode that closed `COMPLETED / NOT_REACHED` under the
  old rule is not rewritten.

## 5. Tests

| # | Proven | Where |
|---|---|---|
| 1 | a capability proven in 194 s cannot make a runtime READY, activated or loaded under 180 s | `tests/integration/test_inference_deadline_postgres.py` |
| 2 | under 300 s the same locked route is ready, activated and loaded -- probes, lock and fingerprint byte-identical before and after | same |
| 3 | probes and research calls wait the same deadline (42 s; the workspace's 37 s); discovery and health 20 s | same; `tests/e2e/test_web_debate_retry_postgres.py` |
| 4 | a socket that took the request and never answered: TIMEOUT within the deadline; a closed port: UNREACHABLE | `tests/unit/test_llm_deadline.py` |
| 5 | a Hypothesis Engine call slower than a 2 s deadline: `ProviderError: TIMEOUT`, episode SUSPENDED with the reason, no set | `tests/e2e/test_web_debate_retry_postgres.py` |
| 6 | with the deadline raised, continuing the SAME episode retries the debate over run 1's recorded statements | same |
| 7 | no ingestion item or attestation of the document added; no InferenceProvenance for the failed call | same |
| 8 | after the retry, verification runs and the episode parks on the simulator; a third run reuses the one set; the database refuses a second set and edits to what a run admitted | same |
| 9 | every existing budget, egress, locality, redirect, credential and continuation test | the whole suite |

Mutation battery: eleven entries -- the probe and research deadlines, the runtime and readiness
blockers, the workspace's two propagations, TIMEOUT, the suspend, recording the statements, the
retry, recording the retried set.

## 6. Verification

Recorded in the follow-up commit, once CI and the full mutation battery have run.
