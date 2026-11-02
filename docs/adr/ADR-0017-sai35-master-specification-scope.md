# ADR-0017: SAI 3.5 as the master specification candidate of the autonomous AI scientist, and OD-10 proposal A' for the SAI 3.4 boundary

Status: Proposed — candidate only; not accepted
Date: 2026-11-02
Affected Requirements: S35-GOV-001 … S35-CMP-009 (77 SAI 3.5 candidate requirements; D-001–D-046 retired); no SAI 3.3 requirement and no SAI 3.4 obligation (ASM-001–018, G0–G9) changes
Human Approval Required: Yes — Owner decisions OD-01 (candidate), OD-10 (boundary mechanism) and, for activation, OD-16 after an Independent Chief Auditor review
Spec revision: SAI `3.5.0-master-candidate.1`; active profile unchanged (SAI 3.4 `3.4.0-phased.1` with the SAI 3.3 executable profile)

Supersedes in part [ADR-0016](ADR-0016-sai35-discovery-candidate.md) (scope of the SAI 3.5 candidate
and its OD-10 handling). ADR-0015 is used on the unintegrated G0 line.

## Context

The discovery candidate (`3.5.0-discovery-candidate.1`) specified autonomous discovery and its
independent acceptance, but an implementation agent without conversation history could not build
the finished product from it: the twelve required capabilities were not all specified, several
components had no contract (Hypothesis Brain, model qualification, worker contract, feedback,
envelope, autonomy levels, permissions), and "matched budget" could be met by caps while realized
spend differed fourfold. An auditor also found that commit `9d44198` widened the SAI 3.4 allowlist
(`docs/spec/sai34/activation.yaml`, `check_activation.py`) while the candidate's documents and
checker said no SAI 3.4 file was edited.

Implementation facts at this date: G0 is NOT PASSED; the G0 line (`f41758c`) is unintegrated; its
forged-authorization read-path bypass is fixed on the unmerged branch
`g0-authorization-read-path-closure`, pending audit; the offline Discovery Loop (`118a4ac`) is
engineering evidence only; nothing licensed exists.

## Constraints

SAI 3.3 and SAI 3.4 files, ACTIVE_SPEC.yaml, the active registry and milestones stay byte-identical
to `a38ad63`, with no exception. No runtime code, migration, test or script changes. G0–G9 intact;
`READY_FOR_REAL_RESEARCH` false. Owner gates for money, licenses, physical experiments and
publication are not bypassed. History is preserved: nothing is rewritten or deleted; superseded
files keep their content.

## Options Considered

Scope of SAI 3.5:

1. **A master specification candidate covering the complete product (chosen).** One entry point
   with precedence rules and a navigation map; 77 testable requirements in 21 areas with owner,
   phase, gates, status and inherited links; normative appendices for lifecycle, architecture,
   records and states, provenance and novelty, governance, UX and glossary, deployment, roadmap,
   G-D, the A/B/C protocol, traceability and compatibility. Cost: a larger document set to keep
   consistent, held by a checker.
2. **Patch the discovery candidate.** Rejected: the gaps were structural, and keeping D-NNN IDs that
   look like SAI 3.4's D-01–D-08 invites confusion.
3. **Amend SAI 3.4.** Rejected: protected files; a just-integrated, narrowly authorized basis.

Keeping the SAI 3.4 boundary while the candidate files exist (OD-10):

- **(A') Run the unmodified SAI 3.4 checker on the tree without the candidate (proposed,
  recommended).** `docs/spec/sai35/candidate-paths.txt` lists every path the candidate adds;
  `check_sai34_boundary_without_candidate.py` refuses protected, runtime, migration, test, script
  and CI paths, paths that existed at `a38ad63`, an edited `docs/spec/sai34/` and any mismatch
  between the list and the real diff, then deletes exactly those paths in a temporary detached
  worktree of HEAD and runs `docs/spec/sai34/check_activation.py --self-test` there. Its self-test
  also proves the same SAI 3.4 checker still fails on the full tree. Cost: the boundary of the
  candidate rests on an enumerated list, checked twice.
- **(B) Owner-approved widening of the SAI 3.4 allowlist.** Edits SAI 3.4 files; tried in
  `9d44198` without approval and reverted.
- **(C) Keep SAI 3.5 off the integration line.** No boundary question, but the candidate cannot be
  reviewed on the line it targets.

## Decision

Propose `docs/spec/SAI_3.5.md` as the master specification candidate with its appendices in
`docs/spec/sai35/`, the regenerated registry and the rewritten checker. Keep
`SAI_3.5_Discovery_Candidate.md` as a superseded historical record. Retire D-001–D-046 through an
individual audit and a change register. Revert `9d44198` and implement proposal A' as a proposal
pending OD-10; the CI step that ran the SAI 3.4 checker now runs it through the wrapper.

## Consequences

Positive: an external agent can build from one entry point; every requirement has an acceptance
test, owner, phase, gate and evidence-backed status; the SAI 3.4 boundary holds with the SAI 3.4
files untouched; G-D and G0–G9 stay independent; arm comparisons are on realized consumption.

Negative: more documents; English normative text while SAI 3.3/3.4 are mostly zh-TW (OD-13); the
bare SAI 3.4 checker fails on the full tree by design; many requirements rely on code that exists
only on unintegrated, unaudited lines.

## Migration / Rollback

No runtime, schema or data migration. Rolling back: delete the candidate paths listed in
`candidate-paths.txt`, remove the SAI 3.5 CI step and restore the SAI 3.4 CI step to its `a38ad63`
command, in a new commit. Activation, if ever approved, follows
[activation-proposal.md](../spec/sai35/activation-proposal.md).

## Tests / Evidence

`python docs/spec/sai35/check_candidate.py --self-test`;
`python docs/spec/sai35/check_sai34_boundary_without_candidate.py --self-test -- python docs/spec/sai34/check_activation.py --self-test`;
`python docs/spec/sai34/check_candidate.py --self-test`. All `T-S35-*` are planned obligations; none
is implemented or executed. No G-D level has been evaluated.
