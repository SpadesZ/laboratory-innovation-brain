# Review 2 — executable verification against `661d8a0` (incomplete)

Condensed as delivered.

**This run, too, executed no attack.** An automated safety check stopped it while it was still
reading the code and planning tests. As a baseline, before that, it ran the implementer's own suite
`tests/e2e/test_causal_warrant_v1_1_postgres.py` on its own database (`lab_brain_v11_verify`, 63
migrations): 21 passed. That is not independent evidence for any claim. It reported no leads,
because none was executed. `git status` was clean, and its database was dropped.

**Resolution.** The delegated executable attacks were stopped twice. Rather than try a third
time, the implementer wrote the adversarial checks as committed PostgreSQL tests:
- `tests/e2e/test_causal_warrant_v1_1_adversarial_postgres.py`;
- the attack sections of `tests/e2e/test_causal_warrant_v1_1_postgres.py`.

They cover what a writer holding the database credential but no key would try:
- answering as the PI with the V1 call, unsigned, under the PI's enrolment with another key, and
  under a forged enrolment;
- replaying a genuine signature onto another question;
- non-canonical spellings of a key or signature;
- self-enrolment, shared keys, mislabelled key ids, non-members, authority keys used as reviewer
  keys;
- revocation before and after a belief moved;
- direct CONFIRMED rows for each blocking clause;
- rows written past every trigger;
- stranger declaration sets;
- flags on other content;
- the denial of service a junk answer can cause.

**This is not independent.** `REPORT.zh-TW.md` §7 says so: the executable adversarial evidence for
V1.1 was written by the implementer.
