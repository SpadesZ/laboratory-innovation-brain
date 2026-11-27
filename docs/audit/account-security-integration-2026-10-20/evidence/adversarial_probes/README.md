# Adversarial probes (independent audit, 2026-10-20)

Written and run by the independently scoped review against commit `bfde08b`, on a disposable
database. Each test PASSES while the defect it names is present; `test_adv_held.py` instead
checks defences that held, and `test_measure_*` only measures.

These are evidence, not part of the test suite (pytest collects `tests/` only). The findings
they demonstrate are held closed by `tests/security/test_adversarial_findings_postgres.py` and
the other tests the audit report names.

To run them against another commit, copy them into the worktree and run with
`-p tests.conftest -o addopts=""` against a disposable database. Since `55afcfd`,
`LabProjects.create` takes the opening administrator and the owner's account
(`projects.create(admin, owner_account_id=..., name=..., clearance=...)`), and the two
concurrency probes hold two transactions on one thread, which now wait on 012w's lock: run
them only with a second thread, as `test_a5` does.
