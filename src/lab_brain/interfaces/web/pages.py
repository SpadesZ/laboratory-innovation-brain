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

import datetime as dt
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
.lede{color:#3a4254;margin:4px 0 12px}
.cta{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0 6px}
a.button{display:inline-block;padding:10px 18px;border-radius:6px;background:#1f2a44;color:#fff;
font-weight:700;text-decoration:none}a.button.secondary{background:#fff;color:#1f2a44;
border:1px solid #1f2a44}a.button.small{padding:4px 10px;font-size:13px;font-weight:600}
.card{background:#fff;border:1px solid #d9dde5;border-radius:8px;padding:12px 16px}
.card h2{margin-top:0;border:0;font-size:16px}.card h2 small{font-weight:400;color:#5b6475;
font-size:13px;margin-left:6px}
.next{background:#eef4ff;border:1px solid #bcd0f5;border-radius:6px;padding:10px 14px;
margin:10px 0}.next strong{color:#1f3d7a}
.step{display:inline-block;min-width:22px;height:22px;line-height:22px;text-align:center;
border-radius:11px;background:#1f2a44;color:#fff;font-size:12px;margin-right:6px}
fieldset{border:1px solid #d9dde5;border-radius:6px;margin:12px 0;padding:8px 14px;
background:#fff}legend{font-weight:700;padding:0 6px}
label.choice{font-weight:400;display:block;margin:6px 0}label.choice .hint{display:block;
margin-left:22px}
.state-PARTIAL,.state-PROCESSING,.state-NEEDS_REVIEW,.state-DUPLICATE,.state-WAITING,
.state-EVIDENCE_GATHERING{background:#fff1c2;color:#6b4e00}
.info{background:#f2f4f8;border-color:#d9dde5}
.cta>div{display:flex;flex-direction:column;gap:4px;max-width:360px}
button.primary{font-size:16px;padding:10px 22px}
.card.intake{border:2px solid #1f2a44;margin:14px 0}.card.intake h2 small{font-size:14px}
label.choice.off{color:#8a91a0}label.inline{display:inline;font-weight:600;margin:0}
.warn-line{margin-top:4px;padding:4px 8px;background:#fff1c2;border-radius:4px}
form.picker{display:flex;gap:8px;align-items:center;margin:8px 0}form.picker label{margin:0}
form.picker select{width:auto}p.actions{display:flex;gap:16px;align-items:center}
ol.steps li.here{background:#1f2a44;color:#fff;border-color:#1f2a44}
details.legend{margin:12px 0}details.legend dt{margin-top:6px}details.legend dd{margin:2px 0 0 12px;
color:#3a4254;font-size:13px}
table.status td:first-child{width:22%}table.status td:nth-child(2){width:12%}
.checklist td:first-child{width:45%}
table.summary th{width:22%;font-weight:600}table.summary td{font-size:14px}
header.top .muted{color:#aeb7cc}
.conn{border:1px solid #d9dde5;border-radius:6px;padding:10px 12px;margin:8px 0;background:#fcfcfd}
.conn .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.conn .row form{display:inline-flex;gap:6px;align-items:center;margin:0}
.conn .row select{width:auto;max-width:320px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:#e3e7ee}
button[disabled]{background:#b9bfca;cursor:not-allowed}
.field{display:flex;flex-direction:column}.field label{margin-top:0}
.next-step{color:#1f3d7a}details.advanced{margin:10px 0}details.advanced>summary{cursor:pointer;
font-weight:600;color:#1f3d7a}details.advanced.card{margin-top:24px}
.card{margin:12px 0}
#add:has(#kind-ollama:checked) #f-external,#add:has(#kind-external:checked) #f-ollama{display:none}
fieldset.kinds{display:flex;flex-wrap:wrap;gap:18px;border:0;padding:0;margin:6px 0 10px;
background:none}
p.ready{color:#11522a;font-weight:700}form.kind-form{margin-top:6px}
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


def when_text(value: object) -> str:
    """A stored timestamp in this machine's local time, as plain text (for inside a sentence)."""
    if not isinstance(value, dt.datetime):
        return "-" if value is None else str(value)
    moment = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def when(value: object) -> Html:
    """A stored timestamp in this machine's local time (the deployment sets `TZ`), the stored
    UTC instant as its tooltip."""
    if not isinstance(value, dt.datetime):
        return e("-" if value is None else value)
    moment = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    return h(
        '<time datetime="{}" title="{}">{}</time>',
        moment.astimezone(dt.UTC).isoformat(timespec="seconds"),
        moment.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        moment.astimezone().strftime("%Y-%m-%d %H:%M"),
    )


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


#: The main entries, in the order a researcher works: add data, start research, read what came of
#: it; then the AI models and the system's state. Each answers the question in its `.hint`.
_SECTIONS = (
    ("home", "/", "nav.home"),
    ("data", "/data", "nav.data"),
    ("new", "/runs/new", "nav.new"),
    ("episodes", "/episodes", "nav.episodes"),
    ("llm", "/settings/llm", "nav.llm"),
    ("status", "/status", "nav.status"),
)


def page(title: str, body: Html, *, chrome: Chrome) -> bytes:
    m = chrome.m
    nav = cat(
        h(
            '<a href="{}" title="{}"{}>{}</a>',
            href,
            m(f"{label}.hint"),
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


def outcome_words(outcome: str | None, m: Messages) -> Html:
    """A research run's recorded outcome (`SUSPENDED:PROVISIONAL`, `CONFIRMED:<cause>`, ...) in
    the researcher's words; the stored value is its tooltip."""
    if not outcome:
        return e(m("ep.running"))
    head, _, rest = outcome.partition(":")
    key = f"outcome.{head}"
    try:
        text = m(key)
    except KeyError:
        return h('<span title="{}">{}</span>', outcome, outcome)
    detail = rest if head in ("FAILED",) else ""
    status = f"outcome.status.{rest}" if head == "SUSPENDED" and rest else ""
    if status:
        try:
            detail = m(status)
        except KeyError:
            detail = rest
    return h(
        '<span title="{}">{}{}</span>', outcome, text, h(" ({})", detail) if detail else Html("")
    )


def waiting_words(reason: str | None, m: Messages) -> str:
    """Why an episode waits, in the researcher's words where the reason is a known shape."""
    if not reason:
        return ""
    prefix = "awaiting simulator for "
    if reason.startswith(prefix):
        return m("ep.waiting.simulator", capability=reason.removeprefix(prefix))
    return reason


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
    project_name: str | None = None,
) -> bytes:
    frame = _chrome(actor_id, chrome, "episodes")
    m = frame.m
    state_key = f"ep.{episode.state}"
    try:
        state_text = m(state_key)
    except KeyError:
        state_text = episode.state
    waiting = waiting_words(episode.suspend_reason, m)
    live = h(
        '<div class="box"><div><strong>{}</strong> '
        '<span class="state state-{}" title="{}">{}</span>{}</div>'
        '<div class="muted">{} {} · {} {} · {}</div></div>',
        m("ep.state_now"),
        re.sub(r"[^A-Z_]", "", episode.state),
        episode.state,
        state_text,
        h(' <span class="purpose">{}</span>', waiting) if waiting else Html(""),
        m("ep.project"),
        project_name or episode.project_id,
        m("ep.opened"),
        when(episode.start_time),
        m("ep.run_count", n=episode.runs),
    )
    if continuable:
        action = h(
            '<form method="post" action="/episodes/{}/continue" class="box">'
            '<input type="hidden" name="csrf" value="{}">'
            '<div>{}</div><button type="submit" class="primary">{}</button></form>',
            episode.episode_id,
            csrf,
            m("ep.continue.text"),
            m("ep.continue.button"),
        )
    else:
        action = h(
            '<p class="box muted">{}</p>',
            m("ep.readonly", state=state_text),
        )
    run_rows = []
    for r in runs:
        link = (
            h(
                '<a href="/episodes/{}?run={}">{}</a> · '
                '<a href="/episodes/{}/runs/{}/report.md">{}</a>',
                episode.episode_id,
                r.ordinal,
                m("ep.report_link"),
                episode.episode_id,
                r.ordinal,
                m("ep.markdown"),
            )
            if r.recorded
            else h('<span class="muted">{}</span>', m("ep.not_recorded"))
        )
        run_rows.append(
            (
                m("ep.run_n", n=r.ordinal),
                when(r.started_at),
                when(r.finished_at) if r.finished_at else "-",
                outcome_words(r.outcome, m),
                link,
            )
        )
    runs_table = _table(
        (
            m("col.run"),
            m("col.started"),
            m("col.finished"),
            m("col.outcome"),
            m("col.report"),
        ),
        run_rows,
    )
    technical = h(
        '<details class="tech"><summary>{}</summary><table>{}</table></details>',
        m("tech.details"),
        cat(
            h("<tr><th>{}</th><td><code>{}</code></td></tr>", k, v)
            for k, v in (
                ("episode", episode.episode_id),
                ("state", episode.state),
                ("outcome_status", episode.outcome_status or "-"),
                ("suspend_reason", episode.suspend_reason or "-"),
                ("project", episode.project_id),
                ("trace", episode.trace_id),
                *(
                    (
                        f"run {r.ordinal}",
                        f"{r.research_run_id} actor={r.actor_id} {r.outcome or ''}",
                    )
                    for r in runs
                ),
            )
        ),
    )
    if report is None:
        shown = h('<p class="box muted">{}</p>', m("ep.no_report"))
    else:
        shown = h(
            '<h2>{}</h2><p class="muted">{}</p><section class="report">{}</section>',
            m("ep.report_of", n=report_ordinal if report_ordinal else "-"),
            m("ep.report_language"),
            report_html(report, locale=m.locale),
        )
    body = h(
        '<p class="muted">{}</p><h1>{}</h1>{}{}{}<h2>{}</h2>{}{}{}',
        m("ep.title"),
        episode.goal,
        h('<p class="box notice">{}</p>', notice) if notice else Html(""),
        live,
        action,
        m("ep.runs"),
        runs_table,
        technical,
        shown,
    )
    return page(f"{m('ep.title')}: {episode.goal[:60]}", body, chrome=frame)


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
    "message_page",
    "outcome_words",
    "page",
    "report_html",
    "rich",
    "state",
    "waiting_words",
    "when",
    "when_text",
]
