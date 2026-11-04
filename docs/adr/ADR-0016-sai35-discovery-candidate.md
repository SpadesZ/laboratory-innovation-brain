# ADR-0016: Propose SAI 3.5 autonomous discovery as a candidate, not activate it, and keep the branches unintegrated

Status: Superseded in part by [ADR-0017](ADR-0017-sai35-master-specification-scope.md) (2026-11-02, SAI `3.5.0-master-candidate.1`) — candidate only; not accepted
Date: 2026-11-01
Affected Requirements: D-001–D-046 (SAI 3.5 candidate namespace); none of the SAI 3.3 requirements or SAI 3.4 ASM-001–018 are changed
Human Approval Required: Yes — Owner decision OD-01 on the candidate; activation would need a separate decision
Spec revision: SAI `3.5.0-discovery-candidate.1`; active profile unchanged (SAI 3.4 `3.4.0-phased.1` with the SAI 3.3 executable profile)

Supersession note (2026-11-02; the master candidate is now `3.5.0-master-candidate.2`): the master specification candidate `3.5.0-master-candidate.1`
([SAI_3.5.md](../spec/SAI_3.5.md)) replaces the discovery candidate this ADR proposed and retires
D-001–D-046 ([change register](../spec/sai35/change-register.md)). The OD-10 handling below is
superseded by proposal A' as recorded in ADR-0017. The text below is kept as the record of
2026-11-01, corrected only where it stated something false about the SAI 3.4 files.

Number note: ADR-0015 is used on the unintegrated G0 line (`58c68be`) for exploratory screening.
This ADR therefore takes 0016 so the two never collide when the lines are integrated.

## Context

SAI 3.4 specifies governed autonomous modeling and its acceptance gates G0–G9. The long-term goal
is broader: an autonomous AI scientist that discovers research problems, generates genuinely novel
and falsifiable physical hypotheses, reframes failed research and has its findings independently
validated. Nothing in G0–G9 measures discovery. A system can pass all of them and still never find
anything new. Meanwhile the work sits on separate branches:

- `integration-integrity-accounts` @ `a38ad63` holds the SAI 3.4 phased basis and `f3fadf6` code;
- `g0-owner-boundary-closure` @ `58c68be` holds 72 G0 commits (prospective-evidence rules
  `011p`/`011s`, spend administration, evaluation tooling) but not the SAI 3.4 documents; G0 is NOT
  PASSED and that line awaits an independent audit;
- `discovery-loop-offline` @ `118a4ac` (from `58c68be`) holds an offline Discovery Loop v0
  prototype with a synthetic benchmark; it is not integrated and not independently reviewed.

## Constraints

SAI 3.3 and SAI 3.4 stay byte-identical, including ACTIVE_SPEC.yaml, with no exception. An
earlier commit on this branch (`9d44198`) widened the SAI 3.4 change-boundary allowlist; it is
reverted. The SAI 3.4 boundary is instead held by OD-10 proposal A' (below), pending the Owner.
G0–G9 conditions stay intact. READY_FOR_REAL_RESEARCH stays false. No runtime, migration, test or
dependency changes in this delivery. No merge or cherry-pick from other branches. Owner gates for
money, licenses, physical experiments and publication are not bypassed.

## Options Considered

1. **Propose SAI 3.5 as a documentation-only candidate on its own branch from `a38ad63`
   (chosen).** It is reviewable now, it changes nothing that is active, and it states the
   integration questions instead of deciding them. Cost: the SAI 3.4 activation checker's closed
   documentation allowlist rejects the new files; OD-10 proposal A' runs that checker, unmodified,
   on the tree without the candidate. A second cost: a third line of documents to keep consistent.
2. **Amend SAI 3.4 with discovery requirements.** Rejected. It would reopen an architecture that
   was just integrated under a narrow Owner authorization, change protected files, and blur G0–G9
   with a different kind of acceptance.
3. **Integrate the G0 line and the discovery branch first, then write the spec.** Rejected for
   now. The G0 line is waiting for an independent audit, the discovery code is not reviewed, and
   integration is an Owner decision (OD-09), not something a documentation task may do.
4. **Activate SAI 3.5 directly.** Rejected. There is no Owner approval, no evaluator, no frozen
   protocol and no implementation; activation would turn targets into unmet active obligations.

## Decision

Propose `docs/spec/SAI_3.5_Discovery_Candidate.md` with its companion documents in
`docs/spec/sai35/`, a candidate registry of D-001–D-046, and a checker that proves the candidate is
not active and that the SAI 3.3/3.4 files are untouched. Add a CI step for that checker.

OD-10 proposal A' (a proposal, pending the Owner): `docs/spec/sai35/candidate-paths.txt` lists
every path the candidate adds; `check_sai34_boundary_without_candidate.py` deletes exactly those
paths in a temporary worktree of HEAD and runs the unmodified SAI 3.4 activation checker there.
It refuses protected, runtime, migration, test and script paths and any difference between the
list and the real diff. The CI step that ran the SAI 3.4 checker now runs it through this wrapper.
Alternatives: (B) an Owner-approved widening of the SAI 3.4 allowlist; (C) SAI 3.5 stays off the
integration line.

The candidate defines an independent G-D acceptance framework (G-D0 to G-D4). Completing G0–G9
alone never implies discovery, and a G-D level passes only by an independent evaluator. Whether
discovery helps is tested by a matched-budget comparison of a single LLM, existing LIB and LIB with
Discovery, with a zero-cost first stage.

The branches stay unintegrated because integration needs (a) the independent audit of the G0 line,
(b) review of the offline discovery work, (c) a decision on the SAI 3.4 activation checker's scope,
and (d) an Owner decision on the order. These are recorded as OD-09 and OD-10.

## Consequences

Positive: discovery has a precise, falsifiable target and an acceptance route that cannot be
satisfied by G0–G9 progress or by the implementer's own report. The current active contracts are
unaffected and checked byte for byte.

Negative: there are now three unintegrated lines; the bare SAI 3.4 activation checker fails on
the full tree of this branch by design, and CI relies on proposal A' until OD-10 is decided; the
normative text is English while SAI 3.3/3.4 are mostly zh-TW
(OD-13); the candidate depends on rules (`011p`/`011s`) and tooling that exist only on the G0 line.

## Migration / Rollback

No runtime, schema or data migration. Rolling back means deleting the new files, removing the
SAI 3.5 CI step and restoring the SAI 3.4 CI step to its `a38ad63` command. If the candidate is later activated, that needs its own ADR revision, an integration plan, an
SAI 3.4 checker scope change and a migration of D-NNN into the active registry with real tests.

## Tests / Evidence

`python docs/spec/sai35/check_candidate.py --self-test` (structure, IDs, not-active state, protected
hashes, negative mutations). All T-D-NNN are planned obligations; none is implemented or executed.
No G-D level has been evaluated.
