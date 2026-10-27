# G0 exploratory screening — handoff

Branch: `g0-exploratory-screening-v2` (from `g0-research-reliability` `d14c1cd`).
Reports: `docs/audit/g0-exploratory-screening-2026-10-27/REPORT.zh-TW.md` (V1),
`docs/audit/g0-screening-v2-closure-2026-10-27/REPORT.zh-TW.md` (V2 closure).
Status: candidate for review. G0 NOT PASSED. No merge, deploy, paid call or Lumerical run.
Screening is OFF by default in production (ADR-0015); a deployment must pass
`ResearchFeatures(exploratory_screening=True)`.

## What exists now

| Piece | Where |
|---|---|
| Screening types, policy `screening:research-run@1.0.0` | `src/lab_brain/core/models/screening.py` |
| Selection (pure) and execution (Job/Run, no relations) | `src/lab_brain/verification/screening.py` |
| Durable records and the SUPPORTS guard (a)(b)(c) | `migrations/012y_exploratory_screening.sql`, `src/lab_brain/core/repositories/screening.py` |
| Stage inside the debate, post-screening review, Critic token reserve, grounding relevance, overlap record | `src/lab_brain/cognition/debate.py`, `roles.py`, `overlap.py` |
| Service wiring, verification exclusion, report section, feature flags `ResearchFeatures` | `src/lab_brain/research/service.py`, `report.py`, `render.py` |
| Device structure summary (flag, default off) | `src/lab_brain/research/structure.py`, `src/lab_brain/domains/silicon_photonics/structure.py` |
| Page rendering zh-TW / en | `src/lab_brain/interfaces/web/pages.py`, `i18n.py` |
| Offline matrix, frozen protocol, evaluator scorer | `benchmarks/g0_screening/`, `tests/e2e/test_g0_screening_matrix_postgres.py`, `tests/g0_standin.py` |
| Spec question | `docs/spec_issues/SPEC-ISSUE-016-exploratory-screening.md` (RESOLVED, Reading B) |
| Owner decision record | `docs/adr/ADR-0015-exploratory-screening-is-not-a-verification-action.md` |
| Screening review contract and probe (rc-6.0.0, probe-8.0.0) | `src/lab_brain/llm_runtime/contracts.py`, `probes.py` |
| Fail-closed preflight, in-flight tool guard, atomic evidence, REFUSED status | `src/lab_brain/verification/screening.py`, `migrations/012z_screening_fail_closed.sql` |
| Interrupted-run close-out (`SCREENING_INTERRUPTED`) | `src/lab_brain/research/service.py` |
| Fault injection | `tests/e2e/test_g0_screening_faults_postgres.py` |
| Holdout reclassified as exposed regression | `benchmarks/g0_screening/protocol-amendment-1.json` |

## How to verify

```
make test                                   # backend-free
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<fresh migrated db> pytest
LAB_BRAIN_G0_MATRIX_OUT=<dir> pytest tests/e2e/test_g0_screening_matrix_postgres.py
python benchmarks/g0_screening/score.py <dir>/<config>.outputs.json
python scripts/mutation_battery.py --only <screening entry names>   # see the report §7
```

A local PostgreSQL must use password authentication on host connections, or
`test_service_roles_postgres` fails (it expects a wrong password to be refused).

## Open items for the next session

1. Owner gates: enable screening in production; structure summary on/off; a review-only promotion
   path; authorize a live Gemini qualification retest (probe-8.0.0 makes every earlier lock stale;
   give a maximum cost first); delete the old branch `g0-exploratory-screening` (AI-authored
   commits); confirm commit identity; build a new blind holdout (the old one is exposed).
2. Run the full 732-entry mutation battery before Owner acceptance (only the 52 screening entries
   ran in V2: 52/52 killed).
3. This environment's proxy blocks the CI log host, so read failing-test names in the GitHub UI.
4. V2 verification evidence and CI SHA: see the V2 report §3.5. Commit hygiene was fixed by
   stripping AI attribution trailers from the V2 commits and force-pushing (Owner authorized).
