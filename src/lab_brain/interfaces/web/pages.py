"""HTML for the research workspace: presentation only, and escaped by construction.

EVERY DYNAMIC VALUE IS ESCAPED. Markup is built with `h(template, *values)`, whose template is a
literal in this module and whose values are escaped unless they are already `Html` built the same
way. Nothing a user, a document or a report supplies can become markup.

NOTHING HERE DECIDES OR DERIVES. The report section renders an `EpisodeReport` -- the account the
research service returned, the same object `research.render.render_markdown` renders for the CLI --
field by field, in the same order. The episode header shows the stored episode and research-run
rows as they are. There is no script: the browser receives HTML and forms, nothing that computes.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lab_brain.research.report import EpisodeReport

_CSS = """
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;color:#1d2330;
background:#f6f7f9}
header.top{background:#1f2a44;color:#fff;padding:10px 24px;display:flex;gap:24px;
align-items:center}
header.top a{color:#fff;text-decoration:none;font-weight:600}
header.top .who{margin-left:auto;opacity:.9;font-size:13px}
header.top code{background:#34416a;color:#fff}
main{max-width:1180px;margin:0 auto;padding:20px 24px 60px}
h1{font-size:22px;margin:8px 0 4px}h2{font-size:18px;margin:28px 0 8px;
border-bottom:1px solid #d9dde5;padding-bottom:4px}h3{font-size:15px;margin:16px 0 4px}
table{border-collapse:collapse;width:100%;background:#fff;margin:6px 0}.scroll{overflow-x:auto}
th,td{border:1px solid #d9dde5;padding:5px 8px;text-align:left;vertical-align:top;font-size:13px}
th{background:#eef1f6}code{font:12px ui-monospace,Consolas,monospace;background:#eef1f6;
padding:1px 4px;border-radius:3px;word-break:break-all}
.box{background:#fff;border:1px solid #d9dde5;border-radius:6px;padding:12px 16px;margin:10px 0}
.state{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;
background:#e3e7ee}
.state-SUSPENDED,.state-BLOCKED,.state-PROVISIONAL{background:#fff1c2;color:#6b4e00}
.state-COMPLETED,.state-CONFIRMED,.state-DONE,.state-READY,.state-SUPPORTED{background:#d7f2de;
color:#11522a}
.state-FAILED,.state-REFUSED,.state-ABANDONED{background:#fbd9d9;color:#7a1a1a}
.state-CONTRADICTED{background:#e8e8e8;color:#555}
.muted{color:#5b6475;font-size:13px}.error{background:#fbd9d9;border-color:#e2a0a0}
.notice{background:#fff8e1;border-color:#e8d38c}
form.inline{display:inline}label{display:block;font-weight:600;margin-top:12px}
input[type=text],textarea,select{width:100%;box-sizing:border-box;padding:6px;font:inherit}
textarea{min-height:70px}button{margin-top:14px;padding:7px 16px;font:inherit;font-weight:600;
background:#1f2a44;color:#fff;border:0;border-radius:4px;cursor:pointer}
.hint{font-weight:400;color:#5b6475;font-size:13px}blockquote{margin:4px 0 8px 12px;
padding-left:10px;border-left:3px solid #c9cfda;color:#333}
"""


class Html(str):
    """Markup this module built. Everything else is text and is escaped when interpolated."""

    __slots__ = ()


def e(value: object) -> Html:
    return value if isinstance(value, Html) else Html(html.escape(str(value), quote=True))


def h(template: str, *values: object) -> Html:
    """`template` is a literal in this module; every value is escaped (or already `Html`)."""
    return Html(template.format(*(e(v) for v in values)))


def cat(parts: Iterable[Html], sep: str = "") -> Html:
    return Html(sep.join(e(p) for p in parts))


_CODE = re.compile(r"`([^`]+)`")
_STRONG = re.compile(r"\*\*([^*]+)\*\*")


def rich(text: str) -> Html:
    """Report text with its inline `code` and **emphasis** shown as such -- after escaping, so
    the markers cannot carry markup."""
    escaped = html.escape(text, quote=True)
    return Html(_STRONG.sub(r"<strong>\1</strong>", _CODE.sub(r"<code>\1</code>", escaped)))


def state(value: str | None) -> Html:
    label = value or "-"
    css = re.sub(r"[^A-Z_]", "", label)
    return h('<span class="state state-{}">{}</span>', css, label)


def page(title: str, body: Html, *, actor_id: str) -> bytes:
    return h(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>{} - Lab Brain research workspace</title><style>{}</style></head><body>"
        '<header class="top"><a href="/">Research workspace</a><a href="/runs/new">New research '
        'run</a><span class="who">acting as <code>{}</code></span></header><main>{}</main>'
        "</body></html>",
        title,
        Html(_CSS),
        actor_id,
        body,
    ).encode("utf-8")


def _list(items: Sequence[Html]) -> Html:
    return h("<ul>{}</ul>", cat(h("<li>{}</li>", i) for i in items)) if items else Html("")


def _table(head: Sequence[str], rows: Iterable[Sequence[object]]) -> Html:
    return h(
        '<div class="scroll"><table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></div>',
        cat(h("<th>{}</th>", c) for c in head),
        cat(h("<tr>{}</tr>", cat(h("<td>{}</td>", c) for c in row)) for row in rows),
    )


# -- view rows: what the database holds, as read ---------------------------------------------------


@dataclass(frozen=True)
class ProjectRow:
    project_id: str
    name: str


@dataclass(frozen=True)
class EpisodeRow:
    episode_id: str
    project_id: str
    trace_id: str
    goal: str
    state: str
    outcome_status: str | None
    suspend_reason: str | None
    start_time: object
    end_time: object
    runs: int


@dataclass(frozen=True)
class RunRow:
    ordinal: int
    research_run_id: str
    actor_id: str
    started_at: object
    finished_at: object
    outcome: str | None
    recorded: bool


# -- pages ---------------------------------------------------------------------------------------


def home_page(
    *, actor_id: str, projects: Sequence[ProjectRow], episodes: Sequence[EpisodeRow]
) -> bytes:
    if projects:
        project_list = _table(
            ("Project", "Name"), ((h("<code>{}</code>", p.project_id), p.name) for p in projects)
        )
    else:
        project_list = h(
            '<p class="box">{} is not an active member of any project, so there is nothing to '
            "research here.</p>",
            actor_id,
        )
    if episodes:
        rows = (
            (
                h('<a href="/episodes/{}"><code>{}</code></a>', ep.episode_id, ep.episode_id),
                h("<code>{}</code>", ep.project_id),
                ep.goal,
                state(ep.state),
                ep.suspend_reason or ep.outcome_status or "-",
                ep.runs,
                str(ep.start_time),
            )
            for ep in episodes
        )
        episode_list = _table(
            ("Episode", "Project", "Goal", "State", "Reason / outcome", "Runs", "Opened"), rows
        )
    else:
        episode_list = Html('<p class="muted">You have not opened a research episode yet.</p>')
    body = h(
        '<h1>Research workspace</h1><p class="muted">Research episodes you opened, in projects '
        "you are an active member of. A SUSPENDED episode can be continued; a COMPLETED one is "
        'read-only.</p><p><a href="/runs/new">Start a new research run</a></p>'
        "<h2>Your episodes</h2>{}<h2>Your projects</h2>{}",
        episode_list,
        project_list,
    )
    return page("Workspace", body, actor_id=actor_id)


def new_run_page(
    *,
    actor_id: str,
    projects: Sequence[ProjectRow],
    csrf: str,
    sensitivities: Sequence[str],
    error: str | None = None,
) -> bytes:
    if not projects:
        body = h(
            '<h1>New research run</h1><p class="box">{} is not an active member of any '
            "project.</p>",
            actor_id,
        )
        return page("New research run", body, actor_id=actor_id)
    options = cat(
        h('<option value="{}">{} ({})</option>', p.project_id, p.name, p.project_id)
        for p in projects
    )
    levels = cat(
        h('<option value="{}"{}>{}</option>', s, Html(" selected" if s == "INTERNAL" else ""), s)
        for s in sensitivities
    )
    failure = h('<p class="box error">{}</p>', error) if error else Html("")
    body = h(
        "<h1>New research run</h1>{}"
        '<p class="muted">Opens a new research episode: your files are stored and read, competing '
        "hypotheses are debated, the verification this deployment can run is run, and one report "
        "comes back. Simulations this deployment cannot run are reported as blocked, never run or "
        "emulated.</p>"
        '<form method="post" action="/runs" enctype="multipart/form-data" class="box">'
        '<input type="hidden" name="csrf" value="{}">'
        '<label for="project">Project</label><select id="project" name="project">{}</select>'
        '<label for="goal">Research goal <span class="hint">the question, in your own words'
        '</span></label><textarea id="goal" name="goal" required></textarea>'
        '<label for="measurement">Measurement records <span class="hint">statements are used as '
        "INTERNAL_MEASUREMENT evidence</span></label>"
        '<input type="file" id="measurement" name="measurement" multiple>'
        '<label for="run_record">Run records <span class="hint">earlier simulations or runs '
        "(INTERNAL_RUN)</span></label>"
        '<input type="file" id="run_record" name="run_record" multiple>'
        '<label for="note">Notes <span class="hint">notes or expert heuristics (EXPERT_HEURISTIC)'
        '</span></label><input type="file" id="note" name="note" multiple>'
        '<label for="verification_input">Verification input <span class="hint">optional; the '
        "domain's input, e.g. a device project JSON. Without it nothing is verified.</span></label>"
        '<input type="file" id="verification_input" name="verification_input">'
        '<label for="literature_corpus">Literature corpus <span class="hint">optional; a local '
        "corpus file, searched only with the query below</span></label>"
        '<input type="file" id="literature_corpus" name="literature_corpus">'
        '<label for="literature_query">Literature query <span class="hint">sent to the literature '
        'provider</span></label><input type="text" id="literature_query" name="literature_query">'
        '<label><input type="checkbox" name="literature_query_public" value="yes"> I declare this '
        "query PUBLIC: it may leave this workspace</label>"
        '<label for="symptom">Symptom <span class="hint">optional</span></label>'
        '<input type="text" id="symptom" name="symptom">'
        '<label for="expected">Expected behaviour <span class="hint">optional</span></label>'
        '<input type="text" id="expected" name="expected">'
        '<label for="observed">Observed behaviour <span class="hint">optional</span></label>'
        '<input type="text" id="observed" name="observed">'
        '<label for="sensitivity">Classification of the goal and files</label>'
        '<select id="sensitivity" name="sensitivity">{}</select>'
        '<button type="submit">Run research</button></form>',
        failure,
        csrf,
        options,
        levels,
    )
    return page("New research run", body, actor_id=actor_id)


def message_page(*, actor_id: str, title: str, message: str, back: str = "/") -> bytes:
    body = h(
        '<h1>{}</h1><p class="box notice">{}</p><p><a href="{}">Back</a></p>', title, message, back
    )
    return page(title, body, actor_id=actor_id)


def episode_page(
    *,
    actor_id: str,
    episode: EpisodeRow,
    runs: Sequence[RunRow],
    report: EpisodeReport | None,
    report_ordinal: int | None,
    csrf: str,
    continuable: bool,
    notice: str | None = None,
) -> bytes:
    live = h(
        '<div class="box"><div>Episode state now: {} {}</div>'
        '<div class="muted">Project <code>{}</code> | trace <code>{}</code> | opened {}{}</div>'
        "</div>",
        state(episode.state),
        (
            h("-- {}", episode.suspend_reason)
            if episode.suspend_reason
            else (h("-- {}", episode.outcome_status) if episode.outcome_status else Html(""))
        ),
        episode.project_id,
        episode.trace_id,
        str(episode.start_time),
        h(" | closed {}", str(episode.end_time)) if episode.end_time else Html(""),
    )
    if continuable:
        action = h(
            '<form method="post" action="/episodes/{}/continue" class="box">'
            '<input type="hidden" name="csrf" value="{}">'
            "<div>Continue this episode: the same episode, resumed through its lifecycle, over "
            "its own hypotheses and inputs. Checks already executed are not run again.</div>"
            '<button type="submit">Continue episode</button></form>',
            episode.episode_id,
            csrf,
        )
    else:
        action = h(
            '<p class="box muted">This episode is {}: it is read-only and receives no new '
            "research run.</p>",
            episode.state,
        )
    run_rows = []
    for r in runs:
        link = (
            h(
                '<a href="/episodes/{}?run={}">report</a> | '
                '<a href="/episodes/{}/runs/{}/report.md">'
                "Markdown</a>",
                episode.episode_id,
                r.ordinal,
                episode.episode_id,
                r.ordinal,
            )
            if r.recorded
            else Html('<span class="muted">not recorded in the workspace (run elsewhere)</span>')
        )
        run_rows.append(
            (
                r.ordinal,
                h("<code>{}</code>", r.research_run_id),
                h("<code>{}</code>", r.actor_id),
                str(r.started_at),
                str(r.finished_at or "-"),
                r.outcome or "running",
                link,
            )
        )
    runs_table = _table(
        ("Run", "Research run", "Actor", "Started", "Finished", "Outcome", "Report"), run_rows
    )
    if report is None:
        shown = Html(
            '<p class="box muted">No report of this episode was recorded in the workspace.</p>'
        )
    else:
        shown = h(
            "<h2>Report of run {}</h2>{}",
            report_ordinal if report_ordinal else "-",
            report_html(report),
        )
    body = h(
        "<h1>Research episode <code>{}</code></h1><p><strong>Goal:</strong> {}</p>{}{}{}"
        "<h2>Runs of this episode</h2>{}{}",
        episode.episode_id,
        episode.goal,
        h('<p class="box notice">{}</p>', notice) if notice else Html(""),
        live,
        action,
        runs_table,
        shown,
    )
    return page(f"Episode {episode.episode_id}", body, actor_id=actor_id)


# -- the report: `render_markdown`'s sections, as HTML ------------------------------------------


def report_html(r: EpisodeReport) -> Html:
    parts: list[Html] = [
        h(
            '<div class="box"><div>Episode <code>{}</code> -- {}</div>'
            "<div>Episode state at the end of this run: {}</div>"
            '<div class="muted">Project <code>{}</code> | actor <code>{}</code> | domain '
            '<code>{}</code> | trace <code>{}</code></div><div class="muted">Started {} | '
            "finished {}</div></div>",
            r.episode_id,
            r.goal,
            state(r.episode_state),
            r.project_id,
            r.actor_id,
            r.domain,
            r.trace_id,
            r.started_at.isoformat(),
            r.finished_at.isoformat(),
        )
    ]
    add = parts.append

    if r.continuation is not None:
        k = r.continuation
        add(h("<h2>Continuation: run {} of this episode</h2>", k.run_ordinal))
        add(
            h(
                "<p>Resumed from {}.</p><p>Reasoning: {}.</p>",
                rich(k.resumed_from),
                rich(k.reasoning),
            )
        )
        add(h("<h3>Earlier runs</h3>{}", _list([rich(x) for x in k.earlier_runs])))
        if k.earlier_checks:
            add(
                h(
                    "<h3>Checks executed by earlier runs (not executed again)</h3>{}",
                    _list([rich(x) for x in k.earlier_checks]),
                )
            )
        if k.superseded_jobs or k.recovered:
            add(_list([rich(x) for x in (*k.superseded_jobs, *k.recovered)]))

    c = r.conclusion
    result = [h("<p>{} -- {}</p>", state(c.status), rich(c.statement))]
    if c.ruled_out:
        result.append(h("<p>Ruled out by executed checks: {}</p>", "; ".join(c.ruled_out)))
    if c.still_competing:
        result.append(h("<p>Still competing: {}</p>", "; ".join(c.still_competing)))
    if c.trace:
        result.append(h("<p>Confirmation trace: {}</p>", rich(" -> ".join(c.trace))))
    if c.confirmed_hypothesis:
        result.append(h("<p>Confirmed hypothesis: <code>{}</code></p>", c.confirmed_hypothesis))
    if r.pending:
        best = next((p for p in r.pending if p.best_next), r.pending[0])
        result.append(
            h(
                "<p><strong>Pending simulation:</strong> <code>{}</code> is the best next "
                "verification action and cannot run here -- {}.</p>",
                best.capability_id,
                best.blocked_because,
            )
        )
    add(h('<h2>Result</h2><div class="box">{}</div>', cat(result)))

    add(
        h(
            "<h2>Stages</h2>{}",
            _table(
                ("Stage", "Status", "Detail"),
                ((s.stage, state(s.status), rich(s.detail)) for s in r.stages),
            ),
        )
    )

    add(
        h(
            "<h2>Inputs and ingestion</h2>{}",
            _table(
                (
                    "File",
                    "Role",
                    "Declared as",
                    "State",
                    "Artifact",
                    "Job",
                    "Run",
                    "Units",
                    "Statements",
                    "Detail",
                ),
                (
                    (
                        i.name,
                        i.role,
                        i.declared_kind,
                        state(i.state),
                        h("<code>{}</code>", i.artifact_id or "-"),
                        h("<code>{}</code>", i.job_id or "-"),
                        h("<code>{}</code>", i.run_id or "-"),
                        i.evidence_units,
                        i.statements,
                        i.detail or "-",
                    )
                    for i in r.inputs
                ),
            ),
        )
    )
    if r.verification_input:
        add(h("<p>Verification input: {}</p>", rich(r.verification_input)))

    evidence: Html
    if r.evidence:
        evidence = cat(
            h(
                "<li><code>{}</code> ({}, {}) {} [{}]<blockquote>{}</blockquote></li>",
                x.attestation_id,
                x.origin,
                x.trust_class,
                x.source,
                x.locator,
                x.excerpt,
            )
            for x in r.evidence
        )
        evidence = h("<ul>{}</ul>", evidence)
    elif r.continuation is not None:
        evidence = Html(
            "<p>This run admitted no statement. The statements the hypotheses were "
            "debated over were admitted by run 1 of this episode and stand unchanged."
            "</p>"
        )
    else:
        evidence = Html("<p>No statement was admitted as evidence.</p>")
    add(h("<h2>Evidence and sources</h2>{}", evidence))
    if r.literature is not None:
        lit = r.literature
        consulted = [
            h(
                "{} <code>{}</code> -- {}, licence {}, kept {}, status {}; {}. {}",
                x.title,
                x.locator,
                x.trust_class,
                x.license,
                x.retention,
                state(x.status),
                h("<code>{}</code>", x.admitted_attestation_id)
                if x.admitted_attestation_id
                else "not admitted",
                x.note,
            )
            for x in lit.consulted
        ] + [h("refused: {}", x) for x in lit.refusals]
        add(
            h(
                "<h3>External literature -- <code>{}</code></h3><p>Source: {}. Query (declared "
                "public by the actor): '{}'. Egress policy for this run: {}. Passages discovered: "
                "{}.</p>{}",
                lit.provider,
                lit.description,
                lit.query,
                lit.egress_policy,
                lit.discovered,
                _list(consulted),
            )
        )

    hypotheses = [
        h(
            "<h3>{} -- {}</h3><p><code>{}</code> | {}</p>{}",
            x.mechanism,
            state(x.final_state),
            x.hypothesis_id,
            x.statement,
            _list(
                [
                    h("Falsifier: {}", x.falsifier),
                    h("Cheapest test: <code>{}</code>", x.minimal_test),
                    h("Predictions: {}", "; ".join(x.predictions)),
                    *(h("Critique: {}", o) for o in x.objections),
                ]
            ),
        )
        for x in r.hypotheses
    ]
    add(
        h(
            "<h2>Competing hypotheses</h2>{}",
            cat(hypotheses) if hypotheses else Html("<p>No hypothesis was admitted.</p>"),
        )
    )

    if r.debate is None:
        add(Html("<h2>Debate and critique</h2><p>The debate did not run.</p>"))
    else:
        d = r.debate
        add(
            h(
                "<h2>Debate and critique</h2><p>Debate <code>{}</code> | reasoner {} | "
                "{} round(s) | "
                "stopped: {}</p>{}",
                d.debate_id,
                d.reasoner,
                d.rounds,
                d.stop_reason,
                _list(
                    [
                        *(h("Position: {}", p) for p in d.positions),
                        h(
                            "Critic cross-examined {} evidence item(s); its inverted "
                            "retrieval found {}.",
                            d.critic_evidence,
                            d.inverted_evidence,
                        ),
                        *(
                            [h("Critic named alternatives: {}", ", ".join(d.alternatives_named))]
                            if d.alternatives_named
                            else []
                        ),
                        h("Surviving after critique: {}", ", ".join(d.surviving) or "none"),
                        h("Contradicted by critique: {}", ", ".join(d.contradicted) or "none"),
                        h("Debate gate: {}", d.gate),
                    ]
                ),
            )
        )

    add(
        h(
            "<h2>Belief state</h2>{}",
            _table(
                ("Hypothesis", "Mechanism", "State", "Governed moves"),
                (
                    (
                        h("<code>{}</code>", b.hypothesis_id),
                        b.mechanism,
                        state(b.state),
                        _list([rich(m) for m in b.moves]) if b.moves else "-",
                    )
                    for b in r.belief
                ),
            ),
        )
    )

    plans = [
        h(
            "<li><code>{}</code> -- <strong>{}</strong>{}<div>{}</div>{}</li>",
            p.plan_id,
            p.decision,
            h(" -&gt; <code>{}</code>", p.chosen) if p.chosen else Html(""),
            rich(p.summary),
            _list([rich(x) for x in p.candidates]),
        )
        for p in r.plans
    ]
    add(
        h(
            "<h2>Verification plans</h2>{}",
            h("<ol>{}</ol>", cat(plans))
            if plans
            else Html("<p>No verification plan was made.</p>"),
        )
    )

    completed = [
        h(
            "<code>{}</code> ({}) {} by {} -- job <code>{}</code>, run <code>{}</code>{}",
            a.capability_id,
            a.action_type,
            state(a.status),
            a.backend,
            a.job_id or "-",
            a.run_id or "-",
            _list(
                [
                    *(rich(o) for o in a.outcomes),
                    *(
                        [h("output: {}", ", ".join(a.output_artifacts))]
                        if a.output_artifacts
                        else []
                    ),
                    *([rich(a.detail)] if a.detail else []),
                ]
            ),
        )
        for a in r.completed
    ]
    add(
        h(
            "<h2>Completed actions</h2>{}",
            _list(completed) if completed else Html("<p>No verification action was executed.</p>"),
        )
    )

    add(
        h(
            "<h2>Actions awaiting a person</h2>{}",
            _list([rich(x) for x in r.human_actions]) if r.human_actions else Html("<p>None.</p>"),
        )
    )

    pending = [
        h(
            "<code>{}</code> ({}, {}) -- {}: {}{}",
            p.capability_id,
            p.action_type,
            "best next action" if p.best_next else "also sufficient",
            state("BLOCKED"),
            p.blocked_because,
            _list(
                [
                    h("would decide: {}", "; ".join(p.would_decide) or "-"),
                    h("estimated cost: {}", p.estimated_cost),
                    h("requires: {}", p.requires),
                ]
            ),
        )
        for p in r.pending
    ]
    add(
        h(
            "<h2>Blocked simulation actions</h2>{}",
            _list(pending)
            if pending
            else Html(
                "<p>None: no simulation is needed for the next step, or none would change "
                "a decision.</p>"
            ),
        )
    )

    add(h("<h2>Next steps</h2>{}", _list([rich(x) for x in r.next_steps])))

    provenance = (
        ([h("Failure analysis: {}", rich(r.failure_analysis))] if r.failure_analysis else [])
        + [h("Heuristic candidate (pending review): {}", rich(x)) for x in r.heuristic_candidates]
        + [rich(x) for x in r.provenance]
    )
    add(h("<h2>Provenance</h2>{}", _list(provenance)))

    add(
        h(
            "<h2>What ran, and what did not</h2>{}",
            _list(
                [rich(x) for x in r.deployment]
                + [h("Not performed: {}", rich(x)) for x in r.not_performed]
                + [h("Note: {}", rich(x)) for x in r.notes]
            ),
        )
    )
    return cat(parts)


__all__ = [
    "EpisodeRow",
    "Html",
    "ProjectRow",
    "RunRow",
    "e",
    "episode_page",
    "h",
    "home_page",
    "message_page",
    "new_run_page",
    "report_html",
    "rich",
]
