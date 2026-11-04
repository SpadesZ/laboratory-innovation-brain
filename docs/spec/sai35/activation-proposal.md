# SAI 3.5 — Appendix N: Activation proposal

Version: `3.5.0-master-candidate.2`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: informative. This is a proposal; none of its steps has been taken. It refines the
activation boundary of [SAI 3.5](../SAI_3.5.md) §5 and S35-GOV-005.

## 1. Conditions

SAI 3.5 may become the primary active master specification **only** after both:

1. an Independent Chief Auditor has reviewed this candidate (requirements, appendices, registry,
   checkers, compatibility analysis) and recorded a verdict; and
2. the Owner has explicitly approved activation (OD-16), naming the version and commit approved.

Until then it is CANDIDATE — NOT ACTIVE. Neither condition can be met by CI, a developer, a coding
agent or this document. Activation does not by itself make any requirement complete, pass any gate
or change `READY_FOR_REAL_RESEARCH`.

## 2. What activation means

Activation would make SAI 3.5 the architecture entrypoint for future work, with SAI 3.3 and SAI 3.4
still inherited unchanged and still winning where SAI 3.5 is silent. Two forms are possible, and
choosing one is part of OD-16:

| Form | Meaning | Consequence |
|---|---|---|
| architectural basis (like SAI 3.4 P0-BASIS) | SAI 3.5 is the architectural entrypoint; S35 requirements are named obligations with deferrals; the executable profile stays SAI 3.3 | no runtime parser or ratchet change; S35 requirements stay `tests: []` with deferral and review date |
| executable profile | S35 requirements enter the runtime namespace with real test bindings and the executed-coverage ratchet | needs the full migration of §3 step 6 and independent slices; comparable to SAI 3.4 P-FULL-RUNTIME |

## 3. Steps (in order)

1. **Audit.** Independent Chief Auditor review; findings recorded; corrections applied on the
   candidate branch with the checker passing.
2. **Owner decisions.** OD-01 (candidate accepted), OD-10 (boundary mechanism), OD-13 (zh-TW
   normative edition, if required before activation), OD-16 (activation and its form).
3. **ADR.** ADR-0017 moves from Proposed to Accepted (or a successor ADR records the decision);
   ADR-0016 is marked superseded.
4. **Freeze.** Tag the approved commit; record the SHA-256 of every SAI 3.5 document in a new
   activation registry (proposed path `docs/spec/sai35/activation.yaml`) with the S35 requirement
   list, deferrals, review dates and owners, in the pattern of the SAI 3.4 activation registry.
5. **Entrypoint and checker changes.**
   - `docs/spec/ACTIVE_SPEC.yaml`: `architecture_version` → the approved SAI 3.5 version,
     `architecture_spec` → `docs/spec/SAI_3.5.md`, `activation_registry` → the new registry,
     `activation_state` → the approved form; `executable_*` fields unchanged unless the executable
     form is chosen; `ready_for_real_research: false` unchanged.
   - SAI 3.4 activation checker: SAI 3.4 is then a frozen inherited profile. Either keep running the
     unmodified SAI 3.4 checker on the tree without SAI 3.5 (proposal A' continued), or add a
     successor checker that freezes the SAI 3.4 files by hash and runs the SAI 3.4 mapping checks;
     editing `docs/spec/sai34/*` stays forbidden without its own Owner decision.
   - SAI 3.5 checker: replace the NOT ACTIVE assertions by activation assertions (approved SHA,
     registry hashes, deferrals with review dates), keep every protected-hash and traceability check.
   - CI: add the activation checker step; keep every existing step.
6. **Executable form only.** Add S35 identifiers to the runtime spec parser's namespace, bind real
   tests with markers to each requirement, extend `docs/milestones.yaml` or add a parallel milestone
   catalog through its own decision, extend `scripts/update_status.py` and the executed-coverage
   ratchet, and the normative-statement coverage audit (§23.5). Each is an independent slice with
   its own CI evidence.
7. **Status.** Regenerate `IMPLEMENTATION_STATUS.md` from a whole-suite run; record activation in
   the CHANGELOG; update the zh-TW report.

## 4. Rollback

Restore `ACTIVE_SPEC.yaml` to its SAI 3.4 values in a new commit, mark the activation registry
withdrawn, keep every record; never delete history or force-push.

## 5. What activation does not do

It does not integrate the G0 line or the discovery line (OD-09), pass G0, evaluate any G-D level,
authorize money, licenses, physical experiments or publication, settle A3, A9 or A12, or close any
SAI 3.4 decision D-01–D-08.
