# Discovery independent-evaluation kit (round 6)

**Status: a frozen, verified evaluation kit for the 58 sealed round-5 cases, ready for a
third-party evaluator. It has NOT been run on the sealed cases.** Everything measured here is on the
PUBLIC example file (`benchmarks/discovery_independent/example.hidden-worlds.json`, 8 worlds) and is
format and plumbing evidence only: **not evidence about the sealed set, the arms' merit, physical
reality or any G-D gate.** `READY_FOR_REAL_RESEARCH` stays false; G0 and G-D stay NOT PASSED.
Discovery stays offline; no model, network, simulator, Lumerical, paid call, merge, deploy or SAI
activation. `ACTIVE_SPEC.yaml` and `docs/spec/` were not touched.

Branch `claude/lib-implementation-agent-47evs0-independent-eval` (from `0eac9b3`, the round-5 head).
Protocol: [`docs/evaluation/discovery-independent-evaluation-protocol.md`](../evaluation/discovery-independent-evaluation-protocol.md)
v0.2, §12-§15 (with a zh-TW summary).

## 1. Information barrier kept

The implementation side never read, listed, copied or decrypted `/home/user/sealed`,
`/home/user/sealed_key.txt`, `/home/user/key_transfer` or the plaintext of
`round5-hidden-worlds.tar.gz.enc`. Two public files were read from the hidden-cases branch
(`sealed/README.md`, `sealed/round5-commitments.json`; the latter is copied into the kit). The
ciphertext's SHA-256 is computed by streaming the git object (`git cat-file blob 3d54297:...`) into
SHA-256, never written to disk, never decrypted: `b23db527e50cf58f5e0a7d5a550b612fd8b0f4a274eaf6dbb5fa89693ca2fe83`
(matches). The commitments root recomputes to the pinned
`sha256:839ac0110308102f990c1d2e9e5e246600c310f7adb71b59eeaf9c28db2dcf8b` over 58 cases. The kit
needs no hidden truth on the implementation side at any point: V decrypts, runs, reveals, scores
and signs on V's machine (§6).

**Disclosed limitation (Owner update).** On 2026-11-24 the decryption key was displayed in the lead
implementation session's transcript at the Owner's request. This is an **evaluation limitation, not
confirmed exposure of hidden answers**: nobody decrypted. The lead has deleted the plaintext working
copies and key copies from the container; the encrypted archive on GitHub (sha256 b23db527…2fe83) is
the only copy of the cases and the key is held by the Owner off-container. The protocol (§14)
recommends V report it as a disclosed limitation, and describes regenerating a fresh sealed set by
an independent author with a key the implementation side never sees; the kit runs unchanged on such
a set after a freeze that changes only the sealed-set pins.

## 2. Commits

| commit | what |
|---|---|
| `ecfef25` | kit: run traces, the evaluator's laboratory service, checkpoint scorer, arm worker, arm registry (B4/B6/B7 pinned at `bff315f`, B8 empty) |
| `cb08949` | adversarial tests, analysis plan, power analysis, protocol v0.2 (runbook, key disclosure) |
| `e4db596` | protocol zh-TW summary |
| `f757f15` | decision rule: a direction needs the exact McNemar test as well as the bootstrap bound |
| `842f3ad` | dry run on the public example (31 files) |
| **`607bd66`** | **FREEZE** (`kit-manifest.json`), pushed |
| `e444067` | first full PostgreSQL run log |
| later | this report, second full run log, status inventory (no kit file changes; `verify --quick` on the head: OK) |

## 3. Design, and why

**Where the kit lives.** `src/lab_brain/discovery_eval/independent/` (trace, service, plan,
analysis: domain-free, no process, no clock); `src/lab_brain/discovery_safety/independent/checkpoint.py`
(the scorer: it must import the v1.2-v1.4 evaluator code, which `discovery_eval` may not);
`scripts/discovery_independent_kit.py` (composition root; exempted from the §24.2 ban in
`pyproject.toml` like the other discovery roots); `benchmarks/discovery_independent/kit/`
(standalone arm worker, registry, manifest, commitments copy, power analysis, dry run).
**`hidden_worlds.py` was deliberately not edited**: it is frozen in the 2026-11-02 evaluation
manifest that the v1.1-v1.4 scripts verify, so editing it would break frozen evidence checks. The
kit uses it unchanged.

**One run per case and arm (requirement 1).** Each pinned arm runs each case once at the cap (48
units) in a fresh interpreter (`python -s -B -P arm_worker.py`, minimal environment, empty cwd,
PYTHONHASHSEED=0) loaded only from a tree `git archive`d from the arm's pinned commit (tree id and
import-closure hashes checked; links refused). The evaluator process holds the world, meter and an
append-only hash-chained trace: START, MOTIVATING, MEASURE (experiment, replicate, session, cost,
charge before/after, values), REGISTER (identity, experiment, runs; the arm's data digest kept
beside), DECLARE (answer, stamped by the evaluator with charge and evidence count; the arm's stated
level kept and ignored), REFUSED, INCIDENT, END.

- *Answer at checkpoint c* = the answer of the last DECLARE whose charge (frozen cost of every
  experiment started before it) is <= c; none: no claim. Costs are fixed, so reservation equals
  settlement and an experiment whose reservation does not fit never starts; nothing straddles a
  declaration.
- *SUPPORTED at c* is recomputed from the MOTIVATING/MEASURE/REGISTER events **before** that
  declaration only, replayed into a fresh v1.3 evaluator ledger (chain, data digests, run counts
  recomputed) and judged by the frozen v1.4 rule under candidate.5.
- *Ladder* 6, 8, 12, 16, 24, 32, 48; c* = 48 (Appendix J's proposal). Other checkpoints refused.

**Trace vs fresh capped run.** Proved by test: for an arm whose choices do not depend on its cap and
that declares after each experiment, the trace answer at c equals a fresh run capped at c, with
the same category and the same evidence (3 example worlds x 7 checkpoints). The legacy arms are not
of that kind: they plan with the cap (`engine_fraction * budget`, `affordable()`) and commit only a
final answer. Measured on the example (`dry-run/equivalence.json`, 56 cells per arm):

| arm | EQUAL | trace holds no answer yet | different answer | credited cells: trace / fresh |
|---|---|---|---|---|
| B4 | 26 | 13 | 17 | 0 / 0 |
| B6 | 26 | 13 | 17 | 10 / 18 |
| B7 | 20 | 12 | 24 | 11 / 23 |

So for these arms the one-trace anytime curve is lower than a per-cap rerun curve: that is the
estimand difference (what the arm knows after spending c given the full cap, vs what it does when
told the cap is c), not an error. At c* = cap the two coincide by construction.

**What differs from v1.4 per-world matching, and why checkpoint accounting is primary.** v1.4 ran
every arm at every cap and matched worlds after the fact at the lower of two realized costs (±1),
dropping unmatched worlds: conditioning on a post-treatment variable, a selected subset, a fresh
cap-aware run per cap, and one arm's comparison point depending on the other arm's trace.
Checkpoint accounting keeps every case in the denominator, fixes the points before any run, and
makes each arm's score a function of its own single trace (Appendix J §3.3; S35-ISSUE-22 option B).
Per-world matching is not computed by the kit.

**Evaluator-controlled evidence (requirement 2).** Only `motivating`, `measure`, `register`,
`declare`, `done`, `failed` (and the guard's `violation`) are accepted; answers pass a closed
schema (outcome must be in the engine's vocabulary; this was found by a test: an unknown outcome
string used to crash scoring). Statuses: COMPLETED; CRASHED; INVALID (protocol, budget, metering,
isolation incident); TRUNCATED (message flood); at scoring TAMPERED (trace fails its chain or the
head recorded in the run summary) and LEAK (world id, effect id or salt in the arm's output). Every
non-COMPLETED run is DEFICIENT: never credited, counted as an error, and scored against its own arm
in every paired comparison (Appendix J §3.4). The worker's audit hook (installed before arm code,
not removable from Python) refuses reads outside the arm tree and interpreter, all writes, process
creation, sockets, ctypes and chdir. It is defence in depth; the runbook requires OS isolation.

**Freezing (requirement 3).** `kit-manifest.json` pins kit code, engine sources, the evaluator's
import closure (141 files), the hidden-world format, arms (commit, src tree, entry, context, 133
closure hashes each; B8 EMPTY), scoring (rule, grammar, catalog, protocol digests), the plan, the
sealed set (archive hash, root, 58, commitments file hash, source commit), the dry-run outputs, the
power analysis and the interpreter. `verify` recomputes all of them and `run`/`score` refuse on any
mismatch (tested). **B8**: `pin-arm --arm-id B8 --commit SHA --entry M:F` fills the registry slot
(data only), then `freeze`; the plan then makes B8 - B4 primary. No kit code change.

## 4. Freeze and manifest hashes

| item | value |
|---|---|
| freeze commit | `607bd66272d2d6657b7a2df102c66e7a52c38080` (pushed) |
| **freeze id** | `sha256:bbaf96ef222ffad97991658d726cc8d8e6fc53aec7f20eb97877ad70686effb8` |
| kit code hash | `sha256:92acf2f74055e3b957af09249851b38b5f52ae654bab3713a76518d5944648b2` |
| engine hash | `sha256:e149adaabf60ac61b8c08dd49ec4df6d2ae614dcbfcbb5ebb6ac075a772ecb0a` |
| evaluator closure hash | `sha256:8cdbaece891bbf255835ad34a0fdc6ad853c9af05bf92225ebe3d267fd5b4765` |
| analysis plan digest | `sha256:ae3e2d923d26dc5f66472b2d3f11321b235b61feed8b5567639f46fd37073b32` |
| evaluator rule v1.4 digest | `sha256:f12d3af864d491af6825fbf2a0972f188f515cdbe12c1ac882cff4f96ad972d2` |
| grammar / catalog digest | `sha256:767111e5…f8942` / `sha256:69c86963…d9119` |
| arm registry sha256 | `0867bb4e63289e99d9e30b7b8913570745b784ac907b1e15f1563855cc7cd2cf` |
| arms B4, B6, B7 | commit `bff315f` (v1.4 design freeze), src tree `a819f9e6922961c4a0f328995f0f5dddb5f69f4f`, entry `lab_brain.discovery_safety.v14.evaluation:run_arm`; **B8 EMPTY** |
| archive sha256 / commitments root | `b23db527…2fe83` / `sha256:839ac011…dcf8b`, 58 cases |
| interpreter | CPython 3.13 |

`verify` on the freeze (fresh workdir, arms re-materialized, archive hashed from git):
**`verify: OK; kit freeze id sha256:bbaf96ef…6effb8`**.

## 5. Pre-registered plan and power (58 cases)

Primary: EXACT_IDENTIFICATION at c* = 48 over expressible cases, B7 - B4 (B8 - B4 if pinned),
paired percentile bootstrap (10,000, seed 20261124). Safety co-primary: candidate.5 error
indicator, non-inferiority 0.02. Decision: BETTER / WORSE / SAFETY_FAIL / INCONCLUSIVE / INVALID;
**a direction requires the exact McNemar test (p < 0.05) as well as the bound** (added after the dry
run showed the percentile bootstrap degenerating to [1, 1] on 5 one-sided pairs; changed before the
freeze and before any sealed run). Secondary comparisons Holm-adjusted per (metric, checkpoint).
Study INVALID above 2 % incident runs or 5 % deficient cases.

Minimum detectable paired difference (80 % power, two-sided 5 %; simulation of the plan's bootstrap
gives 0.76-0.81 power at these values):

| primary cases | D=0.2 | D=0.3 | D=0.4 | D=0.5 |
|---|---|---|---|---|
| 20 | 0.24 | 0.29 | 0.34 | 0.38 |
| 29 | 0.21 | 0.25 | 0.29 | 0.33 |
| 40 | 0.18 | 0.22 | 0.26 | 0.29 |
| 58 | 0.15 | 0.19 | 0.22 | 0.24 |

58 cases can support a large difference (about 0.2-0.35) and a gross safety failure. They cannot
support differences of 10 points or less (about 130+ primary cases needed), non-inferiority at 0.02
unless the candidate makes no net extra error (one extra error out of 58: upper bound 0.052), a
zero-event bound below about 6 % (Wilson 0/58), per-category claims, or anything about another
author's distribution, physical reality, language models or the PostgreSQL LIB workflow.

## 6. Evaluator runbook (summary; full text in protocol §13)

verify (with `--archive`) -> `dry-run --check` and `power --check` -> decrypt on V's machine
outside the repository (0700) -> isolate arm processes at OS level (container or separate account,
no egress) -> `run` once (verifies package root and every world's commitment before any arm runs;
publish `run-summary.json` sha256) -> `score` (reveal, checkpoint scoring, plan) -> `keygen` /
`sign` (Ed25519) -> publish results, signature and, afterwards, the sealed file. Must not hold the
key: the engine/arm/kit author lineage, arm operators, anyone acting on per-case outputs before the
run closes. V attests the checks, one run, isolation, no changes after freeze, deviations, conflicts.

## 7. Adversarial tests (`tests/unit/test_discovery_independent_kit.py`, 44 tests, all pass)

| attack | result |
|---|---|
| asserts SUPPORTED with no evidence (stated_level SUPPORTED, true class) | COMPLETED; level PROPOSAL, UNSUPPORTED_CLAIM, error, never credited |
| forges evidence: `evidence` in the answer; an `observation` message; a dated declaration (`charge`); readings in a declaration; an outcome outside the vocabulary | INVALID (protocol), deficient |
| forged data digest in a registration | kept beside, evaluator's own digest used, not credited |
| misreports `spent` | INVALID (metering) |
| edits its trace after the fact: alter a value, drop, reorder, back-date, append after END, rewrite and re-chain | TraceTampered (the last caught only by the head recorded at run end) -> TAMPERED, deficient |
| reads the world spec / a file outside its tree; lists a directory; starts a process; writes a file (real subprocesses) | guard violation -> INVALID (isolation) |
| exceeds budget | INVALID (budget); the over-cap experiment is never run (the lab is not called) |
| crashes mid-case (raises, process dies, reports failure), even after a correct anytime answer | CRASHED, deficient at every checkpoint |
| session goes backwards; message flood | INVALID; TRUNCATED |
| truth string in output | found (LEAK at scoring) |
| positive control | B7 through the worker equals the v1.4 in-process harness (same digest, claim, meter) and is credited SUPPORTED at c* |

Also: trace equality with fresh capped runs for a cap-independent arm; S2-CE-1 early stopping;
S2-CE-5 checkpoint refusal; deficient-record rule; decision rules; bootstrap determinism, McNemar,
Holm, Wilson; `verify` refuses a changed kit file; the committed dry run is internally consistent.

## 8. Dry run (PUBLIC example only; not evidence about the sealed set)

Seal (reproducible example salts) -> blind run of B4, B6, B7 (24 runs, all COMPLETED, no
incidents) -> reveal verified -> scored at every checkpoint -> plan applied -> trace-vs-fresh study
(168 fresh capped runs). `dry-run --check` on the freeze in a fresh workdir: **every file
byte-identical** (399 s); `power --check`: current.

| arm | credited at 6 / 12 / 16 / 24 / 32 / 48 | errors at 48 | realized cost mean (max) |
|---|---|---|---|
| B4 | 0 / 0 / 0 / 0 / 0 / 0 | 6 (UNSUPPORTED_CLAIM) | 19.5 (29) |
| B6 | 0 / 0 / 0 / 3 / 3 / 4 | 2 | 19.75 (35) |
| B7 | 0 / 0 / 0 / 2 / 3 / 6 | 0 | 24.9 (40) |

Plan applied to the 8 example worlds: primary B7 - B4 exact = +1.0 on 5 primary cases, bootstrap
[1.0, 1.0], McNemar p = 0.0625 -> **INCONCLUSIVE** (five cases cannot decide anything, as the rule
intends). These numbers show only that the pipeline works; they repeat the v1.4 example pattern
(B4's endorsements are unregistered, hence UNSUPPORTED under candidate.5) and say nothing about the
sealed set.

## 9. Final checks

| check | result |
|---|---|
| ruff check / ruff format --check (src tests scripts) | All checks passed / 672 files already formatted |
| mypy (repository config; and the kit script separately) | no issues in 338 source files; no issues |
| governance tests (discovery_eval, discovery_safety, extension boundary) | pass (unchanged tests; the kit packages fall under them) |
| `check_commit_messages.py` | no AI authorship found |
| full PostgreSQL suite, run 1 at `607bd66` (fresh `ie6_full`, migrate twice: 81 applied, then up to date) | 3948 passed, 4 skipped, **1 failed** in 51 min 39 s: `test_g0_eval_environment::test_the_script_captures_this_repository` -- the subprocess resolved `lab_brain` through the shared `.venv`'s editable install, which points at the main checkout (another branch, no `lab_brain.evaluation`). Environment artifact of the worktree, not of this change; the test passes with `PYTHONPATH` set to this tree. Log: `discovery-independent-eval-kit-evidence/full-suite-607bd66-run1-editable-path.log` |
| full PostgreSQL suite, run 2 at `607bd66` (fresh `ie6_full2`, migrate twice: 81 applied, then up to date; `PYTHONPATH=<worktree>/src`) | **3949 passed, 4 skipped, 0 failed in 27 min 28 s (exit 0)** -- the one complete clean run of record. Log: `discovery-independent-eval-kit-evidence/full-suite-607bd66-run2.log` |
| `update_status.py` | regenerated after the full run |

## 10. What remains open

- **The sealed run itself**, by an independent evaluator, with the Owner-held key; and the
  Owner's choice whether to regenerate a fresh sealed set first (protocol §14).
- **B8**: empty slot; pin and re-freeze before any sealed run if it is to be included.
- **OS-level isolation** of arm processes is the evaluator's responsibility; the in-process guard
  is defence in depth for Python arms only. `--arm-uid` style privilege drop exists in `run_one`
  but is not exposed or tested (needs root and a second account).
- **Sessions are arm-stated** (refused only when they go back): an arm can stall time; that can
  only hurt it on non-stationary worlds, but it is not evaluator-controlled.
- **Legacy arms are not anytime**: below their realized cost they hold no claim; the anytime curve
  is therefore a lower curve than per-cap reruns. An arm built for SAI 3.5 should call
  `lab.declare` after each experiment.
- **Values are proposals** (cap 48, ladder, c*, margin 0.02, primary metric) taken from Appendix J
  for Owner decision OD-03; changing any of them requires a new freeze before the sealed run.
- **Interpreter pinning**: CPython 3.13 is required by `verify`; reproduction on another platform
  is checked by `dry-run --check`, not assumed.
- One AI world author; procedural, not institutional, independence; S35-ISSUE-22 stays OPEN until
  the lead/Owner decide.
