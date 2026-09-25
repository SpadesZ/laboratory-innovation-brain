# M2 — Silicon Photonics Tool Layer: readiness for independent sign-off

Date: 2026-09-24; revised after the first independent M2 review (§9), again after the second (§10),
and on 2026-09-25 for the final blocker it named (§11)
Milestone: **M2 — Silicon Photonics Tool Layer**, `IN_PROGRESS` — implementation complete, awaiting
independent sign-off
M1: **`DONE` / HARD-LOCKED** at `bdb72129a1075d69a30f5043a3491570ca7d4521`; the executed-coverage
ratchet now enforces its 21 requirements on every CI run
M1-P1 locked baseline: `f8e5e9c02ee98ed2a7faa6f604347b84b88c773b` — **untouched**
M0a / M0b: `DONE`, hard-locked — **untouched**
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`. **No amendment, no ADR, no new Requirement or
Test ID was added by this work.** 60 ↔ 60 throughout.

> This document claims readiness for audit, not completion. M2's status is the maintainer's to
> change; the implementing agent does not sign off its own milestone.

## 1. The exit gate, clause by clause

> simulated + measured fixtures use the same extractor contract; license/resource queue mock pass.

| Clause | Where it is demonstrated |
|---|---|
| every tool call is **budgeted** and **typed** | `unit/test_budgeted_tool_dispatch.py` (26) + `e2e/test_m2_vertical_postgres.py` — `BudgetedToolDispatcher` is the one production tool call: **scope binding** → registry resolution → **durable Job binding** → Capability/contract estimate → `BudgetRequest` → `dispatch_action` → ALLOW-only `invoke` → measured actual → closed span. See §9A, §10E and §11F. |
| ...and the scope that is **gated** is the scope that **executes** | `unit/test_budgeted_tool_dispatch.py`, `unit/test_typed_tool_registry.py`, `contract/test_resource_demand_binding.py` — project, trace, **Episode** and capability are bound across `ToolAction` → `ToolRequest` → `SimulationRequest` → `Job`. The Job is resolved and compared **before the gate**, so a mismatch consumes no approval and writes no ledger row, and again at execution, before any Job mutation, seat or backend call. The vertical asserts the whole chain as **equality**, including `ResearchEpisode.episode_id == ToolAction.episode_id == Job.episode_id` and the Episode on both durable ledger rows and the span. See §10E and §11F. |
| ...and **the Episode that pays is the Episode whose Job executes** | `e2e/test_m2_vertical_postgres.py::test_a_job_in_another_episode_is_refused_before_the_approval_is_spent` — two Episodes of one project on one trace, the Job under the second, the action budgeted in the first with a valid approval: refused with the approval row unconsumed, no `cost_entries`, no span, the Job exactly as submitted, no lease, backend never entered, no Run. Its positive control releases the same action through the same approval when the Job is in the budgeted Episode. See §11F. |
| simulated + measured fixtures use the **same extractor contract** | `domains/test_shared_extractor_contract.py` — one `CjRsExtractor` instance, one `ExtractionInput` type, one `ExtractionResult` type, both modalities, and the **numbers are equal**. Reinforced structurally: `test_there_is_exactly_one_extraction_protocol_and_one_input_type` fails if a parallel type appears, and `test_the_extractor_source_never_branches_on_modality` parses the reduction and fails if it reads `modality` at all. |
| ...and the provenance is **not** shared | the same file: SIMULATED names a Run and carries backend validity, MEASURED names a source Artifact, and four relabelling attempts are refused at the boundary (`test_measured_provenance_cannot_be_relabelled_as_simulated` and its three siblings). |
| license/resource queue mock pass | `e2e/test_m2_vertical_postgres.py` — one seat, a rival job holds it, the simulation parks in `WAITING_RESOURCE` with `attempt_count` untouched and no `structured_error`, the rival releases, and **the same `job_id`** resumes and produces exactly one Run. |
| ...and the ceiling is the database's | `test_the_database_holds_the_seat_ceiling_against_a_writer_outside_python` inserts a lease with raw SQL, bypassing the broker entirely, and `007c`'s trigger refuses it under an advisory lock. |

**The end-to-end chain**, with the durable object each step leaves behind, is the docstring of
`tests/e2e/test_m2_vertical_postgres.py` and is exercised by
`test_the_whole_m2_vertical_runs_through_durable_rows`.

## 2. Requirement-by-requirement readiness

| # | Requirement | §26 pass condition (abridged) | Implementation | Tests | Status |
|---|---|---|---|---|---|
| 1 | **SIM-001** | run manifest 缺 solver/project/conditions/validity 任一必要欄位即拒絕升級正式 evidence | `tools/simulation.py` — `BackendValiditySchema` + `validate_backend_validity`, called **before** the manifest is minted; the required field list is `domains/silicon_photonics/backend_validity.py`'s, never core's | `contract/test_simulation_contract.py` (27, incl. one parametrised refusal per required field), `e2e/test_m2_vertical_postgres.py` (durable row) | READY |
| 2 | **SIM-002** | low-fidelity contradiction 只使 hypothesis → CHALLENGED，不得直接 → REJECTED | two registered §8.2.1 `TransitionPolicy` records + `SiliconPhotonicsAuthorityPolicy`. **No core file changed**: `TransitionPolicy.evaluate` is untouched M0b code and is what refuses | `e2e/test_sim_fidelity_gate_postgres.py` (12, policy semantics) + `e2e/test_sim_fidelity_vertical_postgres.py` (7, **durable e2e**: Decision to event to replay to CHALLENGED) | READY |
| 3 | **SIM-003** | static test rejects `eval_script`-class interfaces; every invocation resolves through the typed ToolRegistry | `tools/registry.py` + `tools/contracts.py`; the static half is `unit/test_no_arbitrary_script_execution.py`, which existed since M0a and was deliberately unmarked | `unit/test_typed_tool_registry.py` (28, incl. the two structural probes that permit `.invoke(...)` only in `tools/dispatch.py`, the six that stop a typed request describing two executions at once, and the three that pin which Job a request binds and that its Episode cannot be left unstated), `e2e/test_m2_vertical_postgres.py` (the whole chain, budgeted) | READY |
| 4 | **EVI-001** | Cj/Rs fixture missing unit / normalization basis / bias-frequency condition / extraction method fails; complete fixture round-trips | `tools/extraction.py` `ExtractedQuantity` refuses a value missing any of the four; `domains/silicon_photonics/extractors.py` supplies all four | `domains/test_cj_rs_evidence_contract.py` (18, incl. the six condition-provenance refusals) | READY |
| 5 | **DOM-SP-001** | Rs trend validator 只存在 SiPh DomainPack，移除 plugin 後 core 仍可啟動 | `domains/silicon_photonics/validators.py`; core has no place to put a rule — `ValidationReport` keys findings by an opaque `rule_id` | `domains/test_domain_pack_boundary.py` (14) | READY |
| 6 | **DOM-SP-002** | 同一 `extract_cj_rs` contract 通過 simulated 與 measured impedance fixtures | one `MetricExtractor` protocol, one `ExtractionInput`/`ExtractionResult` pair; `ToolDescriptor` refuses an `extract_*` tool that names a backend | `domains/test_shared_extractor_contract.py` (9), `e2e/test_m2_vertical_postgres.py` | READY |
| 7 | **VER-002** | Planner 對無 capability descriptor 的 backend 不可規劃；有 descriptor 時依 produces/requires match | `verification/capability_registry.py` + `verification/planner.py`; `007c`'s `capabilities` makes the absence durable | `unit/test_capability_planning.py` (23), `e2e/test_m2_vertical_postgres.py` | READY |
| 8 | **EXT-001** | 新增 ToyDomain 時 core package 無 source modification；plugin registration 即運作 | `domains/base.py` + `domains/registry.py`; the second domain is `tests/toy_domain.py`, **outside `src/`** | `unit/test_extension_boundary.py` (24) | READY |

## 3. The architecture, and the four decisions that shaped it

### 3.1 SIM-001 and §17.4 are not in tension

§25.3's SIM-001 names CHARGE-specific things — solver version, mesh, bias, convergence. §17.4 says
*Core MUST NOT hard-code solver_settings / mesh_convergence / calibration fields*. The resolution is
the one §17.10 states: core owns that an execution **declares which validity schema it conforms
to** and carries a payload; the DomainPack owns that `silicon_photonics/simulator_validity@1.0.0`
requires `solver_id`, `solver_version`, `project_hash`, `mesh_config_ref`, `bias_config_ref` and
`convergence_status`.

So `BackendValiditySchema` has a `required_fields` tuple and no opinion about its contents, and
`test_core_declares_no_physical_quantity` (M0a) plus `test_the_forbidden_dependency_directions_hold`
(new) keep it that way.

### 3.2 SIM-002 is an authority question, so it changed no core file

"A coarse result may challenge but not reject" is a statement about how much weight a fidelity level
carries — §10.5's DomainPack column. The mechanism already existed and is hard-locked:
`TransitionPolicy.evaluate` asks `meets(required_authority_rule, candidate)` and DENYs on False. So
the requirement is discharged by

* an `ACTIVE→CHALLENGED` policy whose rule is `SIM_COARSE`, and
* an `ACTIVE→CONTRADICTED` policy whose rule is `SIM_STANDARD`,

plus a comparator ranking coarse below standard. `CONTRADICTED` rather than `REJECTED` because
that is the state §8.2's diagram declares; SPEC-ISSUE-010 ruled on the shorthand.

**The lie the gate would otherwise be walked through.** A provider that stamped `SIM_VALIDATION`
on a run that hit its iteration cap would reject a hypothesis on a result that did not converge.
`backend_validity.fidelity_for` makes the declared class a **ceiling** and the convergence status
what decides whether it is reached.

### 3.3 §10.6 is why simulated and measured are INCOMPARABLE

A comparator returning STRONGER for a calibrated measurement would encode "measurement 永遠最高",
which §10.5 names as the thing core must not assume — and a DomainPack asserting it is the same
error one layer out. With the cross-family pairs INCOMPARABLE, §10.6's `SIM_TO_REAL_CONFLICT` can
actually arise, and EPI-004 routes it to `NEED_HUMAN_REVIEW` with a `ReviewItem(AUTHORITY_CONFLICT)`.

### 3.4 "The same extractor contract" had to be structural

Two extractors returning similarly-shaped dictionaries satisfy every test written against the
shape, and then one is corrected and the other is not. §10.2.2 says so about this tool directly:
*Splitting it would allow simulated and measured paths to diverge in normalization.* So there is
one `ExtractionInput`, one `ExtractionResult`, one `MetricExtractor` — and the tests assert the
types are one type, not merely that two objects currently agree.

And yet `SIMULATED != MEASURED`: `ExtractionSource.modality` carries the canonical `EpistemicType`
(not a parallel enum), the simulated side owes a Run and a validity record, the measured side owes
a source Artifact, and four relabelling attempts are refused.

## 4. What changed outside the new packages

Five surfaces, each with the reason:

| Surface | Change | Why it was necessary |
|---|---|---|
| `core/models/__init__.py` | exports `Capability`, `ActionType`, `Availability`, `ValidationReport`, `ValidationStatus`, `ValidationFinding` | §24.1 puts Capability in the **Core MUST know** column, and §17.19.2's report is what a domain validator returns. Neither names a solver or a quantity. |
| `core/models/identifiers.py` | two new `_ID_PREFIXES` entries (`validation`, `resource_lease`) | both are event-addressed entities; minting an id for one is refused otherwise. No existing prefix changed. |
| `spec/schema_drift.py` | `Capability` bound to `007c`; `ValidationReport` exempted with a stated reason | the guard requires every §17 schema naming an exported core model to be bound or exempted. `Capability` is bound **field-for-field**. |
| `scripts/migrate.py` | `007c_capabilities.sql` appended to `APPLY_ORDER` | forward-only; no applied migration was edited. |
| `pyproject.toml` | two `per-file-ignores` entries | the `TID251` ban is on the shipped package reaching into a DomainPack; a pack importing itself, and tests importing packs on purpose, are not that. The structural check is `test_extension_boundary.py`, which parses the graph. |

**No locked surface was reopened.** `TransitionPolicy`, `AuthorityPolicy`, the admission gate, the
segmentation path, `can_access_project` and every M1-P1 item in §12 of that document are unchanged.

## 5. Migration `007c_capabilities.sql`

The capabilities half of Appendix A's `007` slot, which `007a`'s header reserved for M2. Three
tables and one trigger:

* `capabilities` — §17.18 field-for-field, **fifteen columns and no `created_at`**. The header
  explains why: `schema_drift` compares this table, the model and §17.18 in both directions, and
  registration history is `version`.
* `resource_pools` / `resource_leases` — §10.7's seats. A lease is a ROW because a check-then-insert
  is correct for one scheduler and wrong for two, which is the argument `006` makes about duplicate
  callbacks.
* `resource_lease_within_pool()` — the ceiling, enforced under `pg_advisory_xact_lock` so the loser
  loses the INSERT rather than the race. A released lease is retained, never deleted: "who was
  holding the seats when this job was refused one" is what a contention incident asks.

Replayed from empty, `pending 0`, idempotent re-run.

## 6. Verification

Local, full history, PostgreSQL last. Re-measured after §11 against a fresh database.

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | clean, 259 files |
| `mypy` (strict) | clean, **138** source files |
| Backend-free suite | **1327 passed**, 627 skipped |
| Migration replay from empty | **38 applied** (fresh `lab_brain_m2r3`) |
| Migration idempotency | `pending 0`, second run a no-op |
| Full PostgreSQL profile | **1954 passed**, 0 skipped |
| Executed-coverage ratchet | ok ×4; **DONE `['M0a','M0b','M1']`**, IN_PROGRESS `['M2']`; **45** requirements with a passing test |
| Status freshness | up to date |
| Spec conformance | **205 passed** |
| Requirement ↔ Test | **60 ↔ 60** |
| Obligation inventory | **84**, in sync |
| Schema drift / unbound / stale | all empty |
| Mutation battery | **120/120 killed** (75 through M1, + 15 M2, + 9 first-review repairs, + 8 execution scope, + 13 Episode binding), run with `LAB_BRAIN_TEST_POSTGRES=1` — 19 entries are killed only by PostgreSQL-gated tests |
| M1-P1 benchmark | current (`run_benchmark.py --check`) |

The local and shallow-CI figures are separate numbers and are not interchangeable: 1327 is a bare
`pytest`, 1954 is the same suite with `LAB_BRAIN_TEST_POSTGRES=1` against a database migrated from
empty. A milestone whose `gate_profile` names `postgres` cannot be signed off by the first — and the
executed-coverage ratchet says so: run over the backend-free report it fails *DONE milestones ran
their declared gate profile*, and over the PostgreSQL report it is ok ×4.

**M1's ratchet is live in these figures.** The coverage gate now enforces M1's 21 requirements as
well as M0a's and M0b's, so a regression in any of them fails CI rather than being noticed.

## 7. Remaining risks and limitations

**Environmental, and the most important one to state plainly:**

1. **No Lumerical seat, and nothing pretends otherwise (R-1).** No module in `src/` imports
   `lumapi`; `test_no_vendor_sdk_is_imported_anywhere_in_the_shipped_package` is the tripwire.
   `MockChargeAcBackend` is deterministic and stamps `solver_id = mock.charge.ac` — never `CHARGE`
   — which `test_the_mock_never_claims_to_be_a_vendor_solver` asserts. **What M2 proves is the
   contract.** TST-001's second half — the same case replayed against a real project on a licensed
   machine — is **not discharged**, is allocated to M4, and stays open.

**M2 implementation risks:**

2. **Three of §25.2's six tools are not registered.** `run_charge_dc_sweep` (001),
   `run_mesh_sensitivity` (003) and `inspect_contact_connectivity` (005) are declared by §25.2 for
   the FIRST VERTICAL, which is M4's VS-SP-001 loop. Stubs would put three unplannable capabilities
   in the registry — worse than their absence, because a registry entry reads as a capability.
3. **The condition schema is one version of one schema.** `pn_junction_ac@1.0.0` carries bias,
   frequency, device length, temperature and wavelength, and nothing else. Ring radius, doping
   profile and mesh settings are **deliberately absent**: the spec does not authorise them yet, and
   inventing them because they are scientifically plausible is what §23.4 reserves for a human
   steering point.
4. **`estimate_charge_ac_cost` is a declared stub, not a calibrated estimator.** It says so. A real
   estimator calibrated against measured run times is M4's; a stub pretending to be calibrated would
   be worse than one that admits it.
5. **No `SelectionPolicy`.** `VerificationPlanner` returns candidates in a declared order and never
   ranks by a scalar (VER-003). Ranking is VER-005 in M4.
6. **`ValidationReport` is not persisted.** §26's VER-002 and DOM-SP-001 rows are `unit` and
   `domain`; the table arrives with VER-004's planner-side plausibility check. Recorded in
   `schema_drift.UNBOUND` rather than left implicit.
7. **No Attestation is written by the M2 layer, and that is asserted.** The vertical's step 15
   checks that `attestations`, `evidence_units`, `belief_revision_events` and `observations` are
   still empty. Admitting a simulated observation as evidence is M4's VS-SP-001 loop; a tool layer
   that wrote one would be the second evidence model the extension boundary exists to prevent.

**Carried forward from M1, unchanged:** no LLM slot configured, R-2 (no ground-truth benchmark),
§17.3's declared subset, the in-memory dense index, bounded-retry error-id minting, COST-001 wired
as a seam without a live retry caller, and R-8 / R-9 / R-10 / R-11 / R-12.

## 8. Governance

No SPEC-ISSUE was raised. Two readings were tight enough to record:

* **SIM-001's field names versus §17.4's prohibition.** Resolved by §17.10, which makes the
  validity schema DomainPack-supplied. The narrower reading — core knows a schema has required
  fields and not what they are — is what shipped.
* **`register_transition_policies` does not exist in §24.3.** The SiPh pack *offers* SIM-002's two
  policy records through a plain method; it does not register them, and the `DomainPack` protocol
  did not grow a method the spec does not declare. Inventing normative extension surface is not
  this implementation's to do.

One ordering decision was **corrected against the spec during implementation** and is recorded
rather than quietly swapped: `run_simulation` originally acquired the license seat *before* moving
the Job to RUNNING, on the argument that a RUNNING job refused a seat has already told every reader
that execution began. §17.16's declared transition graph says WAITING_RESOURCE is reachable only
from RUNNING — it is the suspend edge — and it is right: a job nobody has picked up is QUEUED,
waiting for the scheduler, and a job waiting for a seat is waiting for the world. The ordering
changed; what the original was protecting (waiting must not look like failing) is carried by the
state, the untouched `attempt_count` and §17.24's degraded reading, all of which are asserted.


## 9. The first-review repairs

Independent review accepted the SIM-001 validity architecture, the typed ToolRegistry contracts,
the shared simulated/measured extractor, the DomainPack boundary, `007c`'s resource-pool database
invariants, Capability planning, the ToyDomain extensibility proof and the deterministic mock
backend, and named four remaining gates. All four are closed below. **No accepted surface was
refactored for cleanliness.**

### A (P0) — M2 tool execution bypassed COST-001

**The defect.** Both requirements held, separately, through two seams that did not meet:
`ToolRegistry.invoke` was typed and ungated; `core.dispatch.dispatch_action` was gated and knew
nothing about tools. `run_simulation`'s own docstring said budget *"belongs to `dispatch_action`"*
-- true, and nobody's job. So the shipped chain

    ToolRegistry.invoke -> ChargeAcSweepTool -> runner -> run_simulation -> backend.execute

reached a simulator without passing a gate, reopening a hard-locked COST-001 invariant. Satisfying
SIM-003 through a path that bypasses COST-001 satisfies neither.

**The repair is a composition, not a change to the gate.** `lab_brain.tools.dispatch.
BudgetedToolDispatcher` is one operation:

    resolve the descriptor      SIM-003. An unregistered tool is refused before a span opens.
    resolve the estimate        §9.5 for `run_*` (its Capability); the descriptor's declared
                                `cost_contract` otherwise. No estimate -> no dispatch.
    build the BudgetRequest     caps, session consumption, approval -- all passed in.
    dispatch_action             opens the span, asks the gate, calls `perform` ONLY on ALLOW.
      -> ToolRegistry.invoke    inside `perform`, so it cannot happen first.
    actual cost                 measured, never copied from the estimate.
    close the span              SUCCEEDED, both ledger rows linked.

`dispatch_action` is untouched hard-locked M0b code. What was missing was a caller.

**`extract_*` and `validate_*` go through the same surface.** `ToolDescriptor` now requires a
`cost_contract` on every non-`run_*` tool and forbids one on a `run_*` tool (§9.5 makes the
Capability authoritative; two contracts would be priced apart). The SiPh pack registers
`cost:sp.local_tool@1.0.0` returning a two-second vector. A zero CostVector is a legitimate answer;
*having no answer* is not, because that is what `evaluate_budget` refuses outright.

**Before / after, with a fatal spy** (`tests/unit/test_budgeted_tool_dispatch.py`, 14 probes, and
`test_an_over_budget_simulation_never_reaches_the_mock_backend` in the vertical):

| Attack | Before | After |
|---|---|---|
| over-budget `run_charge_ac_sweep` | backend entered, solver ran, cost recorded afterwards | `tool.entered == []`, BLOCKED span, `exceeded_dimensions` names the cap, no Run, Job still QUEUED, seat never taken |
| no BudgetPolicy | no gate consulted at all | BLOCKED; a missing policy is a refusal, not "no limits" |
| scoped supervisor approval | n/a | the **same** action executes, `ALLOWED_BY_APPROVAL`, approval named |
| the same approval twice | n/a | second call refused; §17.17.1's ONCE is the store's |
| estimate/actual | no ledger rows at all | ESTIMATED before the call, ACTUAL after, and they **differ** -- the tool reports 25s/25 seat-s against an estimate of 30/30/50 money |
| a tool that raises | n/a | FAILED span, ESTIMATED row kept, **no** ACTUAL row -- an action that raised reported no cost |
| a refused dispatch | n/a | **no** ledger row, so the retry a supervisor's approval enables still has its estimate slot |
| unpriceable tool | dispatched | `ToolDispatchRefused` -- a wiring error, not a supervisor's queue |
| duplicate simulator callback | one Run | one Run (unchanged; `JobStore.complete` still owns it) |

Two structural probes carry the claim past this commit:
`test_no_shipped_orchestration_surface_invokes_the_registry_directly` parses the whole shipped
package and permits `.invoke(...)` only in `tools/dispatch.py`; `test_the_dispatcher_calls_the_
registry_inside_the_perform_closure` parses `dispatch` and fails if the call moves out of the
closure, because a call at `dispatch` scope runs before the gate regardless of any docstring.

### B (P1) — EVI-001's bias/frequency conditions were unenforced

**The defect.** `ExtractionSource` parsed only the *syntax* of `conditions_schema_version`;
`CjRsExtractor` did not require `bias_v`, and recovered `frequency_hz` from the numerical series
when the condition record omitted it. So a payload with no recorded bias and no recorded frequency
produced a DERIVED Cj and Rs that looked fully conditioned.

**The repair delegates to the registered schema.** `silicon_photonics/pn_junction_ac@1.0.0` already
declares `bias_v`, `frequency_hz` and `device_length_um` as required, and
`ConditionSchemaRegistry.validate` already refuses a missing required field, an undeclared field
and an unregistered version. A second list would be two statements of one contract, corrected
separately. `CjRsExtractor` takes the registry as a **required** constructor argument -- the
`DiagnosticsService` lesson reapplied: an extractor built without one could only skip the check.

**The line this repair does not cross.** EVI-002's UNKNOWN semantics are intact, and the two kinds
of absence now get different answers:

| | Answer | Why |
|---|---|---|
| missing scientific **value** (no impedance series; a reactance the series-RC model cannot reduce; `frequency_hz` declared as `0`) | `UNKNOWN`, no value, warning | the provenance IS recorded; what is missing is a derivable number |
| missing condition **provenance** (`bias_v`, `frequency_hz`, `device_length_um`, an undeclared field, an unregistered version) | **refused** | T-EVI-001 says *admission fail*; a DERIVED value with no conditions is a number nobody can compare |

Attacks, each its own probe in `domains/test_cj_rs_evidence_contract.py`: missing `bias_v` (with
the array still present, so recovery would be possible); missing `frequency_hz` (likewise -- the
attack the old code actually lost); missing `device_length_um`; undeclared field; unregistered
schema version; plus the regression control that a complete record produces exactly what it
produced before the check existed.

### C (P1) — the simulation ResourceDemand was not on the Job

**The defect.** §10.7 requires a long-running Job to carry `resource_requirements (including
license seat)` and §17.16 makes it canonical. The requirement lived only on
`SimulationRequest.resource_demand` -- an in-flight object -- while the durable Job was submitted
with `resource_requirements = {}`. A reloaded `WAITING_RESOURCE` Job could not say what it was
waiting for.

**The repair.** `submit_simulation_job` binds `ResourceDemand.as_requirements()` onto the Job and
checks the demand against the Capability's `license_constraints` -- at submission, which is the
last place the descriptor is still in hand. `run_simulation` then reads the requirement **off the
Job** and checks the request against it, rather than trusting it: a resumer is a new caller in a
new process, and one that could supply a different demand could move a parked job to a different
pool.

Five fail-closed cases, one probe each
(`contract/test_resource_demand_binding.py` and `unit/test_capability_planning.py`):

1. request declares a demand, Job carries none → refused
2. Job is bound to one resource, request names another → refused
3. seat counts differ → refused
4. demand names a resource the Capability does not declare → refused **at submission**; and the
   mirror, a seat-requiring Capability submitted with no demand → refused
5. a reloaded `WAITING_RESOURCE` Job → `bound_demand(job)` reconstructs it; the vertical does this
   **through a second connection** so nothing in-flight is shared

WAITING_RESOURCE remains contention, not failure: `attempt_count` is untouched, `structured_error`
is `None`, and §17.24 still reads the parked job as degraded availability.

### D (P1) — T-SIM-002 stopped at `evaluate()`

**The defect.** The existing test proved the DomainPack's policy semantics correctly and stopped at
`TransitionPolicy.evaluate()`. §26 types T-SIM-002 `e2e`, and between a verdict and a moved belief
sit the durable Decision, the BeliefRevisionEvent and the re-derivation `v3.3-a13` requires on the
read path. A policy could be perfect and the projection still land somewhere else.

**The repair** is `tests/e2e/test_sim_fidelity_vertical_postgres.py`, which runs the existing M0b
machinery -- `BeliefEpisode.attempt_transition` and `BeliefEpisode.project` -- and writes no second
state mutator. `test_this_file_declares_no_second_belief_path` parses the module and fails if one
appears.

    ACTIVE -> CONTRADICTS relation backed by SIM_COARSE
           -> canonical evaluate()        (hard-locked M0b)
           -> durable BeliefTransitionDecision  (`005d`)
           -> BeliefRevisionEvent               (`005a`)
           -> verified replay                   (re-derive, then fold)
           -> projection == CHALLENGED

and the prohibition, asserted **against the store**: the same coarse evidence attempting
`CONTRADICTED` produces `DENY/AUTHORITY_INSUFFICIENT`, no event is written, and the projection is
still ACTIVE. Positive controls: SIM_STANDARD and SIM_VALIDATION both reach CONTRADICTED durably,
and a separate probe shows the fidelity gate is not the only requirement -- the same standard-
fidelity contradiction with no corroboration returns NEED_MORE_EVIDENCE.

**Non-vacuity, checked by hand.** Changing the reject policy's `required_authority_rule` from
`SIM_STANDARD` to `SIM_COARSE` makes
`test_the_same_coarse_contradiction_cannot_produce_a_contradicted_event` fail. The test catches a
broken gate rather than describing a working one.

## 10. The second-review repair — execution scope

The second independent review accepted repairs A–D and named one remaining P0. **None of A–D was
redesigned**: `dispatch_action` is still untouched, `CjRsExtractor` still takes a required
`ConditionSchemaRegistry` and still recovers no frequency from a series, the durable ResourceDemand
is still authoritative after a reload, and there is still exactly one belief mutator.

### E (P0) — execution scope was not bound across the layers that describe one call

**The defect.** A tool call is described four times on its way to a backend, and nothing compared
the descriptions:

    ToolAction.project_id          what `dispatch_action` budgets against
    ToolRequest.project_id         what the registry hands the implementation
    SimulationRequest.project_id   what the backend is asked to run
    Job.project_id                 what the durable record says was admitted

Four independent strings for one fact, so `A`, `B`, `C`, `D` was representable. The layer that
*paid* was not the layer that *ran*: project A's caps admitted an action, the implementation
executed inside project B, and the Run landed on project D's Job. `trace_id` had the same shape —
OPS-003 reassembles a call from its spans, and a trace that changes halfway down reassembles into
two unrelated halves — and so did `capability_id`, which §9.5 plans and §17.18 prices.

**Why late detection was not a repair.** `JobStore.complete` *did* catch the project case:
`_RUN_LINKAGE` checks it precisely because *"a run scoped away from its job escapes SEC-002 through
the side door"*. But by the time it speaks, the Job has been moved to RUNNING, a licence seat has
been held and the solver has run to completion, so what it refuses is the **record** of an
execution that already happened inside a project that never admitted it. The requirement is that
the execution not happen.

**The repair is one comparison, made at the three boundaries that hold both sides.**
`lab_brain.tools.scope` is ninety lines: an `ExecutionScope` (a layer label plus project, trace and
an optional capability), a `require_same_scope` that reports **every** dimension that disagrees,
and `ExecutionScopeMismatch`. It compares strings; it does not know what a CHARGE sweep is.

| Boundary | Where | When |
|---|---|---|
| `ToolAction` ↔ `ToolRequest` | `tools/dispatch.py` | first statement of `dispatch` — before the descriptor is resolved, before an estimate exists, before a span is opened, before `perform` is built |
| `ChargeAcSweepRequest` ↔ its nested `SimulationRequest` | `domains/silicon_photonics/tools.py` | `model_validator(mode="after")` — the object cannot be constructed |
| `SimulationRequest` ↔ `Job` | `tools/execution.py` | step **0**, after the Job resolves and before `jobs.transition`, `broker.acquire`, any lease, and `backend.execute` |

**Neither side wins, and that is the difference from `_require_bound_demand`.** A ResourceDemand
has an authoritative copy — the Job's — because a resumer may legitimately restate a requirement.
An identity has no such reading: if the layer that was budgeted and the layer that will execute
disagree about the project, there is no rule that makes one of them correct. So no preference is
expressed and the execution does not happen.

**A scope mismatch is not a budget outcome.** §17.17's BLOCKED span means *this project ran out of
money*, and a supervisor holding `BUDGET_OVERRUN` can release it. There is no scope under which
*execute inside a project the gate never evaluated* is releasable, so the refusal leaves the
governance channel entirely: `dispatch` raises and returns no `ToolDispatchResult` to mistake for a
decision. It also cannot live inside `perform` — `dispatch_action` writes the ESTIMATED row and
consumes the approval claim *before* calling it, and wraps the call in `except Exception`, so a
check made there would fire after the money was recorded and would close the span FAILED, which is
the *the solver crashed* channel.

**No new identifier was added.** §7's rule is kept: `ToolAction` gains no `capability_id`, the
`Capability` model is not duplicated, and the capability chain is closed by making the identities
that already exist agree — `charge_ac_descriptor()` and the request validator read the same
`CHARGE_AC_CAPABILITY` constant, so the pack has one capability identity rather than two.

**Before / after.** Eight guards, one probe each, with fatal spies (implementation, broker,
backend). *Job mutated / seat taken / backend entered / ledger written / Run created* is reported
for every attack.

| # | Attack | Before | After |
|---|---|---|---|
| 1 | `ToolAction.project_id = A`, `ToolRequest.project_id = B` | gated against A, executed in B | `ExecutionScopeMismatch`; tool not entered, **no span opened**, no ESTIMATED or ACTUAL row, approval **not** consumed |
| 2 | `ToolAction.trace_id = T1`, `ToolRequest.trace_id = T2` | two half-traces | same, and the refusal names **only** the trace |
| 2a | the same, with a valid scoped supervisor approval attached and a cap below the estimate | n/a | still refused, still unconsumed — an approval releases an over-budget action, not an incoherent one |
| 3 | `ChargeAcSweepRequest.project_id ≠ simulation.project_id` | constructible; the tool unwrapped the nested request | refused at construction |
| 4 | `…trace_id ≠ simulation.trace_id` | constructible | refused at construction |
| 5 | `simulation.capability_id ≠ the descriptor's` | constructible | refused at construction |
| 6 | `SimulationRequest.project_id ≠ Job.project_id` | RUNNING, seat held, solver ran, **then** `complete` refused | Job still QUEUED, `attempt_count == 0`, `result_run_id is None`, `resume_stage is None`, no lease, backend never entered, no Run |
| 7 | `SimulationRequest.trace_id ≠ Job.trace_id` | executed | same, and only the trace is named |
| 8 | `SimulationRequest.capability_id ≠ Job.capability_id` | executed | same |
| — | mis-scoped **and** mis-demanded at once | n/a | refused as a **scope** error, not a `ResourceBindingError` — an operator told *the pools disagree* would go and look at the queue |

Positive controls, because refusing everything would satisfy all eight: a matching envelope
dispatches and the implementation receives the project and trace the `BudgetRequest` was built
from; a coherent `ChargeAcSweepRequest` constructs; a matching request executes against the real
broker and the real backend and the Run inherits the Job's project, trace and capability.

**The chain, asserted as equality end to end.** Step 4 of
`test_the_full_tool_chain_runs_budgeted_through_the_typed_registry` — the vertical that has a
`ToolAction` — reads every layer back from PostgreSQL and requires one value per dimension:

    ResearchEpisode -> ToolAction -> ToolRequest -> SimulationRequest -> Job -> Run   project_id
    ResearchEpisode -> ToolAction -> ToolRequest -> SimulationRequest -> Job -> Run   trace_id
                       ToolDescriptor -> SimulationRequest -> Job -> Run              capability_id

The Episode is the head of the chain rather than one more row: §17.3 makes it what the trace
belongs to, so an execution agreeing with itself all the way down and disagreeing with its Episode
would still be unattributable. The capability row has no `ToolAction` entry — that is §7's rule,
not an omission.

**Eight, not seven.** The review counted seven equalities. The capability chain
`ToolDescriptor -> SimulationRequest -> Job` has two links, and the second is what stops a Job
accepting an execution its own Capability never planned; it is guarded and mutated separately.

**Mutation anchors.** Eight entries, each making **one** dimension compare against itself rather
than deleting a `require_same_scope(...)` call. Deleting a call would disable three dimensions at
one boundary and prove only that *something* there is tested; reading the same value into both
`ExecutionScope`s leaves the other two live, so exactly one equality is under attack. All eight
killed, each by the probe written for it.

## 11. The final M2 blocker — the Episode that pays is the Episode whose Job executes

The review of §10 accepted repairs A–E and named one remaining blocker. **None of A–E was
redesigned**: `dispatch_action` is untouched, `BudgetedToolDispatcher` is still the one production
tool call, the project/trace/capability guards and their eight mutation anchors are unchanged and
still killed, `CjRsExtractor` still requires its `ConditionSchemaRegistry`, the durable
ResourceDemand is still authoritative after a reload, and the SIM-002 vertical is untouched.

### F (P0) — the budgeted Episode was not bound to the executing Job's Episode

**The defect.** COST-001 checks *project/episode caps*, and everything it writes or spends is keyed
by `ToolAction.episode_id`: `BudgetRequest.episode_id`, both `cost_entries` rows, and the
`BudgetApproval` (§17.17.1: *ONE action, in ONE episode*). The durable execution belongs to
`Job.episode_id` (§17.16). After E, those two could still differ with every other dimension agreeing:
`research_episodes.trace_id` is indexed, not unique, and `006b`'s trigger requires a Job to match
**its own** Episode's project and trace — which a Job in a second Episode on the same trace does. So
Episode E1's caps admitted the call, E1's approval was spent, E1 was charged, and E2's Job ran.

**Why adding the Episode to step 0 alone would not have been a repair.** `run_simulation`'s step 0
was the only place a request met its Job, and it runs inside `perform`.
`core.dispatch.dispatch_action` (hard-locked M0b) calls `perform` only after it has consumed the
approval claim and written the ESTIMATED row. A step-0-only check is correct about the execution and
too late about the money.

**The repair: the Episode is a fourth dimension of the execution scope, carried explicitly by every
layer, and the Job is resolved before the gate.**

| Boundary | Where | When | Dimensions |
|---|---|---|---|
| `ToolAction` ↔ `ToolRequest` | `tools/dispatch.py` | first statement of `dispatch` | project, trace, **episode** |
| `ChargeAcSweepRequest` ↔ its nested `SimulationRequest` | `domains/silicon_photonics/tools.py` | model validator — cannot be constructed | project, trace, **episode**, capability |
| **the request's `JobBinding` ↔ the durable `Job`** (new) | `tools/dispatch.py` `_bind_to_durable_job` | after the descriptor resolves; **before** the estimate, the span, the gate, the approval claim, the ledger and `perform` | project, trace, **episode**, capability |
| `SimulationRequest` ↔ `Job` | `tools/execution.py` | step 0, at execution — before `transition`, `acquire`, `execute` | project, trace, **episode**, capability |
| a simulation Job has an Episode at all | `submit_simulation_job` | before the Job is durable | — |

Composed, with the database's own link at the head:

    ResearchEpisode.episode_id   = Job.episode_id                006b FK + jobs_match_their_episode
    Job.episode_id               = SimulationRequest.episode_id  pre-gate, and again at step 0
    SimulationRequest.episode_id = ToolRequest.episode_id        ChargeAcSweepRequest validator
    ToolRequest.episode_id       = ToolAction.episode_id         first statement of dispatch
    ToolAction.episode_id        = BudgetRequest / CostEntry / BudgetApproval scope

**Never inferred.** `ToolRequest.episode_id` and `SimulationRequest.episode_id` are required fields,
`ExecutionScope.episode_id` has no default, and nothing anywhere reads an Episode off a project and a
trace — that reading is exactly the one two Episodes can both satisfy.

**How the domain-free dispatcher knows which Job.** A request that executes a durable Job says so:
`ToolRequest.job_binding()` returns `None` by default, and `ChargeAcSweepRequest` returns a
`JobBinding` read off `self.simulation` — the object `ChargeAcSweepTool` hands the runner, and whose
`job_id` `run_simulation` executes. The binding carries the nested execution's scope, so the pre-gate
comparison is literally step 0's comparison made earlier, with the same two layers named. It is a
method rather than a field: it restates nothing, so there is nothing more to disagree.

**Why the Job is compared twice.** The pre-gate check is what keeps the approval unspent and the
ledger clean. Step 0 is against the row as it is at the moment of execution: it holds for a resumer
that never passed through a dispatcher, and for a Job re-pointed between the two checks —
`jobs.episode_id` is not immutable in `006`/`006b`, and making it so would have been a migration this
repair did not need.

**Fail closed where the check could otherwise be skipped.** A `run_*` request whose `job_binding()`
is `None` is refused (`ToolDispatchRefused`): a backend execution is a Job, and a run request that
does not say which one could not be checked. A binding naming a Job that does not resolve is refused.
A Job whose `episode_id` is `None` compares as `None` against the Episode that is paying and is
refused at both checks, and `submit_simulation_job` refuses to persist one in the first place.

**What changed in the API, all of it M2 code.** `ExecutionScope` gains `episode_id`; `JobBinding` is
new; `ToolRequest` gains `episode_id` and `job_binding()`; `SimulationRequest` gains `episode_id`;
`BudgetedToolDispatcher` takes a **required**, read-only `jobs: JobStore` — a dispatcher that could
be built without one could only compare the paying Episode with itself. **No migration, no core
file, no amendment, no ADR, no new Requirement or Test ID, no new marker pair.** `episode_id` is
§17.16's and §17.17's existing identity, not a new identifier. 60 ↔ 60.

**One new obligation on a DomainPack, stated rather than implied.** A pack's `run_*` request must
override `job_binding()` to be dispatchable; the dispatcher refuses one that does not, at dispatch
rather than at registration. The ToyDomain's run tool is exercised by EXT-001 through the raw
registry, which asks a typing question and not a governance one, and is unaffected.

**Before / after.** Fatal spies throughout (implementation, broker, backend); every refusal reports
span, ledger, approval, Job, seat, backend and Run.

| # | Attack | Before | After |
|---|---|---|---|
| F1 | `ToolAction.episode_id = E1`, `ToolRequest.episode_id = E2` | not expressible — the request had no Episode, so nothing said which one it was for | `ExecutionScopeMismatch` at the first statement, naming only the Episode; no span, no ledger row, approval unconsumed |
| F2 | envelope in E1 wrapping a `SimulationRequest` for E2 | not expressible | refused at construction |
| F3 | action, request and simulation in E1; **Job in E2**; project, trace, capability equal | gate ran, **approval consumed**, ESTIMATED and ACTUAL charged to E1, E2's Job moved to RUNNING, seat taken, backend ran, Run minted | refused **before the gate**: no span, no `cost_entries`, approval unconsumed, Job exactly as submitted, no lease, backend never entered, no Run — unit **and** PostgreSQL |
| F4 | F3, over budget, with a valid scoped PI approval attached | the approval released E2's execution | approval unconsumed; `consumed_at` / `consumed_by_action` still NULL in `budget_approvals` |
| F5 | `Job.episode_id is None` | executed | refused before the gate, refused at step 0, and refused at submission |
| F6 | `run_simulation` called directly (a resumer) with E1 against E2's Job | executed | step 0 refuses; Job QUEUED, `attempt_count` 0, no lease, no Run |
| F7 | a `run_*` request that binds no Job | n/a | `ToolDispatchRefused` before the gate |
| F8 | a binding naming a Job that does not resolve | step 0's `ResourceBindingError`, after the approval | `ToolDispatchRefused` before the gate |
| F9 | Job differs from the request **only** in project, trace or capability | refused at step 0 — after the approval and the ESTIMATED row | refused before the gate, each naming itself alone — strictly earlier than E |
| F10 | a `ToolRequest` or `SimulationRequest` that omits its Episode | n/a | refused at construction |

**Positive controls**, because refusing everything would satisfy every row above: a matching dispatch
runs and both ledger rows and the span carry the Job's Episode; a matching `run_simulation` executes
and the Run's Job is in the request's Episode; a coherent `ChargeAcSweepRequest` constructs and binds
exactly its nested request's Job; and in PostgreSQL **the same over-budget action with the same
approval** is released when its Job is in the budgeted Episode — `ALLOWED_BY_APPROVAL`, the approval
row consumed by `act:m2-run`, the Job SUCCEEDED, `cost_entries` and the TOOL_CALL span all on E1.

**The chain as equality, read back from PostgreSQL.** Step 4 of
`test_the_full_tool_chain_runs_budgeted_through_the_typed_registry` gains an `episode_id` row:

    ResearchEpisode -> ToolAction -> ToolRequest -> SimulationRequest -> Job
        -> CostEntry[ESTIMATED] -> CostEntry[ACTUAL] -> ExecutionSpan[TOOL_CALL]     episode_id

The ledger rows and the span are read from their own tables, so "the cost was attributed to the
Episode that ran" is a statement about durable rows. There is no `Run` entry: §17.4's Run reaches its
Episode through its Job, which is the `Job` entry.

**Non-vacuity, checked by hand.** Disabling only the pre-gate Episode comparison makes the PostgreSQL
probe fail with *"an approval was spent on a Job outside its Episode"* — the pre-repair behaviour —
while its scope-message assertions still pass, because step 0 still refuses the execution. The probe
therefore distinguishes *refused in time* from *refused too late*, which is the whole blocker.

**Mutation anchors.** Thirteen entries, one guard each, every one killed by the probe written for it:

| Entry | Guard |
|---|---|
| `the_gated_episode_need_not_be_the_requested_episode` | `ToolAction.episode_id == ToolRequest.episode_id` |
| `a_sweep_envelope_may_wrap_another_episodes_simulation` | envelope Episode == nested request Episode |
| `a_simulation_may_execute_another_episodes_job` | step 0: `SimulationRequest.episode_id == Job.episode_id` |
| `the_budgeted_episode_need_not_be_the_jobs_episode` | pre-gate: the Job's Episode |
| `the_pre_gate_binding_ignores_the_jobs_project`, `…_trace`, `…_capability` | pre-gate: the other three, one entry each |
| `a_run_request_may_bind_no_job` | a `run_*` request with no binding is refused |
| `an_unresolvable_bound_job_is_not_refused_as_wiring` | a binding to a missing Job is refused |
| `a_sweep_binds_a_job_other_than_the_one_it_executes` | the binding names `simulation.job_id` |
| `a_simulation_job_may_be_submitted_with_no_episode` | submission refuses an Episode-less Job |
| `a_tool_request_may_leave_its_episode_unstated`, `a_simulation_request_may_leave_its_episode_unstated` | both fields are required |

One candidate is deliberately absent: the binding's scope reading the envelope's Episode instead of
the nested request's. The model validator makes those equal, so that mutant is equivalent and would
survive for the right reason.
