# M2 — Silicon Photonics Tool Layer: readiness for independent sign-off

Date: 2026-09-23
Milestone: **M2 — Silicon Photonics Tool Layer**, `IN_PROGRESS` — implementation complete, awaiting
independent sign-off
M1: `IN_PROGRESS`, implementation complete, awaiting independent sign-off
(docs/implementation/M1-readiness.md)
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
| 2 | **SIM-002** | low-fidelity contradiction 只使 hypothesis → CHALLENGED，不得直接 → REJECTED | two registered §8.2.1 `TransitionPolicy` records + `SiliconPhotonicsAuthorityPolicy`. **No core file changed**: `TransitionPolicy.evaluate` is untouched M0b code and is what refuses | `e2e/test_sim_fidelity_gate_postgres.py` (12) | READY |
| 3 | **SIM-003** | static test rejects `eval_script`-class interfaces; every invocation resolves through the typed ToolRegistry | `tools/registry.py` + `tools/contracts.py`; the static half is `unit/test_no_arbitrary_script_execution.py`, which existed since M0a and was deliberately unmarked | `unit/test_typed_tool_registry.py` (15), `e2e/test_m2_vertical_postgres.py` (the whole chain through `invoke`) | READY |
| 4 | **EVI-001** | Cj/Rs fixture missing unit / normalization basis / bias-frequency condition / extraction method fails; complete fixture round-trips | `tools/extraction.py` `ExtractedQuantity` refuses a value missing any of the four; `domains/silicon_photonics/extractors.py` supplies all four | `domains/test_cj_rs_evidence_contract.py` (8) | READY |
| 5 | **DOM-SP-001** | Rs trend validator 只存在 SiPh DomainPack，移除 plugin 後 core 仍可啟動 | `domains/silicon_photonics/validators.py`; core has no place to put a rule — `ValidationReport` keys findings by an opaque `rule_id` | `domains/test_domain_pack_boundary.py` (14) | READY |
| 6 | **DOM-SP-002** | 同一 `extract_cj_rs` contract 通過 simulated 與 measured impedance fixtures | one `MetricExtractor` protocol, one `ExtractionInput`/`ExtractionResult` pair; `ToolDescriptor` refuses an `extract_*` tool that names a backend | `domains/test_shared_extractor_contract.py` (9), `e2e/test_m2_vertical_postgres.py` | READY |
| 7 | **VER-002** | Planner 對無 capability descriptor 的 backend 不可規劃；有 descriptor 時依 produces/requires match | `verification/capability_registry.py` + `verification/planner.py`; `007c`'s `capabilities` makes the absence durable | `unit/test_capability_planning.py` (20), `e2e/test_m2_vertical_postgres.py` | READY |
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

Local, full history, PostgreSQL last.

| Gate | Result |
|---|---|
| `ruff format` / `ruff check` | clean |
| `mypy` (strict) | clean, **136** source files |
| Backend-free suite | **1258 passed**, 617 skipped |
| Migration replay from empty | **38 applied** (fresh `lab_brain_m2final`) |
| Migration idempotency | `pending 0`, second run a no-op |
| Full PostgreSQL profile | **1875 passed**, 0 skipped |
| Executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1','M2']`; **45** requirements with a passing test |
| Status freshness | up to date |
| Spec conformance | **205 passed** |
| Requirement ↔ Test | **60 ↔ 60** |
| Obligation inventory | **84**, in sync |
| Schema drift / unbound / stale | all empty |
| Mutation battery | **90/90 killed** (75 through M1, + 15 M2 anchors) |
| M1-P1 benchmark | current, byte-identical |

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
