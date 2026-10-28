"""Render an `EpisodeReport` as Markdown -- presentation only; every line is a report field.

ONE LAYOUT, A VOCABULARY PER LANGUAGE. `render_markdown` lays the report out once; the fixed words
around each field come from a `Words` -- `ENGLISH` here, whose templates (`MARKDOWN_TEMPLATES`) are
the record's export exactly as it has always read, or another language's, supplied by the
interface (`interfaces.web.pages.MarkdownWords`) from its curated vocabulary. A `Words` changes the
words AROUND a field and how a stored value is named; it never changes a field. Identifiers,
digests, numbers and quoted evidence are inserted exactly as stored, and report prose goes through
`Words.text`, which in English is the text itself and elsewhere a curated rendering or the original,
marked. Every language therefore has the same lines in the same order -- what
`bilingual_parity.check_markdown` compares.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from lab_brain.research.episode_view import Conclusion
from lab_brain.research.report import (
    EpisodeReport,
    ReliabilitySection,
    ScreeningSection,
    UsageLine,
)
from lab_brain.security.interaction_attestation import interaction_claim

_EXCERPT = 220


class Words(Protocol):
    """The fixed words of a Markdown export in one language, and how it names a stored value."""

    locale: str

    def __call__(self, key: str, /, **values: object) -> str:
        """`MARKDOWN_TEMPLATES[key]` in this language, with `values` inserted as given."""
        ...

    def text(self, canonical: str) -> str:
        """Report prose: as written, or a curated rendering, or the original marked as such."""
        ...

    def status(self, family: str, value: str, *, bold: bool = False) -> str:
        """A stored value (`family` names its words, e.g. `bs`, `ws`), the value itself kept."""
        ...


#: The English export's fixed words, by key. Changing one changes the record's export: the English
#: rendering is pinned byte for byte (`tests/unit/test_g0_bilingual_export_markdown.py`).
MARKDOWN_TEMPLATES: dict[str, str] = {
    "md.title": "# Research episode {episode}",
    "md.goal": "**Goal:** {goal}",
    "md.header": (
        "Project `{project}` | actor `{actor}` | domain `{domain}` | trace `{trace}` | "
        "episode state {state}"
    ),
    "md.times": "Started {started} | finished {finished}",
    "md.continuation": "## Continuation: run {n} of this episode",
    "md.resumed_from": "Resumed from {value}.",
    "md.reasoning": "Reasoning: {value}.",
    "md.earlier_runs": "Earlier runs:",
    "md.earlier_checks": "Checks executed by earlier runs (not executed again):",
    "md.result": "## Result",
    "md.conclusion": "{status} -- {statement}",
    "md.ruled_out": "Ruled out by executed checks: {items}",
    "md.still_competing": "Still competing: {items}",
    "md.trace": "Confirmation trace: {items}",
    "md.pending_simulation": (
        "**Pending simulation:** `{capability}` is the best next verification action and cannot "
        "run here -- {reason}."
    ),
    "md.stages": "## Stages",
    "md.stages.head": "| Stage | Status | Detail |",
    "md.inputs": "## Inputs",
    "md.inputs.head": "| File | Role | Declared as | State | Artifact | Units | Statements |",
    "md.verification_input": "Verification input: {value}",
    "md.evidence": "## Evidence and sources",
    "md.evidence.line": "- `{attestation}` ({origin}, {trust}) {source} [{locator}]: '{excerpt}'",
    "md.evidence.continuation": (
        "- This run admitted no statement. The statements the hypotheses were debated over "
        "were admitted by run 1 of this episode and stand unchanged."
    ),
    "md.evidence.none": "- No statement was admitted as evidence.",
    "md.literature": "### External literature -- `{provider}`",
    "md.literature.source": (
        "Source: {description}. Query (declared public by the actor): '{query}'."
    ),
    "md.literature.policy": "Egress policy for this run: {policy}.",
    "md.literature.discovered": "Passages discovered: {n}.",
    "md.literature.line": (
        "- {title} `{locator}` -- {trust}, licence {license}, kept {retention}, status {status}; "
        "{admitted}. {note}"
    ),
    "md.literature.not_admitted": "not admitted",
    "md.literature.refused": "- refused: {value}",
    "md.hypotheses": "## Competing hypotheses",
    "md.hypotheses.none": "No hypothesis was admitted.",
    "md.hypothesis": "### {mechanism} -- {state}",
    "md.hypothesis.statement": "`{hypothesis}` | {statement}",
    "md.hypothesis.machine": "- Machine falsifier (what verification adjudicates): `{value}`",
    "md.hypothesis.falsifier": "- Model's explanation (prose falsifier, not adjudicated): {value}",
    "md.hypothesis.cheapest": "- Cheapest test: `{value}`",
    "md.hypothesis.predictions": "- Predictions: {items}",
    "md.hypothesis.critique": "- Critique: {value}",
    "md.debate": "## Debate and critique",
    "md.debate.none": "The debate did not run.",
    "md.debate.head": (
        "Debate `{debate}` | reasoner {reasoner} | {rounds} round(s) | stopped: {stopped}"
    ),
    "md.debate.position": "- Position: {value}",
    "md.debate.critic": (
        "- Critic cross-examined {n} evidence item(s); its inverted retrieval found {m}."
    ),
    "md.debate.alternatives": "- Critic named alternatives: {items}",
    "md.debate.surviving": "- Surviving after critique: {items}",
    "md.debate.contradicted": "- Contradicted by critique: {items}",
    "md.debate.gate": "- Debate gate: {value}",
    "md.line": "- {value}",
    "md.none": "none",
    "md.belief": "## Belief state",
    "md.belief.head": "| Hypothesis | Mechanism | State | Governed moves |",
    "md.plans": "## Verification plan",
    "md.plans.none": "No verification plan was made.",
    "md.plan": "{n}. `{plan}` -- {decision}",
    "md.plan.chosen": " -> `{chosen}`",
    "md.completed": "## Completed actions",
    "md.completed.none": "No verification action was executed.",
    "md.completed.line": (
        "- `{capability}` ({kind}) {status} by {backend} -- job `{job}`, run `{run}`"
    ),
    "md.completed.output": "  - output: {items}",
    "md.pending": "## Pending simulation actions",
    "md.pending.none": (
        "None: no simulation is needed for the next step, or none would change a decision."
    ),
    "md.pending.line": "- `{capability}` ({kind}, {tag}) -- {status}: {reason}",
    "md.pending.best": "best next action",
    "md.pending.also": "also sufficient",
    "md.pending.decide": "  - would decide: {items}",
    "md.pending.cost": "  - estimated cost: {value}",
    "md.pending.requires": "  - requires: {value}",
    "md.human": "- Awaiting a person: {value}",
    "md.next": "## Next steps",
    "md.provenance": "## Provenance",
    "md.failure": "- Failure analysis: {value}",
    "md.heuristic": "- Heuristic candidate (pending review): {value}",
    "md.session": "### Session provenance",
    "md.session.origin": "- Origin: {origin}",
    "md.session.ref": "- Session audit reference (not a secret): `{ref}`",
    "md.session.unattested": "- No signed-in session is attested for this run.",
    "md.session.binds": (
        "- Actor `{actor}` | project `{project}` | research run `{run}` | trace `{trace}`"
    ),
    # The claim level (`011q`), verified when the export is rendered against the keys pinned
    # outside the database. Only INTERACTION_VERIFIED says "authenticated interaction"; every
    # other level says what is NOT shown.
    "md.session.claim": "- Claim level: {level}",
    "md.session.says.INTERACTION_VERIFIED": (
        "- This run originated from an authenticated interaction: a pinned web-tier key signed "
        "its statement on a signed-in, CSRF-verified request. It does not show who held the "
        "session credential."
    ),
    "md.session.says.SESSION_RECORDED_UNVERIFIED": (
        "- A session reference was recorded, but this does not show that it originated from an "
        "authenticated interaction: no interaction attestation verifies under a key pinned in "
        "this deployment."
    ),
    "md.session.says.OPERATOR_UNATTESTED": (
        "- No sign-in is claimed: an operator started this run, and nothing shows an "
        "authenticated interaction."
    ),
    "md.session.says.LEGACY_UNATTESTED": (
        "- Stored before session provenance existed: nothing shows a sign-in or an "
        "authenticated interaction."
    ),
    "md.session.key": "- Interaction signing key id (not a secret): `{kid}`",
    "md.ran": "## What ran, and what did not",
    "md.not_performed": "- Not performed: {value}",
    "md.note": "- Note: {value}",
    # reliability_lines
    "md.rel.replies": (
        "Reply checks under {policy}: {replies} model replies, {refused} refused by a typed "
        "parser, {repaired} repaired before parsing"
    ),
    "md.rel.refused": "Refused reply: {value}",
    "md.rel.coverage": "Coverage review: {value}",
    "md.rel.unaddressed": "Unaddressed check {check} ({observable}): {disposition} -- {detail}",
    "md.rel.withheld": "Withheld to keep the Critic's reserve: {value}",
    "md.rel.overlap": "Overlapping rivals (kept, not merged): {value}",
    "md.rel.structure": "Device structure summary shown to the Hypothesis Engine: {value}",
    # screening_lines
    "md.scr.head": "Exploratory screening under {policy}: {status}",
    "md.scr.plan": " (plan `{plan}`)",
    "md.scr.detail": " -- {detail}",
    "md.scr.unaddressed": "Unaddressed observables (no hypothesis predicted them): {items}",
    "md.scr.candidate": "Candidate {check}: {disposition} -- {detail}",
    "md.scr.check": "Screening check {rank}: {check} {status}, estimated {cost}",
    "md.scr.job": ", job `{job}`",
    "md.scr.run": ", run `{run}`",
    "md.scr.reading": (
        "  read {observable} = {outcome} (reference {reference}): {finding}, observation "
        "`{observation}`"
    ),
    "md.scr.review": "Review after abnormal readings: {status}",
    "md.scr.review_line": "  {disposition}: {readings} -- {detail}",
    "md.scr.proposed": " (`{hypothesis}`, proposed after screening)",
    "md.scr.not_repeated": (
        "Not repeated by verification on the same input (a repeat is not independent): {items}"
    ),
    "md.scr.exploratory": (
        "Screening readings are exploratory evidence: they relate to no hypothesis, and a "
        "hypothesis proposed after them cannot be supported by them (012y)."
    ),
    # usage_lines
    "md.usage": (
        "Model use: {model} on {slot}: {calls} call(s), {metered} with provider-reported usage; "
        "tokens prompt {prompt}, completion {completion}, total {total}"
    ),
    # render_recorded_since
    "md.since": "## Recorded since this report",
    "md.since.read": (
        "Read from the stored records when this file was exported. The report above is as its "
        "run wrote it; nothing in it was changed."
    ),
    "md.since.what": "`{analysis}` ({status}, {failure_class})",
    "md.since.flag": "- {what} is flagged {kind} by {by}: {statement} (evidence: {evidence})",
    "md.since.not_relied": "- {what} is not relied on by case memory or the miner: {reason}",
}


class _English:
    """The record's own language: its templates, prose as written, stored values as stored."""

    locale = "en"

    def __call__(self, key: str, /, **values: object) -> str:
        template = MARKDOWN_TEMPLATES[key]
        return template.format(**values) if values else template

    def text(self, canonical: str) -> str:
        return canonical

    def status(self, family: str, value: str, *, bold: bool = False) -> str:
        return f"**{value}**" if bold else value


#: The record's export language: exactly the Markdown the report has always exported as.
ENGLISH: Words = _English()


def _clip(text: str, limit: int = _EXCERPT) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "..."


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(
    report: EpisodeReport, words: Words = ENGLISH, *, preamble: Sequence[str] = ()
) -> str:
    """The report as Markdown in `words`' language. `preamble`: lines a rendering in another
    language puts under the title (each a `> ` note saying what it is derived from); none in the
    record's export."""
    r = report
    w = words
    out: list[str] = []
    add = out.append

    def texts(items: Sequence[str], sep: str = "; ") -> str:
        return sep.join(w.text(x) for x in items)

    add(w("md.title", episode=r.episode_id))
    out.extend(preamble)
    add("")
    add(w("md.goal", goal=w.text(r.goal)))
    add("")
    add(
        w(
            "md.header",
            project=r.project_id,
            actor=r.actor_id,
            domain=r.domain,
            trace=r.trace_id,
            state=w.status("ep", r.episode_state, bold=True),
        )
    )
    add(w("md.times", started=r.started_at.isoformat(), finished=r.finished_at.isoformat()))
    add("")

    if r.continuation is not None:
        k = r.continuation
        add(w("md.continuation", n=k.run_ordinal))
        add("")
        add(w("md.resumed_from", value=w.text(k.resumed_from)))
        add("")
        add(w("md.reasoning", value=w.text(k.reasoning)))
        add("")
        add(w("md.earlier_runs"))
        for line in k.earlier_runs:
            add(w("md.line", value=w.text(line)))
        if k.earlier_checks:
            add("")
            add(w("md.earlier_checks"))
            for line in k.earlier_checks:
                add(w("md.line", value=w.text(line)))
        for line in (*k.superseded_jobs, *k.recovered):
            add(w("md.line", value=w.text(line)))
        add("")

    add(w("md.result"))
    add("")
    add(
        w(
            "md.conclusion",
            status=w.status("cs", r.conclusion.status, bold=True),
            statement=w.text(r.conclusion.statement),
        )
    )
    if r.conclusion.ruled_out:
        add("")
        add(w("md.ruled_out", items=texts(r.conclusion.ruled_out)))
    if r.conclusion.still_competing:
        add("")
        add(w("md.still_competing", items=texts(r.conclusion.still_competing)))
    if r.conclusion.trace:
        add("")
        add(w("md.trace", items=texts(r.conclusion.trace, " -> ")))
    if r.pending:
        best = next((p for p in r.pending if p.best_next), r.pending[0])
        add("")
        add(
            w(
                "md.pending_simulation",
                capability=best.capability_id,
                reason=w.text(best.blocked_because),
            )
        )
    add("")

    add(w("md.stages"))
    add("")
    add(w("md.stages.head"))
    add("|---|---|---|")
    for s in r.stages:
        add(
            f"| {w.status('stage', s.stage)} | {w.status('ss', s.status)} | "
            f"{_cell(w.text(s.detail))} |"
        )
    add("")

    add(w("md.inputs"))
    add("")
    add(w("md.inputs.head"))
    add("|---|---|---|---|---|---|---|")
    for i in r.inputs:
        add(
            f"| {_cell(i.name)} | {w.status('role', i.role)} | {i.declared_kind} | "
            f"{w.status('is', i.state)} | `{i.artifact_id or '-'}` | {i.evidence_units} | "
            f"{i.statements} |"
        )
    if r.verification_input:
        add("")
        add(w("md.verification_input", value=w.text(r.verification_input)))
    add("")

    add(w("md.evidence"))
    add("")
    if r.evidence:
        for e in r.evidence:
            add(
                w(
                    "md.evidence.line",
                    attestation=e.attestation_id,
                    origin=w.status("origin", e.origin),
                    trust=e.trust_class,
                    source=_cell(e.source),
                    locator=e.locator,
                    excerpt=_clip(e.excerpt),
                )
            )
    elif r.continuation is not None:
        add(w("md.evidence.continuation"))
    else:
        add(w("md.evidence.none"))
    add("")
    if r.literature is not None:
        lit = r.literature
        add(w("md.literature", provider=lit.provider))
        add("")
        add(w("md.literature.source", description=w.text(lit.description), query=lit.query))
        add(w("md.literature.policy", policy=lit.egress_policy))
        add(w("md.literature.discovered", n=lit.discovered))
        add("")
        for c in lit.consulted:
            admitted = (
                f"`{c.admitted_attestation_id}`"
                if c.admitted_attestation_id
                else w("md.literature.not_admitted")
            )
            add(
                w(
                    "md.literature.line",
                    title=_cell(c.title),
                    locator=c.locator,
                    trust=c.trust_class,
                    license=c.license,
                    retention=c.retention,
                    status=c.status,
                    admitted=admitted,
                    note=w.text(c.note),
                )
            )
        for refusal in lit.refusals:
            add(w("md.literature.refused", value=w.text(refusal)))
        add("")

    add(w("md.hypotheses"))
    add("")
    if not r.hypotheses:
        add(w("md.hypotheses.none"))
    for h in r.hypotheses:
        add(
            w(
                "md.hypothesis",
                mechanism=w.text(h.mechanism),
                state=w.status("bs", h.final_state, bold=True),
            )
        )
        add("")
        add(w("md.hypothesis.statement", hypothesis=h.hypothesis_id, statement=w.text(h.statement)))
        for machine in h.machine_falsifiers:
            add(w("md.hypothesis.machine", value=machine))
        add(w("md.hypothesis.falsifier", value=w.text(h.falsifier)))
        add(w("md.hypothesis.cheapest", value=h.minimal_test))
        add(w("md.hypothesis.predictions", items=texts(h.predictions)))
        for objection in h.objections:
            add(w("md.hypothesis.critique", value=w.text(objection)))
        add("")

    add(w("md.debate"))
    add("")
    if r.debate is None:
        add(w("md.debate.none"))
    else:
        d = r.debate
        add(
            w(
                "md.debate.head",
                debate=d.debate_id,
                reasoner=w.text(d.reasoner),
                rounds=d.rounds,
                stopped=d.stop_reason,
            )
        )
        add("")
        for position in d.positions:
            add(w("md.debate.position", value=w.text(position)))
        add(w("md.debate.critic", n=d.critic_evidence, m=d.inverted_evidence))
        if d.alternatives_named:
            add(w("md.debate.alternatives", items=texts(d.alternatives_named, ", ")))
        add(w("md.debate.surviving", items=texts(d.surviving, ", ") or w("md.none")))
        add(w("md.debate.contradicted", items=texts(d.contradicted, ", ") or w("md.none")))
        add(w("md.debate.gate", value=w.text(d.gate)))
        for line in reliability_lines(d.reliability, w):
            add(w("md.line", value=line))
    for line in screening_lines(r.screening, w):
        add(w("md.line", value=line))
    add("")

    add(w("md.belief"))
    add("")
    add(w("md.belief.head"))
    add("|---|---|---|---|")
    for b in r.belief:
        add(
            f"| `{b.hypothesis_id}` | {w.text(b.mechanism)} | {w.status('bs', b.state)} | "
            f"{_cell(texts(b.moves) or '-')} |"
        )
    add("")

    add(w("md.plans"))
    add("")
    if not r.plans:
        add(w("md.plans.none"))
    for n, p in enumerate(r.plans, start=1):
        add(
            w("md.plan", n=n, plan=p.plan_id, decision=w.status("pd", p.decision, bold=True))
            + (w("md.plan.chosen", chosen=p.chosen) if p.chosen else "")
        )
        add(f"   {w.text(p.summary)}")
        for candidate in p.candidates:
            add(f"   - {w.text(candidate)}")
    add("")

    add(w("md.completed"))
    add("")
    if not r.completed:
        add(w("md.completed.none"))
    for a in r.completed:
        add(
            w(
                "md.completed.line",
                capability=a.capability_id,
                kind=w.status("act", a.action_type),
                status=w.status("ws", a.status, bold=True),
                backend=w.text(a.backend),
                job=a.job_id,
                run=a.run_id,
            )
        )
        for outcome in a.outcomes:
            add(f"  - {w.text(outcome)}")
        if a.output_artifacts:
            add(w("md.completed.output", items=", ".join(f"`{x}`" for x in a.output_artifacts)))
        if a.detail:
            add(f"  - {w.text(a.detail)}")
    add("")

    add(w("md.pending"))
    add("")
    if not r.pending:
        add(w("md.pending.none"))
    for pending in r.pending:
        add(
            w(
                "md.pending.line",
                capability=pending.capability_id,
                kind=w.status("act", pending.action_type),
                tag=w("md.pending.best") if pending.best_next else w("md.pending.also"),
                status=w.status("ws", "BLOCKED", bold=True),
                reason=w.text(pending.blocked_because),
            )
        )
        add(w("md.pending.decide", items=texts(pending.would_decide) or "-"))
        add(w("md.pending.cost", value=w.text(pending.estimated_cost)))
        add(w("md.pending.requires", value=w.text(pending.requires)))
    if r.human_actions:
        add("")
        for action in r.human_actions:
            add(w("md.human", value=w.text(action)))
    add("")

    add(w("md.next"))
    add("")
    for step in r.next_steps:
        add(w("md.line", value=w.text(step)))
    add("")

    add(w("md.provenance"))
    add("")
    if r.failure_analysis:
        add(w("md.failure", value=w.text(r.failure_analysis)))
    for candidate in r.heuristic_candidates:
        add(w("md.heuristic", value=w.text(candidate)))
    for line in r.provenance:
        add(w("md.line", value=w.text(line)))
    add("")
    if r.session_provenance is not None:
        # How the run was started, as its run row records it (`011n`): the origin and, for a
        # signed-in web session only, the session's NON-SECRET audit reference. Never a token or
        # a session's lookup key -- the report holds neither. Absent from a report stored before
        # `011n`, whose export is then exactly what it always was.
        sp = r.session_provenance
        add(w("md.session"))
        add("")
        add(w("md.session.origin", origin=w.status("so", sp.origin, bold=True)))
        if sp.session_audit_ref:
            add(w("md.session.ref", ref=sp.session_audit_ref))
        else:
            add(w("md.session.unattested"))
        add(
            w(
                "md.session.binds",
                actor=sp.actor_id,
                project=sp.project_id,
                run=sp.research_run_id,
                trace=sp.trace_id,
            )
        )
        # Computed now, against the pinned keys -- never a level the stored report asserts.
        claim = interaction_claim(r)
        add(w("md.session.claim", level=w.status("ic", claim.level.value, bold=True)))
        add(w(f"md.session.says.{claim.level.value}"))
        if claim.key_id is not None:
            add(w("md.session.key", kid=claim.key_id))
        add("")

    add(w("md.ran"))
    add("")
    for line in r.deployment:
        add(w("md.line", value=w.text(line)))
    for line in r.not_performed:
        add(w("md.not_performed", value=w.text(line)))
    for note in r.notes:
        add(w("md.note", value=w.text(note)))
    for line in usage_lines(r.usage, w):
        add(w("md.line", value=line))
    add("")
    return "\n".join(out)


def reliability_lines(reliability: ReliabilitySection | None, words: Words = ENGLISH) -> list[str]:
    """The debate's reply checks and coverage review, as the full report states them."""
    if reliability is None:
        return []
    w = words
    lines = [
        w(
            "md.rel.replies",
            policy=reliability.policy,
            replies=reliability.replies,
            refused=reliability.refused,
            repaired=reliability.repaired,
        ),
        *(w("md.rel.refused", value=w.text(x)) for x in reliability.refusals),
        w("md.rel.coverage", value=reliability.coverage_status),
        *(
            w(
                "md.rel.unaddressed",
                check=c.check,
                observable=c.observable,
                disposition=c.disposition,
                detail=w.text(c.detail),
            )
            for c in reliability.coverage
        ),
        *(w("md.rel.withheld", value=w.text(x)) for x in reliability.withheld_for_critic),
        *(w("md.rel.overlap", value=w.text(x)) for x in reliability.overlap),
        *(
            (w("md.rel.structure", value=reliability.structure_summary),)
            if reliability.structure_summary
            else ()
        ),
    ]
    return lines


def screening_lines(screening: ScreeningSection | None, words: Words = ENGLISH) -> list[str]:
    """The exploratory screening stage, as the full report states it: every candidate and why,
    every reading with its provenance, the review, and what verification did not repeat."""
    if screening is None:
        return []
    w = words
    lines = [
        w("md.scr.head", policy=screening.policy, status=screening.status)
        + (w("md.scr.plan", plan=screening.plan_id) if screening.plan_id else "")
        + (w("md.scr.detail", detail=w.text(screening.detail)) if screening.detail else ""),
        w("md.scr.unaddressed", items=", ".join(screening.unaddressed) or w("md.none")),
        *(
            w(
                "md.scr.candidate",
                check=c.check,
                disposition=c.disposition,
                detail=w.text(c.detail),
            )
            for c in screening.candidates
        ),
    ]
    for check in screening.checks:
        lines.append(
            w(
                "md.scr.check",
                rank=check.rank,
                check=check.check,
                status=check.status,
                cost=w.text(check.estimated_cost),
            )
            + (w("md.scr.job", job=check.job_id) if check.job_id else "")
            + (w("md.scr.run", run=check.run_id) if check.run_id else "")
            + (w("md.scr.detail", detail=w.text(check.detail)) if check.detail else "")
        )
        lines.extend(
            w(
                "md.scr.reading",
                observable=r.observable,
                outcome=r.outcome,
                reference=r.reference,
                finding=r.finding,
                observation=r.observation_id,
            )
            for r in check.readings
        )
    lines.append(w("md.scr.review", status=screening.review_status))
    lines.extend(
        w(
            "md.scr.review_line",
            disposition=x.disposition,
            readings="; ".join(w.text(y) for y in x.readings),
            detail=w.text(x.detail),
        )
        + (w("md.scr.proposed", hypothesis=x.hypothesis_id) if x.hypothesis_id else "")
        for x in screening.review
    )
    if screening.not_repeated:
        lines.append(w("md.scr.not_repeated", items=", ".join(screening.not_repeated)))
    lines.append(w("md.scr.exploratory"))
    return lines


def usage_lines(usage: Sequence[UsageLine], words: Words = ENGLISH) -> list[str]:
    """This run's model calls, with the token counts the provider reported."""
    return [
        words(
            "md.usage",
            model=u.model,
            slot=u.slot,
            calls=u.calls,
            metered=u.metered_calls,
            prompt=u.prompt_tokens,
            completion=u.completion_tokens,
            total=u.total_tokens,
        )
        for u in usage
    ]


def render_recorded_since(conclusions: Sequence[Conclusion], words: Words = ENGLISH) -> str:
    """What the record says about the report's conclusions now, for an exported report.

    A stored report is frozen: written when its run ended, never edited. A conclusion can be
    flagged afterwards (`012p`), or stop being relied on; an export that showed only the report
    would present a flagged CONFIRMED cause as if nothing were known against it. Empty when
    there is nothing to add, so the export is then exactly the stored report.
    """
    w = words
    lines: list[str] = []
    for c in conclusions:
        what = w(
            "md.since.what",
            analysis=c.failure_analysis_id,
            status=c.status,
            failure_class=c.failure_class,
        )
        for flag in c.flags:
            lines.append(
                w(
                    "md.since.flag",
                    what=what,
                    kind=w.status("flag", flag.kind, bold=True),
                    by=flag.recorded_by,
                    statement=w.text(flag.statement),
                    evidence=", ".join(flag.evidence_refs),
                )
            )
        if c.not_relied_on and not c.flags:
            lines.append(w("md.since.not_relied", what=what, reason=w.text(c.not_relied_on)))
    if not lines:
        return ""
    return "\n".join(["", w("md.since"), "", w("md.since.read"), "", *lines, ""])


__all__ = [
    "ENGLISH",
    "MARKDOWN_TEMPLATES",
    "Words",
    "reliability_lines",
    "render_markdown",
    "render_recorded_since",
    "screening_lines",
    "usage_lines",
]
