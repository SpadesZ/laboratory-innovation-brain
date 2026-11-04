# SAI 3.5 — Appendix E: Security, human authorization, autonomy levels, permissions and cost

Version: `3.5.0-master-candidate.2`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-SEC-001–006, S35-COST-001–002, S35-REG-002–003 and S35-CWG-002 of
[SAI 3.5](../SAI_3.5.md). Inherited security rules (SAI 3.3 §14, SEC-001–004, COST-001; SAI 3.4
ASM-014) apply unchanged; the SAI 3.4 security decisions A3, A9 and A12 stay OPEN.

## 1. Identities

| Identity | Kind | Grants an account role? | Notes |
|---|---|---|---|
| Owner | the human decision owner of the specification and the deployment | no (not a third account role) | signs envelopes and Owner gates through an enrolled key; decisions OD-NN |
| ADMIN, MEMBER | the only human account roles | yes | ADMIN supervision is not scientific authority |
| project membership | project-scoped authorization | no | required for every read and write in a project |
| independent scientific reviewer | enrolled Ed25519 key, Causal Warrant Gate scope | no | not the campaign runner, not a hypothesis author, not a second account of either |
| verification authorizer | enrolled Ed25519 key, scope `VERIFICATION_AUTHORIZATION` (G0 line `011w`) | no | signs per-registration authorizations |
| envelope authorizer | enrolled Ed25519 key, scope `RESEARCH_ENVELOPE` | no | signs ResearchEnvelopes on the Owner's recorded decision |
| independent evaluator, arm-label custodian | Owner-assigned persons (OD-02) | no | not the implementer, not a second account of the implementer |
| component service identities | one non-human identity per component of [Appendix B](architecture-end-to-end.md) §2 | no | least privilege per §5 |
| worker service identity | non-human identity of each simulator worker | no | holds no reviewer or authorizer key |

A second account of the same natural person never counts as an independent reviewer, authorizer or
evaluator. Detecting second accounts depends on A3, which stays open; until it is decided,
independence of persons is an Owner responsibility recorded with each assignment.

## 2. Autonomy levels

| Level | Name | The system may, without a per-action human step | Still needs a human or the Owner |
|---|---|---|---|
| `AL0` | manual | record and display; nothing autonomous | every action |
| `AL1` | propose-only (default without an envelope) | propose problems, ideas, mechanisms, experiments and registrations; run zero-cost analysis | every registration and every execution beyond the zero-cost tier, each by a per-action human authorization |
| `AL2` | envelope-autonomous, zero cost | register and run zero-cost capabilities inside the envelope's bounds | anything with money, license, physical experiment or publication |
| `AL3` | envelope-autonomous, budgeted | as AL2, plus paid model calls and compute within the envelope's money and compute ceilings | licensed simulation, physical experiments, publication |
| `AL4` | envelope-autonomous, licensed simulation | as AL3, plus licensed Lumerical runs on qualified workers within the envelope's seat-time ceilings | physical experiments, fabrication, publication |

No level covers physical experiments, fabrication, publication, any CONFIRMED claim, any signed
review or warrant, non-PUBLIC egress, or a change to validators, protocols, thresholds, scoring or
policies (SAI 3.3 §23.4 human steering points stay human). The project's maximum level is an Owner
decision (OD-15); an envelope above it is refused at creation (S35-SEC-001).

## 3. ResearchEnvelope

An envelope is the Owner's advance authorization of a bounded class of research actions
(S35-REG-002). Its record is defined in [records-and-states.md](records-and-states.md) §2.

| Property | Rule |
|---|---|
| creation | only on a recorded Owner decision, signed by an enrolled envelope authorizer; content-hashed; append-only |
| bounds | project; problem scope; mechanism families; capabilities with declaration hashes; model routes; licensed products with seat-time ceilings; money and compute ceilings; maximum registrations and reframings; autonomy level; validity period |
| use | an automatic Registration is valid only if every bound holds at registration time and at dispatch; the check result is stored in the Registration |
| never inside | physical experiments, fabrication, publication, irreversible actions, non-PUBLIC egress, validator, protocol or policy changes |
| never authorizes | CONFIRMED, a signed review, a warrant, a release, a belief move (S35-REG-003, S35-CWG-002) |
| per-hypothesis pre-authorization | whether an envelope registration satisfies rule (l) of `011s` (signed per-hypothesis authorization) is OD-14; default no: such evidence is stored as CITES for post-screening hypotheses |
| end | expiry or EnvelopeRevocation; takes effect before the next reservation or dispatch (S35-SEC-006) |

## 4. Owner gates

| Class | Examples | Envelope may pre-authorize? | Authorization must name |
|---|---|---|---|
| money | paid model calls, paid compute, purchases | yes, within ceilings | actor, time, scope, ceiling, expiry |
| licenses | Lumerical products, seats, entitlements | yes, within seat-time ceilings and named products | actor, time, products, workers, ceiling, expiry |
| physical experiments | fabrication, measurement, lab time | no; per action | actor, time, experiment, registration, ceiling, expiry |
| publication | any external release of findings, data or claims | no; per action, and only for claims meeting S35-CWG-002 | actor, time, content hash, audience, expiry |

Automation never signs for the Owner; a timeout is never consent; an expired authorization covers
nothing (S35-SEC-002).

## 5. Permission matrix

R = read, W = append, — = refused. "Own" means records the component produces. Database rules hold
this matrix for every normal writer (S35-SEC-005); the application checks it too but never instead.

| Identity | problems, anomalies, ideas, distinguishability graphs, reframings | registrations, envelopes | Runs and raw artifacts | evidence, relations, belief events | Causal Warrant Gate tables | sealed evaluation material | cost ledger |
|---|---|---|---|---|---|---|---|
| ProblemDiscovery, HypothesisBrain, MechanismExplorer, ResearchReframing | R, W own | R | R | R | R (decisions only) | — | W own usage |
| NoveltyAuditor | R, W own assessments | R | — | R | — | — | W own usage |
| VerificationPlanner | R | R, W selection only | R | R | R | — | R |
| RegistrationRegistry | R | R, W | — | R | — | — | W reservations |
| PhysicalModelBuilder, SimulatorWorkers | — | R (own Job's registration) | W own | — | — | — | W own usage |
| NumericalValidation, PhysicalValidation, ModelQualification | R | R | R | W validation reports | — | — | W own usage |
| ValidationLoop | R, W feedback, stop records | R | R | W through admission and TransitionPolicy | R | — | R |
| CausalWarrantGate | R | R | R | R | W | — | — |
| ReportGenerator, ResearcherWorkspace | R | R | R | R | R | — | R |
| GovernancePlane, CostGovernance | R | R, W revocations | R | R | — | — | W |
| EvaluationPlane | R (outputs) | R | R | R | R | R, W | R |

## 6. Cost governance

- Every side effect reserves budget first and records realized consumption afterwards: tokens,
  compute seconds, money, seat time, wall time, including failures, retries and parsing repairs
  (S35-COST-001, SAI 3.3 COST-001, CostVector §9.4).
- Reservations reconcile against realized consumption per attempt, per campaign and per envelope.
- No endpoint is presumed free; a free declaration is an Owner act for one exact model at one
  endpoint, and a declared-free endpoint answering with billing signs loses the declaration (G0
  line `011v`; SPEC-ISSUE-017 on that line records the residual trust root).
- Ceilings stop reservations; raising one is an Owner authorization through the SAI 3.3 COST-001
  approval path; nothing raises it automatically or by timeout (S35-COST-002).
- Realized consumption appears in every report and is the matching basis of the A/B/C comparison
  (S35-CMP-002).

## 7. Owner stop

The Owner can stop any campaign and revoke any envelope or authorization at any time. The stop is
checked at every reservation and every dispatch; running Jobs are cancelled under SAI 3.4 ASM-007
with costs kept; partial outputs are diagnostic only; the campaign closes as `CLOSED_STOPPED` with
the stop recorded (S35-SEC-006).

## 8. Known residuals

| Residual | State |
|---|---|
| A3 (second accounts), A9 (audit merge), A12 (direct SQL by privileged roles) | OPEN SAI 3.4 security decisions; database rules do not bind a superuser or migrator |
| shared database role for services today | per-component identities (§5) do not exist yet |
| verification-authorization trust root (G0 line SPEC-ISSUE-018) | authority holder can enrol anyone; separation of duty for authorizations is an open decision on that line |
| forged-authorization read path (G0 line) | fixed on the pushed, unmerged branch `g0-authorization-read-path-closure` (from `f41758c`; source code at `2a96ee8`, no source change after it), pending independent audit; as reported there: full PostgreSQL suite 3583 passed / 0 failed, complete mutation battery 928/929 at `2a96ee8`, the one survivor killed afterwards by an added test |
| services' role writes transition policies (finding F2, `claude/lib-implementation-agent-47evs0-g0`) | open, high: a registered requirement-free policy lets an ALLOW decision with an empty snapshot project to SUPPORTED; fix needs an Owner decision on database privileges |
| forged SUPPORTS through the belief projection (`claude/lib-implementation-agent-47evs0-g0`) | fixed on that pushed, unmerged branch (`SUPPORT_UNVERIFIED`), pending independent audit |
| free-declaration trust root (G0 line SPEC-ISSUE-017) | a proxy that strips billing signs is indistinguishable from a free model server |

## 9. Authorization ladder: exploration, spending, admission, support and confirmation

Five separate things are easy to conflate. Each needs its own record and its own authority, and no
rung implies the next (S35-HYP-001, S35-SEC-001, S35-REG-003, S35-CWG-002).

| Rung | What it is | Created by | Authority | What it does **not** do |
|---|---|---|---|---|
| exploratory idea | a stage-1 proposal (ExploratoryIdea) | HypothesisBrain, ProblemDiscovery, MechanismExplorer, ResearchReframing | none needed to exist; zero-cost by itself | it is not a hypothesis, not evidence, not a finding; it cannot be the subject of a reservation for a test |
| spending | a budget reservation and realized-cost record for a model call, compute, a licensed run or an experiment | CostGovernance on a reservation request | AL2 (zero cost), AL3 or AL4 within the envelope's ceilings, or an Owner gate (§4) | it authorizes consumption only; an authorized exploratory model call produces a stage-1 output and nothing more |
| admission | stage 2 (testable hypothesis) | the SAI 3.3 §8 Hypothesis Admission Gate | the admission rule, unchanged | it creates no evidence and authorizes no test |
| registration and support | a prospective Registration (S35-REG-001), then SUPPORTS from admissible prospective evidence through TransitionPolicy | RegistrationRegistry; ValidationLoop | a signed per-registration authorization or a covering envelope for the registration; the inherited prospective-evidence rules for support, including any per-hypothesis signed authorization they require | support is not confirmation; an envelope never replaces a per-hypothesis signed authorization an inherited rule requires (OD-14 default) |
| independent causal confirmation | stage 3 (CONFIRMED) | the Causal Warrant Gate only | a qualifying signed review by an independent reviewer, plus the Owner gate for any consequential action (S35-CWG-002) | nothing below it, and no envelope, level, automation or timeout, substitutes for it |

Consequences:

1. **Exploration may cost money without producing evidence.** Under AL3 an envelope may pay for
   idea generation and screening calls. Their outputs stay stage 1; they never reach SUPPORTS, and
   their cost stays in the campaign's realized consumption and in every matched-cost comparison
   (S35-COST-001, S35-CMP-002).
2. **AL2 and AL3 differ only in what may be spent**, never in what counts as evidence: the same
   admission, registration, prospective-evidence and confirmation rules apply at every level.
3. **OD-14 default.** Until the Owner decides OD-14, a ResearchEnvelope does not satisfy a rule that
   requires an individual signed authorization (rule (l) of `011s` with the `011w` signatures on the
   G0 line); a SUPPORTS whose only authorization is an envelope registration is stored as CITES for
   a post-screening hypothesis (S35-REG-003).
4. **Forged or unverifiable authorizations count as absent.** A rung that needs a signed
   authorization is reached only when the signature verifies against an enrolled key for the right
   scope and record; otherwise the reader fails closed (the read-path rule of the G0 line, S35-ISSUE-06).

The executable statement of the ladder is `reachable()` and `support_admissible()` in
[semantic_reference.py](semantic_reference.py).

