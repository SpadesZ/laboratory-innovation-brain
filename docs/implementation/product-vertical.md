# The product vertical: `lab-brain research run`

Date: 2026-09-28
Scope: the first usable input-to-output Laboratory Innovation Brain workflow, built from
capabilities already implemented. **Not a milestone.** No Requirement or Test ID was added, no
milestone status changed (M0–M3 `DONE`/hard-locked; M4 `IN_PROGRESS`, paused on TST-001; M5
`IN_PROGRESS`, implementation approved), and M6 was not started. The real Lumerical environment
was not touched.

## 1. What a user does, and what comes back

```
lab-brain research run --project P --actor A --goal "..." \
    --measurement report.md [--run-record F] [--note F] \
    [--verification-input device.json] \
    [--literature-corpus corpus.json --literature-query "a query you declare public"] \
    --artifact-root DIR [--report report.md]
```

One Markdown report, printed and optionally written, with: the result (CONFIRMED / PROVISIONAL /
INCONCLUSIVE / NOT_REACHED), stage-by-stage status, input status, evidence and sources (internal
statements and external literature with rights and status), the competing hypotheses with their
falsifiers and typed predictions, the debate and critique, the governed belief state of every
rival, the verification plans, the completed actions (Job, Run, outcome, output artifact), the
**pending simulation actions** (blocked, with why and what would unblock them), the actions awaiting
a person, next steps, provenance ids, and an explicit list of what did **not** run.

## 2. Architecture

```
interfaces/cli.py  research run            parse args, open the connection, select the domain's
                                           vertical BY NAME (entry point), print the report
research/service.py ResearchEpisodeService  composes the existing authorities; decides nothing
research/evidence.py StatementAdmitter      verbatim REPORTED statements through M1's admission gate
research/literature.py                      M5's registry + snapshot service + admission, unchanged
research/report.py, render.py               plain data, Markdown presentation
research/vertical.py ProductVertical        what a DomainPack supplies (domain-agnostic contract)
cognition/catalog_reasoner.py               a LOCAL rule-based reasoner behind the model slots
domains/silicon_photonics/product.py        the §25.1 mechanism catalog; the pack as THIS
                                           deployment can run it
```

| Stage | Authority it calls, unchanged |
|---|---|
| authorize | `ScientificReadGate.require_project` — non-members get nothing |
| episode | `IngestionService.open_episode` (§17.3) |
| ingest | `IngestionService.submit` + `ingest` — raw bytes hashed and stored before parsing, one Job and Run per file, Knowledge Inbox item |
| evidence | M1 `admission_gate` — ACL, EVI-010 re-derivation from stored bytes, canonical body; statements are verbatim units, REPORTED, trust class as the user declared |
| external | M5 `ConnectorRegistry`, `ExternalSnapshotService`, `ExternalEvidenceAdmission`; only with a query the actor declares PUBLIC, under an egress policy the actor declares for the run |
| hypotheses | M3 `StructuredDebate` (intent-aware retrieval, positions, the Critic's inverted retrieval over the literature, §8 admission, typed predictions) |
| verification | M4 `VerificationLoop` (least-cost planning, typed tools, Jobs/Runs, evidence admission, governed belief moves, failure analysis) |
| pending | M4 `LeastCostPlanner`, asked over the loop's own final state with the pack's DECLARED descriptors: "what would you choose if every capability could run here?" — reported, never executed, never stored |

**Selecting the pack.** §24.2 forbids orchestration from importing a DomainPack (TID251 enforces
it). The pack exposes `product_vertical`, named in `pyproject.toml` under the
`lab_brain.domain_verticals` entry-point group; `--domain` selects it by name. `research/` imports
no pack and no provider (`tests/unit/test_research_vertical.py`).

## 3. No simulator, and no pretending

`product_vertical` wires a backend for every capability this deployment can execute — the two
solver-free design readers — and marks every SIMULATION capability UNAVAILABLE with the reason
(no licensed Lumerical provider, installation or seat; TST-001, risk R-1). This is §17.24's existing
rule: the planner never selects an UNAVAILABLE capability, so nothing unexecutable is attempted and
nothing is mocked. Cheap checks run normally. When the planner, over the declared descriptors, would
choose a simulation next, the report lists it as **BLOCKED** with what it would decide, its
estimated cost and what would unblock it; the episode is **SUSPENDED** with that reason, so it is
resumed as the same episode when a simulator exists. Measurement and fabrication have no workflow:
the loop stops for a person and the report says which action.

## 4. No language model, and no pretending

No model slot is configured in this deployment. The debate's slots are served by
`CatalogReasoner`: a deterministic reader of the pack's declared mechanism catalog (statements,
falsifiers, typed predictions, and the words that point at or against each mechanism). Its
`ModelSlot` is `rules:sp.rs_anomaly_mechanisms@1.0.0`, provider `local-rules`, reach LOCAL; every
InferenceProvenance row it produces carries that identity and the report states it. It cannot
invent a mechanism the catalog does not declare. The debate gate is reported as advisory because no
calibrated BenchmarkPolicy is active.

## 5. Changes outside the new modules

- `composition.IngestionService.classifier(*, artifact_of_cited_work=None)` — optional, default
  behaviour unchanged. M5's external attestations cite a SourceWork; the fallback resolves them to
  their snapshot artifact so the Critic may be shown literature. The label still comes from the
  read gate's own occurrence loader. Without it classification refused every such bundle.
- `core/repositories/external_sources.SqlExternalSourceStore.snapshot_artifact_of_attestation` —
  the resolver above; never resolves a quarantined snapshot.
- `verification/loop.VerificationLoop.planning_inputs` — a read-only accessor returning the states
  and projected ConditionMatch the loop itself plans from.
- `core/models/identifiers`: `"episode": "epi"`. **A latent defect found by this work:**
  `open_episode` without an explicit id minted the unregistered kind `episode`, so
  `lab-brain episode open` without `--episode` raised. Covered by
  `test_episode_open_mints_its_own_id_when_none_is_given`.
- `interfaces/cli.py`: `--artifact-root` is resolved to an absolute path. **Second latent defect:**
  the local artifact store builds file URIs, which a relative path cannot express, so both
  `episode open` and `research run` failed with a relative artifact root.
- `pyproject.toml`: the `lab_brain.domain_verticals` entry point.
- `scripts/mutation_battery.py`: 7 entries.

## 6. Verification

End to end on PostgreSQL through `cli.main` (`tests/e2e/test_research_episode_postgres.py`): the
coarse-mesh device with a measurement report and the literature corpus — two checks executed as
Jobs with Runs, two rivals CONTRADICTED through authorised TransitionPolicy decisions, no simulation
Job or Run anywhere, `cap:sp.mesh_sensitivity` reported BLOCKED as the best next action, the
four-point probe awaiting a person, the episode SUSPENDED, literature pinned and admitted (a
RETRACTED paper reported as such); the open-via device — CONFIRMED by a cheap check with its Run
and artifact trace, episode COMPLETED; no verification input — the debate still reports,
NOT_REACHED; a non-member — exit 1, no rows; a literature corpus without a declared query — exit 2,
nothing sent. Unit: the reasoner, the SiPh vertical (every simulation blocked with its reason, the
catalog bound to declared outcome spaces), the renderer, the import boundary.

| Gate | Result |
|---|---|
| ruff / format / mypy strict | clean / 381 files formatted / no issues in 210 source files |
| backend-free suite | 1601 passed, 715 skipped (backend-gated), 0 failed |
| PostgreSQL suite, freshly migrated (49 migrations, re-apply a no-op) | 2314 passed, 2 skipped (`lumerical`, `network`) |
| M4 root-cause benchmark `--check` (regression) | report current |
| mutation battery (PostgreSQL profile on) | **244/244 killed** (237 prior entries still killed; 7 new product entries) |
| coverage ratchet, obligation inventory, status, benchmark reports | current; M0a-M3 enforced, M4 and M5 IN_PROGRESS |
| commit hygiene | no AI attribution |

## 7. Limits

- The reasoner is catalog-bound and lexical: good for the declared mechanism classes, blind to any
  other. A language model behind the same slots changes nothing else.
- Statements are verbatim units; nothing extracts quantities or conditions from them, so they
  inform the debate and never move belief — belief moves only on Run-derived evidence.
- External literature here is a local corpus file; the connectors for live providers exist (M5)
  and are not configured.
- One domain (Silicon Photonics, the Rs anomaly class) supplies a vertical today.
