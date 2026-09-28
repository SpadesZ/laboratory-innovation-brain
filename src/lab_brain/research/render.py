"""Render an `EpisodeReport` as Markdown -- presentation only; every line is a report field."""

from __future__ import annotations

from lab_brain.research.report import EpisodeReport

_EXCERPT = 220


def _clip(text: str, limit: int = _EXCERPT) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "..."


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: EpisodeReport) -> str:
    r = report
    out: list[str] = []
    add = out.append

    add(f"# Research episode {r.episode_id}")
    add("")
    add(f"**Goal:** {r.goal}")
    add("")
    add(
        f"Project `{r.project_id}` | actor `{r.actor_id}` | domain `{r.domain}` | "
        f"trace `{r.trace_id}` | episode state **{r.episode_state}**"
    )
    add(f"Started {r.started_at.isoformat()} | finished {r.finished_at.isoformat()}")
    add("")

    if r.continuation is not None:
        k = r.continuation
        add(f"## Continuation: run {k.run_ordinal} of this episode")
        add("")
        add(f"Resumed from {k.resumed_from}.")
        add("")
        add(f"Reasoning: {k.reasoning}.")
        add("")
        add("Earlier runs:")
        for line in k.earlier_runs:
            add(f"- {line}")
        if k.earlier_checks:
            add("")
            add("Checks executed by earlier runs (not executed again):")
            for line in k.earlier_checks:
                add(f"- {line}")
        for line in (*k.superseded_jobs, *k.recovered):
            add(f"- {line}")
        add("")

    add("## Result")
    add("")
    add(f"**{r.conclusion.status}** -- {r.conclusion.statement}")
    if r.conclusion.ruled_out:
        add("")
        add("Ruled out by executed checks: " + "; ".join(r.conclusion.ruled_out))
    if r.conclusion.still_competing:
        add("")
        add("Still competing: " + "; ".join(r.conclusion.still_competing))
    if r.conclusion.trace:
        add("")
        add("Confirmation trace: " + " -> ".join(r.conclusion.trace))
    if r.pending:
        best = next((p for p in r.pending if p.best_next), r.pending[0])
        add("")
        add(
            f"**Pending simulation:** `{best.capability_id}` is the best next verification action "
            f"and cannot run here -- {best.blocked_because}."
        )
    add("")

    add("## Stages")
    add("")
    add("| Stage | Status | Detail |")
    add("|---|---|---|")
    for s in r.stages:
        add(f"| {s.stage} | {s.status} | {_cell(s.detail)} |")
    add("")

    add("## Inputs")
    add("")
    add("| File | Role | Declared as | State | Artifact | Units | Statements |")
    add("|---|---|---|---|---|---|---|")
    for i in r.inputs:
        add(
            f"| {_cell(i.name)} | {i.role} | {i.declared_kind} | {i.state} | "
            f"`{i.artifact_id or '-'}` | {i.evidence_units} | {i.statements} |"
        )
    if r.verification_input:
        add("")
        add(f"Verification input: {r.verification_input}")
    add("")

    add("## Evidence and sources")
    add("")
    if r.evidence:
        for e in r.evidence:
            add(
                f"- `{e.attestation_id}` ({e.origin}, {e.trust_class}) {_cell(e.source)} "
                f"[{e.locator}]: '{_clip(e.excerpt)}'"
            )
    elif r.continuation is not None:
        add(
            "- This run admitted no statement. The statements the hypotheses were debated over "
            "were admitted by run 1 of this episode and stand unchanged."
        )
    else:
        add("- No statement was admitted as evidence.")
    add("")
    if r.literature is not None:
        lit = r.literature
        add(f"### External literature -- `{lit.provider}`")
        add("")
        add(f"Source: {lit.description}. Query (declared public by the actor): '{lit.query}'.")
        add(f"Egress policy for this run: {lit.egress_policy}.")
        add(f"Passages discovered: {lit.discovered}.")
        add("")
        for c in lit.consulted:
            admitted = (
                f"`{c.admitted_attestation_id}`" if c.admitted_attestation_id else "not admitted"
            )
            add(
                f"- {_cell(c.title)} `{c.locator}` -- {c.trust_class}, licence {c.license}, "
                f"kept {c.retention}, status {c.status}; {admitted}. {c.note}"
            )
        for refusal in lit.refusals:
            add(f"- refused: {refusal}")
        add("")

    add("## Competing hypotheses")
    add("")
    if not r.hypotheses:
        add("No hypothesis was admitted.")
    for h in r.hypotheses:
        add(f"### {h.mechanism} -- **{h.final_state}**")
        add("")
        add(f"`{h.hypothesis_id}` | {h.statement}")
        add(f"- Falsifier: {h.falsifier}")
        add(f"- Cheapest test: `{h.minimal_test}`")
        add("- Predictions: " + "; ".join(h.predictions))
        for objection in h.objections:
            add(f"- Critique: {objection}")
        add("")

    add("## Debate and critique")
    add("")
    if r.debate is None:
        add("The debate did not run.")
    else:
        d = r.debate
        add(
            f"Debate `{d.debate_id}` | reasoner {d.reasoner} | {d.rounds} round(s) | "
            f"stopped: {d.stop_reason}"
        )
        add("")
        for position in d.positions:
            add(f"- Position: {position}")
        add(
            f"- Critic cross-examined {d.critic_evidence} evidence item(s); its inverted "
            f"retrieval found {d.inverted_evidence}."
        )
        if d.alternatives_named:
            add("- Critic named alternatives: " + ", ".join(d.alternatives_named))
        add("- Surviving after critique: " + (", ".join(d.surviving) or "none"))
        add("- Contradicted by critique: " + (", ".join(d.contradicted) or "none"))
        add(f"- Debate gate: {d.gate}")
    add("")

    add("## Belief state")
    add("")
    add("| Hypothesis | Mechanism | State | Governed moves |")
    add("|---|---|---|---|")
    for b in r.belief:
        add(
            f"| `{b.hypothesis_id}` | {b.mechanism} | {b.state} | "
            f"{_cell('; '.join(b.moves) or '-')} |"
        )
    add("")

    add("## Verification plan")
    add("")
    if not r.plans:
        add("No verification plan was made.")
    for n, p in enumerate(r.plans, start=1):
        add(f"{n}. `{p.plan_id}` -- **{p.decision}**" + (f" -> `{p.chosen}`" if p.chosen else ""))
        add(f"   {p.summary}")
        for candidate in p.candidates:
            add(f"   - {candidate}")
    add("")

    add("## Completed actions")
    add("")
    if not r.completed:
        add("No verification action was executed.")
    for a in r.completed:
        add(
            f"- `{a.capability_id}` ({a.action_type}) **{a.status}** by {a.backend} -- "
            f"job `{a.job_id}`, run `{a.run_id}`"
        )
        for outcome in a.outcomes:
            add(f"  - {outcome}")
        if a.output_artifacts:
            add("  - output: " + ", ".join(f"`{x}`" for x in a.output_artifacts))
        if a.detail:
            add(f"  - {a.detail}")
    add("")

    add("## Pending simulation actions")
    add("")
    if not r.pending:
        add("None: no simulation is needed for the next step, or none would change a decision.")
    for pending in r.pending:
        tag = "best next action" if pending.best_next else "also sufficient"
        add(
            f"- `{pending.capability_id}` ({pending.action_type}, {tag}) -- **BLOCKED**: "
            f"{pending.blocked_because}"
        )
        add("  - would decide: " + ("; ".join(pending.would_decide) or "-"))
        add(f"  - estimated cost: {pending.estimated_cost}")
        add(f"  - requires: {pending.requires}")
    if r.human_actions:
        add("")
        for action in r.human_actions:
            add(f"- Awaiting a person: {action}")
    add("")

    add("## Next steps")
    add("")
    for step in r.next_steps:
        add(f"- {step}")
    add("")

    add("## Provenance")
    add("")
    if r.failure_analysis:
        add(f"- Failure analysis: {r.failure_analysis}")
    for candidate in r.heuristic_candidates:
        add(f"- Heuristic candidate (pending review): {candidate}")
    for line in r.provenance:
        add(f"- {line}")
    add("")

    add("## What ran, and what did not")
    add("")
    for line in r.deployment:
        add(f"- {line}")
    for line in r.not_performed:
        add(f"- Not performed: {line}")
    for note in r.notes:
        add(f"- Note: {note}")
    add("")
    return "\n".join(out)


__all__ = ["render_markdown"]
