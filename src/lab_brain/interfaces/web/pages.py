"""HTML for the research workspace: presentation only, and escaped by construction.

EVERY DYNAMIC VALUE IS ESCAPED. Markup is built with `h(template, *values)`, whose template is a
literal in this package and whose values are escaped unless they are already `Html` built the same
way. Nothing a user, a document, a provider or a report supplies can become markup.

NOTHING HERE DECIDES OR DERIVES. The report section renders an `EpisodeReport` -- the account the
research service returned, the same object `research.render.render_markdown` renders for the CLI --
field by field, in the same order. The episode header shows the stored episode and research-run
rows as they are. There is no script: the browser receives HTML and forms, nothing that computes.

ONLY THE INTERFACE IS TRANSLATED (`i18n`). Headings, labels and the workspace's own sentences
follow the chosen locale; a report's text, every identifier and every stored value do not.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lab_brain.interfaces.web.i18n import LOCALE_NAMES, LOCALES, Messages
from lab_brain.research.report import EpisodeReport

_CSS = """
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",
sans-serif;margin:0;color:#1d2330;background:#f6f7f9}
header.top{background:#1f2a44;color:#fff;padding:8px 24px;display:flex;gap:6px;
align-items:center;flex-wrap:wrap}
header.top a{color:#dfe5f2;text-decoration:none;font-weight:600;padding:4px 10px;
border-radius:4px}
header.top a.here{background:#34416a;color:#fff}header.top a.brand{color:#fff;margin-right:12px}
header.top .who{margin-left:auto;opacity:.9;font-size:13px}
header.top code{background:#34416a;color:#fff}
header.top form{display:flex;gap:4px;align-items:center;margin:0 0 0 12px}
header.top form button{margin:0;padding:2px 8px;font-size:12px;background:#34416a}
header.top form button.here{background:#fff;color:#1f2a44}
main{max-width:1180px;margin:0 auto;padding:20px 24px 60px}
h1{font-size:22px;margin:8px 0 4px}h2{font-size:18px;margin:28px 0 8px;
border-bottom:1px solid #d9dde5;padding-bottom:4px}h3{font-size:15px;margin:16px 0 4px}
table{border-collapse:collapse;width:100%;background:#fff;margin:6px 0}.scroll{overflow-x:auto}
th,td{border:1px solid #d9dde5;padding:5px 8px;text-align:left;vertical-align:top;font-size:13px}
th{background:#eef1f6}code{font:12px ui-monospace,Consolas,monospace;background:#eef1f6;
padding:1px 4px;border-radius:3px;word-break:break-all}
td:first-child code{word-break:normal;white-space:nowrap}
.term{border-bottom:1px dotted #9aa3b2;cursor:help}
.purpose{display:block;color:#5b6475;font-size:12px;font-weight:400}
table.readable td{word-break:normal;overflow-wrap:normal}
table.readable td:first-child{min-width:170px}
table.readable code,table.readable .state{word-break:normal;white-space:nowrap}
table.readable td:first-child{width:32%}table.readable td:nth-child(2){width:28%}
details.tech{margin:8px 0;font-size:12px;color:#5b6475}details.tech summary{cursor:pointer}
details.tech table{width:auto}details.tech th{background:none;font-weight:400}
.box{background:#fff;border:1px solid #d9dde5;border-radius:6px;padding:12px 16px;margin:10px 0}
.state{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;
background:#e3e7ee}
.state-SUSPENDED,.state-BLOCKED,.state-PROVISIONAL,.state-FALLBACK,.state-DRAFT,.state-TESTED,
.state-DISCOVERED,.state-DISABLED,.state-FAILED_PROBE{background:#fff1c2;color:#6b4e00}
.state-COMPLETED,.state-CONFIRMED,.state-DONE,.state-READY,.state-SUPPORTED,.state-ACTIVE,
.state-LOCKED,.state-PASSED,.state-REACHABLE,.state-ENABLED,.state-BUILTIN{background:#d7f2de;
color:#11522a}
.state-FAILED,.state-REFUSED,.state-ABANDONED,.state-MISSING,.state-ERROR,.state-AUTH_FAILED,
.state-UNREACHABLE,.state-PROTOCOL_ERROR,.state-SECRET_UNAVAILABLE{background:#fbd9d9;color:#7a1a1a}
.state-CONTRADICTED,.state-RETIRED,.state-UNBOUND{background:#e8e8e8;color:#555}
.muted{color:#5b6475;font-size:13px}.error{background:#fbd9d9;border-color:#e2a0a0}
.notice{background:#fff8e1;border-color:#e8d38c}.warn{background:#fff1c2;border-color:#e8c46a}
form.inline{display:inline}label{display:block;font-weight:600;margin-top:12px}
label.check{font-weight:400}
input[type=text],input[type=password],input[type=url],textarea,select{width:100%;
box-sizing:border-box;padding:6px;font:inherit}
textarea{min-height:70px}button{margin-top:14px;padding:7px 16px;font:inherit;font-weight:600;
background:#1f2a44;color:#fff;border:0;border-radius:4px;cursor:pointer}
button.small{margin:2px 0;padding:3px 10px;font-size:13px}button.danger{background:#8a2323}
.hint{font-weight:400;color:#5b6475;font-size:13px}blockquote{margin:4px 0 8px 12px;
padding-left:10px;border-left:3px solid #c9cfda;color:#333}
ol.steps{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0;margin:8px 0}
ol.steps li{background:#fff;border:1px solid #d9dde5;border-radius:14px;padding:3px 12px;
font-size:13px}ol.steps li.done{background:#d7f2de;border-color:#9fd6ad}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
"""


class Html(str):
    """Markup this package built. Everything else is text and is escaped when interpolated."""

    __slots__ = ()


def e(value: object) -> Html:
    return value if isinstance(value, Html) else Html(html.escape(str(value), quote=True))


def h(template: str, *values: object) -> Html:
    """`template` is a literal in this package; every value is escaped (or already `Html`)."""
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


@dataclass(frozen=True)
class Chrome:
    """What every page's frame needs: who, in which language, and the form token for the switch."""

    actor_id: str
    locale: str = "en"
    csrf: str | None = None
    path: str = "/"
    section: str = ""

    @property
    def m(self) -> Messages:
        return Messages(self.locale)


_SECTIONS = (
    ("episodes", "/", "nav.episodes"),
    ("new", "/runs/new", "nav.new"),
    ("llm", "/settings/llm", "nav.llm"),
    ("runtime", "/runtime", "nav.runtime"),
)


def page(title: str, body: Html, *, chrome: Chrome) -> bytes:
    m = chrome.m
    nav = cat(
        h(
            '<a href="{}"{}>{}</a>',
            href,
            Html(' class="here"' if chrome.section == key else ""),
            m(label),
        )
        for key, href, label in _SECTIONS
    )
    switch = Html("")
    if chrome.csrf is not None:
        switch = h(
            '<form method="post" action="/locale"><input type="hidden" name="csrf" value="{}">'
            '<input type="hidden" name="next" value="{}"><span class="muted">{}</span>{}</form>',
            chrome.csrf,
            chrome.path,
            m("language"),
            cat(
                h(
                    '<button type="submit" name="locale" value="{}"{} lang="{}">{}</button>',
                    code,
                    Html(' class="here"' if code == m.locale else ""),
                    code,
                    LOCALE_NAMES[code],
                )
                for code in LOCALES
            ),
        )
    return h(
        '<!doctype html><html lang="{}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>{} - {}</title><style>{}</style></head><body>"
        '<header class="top"><a class="brand" href="/">{}</a>{}{}'
        '<span class="who">{} <code>{}</code></span></header><main>{}</main>'
        "</body></html>",
        m.locale,
        title,
        m("page_suffix"),
        Html(_CSS),
        m("brand"),
        nav,
        switch,
        m("acting_as"),
        chrome.actor_id,
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


# -- pages -----------------------------------------------------------------------------------------


def _chrome(actor_id: str, chrome: Chrome | None, section: str) -> Chrome:
    if chrome is None:
        return Chrome(actor_id, section=section)
    return Chrome(chrome.actor_id, chrome.locale, chrome.csrf, chrome.path, section)


def home_page(
    *,
    actor_id: str,
    projects: Sequence[ProjectRow],
    episodes: Sequence[EpisodeRow],
    chrome: Chrome | None = None,
) -> bytes:
    frame = _chrome(actor_id, chrome, "episodes")
    m = frame.m
    if projects:
        project_list = _table(
            (m("col.project"), m("col.name")),
            ((h("<code>{}</code>", p.project_id), p.name) for p in projects),
        )
    else:
        project_list = h('<p class="box">{}</p>', m("home.no_projects", actor=actor_id))
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
            (
                m("col.episode"),
                m("col.project"),
                m("col.goal"),
                m("col.state"),
                m("col.reason"),
                m("col.runs"),
                m("col.opened"),
            ),
            rows,
        )
    else:
        episode_list = h('<p class="muted">{}</p>', m("home.no_episodes"))
    body = h(
        '<h1>{}</h1><p class="muted">{}</p><p><a href="/runs/new">{}</a></p><h2>{}</h2>{}'
        "<h2>{}</h2>{}",
        m("home.title"),
        m("home.intro"),
        m("home.start"),
        m("home.episodes"),
        episode_list,
        m("home.projects"),
        project_list,
    )
    return page(m("home.title"), body, chrome=frame)


def new_run_page(
    *,
    actor_id: str,
    projects: Sequence[ProjectRow],
    csrf: str,
    sensitivities: Sequence[str],
    error: str | None = None,
    reasoner: Html | None = None,
    chrome: Chrome | None = None,
) -> bytes:
    frame = _chrome(actor_id, chrome, "new")
    m = frame.m
    if not projects:
        body = h(
            '<h1>{}</h1><p class="box">{}</p>', m("new.title"), m("new.no_projects", actor=actor_id)
        )
        return page(m("new.title"), body, chrome=frame)
    options = cat(
        h('<option value="{}">{} ({})</option>', p.project_id, p.name, p.project_id)
        for p in projects
    )
    levels = cat(
        h('<option value="{}"{}>{}</option>', s, Html(" selected" if s == "INTERNAL" else ""), s)
        for s in sensitivities
    )
    failure = h('<p class="box error">{}</p>', error) if error else Html("")

    def field(key: str, name: str, kind: str, hint: str | None = None, extra: str = "") -> Html:
        return h(
            '<label for="{}">{}{}</label><input type="{}" id="{}" name="{}"{}>',
            name,
            m(key),
            h(' <span class="hint">{}</span>', hint) if hint else Html(""),
            kind,
            name,
            name,
            Html(extra),
        )

    body = h(
        '<h1>{}</h1>{}<p class="muted">{}</p>{}'
        '<form method="post" action="/runs" enctype="multipart/form-data" class="box">'
        '<input type="hidden" name="csrf" value="{}">'
        '<label for="project">{}</label><select id="project" name="project">{}</select>'
        '<label for="goal">{} <span class="hint">{}</span></label>'
        '<textarea id="goal" name="goal" required></textarea>'
        "{}{}{}{}{}{}"
        '<label class="check"><input type="checkbox" name="literature_query_public" value="yes"> '
        "{}</label>{}{}{}"
        '<label for="sensitivity">{}</label><select id="sensitivity" name="sensitivity">{}'
        '</select><button type="submit">{}</button></form>',
        m("new.title"),
        failure,
        m("new.intro"),
        h('<div class="box"><strong>{}:</strong> {}</div>', m("new.reasoner"), reasoner)
        if reasoner is not None
        else Html(""),
        csrf,
        m("new.project"),
        options,
        m("new.goal"),
        m("new.goal.hint"),
        field("new.measurement", "measurement", "file", m("new.measurement.hint"), " multiple"),
        field("new.run_record", "run_record", "file", m("new.run_record.hint"), " multiple"),
        field("new.note", "note", "file", m("new.note.hint"), " multiple"),
        field("new.verification", "verification_input", "file", m("new.verification.hint")),
        field("new.corpus", "literature_corpus", "file", m("new.corpus.hint")),
        field("new.query", "literature_query", "text", m("new.query.hint")),
        m("new.query.public"),
        field("new.symptom", "symptom", "text", m("optional")),
        field("new.expected", "expected", "text", m("optional")),
        field("new.observed", "observed", "text", m("optional")),
        m("new.sensitivity"),
        levels,
        m("new.submit"),
    )
    return page(m("new.title"), body, chrome=frame)


def message_page(
    *,
    actor_id: str,
    title: str,
    message: str,
    back: str = "/",
    chrome: Chrome | None = None,
) -> bytes:
    frame = _chrome(actor_id, chrome, chrome.section if chrome is not None else "")
    body = h(
        '<h1>{}</h1><p class="box notice">{}</p><p><a href="{}">{}</a></p>',
        title,
        message,
        back,
        frame.m("back"),
    )
    return page(title, body, chrome=frame)


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
    chrome: Chrome | None = None,
) -> bytes:
    frame = _chrome(actor_id, chrome, "episodes")
    m = frame.m
    live = h(
        '<div class="box"><div>{} {} {}</div>'
        '<div class="muted">{} <code>{}</code> | {} <code>{}</code> | {} {}{}</div>'
        "</div>",
        m("ep.state_now"),
        state(episode.state),
        (
            h("-- {}", episode.suspend_reason)
            if episode.suspend_reason
            else (h("-- {}", episode.outcome_status) if episode.outcome_status else Html(""))
        ),
        m("ep.project"),
        episode.project_id,
        m("ep.trace"),
        episode.trace_id,
        m("ep.opened"),
        str(episode.start_time),
        h(" | {} {}", m("ep.closed"), str(episode.end_time)) if episode.end_time else Html(""),
    )
    if continuable:
        action = h(
            '<form method="post" action="/episodes/{}/continue" class="box">'
            '<input type="hidden" name="csrf" value="{}">'
            '<div>{}</div><button type="submit">{}</button></form>',
            episode.episode_id,
            csrf,
            m("ep.continue.text"),
            m("ep.continue.button"),
        )
    else:
        action = h('<p class="box muted">{}</p>', m("ep.readonly", state=episode.state))
    run_rows = []
    for r in runs:
        link = (
            h(
                '<a href="/episodes/{}?run={}">{}</a> | '
                '<a href="/episodes/{}/runs/{}/report.md">Markdown</a>',
                episode.episode_id,
                r.ordinal,
                m("ep.report_link"),
                episode.episode_id,
                r.ordinal,
            )
            if r.recorded
            else h('<span class="muted">{}</span>', m("ep.not_recorded"))
        )
        run_rows.append(
            (
                r.ordinal,
                h("<code>{}</code>", r.research_run_id),
                h("<code>{}</code>", r.actor_id),
                str(r.started_at),
                str(r.finished_at or "-"),
                r.outcome or m("ep.running"),
                link,
            )
        )
    runs_table = _table(
        (
            m("col.run"),
            m("col.research_run"),
            m("col.actor"),
            m("col.started"),
            m("col.finished"),
            m("col.outcome"),
            m("col.report"),
        ),
        run_rows,
    )
    if report is None:
        shown = h('<p class="box muted">{}</p>', m("ep.no_report"))
    else:
        shown = h(
            "<h2>{}</h2>{}",
            m("ep.report_of", n=report_ordinal if report_ordinal else "-"),
            report_html(report, locale=m.locale),
        )
    body = h(
        "<h1>{} <code>{}</code></h1><p><strong>{}</strong> {}</p>{}{}{}<h2>{}</h2>{}{}",
        m("ep.title"),
        episode.episode_id,
        m("ep.goal"),
        episode.goal,
        h('<p class="box notice">{}</p>', notice) if notice else Html(""),
        live,
        action,
        m("ep.runs"),
        runs_table,
        shown,
    )
    return page(f"Episode {episode.episode_id}", body, chrome=frame)


# -- the report: `render_markdown`'s sections, as HTML --------------------------------------------


def report_html(r: EpisodeReport, *, locale: str = "en") -> Html:
    """Headings follow `locale`; the report's own text, identifiers and values never do."""
    m = Messages(locale)
    parts: list[Html] = [
        h(
            '<div class="box"><div>{} <code>{}</code> -- {}</div>'
            "<div>{} {}</div>"
            '<div class="muted">{} <code>{}</code> | {} <code>{}</code> | {} '
            '<code>{}</code> | {} <code>{}</code></div><div class="muted">{} {} | '
            "{} {}</div></div>",
            m("r.episode"),
            r.episode_id,
            r.goal,
            m("r.state_end"),
            state(r.episode_state),
            m("ep.project"),
            r.project_id,
            m("r.actor"),
            r.actor_id,
            m("r.domain"),
            r.domain,
            m("ep.trace"),
            r.trace_id,
            m("r.started"),
            r.started_at.isoformat(),
            m("r.finished"),
            r.finished_at.isoformat(),
        )
    ]
    add = parts.append

    if r.continuation is not None:
        k = r.continuation
        add(h("<h2>{}</h2>", m("r.continuation", n=k.run_ordinal)))
        add(
            h(
                "<p>{} {}.</p><p>{} {}.</p>",
                m("r.resumed_from"),
                rich(k.resumed_from),
                m("r.reasoning"),
                rich(k.reasoning),
            )
        )
        add(h("<h3>{}</h3>{}", m("r.earlier_runs"), _list([rich(x) for x in k.earlier_runs])))
        if k.earlier_checks:
            add(
                h(
                    "<h3>{}</h3>{}",
                    m("r.earlier_checks"),
                    _list([rich(x) for x in k.earlier_checks]),
                )
            )
        if k.superseded_jobs or k.recovered:
            add(_list([rich(x) for x in (*k.superseded_jobs, *k.recovered)]))

    c = r.conclusion
    result = [h("<p>{} -- {}</p>", state(c.status), rich(c.statement))]
    if c.ruled_out:
        result.append(h("<p>{} {}</p>", m("r.ruled_out"), "; ".join(c.ruled_out)))
    if c.still_competing:
        result.append(h("<p>{} {}</p>", m("r.still_competing"), "; ".join(c.still_competing)))
    if c.trace:
        result.append(h("<p>{} {}</p>", m("r.trace"), rich(" -> ".join(c.trace))))
    if c.confirmed_hypothesis:
        result.append(h("<p>{} <code>{}</code></p>", m("r.confirmed"), c.confirmed_hypothesis))
    if r.pending:
        best = next((p for p in r.pending if p.best_next), r.pending[0])
        result.append(
            h(
                "<p><strong>{}</strong> <code>{}</code> {} {}.</p>",
                m("r.pending_simulation"),
                best.capability_id,
                m("r.pending_sentence"),
                best.blocked_because,
            )
        )
    add(h('<h2>{}</h2><div class="box">{}</div>', m("r.result"), cat(result)))

    add(
        h(
            "<h2>{}</h2>{}",
            m("r.stages"),
            _table(
                (m("col.stage"), m("col.status"), m("col.detail")),
                ((s.stage, state(s.status), rich(s.detail)) for s in r.stages),
            ),
        )
    )

    add(
        h(
            "<h2>{}</h2>{}",
            m("r.inputs"),
            _table(
                (
                    m("col.file"),
                    m("col.role"),
                    m("col.declared"),
                    m("col.state"),
                    m("col.artifact"),
                    m("col.job"),
                    m("col.run"),
                    m("col.units"),
                    m("col.statements"),
                    m("col.detail"),
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
        add(h("<p>{} {}</p>", m("r.verification_input"), rich(r.verification_input)))

    evidence: Html
    if r.evidence:
        evidence = h(
            "<ul>{}</ul>",
            cat(
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
            ),
        )
    elif r.continuation is not None:
        evidence = h("<p>{}</p>", m("r.evidence.continuation"))
    else:
        evidence = h("<p>{}</p>", m("r.evidence.none"))
    add(h("<h2>{}</h2>{}", m("r.evidence"), evidence))
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
        ] + [h("{} {}", m("r.refused"), x) for x in lit.refusals]
        add(
            h(
                "<h3>{} <code>{}</code></h3><p>{} {}. {} '{}'. {} {}. {} {}.</p>{}",
                m("r.literature"),
                lit.provider,
                m("r.literature.source"),
                lit.description,
                m("r.literature.query"),
                lit.query,
                m("r.literature.policy"),
                lit.egress_policy,
                m("r.literature.discovered"),
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
                    h("{} {}", m("r.falsifier"), x.falsifier),
                    h("{} <code>{}</code>", m("r.cheapest"), x.minimal_test),
                    h("{} {}", m("r.predictions"), "; ".join(x.predictions)),
                    *(h("{} {}", m("r.critique"), o) for o in x.objections),
                ]
            ),
        )
        for x in r.hypotheses
    ]
    add(
        h(
            "<h2>{}</h2>{}",
            m("r.hypotheses"),
            cat(hypotheses) if hypotheses else h("<p>{}</p>", m("r.no_hypotheses")),
        )
    )

    if r.debate is None:
        add(h("<h2>{}</h2><p>{}</p>", m("r.debate"), m("r.debate.none")))
    else:
        d = r.debate
        add(
            h(
                "<h2>{}</h2><p>{} <code>{}</code> | {} {} | {} {} | {} {}</p>{}",
                m("r.debate"),
                m("r.debate.head"),
                d.debate_id,
                m("r.debate.reasoner"),
                d.reasoner,
                d.rounds,
                m("r.debate.rounds"),
                m("r.debate.stopped"),
                d.stop_reason,
                _list(
                    [
                        *(h("{} {}", m("r.position"), p) for p in d.positions),
                        h(
                            "{}",
                            m(
                                "r.critic_examined",
                                n=d.critic_evidence,
                                m=d.inverted_evidence,
                            ),
                        ),
                        *(
                            [h("{} {}", m("r.alternatives"), ", ".join(d.alternatives_named))]
                            if d.alternatives_named
                            else []
                        ),
                        h("{} {}", m("r.surviving"), ", ".join(d.surviving) or m("none")),
                        h("{} {}", m("r.contradicted"), ", ".join(d.contradicted) or m("none")),
                        h("{} {}", m("r.gate"), d.gate),
                    ]
                ),
            )
        )

    add(
        h(
            "<h2>{}</h2>{}",
            m("r.belief"),
            _table(
                (m("col.hypothesis"), m("col.mechanism"), m("col.state"), m("col.moves")),
                (
                    (
                        h("<code>{}</code>", b.hypothesis_id),
                        b.mechanism,
                        state(b.state),
                        _list([rich(x) for x in b.moves]) if b.moves else "-",
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
            "<h2>{}</h2>{}",
            m("r.plans"),
            h("<ol>{}</ol>", cat(plans)) if plans else h("<p>{}</p>", m("r.plans.none")),
        )
    )

    completed = [
        h(
            "<code>{}</code> ({}) {} {} {} -- job <code>{}</code>, run <code>{}</code>{}",
            a.capability_id,
            a.action_type,
            state(a.status),
            m("r.by"),
            a.backend,
            a.job_id or "-",
            a.run_id or "-",
            _list(
                [
                    *(rich(o) for o in a.outcomes),
                    *(
                        [h("{} {}", m("r.output"), ", ".join(a.output_artifacts))]
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
            "<h2>{}</h2>{}",
            m("r.completed"),
            _list(completed) if completed else h("<p>{}</p>", m("r.completed.none")),
        )
    )

    add(
        h(
            "<h2>{}</h2>{}",
            m("r.human"),
            _list([rich(x) for x in r.human_actions])
            if r.human_actions
            else h("<p>{}</p>", m("r.human.none")),
        )
    )

    pending = [
        h(
            "<code>{}</code> ({}, {}) -- {}: {}{}",
            p.capability_id,
            p.action_type,
            m("r.best_next") if p.best_next else m("r.also_sufficient"),
            state("BLOCKED"),
            p.blocked_because,
            _list(
                [
                    h("{} {}", m("r.would_decide"), "; ".join(p.would_decide) or "-"),
                    h("{} {}", m("r.estimated_cost"), p.estimated_cost),
                    h("{} {}", m("r.requires"), p.requires),
                ]
            ),
        )
        for p in r.pending
    ]
    add(
        h(
            "<h2>{}</h2>{}",
            m("r.blocked"),
            _list(pending) if pending else h("<p>{}</p>", m("r.blocked.none")),
        )
    )

    add(h("<h2>{}</h2>{}", m("r.next"), _list([rich(x) for x in r.next_steps])))

    provenance = (
        ([h("{} {}", m("r.failure"), rich(r.failure_analysis))] if r.failure_analysis else [])
        + [h("{} {}", m("r.heuristic"), rich(x)) for x in r.heuristic_candidates]
        + [rich(x) for x in r.provenance]
    )
    add(h("<h2>{}</h2>{}", m("r.provenance"), _list(provenance)))

    add(
        h(
            "<h2>{}</h2>{}",
            m("r.ran"),
            _list(
                [rich(x) for x in r.deployment]
                + [h("{} {}", m("r.not_performed"), rich(x)) for x in r.not_performed]
                + [h("{} {}", m("r.note"), rich(x)) for x in r.notes]
            ),
        )
    )
    return cat(parts)


__all__ = [
    "Chrome",
    "EpisodeRow",
    "Html",
    "ProjectRow",
    "RunRow",
    "cat",
    "e",
    "episode_page",
    "h",
    "home_page",
    "message_page",
    "new_run_page",
    "page",
    "report_html",
    "rich",
    "state",
]
