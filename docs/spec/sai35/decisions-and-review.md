# SAI 3.5 — Appendix O: Owner decisions, risks and self-review

Version: `3.5.0-master-candidate.1`.
Status: **CANDIDATE — NOT ACTIVE.** Every decision below is **OPEN**. Writing them down decides
nothing. `READY_FOR_REAL_RESEARCH = false`.
Authority: informative. Supersedes the `3.5.0-discovery-candidate.1` version of this file (kept in
git history); OD-01…OD-13 keep their meaning, OD-10 is rewritten for proposal A', OD-14…OD-16 are
new.

## 1. Owner decisions

`OD-NN` are SAI 3.5 Owner decisions. The SAI 3.4 decisions `D-01`–`D-08`, the G0 line's decisions
A–F and the security decisions A3, A9 and A12 stay as they are and stay open.

| ID | Decision | Default until decided | Recommendation | Status |
|---|---|---|---|---|
| OD-01 | Accept the SAI 3.5 master candidate for review, modify it, or reject it | the candidate exists only on its branch; NOT ACTIVE; nothing depends on it | review it with the Independent Chief Auditor; keep it NOT ACTIVE | OPEN |
| OD-02 | Assign the independent G-D evaluator, the owner of the hidden-world generator and the arm-label custodian | none assigned; G-D0 is BLOCKED | one evaluator who is not the implementer (not a second account of the same person) and who owns the generator; one separate custodian; at G-D2 and above two independent domain reviewers | OPEN |
| OD-03 | Approve protocol values: primary metric, minimum effect, non-inferiority margins, false-discovery weights, multiplicity method, sample size, re-run invalid limit, no-mechanism share, and the realized-consumption matching rule and tolerance | none; G-D0 is BLOCKED | true-cause discovery primary; +10 points minimum effect; 2-point margins; weights 10/3/3; Holm at α = 0.05; matching at the smallest final realized consumption among arms (protocol §3.2); n from a pilot on separate development worlds | OPEN |
| OD-04 | Approve the local models for zero-cost stages, which also fix arm A's model there, and declare their endpoints free | none; the zero-cost stage cannot run | one pinned open-weight local model with a served digest, declared free per exact model under the spend administration (G0 decisions A4, A6, E5) | OPEN |
| OD-05 | Authorize a paid model stage (including a frontier model for arm A), with a ceiling | not authorized | only after the zero-cost G-D1 report, with a small ceiling and a provider-side hard cap (G0 decision A5) | OPEN |
| OD-06 | Source and rights for held-out literature cases | none; G-D2 is BLOCKED | evaluator-curated cases resolved after every model's training cutoff, with per-source rights recorded and no redistribution of unclear material | OPEN |
| OD-07 | License, worker and budget for licensed simulation discovery (G-D3) | not authorized | wait for SAI 3.4 P-LICENSED (SAI 3.4 D-02, D-04, D-05, D-06); start with one qualified CHARGE worker | OPEN |
| OD-08 | Physical experiments and publication for G-D4 | not authorized | authorize per experiment after G-D3 for the scope; review every publication separately | OPEN |
| OD-09 | How and when to integrate the G0 line (`f41758c` and the read-path closure), the SAI 3.4 line (`a38ad63`), the discovery line (`118a4ac`) and this candidate | not integrated | integrate the G0 line after its independent audit, including the read-path closure; then the reviewed discovery line; then decide this candidate's place (OD-10) | OPEN |
| OD-10 | How SAI 3.5 candidate files may exist on the SAI 3.4 integration line while the SAI 3.4 change boundary stays byte-identical | PROPOSAL (A') implemented on this branch: every SAI 3.4 file equals `a38ad63`; CI runs the unmodified SAI 3.4 checker on a temporary worktree of HEAD minus exactly the paths in [candidate-paths.txt](candidate-paths.txt) ([check_sai34_boundary_without_candidate.py](check_sai34_boundary_without_candidate.py)); the bare SAI 3.4 checker on the full tree still fails, by design | (A') this mechanism, recommended; (B) an Owner-approved widening of the SAI 3.4 allowlist (`docs/spec/sai34/activation.yaml`, `check_activation.py`), which edits SAI 3.4 files — tried in `9d44198` and reverted; (C) keep SAI 3.5 off the integration line, on its own branch | OPEN |
| OD-11 | Prior-art coverage required before a novelty class other than rediscovery may be assigned, and the novelty-class criteria | none beyond SAI 3.3 SRC-003 | at least literature and patents with a recorded coverage record; adopt the criteria of Appendix D §3 | OPEN |
| OD-12 | Reframing policy: maximum reframings per problem and per campaign | none; without a policy a campaign stops at its first failure | a small fixed cap (for example 2 per problem) in the synthetic stage, revisited after G-D1 | OPEN |
| OD-13 | Language of the normative text | English normative text; zh-TW glossary and a zh-TW summary report | keep English for review; produce a zh-TW normative edition, checked against the glossary, before activation | OPEN |
| OD-14 | Research envelope: who may sign envelopes, which bounds are mandatory, and whether an envelope registration satisfies a per-hypothesis human pre-authorization rule (G0 line `011s` rule (l) with `011w`) | no envelope exists; envelope registration does not satisfy rule (l): such evidence is stored as CITES for post-screening hypotheses | an envelope authorizer distinct from the warrant authority; every bound of S35-REG-002 mandatory; keep the default (rule (l) not satisfied) until G-D1 shows the envelope's discipline | OPEN |
| OD-15 | Maximum autonomy level per project | AL1 (propose-only) everywhere | AL2 for the zero-cost stage; AL3 only with OD-05; AL4 only with OD-07 | OPEN |
| OD-16 | Activate SAI 3.5 as the primary master specification, and in which form (architectural basis or executable profile) | not active | decide only after the Independent Chief Auditor review; prefer the architectural-basis form first | OPEN |

## 2. Risks

| ID | Risk | Defense in this candidate | Residual |
|---|---|---|---|
| R35-01 | Hypothesis count is mistaken for discovery ability | diversity only as distinguishable classes (S35-MECH-001, S35-CMP-005) | depends on correct prediction typing |
| R35-02 | Reframing hides failures (garden of forking paths) | append-only reframing, failures in denominators, new registration for successors (S35-REF-002, S35-REF-003) | a writer with database authority can bypass rules (A12) |
| R35-03 | Discovery certifies itself | separate identities; the Causal Warrant Gate is the exclusive confirmation authority; sealed evaluation plane (S35-LOOP-001, S35-CWG-001, S35-GD-001) | designed, not built |
| R35-04 | Benchmark contamination inflates results | evaluator-generated hidden worlds, cutoffs, overlap checks, probes (S35-CMP-004, S35-CMP-007) | contamination cannot be excluded completely for literature cases |
| R35-05 | Unfair comparison | matching on model versions, information exposure, conditions and realized consumption; COST_UNMATCHED (S35-CMP-002) | prompt-engineering effort is hard to match |
| R35-06 | G0–G9 progress is read as discovery progress | explicit non-implication (S35-GD-001, S35-GD-003) | documents must keep repeating it |
| R35-07 | Synthetic success is over-generalized | claim discipline (S35-GOV-004); acceptance-gd §4 | synthetic worlds encode their designer's assumptions |
| R35-08 | Pressure to show progress skips the stop | correct stops scored as correct; confident wrong claims weighted (S35-LOOP-003) | weights are a value judgment (OD-03) |
| R35-09 | Unintegrated lines diverge further | integration order OD-09 | the longer the delay, the costlier the integration |
| R35-10 | The SAI 3.4 activation checker blocks any new file on the integration line | OD-10 proposal A': the unmodified SAI 3.4 checker runs on HEAD minus the enumerated candidate paths; the wrapper refuses protected, runtime, migration, test and script paths and any mismatch between the list and the real diff; its self-test control proves the SAI 3.4 checker still rejects the full tree | A' relies on the candidate list; two checkers compare it with the real diff. If the Owner rejects A', option B or C applies |
| R35-11 | Envelope autonomy erodes independent authorization | envelopes authorize registration and execution only; never conclusions; rule (l) default not satisfied (S35-REG-003, S35-CWG-002) | the envelope's bounds must be set well (OD-14) |
| R35-12 | A capability is claimed from a prototype | status words and evidence paths per requirement; complete only for documentation-level requirements | readers may still over-read "partial" |

## 3. Critical self-review

This is the author's own review. It is **not** an independent review and not an Owner acceptance.

| Finding | Handling | Remaining state |
|---|---|---|
| The earlier candidate said no SAI 3.4 file was edited while commit `9d44198` widened the SAI 3.4 allowlist | `9d44198` is reverted; every SAI 3.4 file equals `a38ad63` with no exception; proposal A' replaces the widening; this page, ADR-0016/0017, the checker message and the zh-TW report now say so | OD-10 stays OPEN; A' is a proposal, not an approval |
| Forty-six requirements left gaps an external agent could not build from (problem valuation, search-space expansion, envelope, autonomy levels, worker contract, model qualification, feedback records, permissions) | audited one by one; 27 new requirements; 5 splits, 1 merge, 1 replacement ([requirement audit](requirement-audit.md)) | prose completeness still needs the Independent Chief Auditor |
| "Matched budget" by caps let an arm spend four times another's budget offline | matching on realized consumption with COST_UNMATCHED (S35-CMP-002, protocol §3.2) | the matching rule is a value choice (OD-03) |
| Automatic registration could weaken G0's per-hypothesis authorization | envelope limits and a conservative default on rule (l) (S35-REG-003, OD-14) | needs the Owner's decision |
| "Autonomous AI scientist" can be read against SAI 3.3 P12 | compatibility §5 tension 1; §23.4 steering points stay human | recorded as S35-ISSUE-10 |
| The offline baselines do not map onto arms A and B | stated in the protocol §2 and the status page; arm A is required to be an LLM | arm A does not exist yet |
| Statuses could be over-read | complete only for GOV-001, GOV-002 and GOV-005 (documentation scope); every other status names its evidence and what is missing | — |
| Normative text in English while SAI 3.3/3.4 are mostly zh-TW | glossary with one zh-TW term per English term; OD-13 | a zh-TW normative edition is still needed before activation if the Owner requires it |
| Document checks could be mistaken for acceptance | the checker verifies structure, identifiers, hashes, links, status vocabulary, the candidate-path list and the not-active state only | prose quality needs human review |

## 4. Reading the verification evidence

The [candidate checker](check_candidate.py) proves only that: the candidate is not active;
ACTIVE_SPEC.yaml and every SAI 3.3/3.4 file are byte-identical to `a38ad63` with no exception; every
S35 statement agrees with the registry; every requirement has a traceability row, an inherited-links
row and a status row; every retired D-NNN is in the change register and the audit; the required
sections exist; the candidate-path list equals the real diff; CI runs the SAI 3.4 checker only via
the OD-10 proposal A' wrapper; local links resolve. The
[boundary wrapper](check_sai34_boundary_without_candidate.py) proves that the tree without the
candidate passes the unmodified SAI 3.4 checker. Neither proves anything about discovery, physics or
the quality of the prose.
