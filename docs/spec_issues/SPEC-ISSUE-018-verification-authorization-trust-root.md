# SPEC-ISSUE-018: who may pre-register a verification, and on whose authority

Severity: GATE
Status: OPEN
Blocks gate: M4
Raised: 2026-11-01
Raised by: G0 reliability closure (`g0-reliability-authenticity-closure`), owner-boundary audit risk 2
Affected: §9 (verification), §14 (human oversight), `VER-001`, `SEC-002`, migrations `011s`, `011w`, `012p`

## The gap

`011s` lets a hypothesis proposed after screening be supported only by a check an accountable
person pre-registered. The specification names no mechanism that proves which person did it. With
one shared database role for every service, `actor_id` on the row was a string anyone could write.

`011w` makes the authorization a statement the person signs with an Ed25519 key that a review
authority enrolled for them in the project (scope `VERIFICATION_AUTHORIZATION`), reusing the
Causal Warrant Gate's design (`012p`, V1.1 §2). The trust root is then the pinned authority file
(`LAB_BRAIN_REVIEW_AUTHORITIES`) and whoever controls the deployment's configuration. The
specification does not say:

- who may be a review authority for verification authorizations, and whether it must be a
  different person from the warrant authority;
- whether the person who authorizes a verification may also run the episode or author the
  hypothesis (the warrant gate forbids both for warrant answers; `011w` does not, yet);
- how authorizer keys are issued, stored, rotated and revoked, and how fast a revocation must take
  effect.

## Competing readings

- Reading A: an authorization is an operational record; a database assertion of membership is
  enough (the pre-`011w` state).
- Reading B: an authorization is a signed statement of an enrolled person (what `011w` implements).
- Reading C: as B, plus the separation of duties of the warrant gate (not the episode's runner,
  not the hypothesis's author).

## Provisional implementation

Reading B: SQL holds the frame (signed, under an unrevoked enrolment of that person, after the
enrolment and the hypothesis, not in the future; rule (l) re-reads it), Python verifies the
signature on every read that counts it, and the scorer requires `unverified_authorization` to be
false (2.3.0).

## Follow-up (2026-11-02): the read path

An auditor showed that a SUPPORTS resting on a forged authorization, which SQL admits, could reach
the inputs of belief decisions. Every relation reader the product decides from now admits a
post-screening SUPPORTS only when its authorization verifies, and admits none when it was given no
verifier (`SqlRelationStore(support_verifier=...)`, branch `g0-authorization-read-path-closure`).
The open question is unchanged: the trust root, and whether SQL itself should verify signatures
(a database extension), are the Owner's.

## What needs an Owner / maintainer decision

1. Accept Reading B, or require C.
2. Name the authority (or authorities) for verification authorizations and their key custody.
3. Rotation period and revocation procedure for authorizer keys.
4. Whether to install a database extension that verifies Ed25519 (for example pgsodium), so the
   signature is checked at admission and not only on read.

## Follow-up (2026-11-04)

The belief projection now re-checks every SUPPORTS a stored decision counted
(`SUPPORT_UNVERIFIED`, commit `7f203df`). Finding F2 of
[the G0 security assurance report](../audit/g0-security-assurance-2026-11-04/REPORT.md) is open:
the services' role can register transition policies, which bypasses signed authorizations entirely.
Item 4 (in-database Ed25519 verification) is analysed in §7 of that report; no extension was
installed.
