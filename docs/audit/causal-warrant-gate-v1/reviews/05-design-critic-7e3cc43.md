# Review 5 — third pass on `7e3cc43` (same reviewer as reviews 2–3)

Read-only. Report as delivered; resolutions in `../REPORT.zh-TW.md` §5.

The fixes close every false-confirmation path raised earlier. Three new defects remain: two let
one wrong human approval through, and one blocks legitimate confirmations.

## Status of earlier items

| item | status | evidence |
|---|---|---|
| B1 twin / silent-falsifier | **RESOLVED** | `binds` requires the signature as SUPPORTS plus every refuting outcome as CONTRADICTS; `family` is every member bound to the candidate's class, and `contested = family & refuted` blocks |
| B2 grant integrity | **PARTLY** | 012o refuses grants from the episode actor, the author, a non-member, or on a closed or expired review; a deferred trigger makes every grant its review's closure. Identity is still whatever `--actor` says |
| B3 queue-dependent threats | **RESOLVED** | threats are read off the records; `_ask` queues them; with no queue the episode parks |
| B4 both-sides skip | **RESOLVED** | the skip counts warranted records only |
| B5 sets and supersession | **PARTLY** | digests are checked at load. Only the current set is registered, so a catalog bump would break past DOMAIN re-checks. `superseded` is passed only by the main research episode |
| B6 discrimination review | **NOT RESOLVED** (deliberately) | see N1 |
| B7 loose ends | **RESOLVED** | |
| #4 silent rivals | **NOT RESOLVED** (deliberately) | rivals with no relations are listed; a rival tested elsewhere but silent on the candidate's observation is not mentioned |
| #11 other pending reviews | **PARTLY** | `held` covers blocking conflicts; rivals stuck at CONDITION_MATCH_UNKNOWN or INDEPENDENCE_BASIS_NOT_MODELLED do not block |

Also verified: relation-content immutability; `warrant_refs` validation; the grant↔prediction
match; the outcome↔attestation check; per-type gating; stored-relation comparison; exclusion
requiring CONTRADICTED state plus a warranted refutation.

## New defects

**N1 — HIGH (over-blocking): a paraphrase of the true cause deadlocks the episode.** Catalog class
C is in the set (bound), and so is a model hypothesis H restating it in other words (unbound); both
affirm C's signature.
- **Reviewer approves H's link:** two SUPPORTED members with different keys give
  COMPETING_SUPPORT. That stop is not in the waiting set, so the episode closes for good.
- **Reviewer rejects H's link:** the rejected SUPPORTS still affirms the observation. Nothing true
  refutes a paraphrase, so the episode parks as SUPPORTED_UNDISCRIMINATED forever.
- **Fix:** an IDENTITY/DISCRIMINATION verdict that merges H into C's family or discharges H.

**N2 — MEDIUM (false confirmation): one approval overrides the domain's declared signature of
another class.**
- The foreign-signature block is waived when the family holds a warranted relation for it
  (`accounted`). Replay CE-1 with a reviewer approving the proxy's `DISAGREES → SUPPORTS`: the
  domain's statement becomes a note, and the proxy is CONFIRMED.
- The CLI packet does not show that signature fact.
- **Fix:** print the signature owner in `review show`, and require an explicit identity statement.

**N3 — MEDIUM (false confirmation): the signature check reads relations, not observations.** An
unpredicted outcome produces no relation. Example: C is confirmed on the connectivity check while
the normalization check observed DISAGREES, the signature of a class not in the set, and no note
appears.
- **Fix:** scan the episode's attestations against `signature_of`.

**N4 — LOW-MEDIUM (over-blocking).**
- In a single-member project nobody may grant, and the workaround (a second self-asserted id) is
  theatre.
- Exclusion needs CONTRADICTED, and the only reject policy is simulation-gated, so a measured
  falsifier can never exclude a rival. Latent here: there are no measurement workflows.

## Verdict for an auditor

Approve as a fail-closed P0 safety gate, with conditions; not as "ready for real research".
- **What holds now:** a model's declared effect alone can no longer confirm or refute anything;
  replay is sound, history hashes are preserved, and quarantine works.
- **Remaining false-confirmation routes:** they need a reviewer error made without the key fact
  (N2), or an unpredicted signature (N3). Both are small fixes before sign-off.
- **The main cost is throughput:** see N1, B6, N4.
- **Document:** #4, B6, revocation, CLI identity, the B5 archive gap, and the spec amendments.
