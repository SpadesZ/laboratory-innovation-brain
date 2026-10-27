# G0 independent holdout: operator workflow

**Status: machinery only. No genuine independent blind holdout exists.** The former
`benchmarks/g0_screening/holdout` was reclassified as exposed-regression evidence by protocol
amendment 1, because its truth was reported to the implementer. Every fixture the tooling below is
tested with is synthetic. Nothing here supports a claim of independent, blind or unseen evaluation
until an independent evaluator has authored, sealed and scored a holdout as described.

SAI 3.4 acceptance §2.1 (G0-S) requires cases and rubric frozen before execution and reviewers
independent of the generator. This workflow enforces the parts software can enforce; independence
of people is an Owner gate.

## Roles

| Role | Does | Must not |
|---|---|---|
| **Owner** | Authorizes the evaluation, names the independent evaluator, approves the protocol values (metrics, thresholds, contamination policy, seed), signs off the result | Pass truth or case content to the implementer |
| **Independent evaluator** | Authors cases and truth; keeps truth **outside the repository**; seals it; runs the contamination check; freezes the manifest; after the run, reveals and scores | Report case content or truth to the implementer before scoring; change anything after freeze |
| **Generator (implementer / system)** | Receives only the generator package and the manifest hash; runs every case blind; returns an outputs document | Read truth, tune on holdout outputs, drop or re-run cases selectively |

## Files

| File | Side | In the public repo? |
|---|---|---|
| `generator-package.json` (`g0-eval/generator-package@1`) + evidence files | generator | yes, after freeze (or handed over privately) |
| truth (`g0-eval/evaluator-truth@1`, cases `{truth}`) | evaluator | **never** |
| sealed truth (same kind, cases `{salt, truth}`) | evaluator | **never** — refused inside the repo by the scripts |
| `commitments.json` (`g0-eval/truth-commitments@1`): per-case salted SHA-256 + root | public | yes |
| `protocol.json` (copy of `benchmarks/g0_evaluation/protocol.example.json`, values fixed) | public | yes |
| `manifest.json` (`g0-eval/protocol-manifest@1`) | public | yes |
| outputs (`g0-eval/outputs@1`), bound to `manifest_sha256` | generator → evaluator | after scoring |

The generator loader (`lab_brain.evaluation.packages.load_generator_package`) refuses evaluator
material by kind, by file name, by any truth key at any depth (including inside the device file) and
by any field outside the schema. A run receives only `research_inputs(...)`: question, device JSON,
evidence bytes, allowed sources, unavailable capabilities — no case id, no provenance, no truth.

## Procedure

1. **Owner** authorizes: names the evaluator, approves `protocol.json` (policy `exclude` or `fail`,
   bootstrap seed and resamples, rubric map).
2. **Evaluator** writes the generator package and, outside the repo, the truth file; then seals:

   ```
   python scripts/g0_eval_seal.py --truth ~/sealed/truth.json \
       --sealed-out ~/sealed/truth.sealed.json --commitments-out holdout/commitments.json
   ```

3. **Evaluator** checks contamination against dev/regression packages and the exposed
   `benchmarks/g0_screening` cases (exact and 8-gram text overlap, source/device family, duplicated
   experimental units by id or normalised content). Passing the sealed truth also compares the
   secret truth strings; the report names fields and reference units, never matched text:

   ```
   python scripts/g0_eval_check_contamination.py --package holdout/generator-package.json \
       --reference dev/generator-package.json --truth ~/sealed/truth.sealed.json
   ```

4. **Evaluator** freezes, **before any run**. The manifest pins protocol id/version, scorer id,
   version and the SHA-256 of every `lab_brain/evaluation/*.py` file, every input file hash, the
   case list, the commitments, the contamination findings and the exclusions (policy `exclude`
   excludes contaminated cases here; `--exclude CASE=REASON` adds declared ones):

   ```
   python scripts/g0_eval_freeze.py --protocol holdout/protocol.json \
       --package holdout/generator-package.json --commitments holdout/commitments.json \
       --reference dev/generator-package.json --truth ~/sealed/truth.sealed.json \
       --out holdout/manifest.json
   ```

   Publish `manifest.json`, `commitments.json` and the printed `manifest_sha256`.
5. **Generator** runs every case once from `research_inputs`, and writes outputs:
   `{"kind": "g0-eval/outputs@1", "manifest_sha256": ..., "cases": {id: {"status": "COMPLETED", "record": {...}} | {"status": "REFUSED"|"CRASHED", "reason": ...}}}`.
   The record is the matrix harness's `collect` shape; include the prompts sent (`"prompts"`) so
   the scorer's leak check can read them.
6. **Evaluator** reveals and scores:

   ```
   python scripts/g0_eval_score.py --manifest holdout/manifest.json --outputs outputs.json \
       --truth ~/sealed/truth.sealed.json --json score.json
   ```

   Scoring refuses (exit 2) on any input or scorer-source hash drift, an edited manifest, outputs
   bound to another manifest or naming unfrozen cases, a reveal not matching its commitment, or
   contamination under policy `fail`.
7. **Owner** reviews the score with the evaluator and decides.

## What the score reports

Every frozen case appears with a status: `COMPLETED`, `REFUSED`, `CRASHED`, `MALFORMED`, `MISSING`
or `EXCLUDED` (with reason). A case that did not complete fails every applicable metric. Each
metric gives `n`, `k`, rate, Wilson 95% interval and a seeded percentile bootstrap 95% interval
(seed and resamples from the manifest), plus a **conservative** figure counting exclusions as
failures. Intervals describe sampling noise over the authored cases only.

## Owner gates that software cannot close

- That the evaluator is genuinely independent of the generator and did not report case content.
- That the cases are scientifically representative and the rubric is the right one (G0-S review by
  a qualified reviewer independent of the generator).
- That no tuning happened between freeze and scoring (the manifest pins code hashes of the scorer,
  not of the research system; pin the research build separately).
- Approval of thresholds; this tooling reports proportions, it does not decide PASS.

## Limitations

- Contamination detection is lexical and declarative: paraphrases below the n-gram threshold, and
  source/device families the evaluator does not declare honestly, are not detected.
- The rubric is the screening matrix's (considered, decisive check executed, no false confirmation,
  no false abnormal, no post-screening support, no leak); G0-S's human usefulness review is not
  automated here.
- Commitments prove the truth did not change after freeze; they cannot prove nobody saw it.
