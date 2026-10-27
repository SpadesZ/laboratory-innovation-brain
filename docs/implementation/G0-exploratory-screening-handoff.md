# G0 exploratory screening — handoff

Branch: `g0-exploratory-screening-v2` (from `g0-research-reliability` `d14c1cd`).
Report: `docs/audit/g0-exploratory-screening-2026-10-27/REPORT.zh-TW.md`.
Status: candidate for review. G0 NOT PASSED. No merge, deploy, paid call or Lumerical run.

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
| Spec question | `docs/spec_issues/SPEC-ISSUE-016-exploratory-screening.md` (OPEN, M4) |

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

1. Owner decisions: SPEC-ISSUE-016 reading; structure summary on/off; a review-only promotion path;
   authorize the live Gemini retest (commands in the report §13); delete the old branch
   `g0-exploratory-screening` (AI-authored commits; the force operation was not permitted here).
2. Add a capability probe case for `prm:hypothesis-screening-review@1.0.0` before real use.
3. Run the full 719-entry mutation battery before Owner acceptance.
4. CI on `baabcf4` (run 40491804674) passed all four jobs. This environment's proxy blocks the CI
   log host, so read failing-test names in the GitHub UI if a later run fails.
