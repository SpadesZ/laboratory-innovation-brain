# Review 1 — independent root-cause verification (baseline `41b3cec`)

Isolated reviewer, read-only access to the baseline tree, its own disposable database, read-only
queries on the deployment. Asked to refute the root-cause analysis, not to confirm it. Report as
delivered; resolutions in `../REPORT.zh-TW.md` §5.

## Verdict per claim

1. **CONFIRMED.** `evidence.py:68-75`. The prediction `prd:1165a3f6` (normalization basis,
   os:sp.normalization_basis@1.0.0, DISAGREES) matches observation `obs:bd423ee6` exactly. The
   AGREES/CONTRADICTS prediction correctly did not match.
2. **CONFIRMED.** `evidence.py:143-149` copies `relation_type=effect.relation_type`.
   - Effects can only land on the prediction's own hypothesis (`prediction.py:200-220`).
   - The loop (`loop.py:660`) is the only production writer of relations.
   - The "outcome discriminates" requirement exists only as prompt text (`roles.py:131-134`).
   - The model sees observable names and outcome ids only (`roles.py:140-152`), never what they
     measure. The normalization reader compares only the drawn length with the normalization
     length (`diagnosis.py:242-246, 266-274`). A contact-resistance correction cannot change it.
3. **CONFIRMED, and worse than stated.**
   - `root_cause.py:142-148` checks only the relation's type and target; `:159-167` checks only the
     attestation. `011l` (lines 113-131) does the same in SQL.
   - Model authorship is also erased from the relation itself. `evidence_from_run` never sets
     `RelationJudgment.inference_provenance_id` and stamps `actor_id` with the request's actor.
   - Deployed `rel:51f1fdc4`: actor `act:researcher`, inference_provenance_id NULL. The link to
     the model survives only through `attributes.prediction_id`.
4. **CONFIRMED.** `transition.py:488-495` checks only that a SUPPORTS is present; steps 5-7 are at
   `:497-573`.
   - Step 5 cannot fail for loop evidence: Runs execute under the request's own conditions
     (`loop.py:547-552, 627-629`). The deployed condition match is EXACT.
   - Independence: 1 Run suffices (`vertical.py:435`).
5. **CONFIRMED.** `loop.py:327-330`, `672-676`, `749`. In addition, confirmation never requires
   rivals to be excluded: 5 of the 6 rivals were still ACTIVE and never tested when the run
   CONFIRMED.
6. **CONFIRMED.** Critic `inf:b72a20f2` (qwen2.5:7b) named the alternative, engine call
   `inf:cac51f0d` certified it, and it was admitted at 12:13:27 (`debate.py:475-505`). In addition:
   - The decisive fact (normalization length 1000 against drawn 500) existed only in the device
     project. Every bundle drew only on the report artifact, and the report itself points at the
     contact-resistance correction.
   - The second engine call gets only the existing mechanism names (`debate.py:605-607`), not the
     rivals' predictions, so it cannot even judge whether its outcome discriminates.
7. **CONFIRMED in code and by probe; not in a recorded run.**
   - One step-0 observation produced two relations; both rivals became SUPPORTED;
     `contact_discontinuity` (id …-0001) was confirmed; `notes=()`.
   - The parser refuses conflicting effects only within one hypothesis (`roles.py:433-447`), never
     across rivals.
   - Latent deployed instance: `prj:smoke-local` set `hst:0f9e7a9b`, where two rivals both declare
     RS_BIAS_INSENSITIVE→SUPPORTS on observable "Rs". It is inert, because no capability produces
     "Rs".
8. **CONFIRMED.**
   - Exactly 1 CONFIRMED analysis; 0 heuristic candidates, 0 review items, 0 review resolutions.
   - 2 plans in `epi:12265cfd` carry the precedent.
   - None of the later episode's 6 bundles contains a Run-derived member, and the confirming
     attestation is in 0 bundles.
   - Only `decision` and `summary` are rendered (`service.py:1521-1523`); the episode view reads
     only `tradeoffs`; no cognition module reads failure memory.
   - Minor: `similar_failures` (`failures.py:73-80`) does not re-check that the cause is still
     SUPPORTED, so a wrong precedent persists.
9. **CONFIRMED (structural).** `loop.py:460-461`. `attempt_revision` has no caller other than the
   loop. A rival holding both SUPPORTS and CONTRADICTS gets only a note (`loop.py:435-442`); several
   SUPPORTED rivals get not even a note.

## Paths the original analysis missed (ranked)

1. **HIGH, recorded 3×: a model-authored CONTRADICTS rejects on a non-diagnostic observable.**
   Every CONTRADICTED event in prj:bench-gemini is a gemini-authored
   `sp.normalization_basis=AGREES→CONTRADICTS` against a contact-resistance-correction mechanism:
   - `epi:d4c74098` hyp:4c81c785 "Uncorrected extraction artefact";
   - `epi:6174b0fe` hyp:1bb80e38 "missing_correction";
   - `epi:12265cfd` hyp:f617016a "missing_extraction_correction".

   They were right only by luck (the true causes were contact discontinuity and mesh artefact),
   and the report still lists them as "ruled out". REJECT is tried before promote, and no loop
   target leaves CONTRADICTED or CHALLENGED, so a wrong rejection of a true cause is final for the
   episode. The revision gate's independent-critique check is satisfied by any model critique that
   names the hypothesis as a target.
2. **HIGH, recorded: the converse failure — a true cause never confirmed.** In `epi:d4c74098` the
   true cause (hyp:3570e31f) declared DISCONTINUOUS as PREDICTS. The connectivity check observed
   DISCONTINUOUS, a PREDICTS relation was written, and the hypothesis never became SUPPORTED. The
   model's label alone sets the evidential weight, in both directions.
3. **MEDIUM: planning is driven by the same model-declared effects.** The extraction check was
   chosen in all four gemini episodes only because a contact-correction hypothesis bound the
   normalization basis. Every candidate had `disagreement=null`, yet each was "sufficient".
4. **MEDIUM: relation provenance laundered to the human actor** (see claim 3).
5. **LOW, latent: the heuristic miner keys on the model's free-text `failure_class` plus a
   symptom that defaults to the goal.**
6. **LOW: `bind()` checks outcome membership only.**

Checked and found not to be paths:
- the Critic cannot drop rivals from verification;
- a prediction cannot target another hypothesis;
- precedents are never visible to models.

## Doubts about the reproduction

- Both strict xfails fail with exactly the expected assertions under `--runxfail`.
- **Control and counterexample differ only in prose.** A fix could therefore flip the xfail
  while keeping the control green just by keying on mechanism text, unless the harness supplies
  explicit warrants.
- **The critic-alternative path (claim 6) is not exercised.** The wrong hypothesis is in the
  initial set, and the ids are deterministic.
- **The shared-support xfail can be gamed.** A "fix" that stops `_revise` after the first
  promotion would XPASS while still confirming the rival whose id sorts first. The test also never
  asserts that both promotions came from one observation.
- **The proxy xfail asserts only "not CONFIRMED".** Any unrelated stop would satisfy it.

## What a fix must guarantee

- **Warrant on the link:** any relation that moves belief carries an accountable, recorded warrant
  that the observable can diagnose that mechanism. It comes from a pack declaration or a human,
  never from the hypothesis author, and the relation keeps its true provenance.
- **Confirmation must discriminate:** no other ACTIVE rival may be SUPPORTED by, or predict, the
  same outcome; ties go to review, never to id order.
- **Escalation:** a NEED_HUMAN_REVIEW, or SUPPORTS and CONTRADICTS evidence that disagree, must
  create review items.
- **Symmetry:** the same rules apply to rejection and challenge.
