# SAI 3.5 — Appendix D: Provenance, novelty, evidence independence and contamination

Version: `3.5.0-master-candidate.2`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-EVI-001–004, S35-NOV-001–003 and S35-REG-004 of
[SAI 3.5](../SAI_3.5.md).

## 1. Provenance

Every SAI 3.5 record carries the envelope and provenance fields of
[records-and-states.md](records-and-states.md) §1. In addition:

| Object | Provenance it must carry | Inherited rule |
|---|---|---|
| model-produced idea, critique, relation judgment | InferenceProvenance: model and version, slot, route, prompt version, EvidenceBundle hash, usage and realized cost | SAI 3.3 LLM-001, EVI-006, AGT-010, AGT-017 |
| literature passage | provider, query (PUBLIC), retrieval time, version and content hash, locator, license class, rights per use | SAI 3.3 SRC-001, SEC-004; SAI 3.4 ASM-003 |
| simulation output | Run, BuildManifest, spec hash, provider, solver product and version, worker identity, checkout record, registration id | SAI 3.3 SIM-001, EVI-009; SAI 3.4 ASM-012, ASM-017 |
| measurement | Run or Artifact, capture time (known, never NULL), instrument and conditions, registration id, authorizing person | SAI 3.3 EVI-001, EVI-009; G0 line `011s` rule (j) |
| belief move | BeliefRevisionEvent with its durable `BELIEF_TRANSITION` Decision, re-derived on read | SAI 3.3 EPI-005 (`v3.3-a12`, `v3.3-a13`) |
| confirmation | Causal Warrant Gate decision, warrant, signed review, confirmation rule | Causal Warrant Gate V1.1 |

A record whose provenance is incomplete may be stored for diagnosis but cannot justify a later
transition, registration, selection or report statement (S35-EVI-002).

## 2. Prior-art coverage

A PriorArtSearchRecord (SAI 3.3 §17.20) supporting a novelty statement must record:

- the sources actually searched (not configured), by coverage class: peer-reviewed literature,
  preprints, patents, theses, technical reports, code repositories; at least literature and patents
  unless Owner decision OD-11 sets a different minimum;
- the queries as sent (PUBLIC only), date range, retrieval time and provider versions;
- result and deduplicated-work counts (SAI 3.3 EVI-004 work identity);
- limitations: unreachable providers, paywalled or rights-restricted material that was not read,
  languages not covered;
- each model's documented training cutoff, compared with the prior-art dates the novelty statement
  relies on, and the result of a memorization probe for literature-derived findings (S35-EVI-004).

The novelty statement is never broader than this coverage. "Not found in the covered sources up to
date D" is the strongest form; "novel" without that qualifier is not allowed (S35-NOV-001).

## 3. Novelty classes

Every finding carries exactly one class (S35-NOV-002). The Novelty Auditor assigns it by these
criteria, in this order; the first that applies wins.

| Class | Criterion | Maximum claim strength |
|---|---|---|
| `KNOWN_MECHANISM_REDISCOVERY` | the finding's mechanism has the identity of, or is certified `INDISTINGUISHABLE` ([Appendix S](mechanism-distinguishability.md) §6) from, a mechanism in the covered prior art for comparable conditions; renaming never changes this | "re-identified a known mechanism for this device and conditions" |
| `ENGINEERING_OPTIMIZATION` | the finding improves a design or operating point within known mechanisms and makes no mechanism claim | "a better design or operating point under the stated model and conditions" |
| `MODEL_CORRECTION` | the finding changes a model's form or parameters to remove a residual, using known physics | "a corrected model for this scope"; requires S35-VAL-004 lineage and re-validation |
| `NEW_PHYSICAL_KNOWLEDGE_CANDIDATE` | a mechanism certified `DISTINGUISHABLE` from every mechanism in the covered prior art (or `UNRESOLVED` against some, which are then listed and bound the claim), or a quantitative relation absent from it, not yet stage 3 with independent physical validation | shown with its epistemic stage and claim state; never as new knowledge |
| `NEW_PHYSICAL_KNOWLEDGE` | as the candidate class, and the claim is stage 3 (Causal Warrant Gate) with independent physical validation (S35-VAL-005) and a covering prior-art record | "a mechanism not found in the covered prior art, confirmed on independent physical data", within its scope |

At G-D2 and above, at least two independent blinded domain reviewers assign classes too; their
agreement with the auditor is reported (S35-CMP-003). Disagreement does not let the auditor's class
stand unreviewed: the pre-registered adjudication rule decides.

## 4. Evidence independence

Independent evidence count for a discovery claim follows SAI 3.3 claim identity (EVI-004) and the
SAI 3.4 source families (ASM-010, ASM-012). The following count **once**, together:

- the same source work in any version (preprint, journal version, review, translation);
- outputs of one model family, including repeated runs, mesh or step levels and sweep points;
- different solvers that share a material model, a geometry source or a calibration family;
- measurements on one device, one process batch, or with one instrument chain when the claim is
  about the device or process;
- evidence that descends, by lineage, from the observation that motivated the hypothesis.

`DEPENDENCE_UNKNOWN` counts zero until resolved. Evidence the campaign produced itself counts as
independent of the hypothesis only when it was registered before it existed (S35-REG-001) and its
lineage is clean (S35-REG-004). Simulated evidence is evidence about the model under its conditions,
never a measurement (SAI 3.4 ASM-012).

## 5. Prospective evidence (no retrospective self-support)

S35-REG-004 applies to every hypothesis, including reframed successors. A SUPPORTS relation is
admitted only if every underlying observation passes the rules of migrations `011p` and `011s`
(rules (a)–(k)) on the G0 line at `f41758c`, restated here for implementation:

| Rule | Condition |
|---|---|
| time | the observation was captured or computed after the hypothesis was registered; registration time is the database clock |
| known capture time | empirical data has a known capture time; NULL means unknown, and unknown is not new |
| lineage | walking `derived_from` and `previous_artifact` links up to depth 16 reaches no screening output, no run started before registration, no empirical data captured before registration, no unknown-time data and no unrecorded artifact; cycles or depth beyond 16 fail closed |
| capability kind | the capability's kind comes from the DomainPack declaration (owner-written, append-only); query, historical comparison and expert review never produce new evidence; rule checks and surrogates count only on new empirical data |
| authorization | the Job is bound to a Registration; where a rule requires a per-hypothesis human pre-authorization (rule (l) with `011w` signatures), an envelope registration satisfies it only if Owner decision OD-14 says so (S35-REG-003) |

Evidence failing any rule is stored as CITES with the reason, never silently dropped. The
forged-authorization read-path bypass an auditor found on the G0 line is fixed on the unmerged
branch `g0-authorization-read-path-closure` (SUPPORTS of a post-screening hypothesis enters decision
inputs only when its authorization verifies, fail closed without a verifier), pending independent
audit; SAI 3.5 relies on that fix and adds no weaker path.

## 6. Contamination defenses

| Threat | Defense | Requirement |
|---|---|---|
| a Discovery or Validation component reads a sealed reference, holdout or truth | sealed material lives in the evaluation plane; database rules refuse other identities; every read is audited | S35-EVI-004, S35-LOOP-001, S35-SEC-003 |
| a model route has seen a sealed answer | the route is marked non-independent for that case and cannot count as independent evidence or evaluation there | S35-EVI-004 |
| a literature "discovery" is memorized | training cutoff against prior-art and resolution dates; memorization probe; a positive probe downgrades the novelty class to rediscovery and is reported | S35-EVI-004, S35-NOV-001 |
| benchmark cases overlap development data or public corpora | frozen overlap check, fresh seeds after the freeze, pre-registered exclusion rule | S35-CMP-007 |
| implementer-written synthetic worlds stand in for an independent evaluation | only evaluator-generated hidden worlds are G-D evidence | S35-CMP-004 |
| evaluation answers flow back into modeling or refinement | no arrow from the evaluation plane back; a holdout seen by a builder leaves the independent set | SAI 3.4 ASM-010; S35-CMP-004 |

A detected contamination is reported in the campaign or evaluation record and in the report; it is
never silently dropped.
