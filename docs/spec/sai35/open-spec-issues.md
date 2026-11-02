# SAI 3.5 — Appendix P: Open spec issues

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: informative register. A conflict found between SAI 3.5 and an inherited text, or inside
SAI 3.5, is recorded here and stops the affected slice (S35-GOV-001, SAI 3.3 AGT-015). These issues
use the prefix `S35-ISSUE-` so they never collide with `docs/spec_issues/SPEC-ISSUE-NNN` on any line.
None of them is a direct conflict that blocks this documentation candidate; each blocks the named
implementation slice until resolved.

| ID | Issue | Competing readings | Provisional handling in this candidate | Blocks | Status |
|---|---|---|---|---|---|
| S35-ISSUE-01 | Envelope registration versus the per-hypothesis pre-authorization of the G0 line (`011s` rule (l), `011w` signatures) | A: an Owner-signed envelope is an accountable pre-authorization of a class of tests; B: rule (l) needs a person to name the specific hypothesis and prediction | B by default (S35-REG-003): envelope-registered evidence is CITES for post-screening hypotheses | P35-4 envelope slice | OPEN (OD-14) |
| S35-ISSUE-02 | "Matched budget" meant caps in the discovery candidate; the offline run shows caps do not match realized spend | A: caps; B: realized consumption | B (S35-CMP-002) with a proposed rule; tolerance and rule frozen under OD-03 | G-D0 | OPEN (OD-03) |
| S35-ISSUE-03 | The anomaly vocabulary of the offline prototype (`ACCOMMODATED`, `ATTRIBUTED_TO_NOISE`) differs from the discovery candidate's | A: candidate set; B: prototype set | union with explicit transitions (Appendix C §3.3) | P35-2 anomaly registry | OPEN (review) |
| S35-ISSUE-04 | SAI 3.3 §8.2 lifecycle (DRAFT, ADMITTED, ACTIVE, …, EVOLVED/SUPERSEDED) versus SAI 3.5 claim states | A: new states replace §8.2; B: projection mapped onto §8.2 | B (Appendix C §3.2); §8.2 unchanged | P35-2 projection | OPEN (review) |
| S35-ISSUE-05 | SAI 3.3 §12.1 episode state machine versus the campaign state machine | A: campaign replaces episodes; B: campaign contains episodes | B (S35-LIFE-002) | P35-2 orchestrator | OPEN (review) |
| S35-ISSUE-06 | The forged-authorization read-path bypass on the G0 line affects S35-REG-001, S35-REG-004 and S35-CWG-002, which rely on verified authorizations | — | fixed on the unmerged branch `g0-authorization-read-path-closure`, pending independent audit; SAI 3.5 adds no weaker path | P35-1, P35-2 registration | OPEN until audited and integrated |
| S35-ISSUE-07 | G0-line spec issues SPEC-ISSUE-017 (free-declaration trust root), -018 (verification-authorization trust root) and -019 (environment equivalence) bear on S35-COST-001, S35-REG-001/002 and S35-CMP-002/005 | as recorded on that line | inherited as open; SAI 3.5 takes the strictest provisional reading of each | P35-3, P35-4 | OPEN (G0 Owner decisions A6, B6–B8, E4–E5) |
| S35-ISSUE-08 | Arm A is a "single frontier LLM", but the zero-cost stage cannot use a paid frontier model | A: skip arm A until paid; B: strongest approved local model at zero cost, frontier model only in a paid stage | B (S35-CMP-001) | G-D1 | OPEN (OD-04, OD-05) |
| S35-ISSUE-09 | SAI 3.3 §14.2 Novelty Audit mode (sanitized public search, separate from internal reasoning) versus automatic prior-art search by the Novelty Auditor | A: only a human may start a novelty audit; B: automatic search allowed with PUBLIC sanitized queries | B within §14.2's egress rules (S35-NOV-003) | P35-5 | OPEN (review) |
| S35-ISSUE-10 | SAI 3.3 P12 and §2 (human owns scientific semantics; not a replacement for researcher judgment) versus the autonomous AI scientist target | A: autonomy contradicts P12; B: autonomy within envelopes, §23.4 steering points human, conclusions under signed human review | B (compatibility §5) | none now; activation review | OPEN (Independent Chief Auditor) |
