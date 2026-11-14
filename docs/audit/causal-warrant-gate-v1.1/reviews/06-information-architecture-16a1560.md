# Review 6 — information architecture and data integrity, `16a1560` (excerpt for the gate)

An independent reviewer audited how the product organizes research data: the schema, the
storage and the provenance links. It worked on its own disposable database (63 migrations) and
probed with synthetic rows inside rolled-back transactions. It did not read or write the
deployment's database.

The full report covers the whole product. It goes with the product audit on the UX branch; see
the audit report §7. This excerpt keeps what bears on the Causal Warrant Gate, condensed as
delivered. [V] means executed or read at the cited line; [I] means inferred.

| # | sev. | finding (reviewer) | resolution |
|---|---|---|---|
| F-04 | MED | `hypotheses` is keyed on (project_id, hypothesis_id), but `012p:223` (the grant's author check) and `012o:347` (the relation's episode check) look a hypothesis up by id alone. Probe: the same id in two projects [V]. | **Fixed** (`fa9e982`). Every gate lookup of a hypothesis and its predictions is scoped to the project, and `012p` restates `012o`'s relation check. A test for each failed before the fix: SQL and the loop disagreed, and a colliding hypothesis blocked a legitimate run. |
| F-07 | MED | The Markdown export renders the frozen stored report, which carries no flag. Exporting `fan:30d9407f`'s episode would show the CONFIRMED cause without its FALSE_CONFIRMATION flag [I]. | **Open.** The fix (export the live flags and reliance) belongs to the web export; it is on the UX branch's list. |
| F-01 | HIGH | The question's sensitivity label is not stored. A continuation re-debates under the default INTERNAL (`service.py:270, 611-617, 1200`) [V]. | **Open, not a gate defect.** Needs a migration (store the label) or an interim fail-closed rule. Owner decision. |
| F-02 | HIGH | A withdrawn relation can be reopened by UPDATE, and invalidation overwrites `actor_id` with the invalidator (probe P15) [V]. The gate's "the runner does not warrant" reads `relation.actor_id`. | **Open.** Needs a migration (`invalidated_by_actor_id`, no reopening). Owner decision. |
| F-03 | MED | The database accepts cross-project and dangling references in relation support lists, bundle members and observation run ids (probes P1–P5) [V]. | **Partly.** `012p`'s relation check now reads attestations and observations in the relation's project. The other tables need insert-time triggers (a migration). |
| F-06 | MED | Every loop run appends a failure analysis; nothing marks which is current [V]. | Open: owner decision (a `research_run_id` or a "current" view). |
| F-16 | LOW | Declaration-set supersession can fork: two versions supersede one [V]. | Python refuses the mismatch before anything runs (`SqlDeclarationSetStore.ensure`), so it fails as a denial [I]. A unique supersession index needs a migration. |

The reviewer also confirmed:
- the scientific core is project-scoped with composite foreign keys, and append-only;
- there is no row-level security, and the deployment has a single database role. §14 of the
  design record answers the second.
