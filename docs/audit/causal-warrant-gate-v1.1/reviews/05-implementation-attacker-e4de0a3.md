# Review 5 — implementation attacker against `e4de0a3` (did not run)

**No attack executed.** This is the third delegated executable attack on V1.1 (after reviews 1
and 2). An automated safety check stopped it while the tester was still reading the code: before
it created a database, wrote a script or connected to anything. It did not try again in another
form, and neither did the implementer.

## What it was asked to do

The tester had its own detached worktree at `e4de0a3`, its own disposable database, and no keys.
It was to attempt, with executable scripts:
- a trusted or mined confirmation that the record does not support, including rows written past
  the triggers;
- replay of a genuine signature across projects, reviews, relations, scopes and enrolments;
- defeating revocation and rotation;
- an SQL/Python rule divergence in the accepting direction;
- forging, moving or removing flags;
- tampering with the declaration registry;
- escaping the restricted services' role (`lab-brain admin db-roles`).

## What it read before it stopped

- the design record;
- `012p` in full;
- `failures.py`, `research/confirmation.py`, `security/reviewer_identity.py`,
  `core/models/reviewer.py`.

It reported two observations from reading only: the second line of defence is the Python
re-derivation, and a superuser deleting a flag is a stated residual. Neither was tested.

## Hygiene

It created no database and no role. `git -C lib-attack status` was clean at `e4de0a3`.

## Consequence for this audit

The executable adversarial evidence for V1.1 is still the implementer's own:
- `tests/e2e/test_causal_warrant_v1_1_adversarial_postgres.py`;
- the attack sections of `tests/e2e/test_causal_warrant_v1_1_postgres.py`;
- the least-privilege escapes in `tests/integration/test_least_privilege_postgres.py`;
- the randomized rule-agreement check.

None of it is independent. An independent attack is still owed: a person, or a tester who is not
stopped, working to the same rules (disposable database, `atk_` roles, drop both).
