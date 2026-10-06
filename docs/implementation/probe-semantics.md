# Probe evidence names its qualification semantics, and a full LOCAL verification smoke

Date: 2026-10-06
Scope: a P1 found in review of the conformance-suite slice, and the first LOCAL smoke through the
verification and belief path. **Not a milestone.** No Requirement or Test ID was added and no
milestone status changed. The qualification architecture, the suite, the prompts, the contracts, the
parser, the research minimum (5), VER-004, routing, budget, the deadline, egress, credentials,
transport locality and the redirect policy are unchanged. The Lumi Agent benchmark was not run.

## 1. The P1: evidence laundered across semantics

A lock's fingerprint names the qualification semantics in force when it is made
(`QUALIFICATION_DIGEST`: probe payloads, role prompts, response contracts), and a lock made under
other semantics is stale. But `lock()` decided which probe rows it could count by `probe_version`
alone, and a probe row did not record the semantics it ran under. So:

1. probes run under version V and semantics D1;
2. a prompt, a response contract or a probe payload changes -- D2 -- and nobody bumps V;
3. the existing lock is (correctly) stale; the operator unlocks the model;
4. `lock()` sees V == V and counts the D1 rows, and computes a fingerprint under D2 -- a lock that
   passes as current, on evidence from semantics no longer in force, without a test.

The guard depended on a developer remembering a version bump.

## 2. The fix

- **Each probe records the semantics it ran under.** `012m` adds
  `llm_capability_probes.qualification_digest` (64 hex characters, or NULL); the registry writes the
  digest in force with every probe. No row is rewritten: rows written before carry NULL, and the
  table stays append-only (`012e`'s guard is unchanged).
- **A lock counts only probes whose recorded digest is the one in force** (`registry.lock`). Any
  other digest -- or none -- is refused before anything is written: `lock.outdated_tests`, "model
  X's latest tests of … were not run under the qualification semantics in force (probe-3.0.0
  9a34d824c9fd; theirs: …); test it again before confirming it". The probe version is no longer
  what decides; it is part of the digest.
- **A lock already made on unproven evidence is refused at use** (`registry.lock_problem`): after the
  fingerprint check, every locked capability's counted probe must carry the digest in force.
  Readiness lists it, `load_active_runtime` refuses it before research or any credential, and the
  guide says it as the stale-lock step ("…counts tests (…) whose qualification semantics were not
  recorded or are no longer in force; test it again and confirm it again"). Every lock made before
  `012m` therefore needs one re-test -- the fail-closed reading of "semantics that cannot be proven".
- The semantics are still the same digest; it is now built by `probes.qualification_inputs()` (and
  `contracts.contract_digest`) so that a test can change one part of it with the version unchanged.
  `QUALIFICATION_DIGEST` did not change value (`9a34d824…`).

## 3. Tests

| Proven | Where |
|---|---|
| a prompt-text change alone (probe version unchanged) makes the lock stale and its evidence unusable: unlock → immediate re-lock refused; after a test under the digest in force a new lock succeeds, under a new fingerprint | `tests/integration/test_probe_semantics_postgres.py` |
| the same for a response-contract change alone (`contract_digest`, contract version unchanged) | same |
| the same for a probe-payload change alone | same |
| probe rows that recorded no semantics qualify nothing; a lock already made on them is refused by readiness and by `load_active_runtime` | same |
| earlier probe and lock rows byte-for-byte after re-qualification; every probe records the digest it ran under | same; `tests/e2e/test_web_hypothesis_conformance_postgres.py` (web: research refused before any model call, the re-lock refusal in zh-TW, InferenceProvenance, lock and probe rows as `t::text` -- with only the digest changed) |
| the guide says a lock on unproven evidence as the stale-lock step | `tests/unit/test_web_llm_guide.py` |

Mutation battery: three new entries (a probe recorded without semantics, a lock on unproven evidence
trusted at use, the guide's pattern) and two re-anchored (the lock's check, now on the digest; the
suite version in the digest).
