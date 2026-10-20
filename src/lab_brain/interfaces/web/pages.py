"""HTML for the research workspace: presentation only, and escaped by construction.

EVERY DYNAMIC VALUE IS ESCAPED. Markup is built with `h(template, *values)`, whose template is a
literal in this package and whose values are escaped unless they are already `Html` built the same
way. Nothing a user, a document, a provider or a report supplies can become markup.

NOTHING HERE DECIDES OR DERIVES. The report section renders an `EpisodeReport` -- the account the
research service returned, the same object `research.render.render_markdown` renders for the CLI --
field by field, in the same order. The episode header shows the stored episode and research-run
rows as they are. There is no script: the browser receives HTML and forms, nothing that computes.

THE EPISODE PAGE READS IN LAYERS. L1, open, answers in words what a researcher asks, in this
order -- the question and the current conclusion, the competing hypotheses side by side, what was
tested and observed, what supports or challenges each hypothesis, why the system can or cannot
conclude, and what to do next -- from the report's typed fields and `research.episode_view`'s read
of the stored records (observations, declared predictions, relations, governed transitions). It
shows no identifiers, marks each line as a hypothesis, prediction, observation, interpretation or
confirmed finding, and parses no prose from the report for meaning. L2 (collapsed) holds the
evidence and reasoning; L3 (collapsed) every record id, the runs, each rendering beside its
original and the full report, as before.

THE RECORD IS NEVER TRANSLATED; ITS READING IS. Headings, labels and the workspace's own sentences
follow the chosen locale (`i18n`), and so do stored status values, named in words with the value
as the tooltip. The pack's declared words -- mechanism names and statements, checks, observables,
outcomes -- are shown through its curated renderings (`Terms`, `ProductVertical.presentation`);
anything without one, model-written text above all, is shown as written and marked untranslated.
Identifiers, stored values and the full report stay exactly as stored.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from lab_brain.interfaces.web.i18n import (
    LOCALE_NAMES,
    LOCALES,
    RESEARCH_OUTPUT_LANGUAGE,
    Messages,
)
from lab_brain.research.episode_view import (
    CheckResult,
    DeclaredPrediction,
    EpisodeView,
    ExecutedCheck,
    Relation,
)
from lab_brain.research.report import (
    ActionLine,
    EpisodeReport,
    HypothesisLine,
    PendingAction,
    StageStatus,
)

_CSS = """
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI","Noto Sans TC","Microsoft JhengHei",
sans-serif;margin:0;color:#1d2330;background:#f6f7f9}
header.top{background:#1f2a44;color:#fff;padding:8px 24px;display:flex;gap:6px;
align-items:center;flex-wrap:wrap}header.top nav{display:flex;gap:6px;flex-wrap:wrap}
header.top a{color:#dfe5f2;text-decoration:none;font-weight:600;padding:4px 10px;
border-radius:4px}
header.top a.here{background:#34416a;color:#fff}header.top a.brand{color:#fff;margin-right:12px}
header.top .who{margin-left:auto;opacity:.9;font-size:13px}
header.top code{background:#34416a;color:#fff}
header.top .badge{background:#34416a;color:#fff}
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
.state-UNREACHABLE,.state-TIMEOUT,.state-PROTOCOL_ERROR,.state-SECRET_UNAVAILABLE{background:#fbd9d9;
color:#7a1a1a}
.state-CONTRADICTED,.state-RETIRED,.state-UNBOUND{background:#e8e8e8;color:#555}
.muted{color:#5b6475;font-size:13px}.error{background:#fbd9d9;border-color:#e2a0a0}
.notice{background:#fff8e1;border-color:#e8d38c}.warn{background:#fff1c2;border-color:#e8c46a}
form.inline{display:inline}label{display:block;font-weight:600;margin-top:12px}
label.check{font-weight:400}
input[type=text],input[type=password],input[type=email],input[type=url],textarea,select{width:100%;
box-sizing:border-box;padding:6px;font:inherit}
textarea{min-height:70px}button{margin-top:14px;padding:7px 16px;font:inherit;font-weight:600;
background:#1f2a44;color:#fff;border:0;border-radius:4px;cursor:pointer}
button.small{margin:2px 0;padding:3px 10px;font-size:13px}button.danger{background:#8a2323}
button.secondary{background:#fff;color:#1f2a44;border:1px solid #1f2a44}
button:focus-visible,a:focus-visible{outline:3px solid #6b8fd6;outline-offset:2px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#fff;border:1px solid #d9dde5;
border-radius:6px;padding:10px 12px;font:13px/1.5 ui-monospace,Consolas,monospace}
.actions{display:flex;flex-direction:column;gap:4px}details>summary{cursor:pointer}
main p,main li,main h1{overflow-wrap:anywhere}
@media (max-width:640px){header.top{padding:8px 12px}main{padding:16px 16px 48px}
header.top .who{margin-left:0}header.top form{margin-left:0}
th,td{padding:4px 6px}}
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
details.layer{margin:18px 0;border-top:1px solid #d9dde5}details.layer>summary{cursor:pointer}
details.layer>summary h2{display:inline-block;border:0;margin:14px 0 6px}
.card.hypothesis h3{margin-top:0}.card.hypothesis li.machine{color:#1f3d7a}
.card.hypothesis li.prose{color:#5b6475}li.no-match{color:#3a4254}li.moved{font-weight:600}
.card.hypothesis h4{font-size:13px;margin:10px 0 2px;color:#3a4254}.card.hypothesis p.prose{
color:#5b6475;font-size:13px}
.tag{display:inline-block;padding:0 6px;margin-right:4px;border:1px solid;border-radius:4px;
font-size:11px;font-weight:700;vertical-align:1px}
.tag-hyp{color:#1f3d7a;border-color:#bcd0f5;background:#eef4ff}
.tag-pred{color:#5a3d8a;border-color:#d3c4ef;background:#f5f0ff}
.tag-obs{color:#11522a;border-color:#9fd6ad;background:#eefaf1}
.tag-interp{color:#6b4e00;border-color:#e8d38c;background:#fff8e1}
.tag-finding{color:#fff;border-color:#11522a;background:#11522a}
.untr{color:#8a5a00;font-size:12px;margin-left:2px}
.box.conclusion{border-left:4px solid #1f2a44}.box.conclusion p strong{font-size:16px}
ul.standing{margin:6px 0 0;padding-left:18px}
.state.bs-ACTIVE,.state.bs-ADMITTED,.state.bs-DRAFT{background:#e3e7ee;color:#3a4254}
.state.bs-CHALLENGED,.state.bs-INCONCLUSIVE{background:#fff1c2;color:#6b4e00}
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
    #: With accounts: the signed-in person's name and whether they administer the laboratory --
    #: or `signed_out` on the sign-in pages. Without accounts (one researcher, named when the
    #: workspace started): None, and the frame shows the actor as before.
    account_name: str | None = None
    admin: bool = False
    signed_out: bool = False

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


#: With accounts, a person also reaches their projects and the decisions waiting for them; an
#: administrator, the laboratory overview -- and only an administrator, the AI model settings.
_ACCOUNT_SECTIONS = (
    ("home", "/", "nav.home"),
    ("projects", "/projects", "nav.projects"),
    ("inbox", "/inbox", "nav.inbox"),
    ("data", "/data", "nav.data"),
    ("new", "/runs/new", "nav.new"),
    ("episodes", "/episodes", "nav.episodes"),
)
_ADMIN_SECTIONS = (
    ("admin", "/admin", "nav.admin"),
    ("llm", "/settings/llm", "nav.llm"),
    ("status", "/status", "nav.status"),
)


def _sections(chrome: Chrome) -> tuple[tuple[str, str, str], ...]:
    if chrome.signed_out:
        return ()
    if chrome.account_name is None:
        return _SECTIONS
    return _ACCOUNT_SECTIONS + (
        _ADMIN_SECTIONS if chrome.admin else (("status", "/status", "nav.status"),)
    )


def page(title: str, body: Html, *, chrome: Chrome) -> bytes:
    m = chrome.m
    links = cat(
        h(
            '<a href="{}" title="{}"{}>{}</a>',
            href,
            m(f"{label}.hint"),
            Html(' class="here" aria-current="page"' if chrome.section == key else ""),
            m(label),
        )
        for key, href, label in _sections(chrome)
    )
    nav = h('<nav aria-label="{}">{}</nav>', m("nav.label"), links) if links else Html("")
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
        '<header class="top"><a class="brand" href="/">{}</a>{}{}{}</header><main>{}</main>'
        "</body></html>",
        m.locale,
        title,
        m("page_suffix"),
        Html(_CSS),
        m("brand"),
        nav,
        switch,
        _who(chrome),
        body,
    ).encode("utf-8")


def _who(chrome: Chrome) -> Html:
    m = chrome.m
    if chrome.signed_out:
        return Html("")
    if chrome.account_name is None:
        return h('<span class="who">{} <code>{}</code></span>', m("acting_as"), chrome.actor_id)
    return h(
        '<span class="who"><a href="/account">{}</a> <span class="badge">{}</span></span>'
        '<form method="post" action="/logout"><input type="hidden" name="csrf" value="{}">'
        '<button type="submit">{}</button></form>',
        chrome.account_name,
        m("acct.role.ADMIN" if chrome.admin else "acct.role.MEMBER"),
        chrome.csrf or "",
        m("acct.sign_out"),
    )


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
    return dataclasses.replace(chrome, section=section)


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


def label(identifier: str) -> str:
    """A declared identifier as words for the default view: its last segment, underscores as
    spaces (`cap:sp.extraction_consistency` -> "extraction consistency"). Presentation only; the
    identifier itself is the element's tooltip and is listed in the audit details."""
    return identifier.rsplit(":", 1)[-1].rsplit(".", 1)[-1].replace("_", " ")


def _named(identifier: str) -> Html:
    return h('<span title="{}">{}</span>', identifier, label(identifier))


def _kind(action_type: str | None, m: Messages) -> str:
    try:
        return m(f"act.{action_type}") if action_type else m("act.unknown")
    except KeyError:
        return str(action_type)


def _section(key: str, title: str, body: Html) -> Html:
    """An L1 section: open, in the reading order."""
    return h('<section id="v-{}" class="view"><h2>{}</h2>{}</section>', key, title, body)


def _layer(key: str, title: str, body: Html) -> Html:
    """An L2/L3 layer: collapsed until the reader opens it."""
    return h(
        '<details id="v-{}" class="layer"><summary><h2>{}</h2></summary>{}</details>',
        key,
        title,
        body,
    )


_RULED_OUT = frozenset({"CONTRADICTED"})

#: Where a hypothesis stands, for reading the comparison: supported first, ruled out last.
_STANDING = {"SUPPORTED": 0, "CONTRADICTED": 2, "EVOLVED": 3, "SUPERSEDED": 3}

#: States that leave the lifecycle (`BELIEF_TERMINAL_STATES`): neither open nor ruled out.
_SET_ASIDE = frozenset({"EVOLVED", "SUPERSEDED"})

#: Publication statuses an excerpt needs no warning for (anything else -- RETRACTED, WITHDRAWN,
#: ERRATUM_ISSUED, SUPERSEDED, SOURCE_UNAVAILABLE -- is shown beside it).
_ORDINARY_STATUS = frozenset({"ACTIVE", "UNKNOWN", ""})


class Terms:
    """The installed pack's declared words in the reader's language (`ProductVertical`).

    A canonical string or identifier is looked up exactly as stored; no record changes. Outside
    the language research is written in, text without a curated rendering -- everything a model
    wrote, and any declared sentence nobody has rendered yet -- is shown as written and marked
    untranslated, never guessed. Every lookup is remembered, so the audit layer can set each
    rendering beside its original. `observes` is which observables each declared check produces,
    for saying what a check that has not run would decide, and `kinds` what kind of action it is.
    """

    def __init__(
        self,
        locale: str = "en",
        presentation: Mapping[str, Mapping[str, str]] | None = None,
        ref: str | None = None,
        observes: Mapping[str, tuple[str, ...]] | None = None,
        kinds: Mapping[str, str] | None = None,
    ) -> None:
        self.m = Messages(locale)
        self.locale = self.m.locale
        self.ref = ref
        self.observes: Mapping[str, tuple[str, ...]] = observes or {}
        #: Each declared check's action type, for one no plan of this run recorded.
        self.kinds: Mapping[str, str] = kinds or {}
        self.presentation: Mapping[str, Mapping[str, str]] = presentation or {}
        self._renderings: Mapping[str, str] = self.presentation.get(self.locale, {})
        #: The pack's own note on these renderings (who has reviewed them), in this locale.
        self.note = self._renderings.get("@note", "")
        self._as_written = self.locale == RESEARCH_OUTPUT_LANGUAGE
        #: canonical -> what was shown for it (None: no curated rendering), first seen first.
        self.shown: dict[str, str | None] = {}

    def text(self, canonical: str) -> Html:
        """Prose -- declared or generated: its curated rendering, or the original, marked."""
        if self._as_written or not canonical:
            return e(canonical)
        rendering = self._renderings.get(canonical)
        self.shown.setdefault(canonical, rendering)
        return e(rendering) if rendering is not None else self._untranslated(canonical)

    def name(self, identifier: str) -> Html:
        """A declared identifier -- a check, an observable, an outcome -- as words; the identifier
        is the tooltip and is listed in the audit layer."""
        rendering = self._renderings.get(identifier)
        if rendering is None:
            words = label(identifier)
            words = words.lower() if words.isupper() else words
            if self._as_written:
                return h('<span title="{}">{}</span>', identifier, words)
            self.shown.setdefault(identifier, None)
            return h('<span title="{}">{}</span>', identifier, self._untranslated(words))
        if not self._as_written:
            self.shown.setdefault(identifier, rendering)
        return h('<span title="{}">{}</span>', identifier, rendering)

    @property
    def untranslated(self) -> int:
        return sum(1 for rendering in self.shown.values() if rendering is None)

    def _untranslated(self, original: str) -> Html:
        return h(
            '<span lang="en">{}</span><span class="untr">{}</span>',
            original,
            self.m("tr.untranslated"),
        )


def mh(m: Messages, key: str, **values: object) -> Html:
    """A message whose values may be markup this package built (a `Terms` name, a status): the
    template is escaped, and each value is escaped unless it is already `Html`."""
    return Html(html.escape(m.template(key)).format(**{k: e(v) for k, v in values.items()}))


def status(kind: str, value: str | None, m: Messages) -> Html:
    """A stored status in words (`kind.<VALUE>`); the stored value is its tooltip and its style.
    A value with no words is shown as stored."""
    stored = value or "-"
    try:
        words = m(f"{kind}.{stored}")
    except KeyError:
        words = stored
    value_class = re.sub(r"[^A-Z_]", "", stored)
    return h(
        '<span class="state state-{} {}-{}" title="{}">{}</span>',
        value_class,
        kind,
        value_class,
        stored,
        words,
    )


def _tag(kind: str, m: Messages) -> Html:
    """What a line is: hypothesis, prediction, observation, interpretation or finding."""
    return h('<span class="tag tag-{}">{}</span>', kind, m(f"v.tag.{kind}"))


def _words(kind: str, value: str, m: Messages) -> str:
    try:
        return m(f"{kind}.{value}")
    except KeyError:
        return value


def _effects(effects: Sequence[str], m: Messages) -> str:
    return "/".join(_words("rt", x, m) for x in effects)


def _joined(items: Sequence[Html], m: Messages) -> Html:
    return cat(items, m("v.sep")) if items else e(m("none"))


#: The waits the research service writes for the Causal Warrant Gate's stops, in words.
_WAITS = {
    "awaiting a person's diagnostic warrant answer": "ep.waiting.warrant",
    "awaiting evidence that tells the SUPPORTED mechanism from a rival": (
        "ep.waiting.undiscriminated"
    ),
    "awaiting a person: two mechanisms are SUPPORTED": "ep.waiting.competing",
}


def _waiting(reason: str | None, t: Terms) -> Html:
    """Why an episode waits, without identifiers: the shapes the service writes, in words."""
    if not reason:
        return Html("")
    if reason in _WAITS:
        return e(t.m(_WAITS[reason]))
    if reason.startswith("awaiting simulator for "):
        return mh(
            t.m,
            "ep.waiting.simulator",
            capability=t.name(reason.removeprefix("awaiting simulator for ")),
        )
    if reason.startswith("the debate failed before a hypothesis set existed"):
        return e(t.m("ep.waiting.debate"))
    return Html("")


def _groups(
    report: EpisodeReport,
) -> tuple[list[HypothesisLine], list[HypothesisLine], list[HypothesisLine]]:
    """Supported, still open, ruled out -- by each hypothesis's state after the run."""
    supported = [x for x in report.hypotheses if x.final_state == "SUPPORTED"]
    ruled_out = [x for x in report.hypotheses if x.final_state in _RULED_OUT]
    still_open = [
        x
        for x in report.hypotheses
        if x not in supported and x not in ruled_out and x.final_state not in _SET_ASIDE
    ]
    return supported, still_open, ruled_out


def _ordered(hypotheses: Sequence[HypothesisLine]) -> list[HypothesisLine]:
    return sorted(hypotheses, key=lambda x: _STANDING.get(x.final_state, 1))


@dataclass(frozen=True)
class _Seen:
    """One observed outcome of one executed check, and whether an earlier run executed it."""

    capability_id: str
    result: CheckResult
    earlier: bool


def _this_run(report: EpisodeReport | None) -> list[ActionLine]:
    return list(report.completed) if report is not None else []


def _earlier(
    report: EpisodeReport | None, view: EpisodeView, runs: Sequence[RunRow], ordinal: int | None
) -> list[ExecutedCheck]:
    """Checks earlier research runs of the episode executed: started before the shown run began,
    and not among its own -- never counted as executed again."""
    mine = {a.run_id for a in _this_run(report) if a.run_id}
    began = next((r.started_at for r in runs if r.ordinal == ordinal), None)
    if not isinstance(began, dt.datetime):
        return []
    return [
        x
        for x in view.executed
        if x.run_id not in mine and isinstance(x.started_at, dt.datetime) and x.started_at < began
    ]


def _seen(
    report: EpisodeReport | None, view: EpisodeView, runs: Sequence[RunRow], ordinal: int | None
) -> list[_Seen]:
    """Every observed outcome the shown run can rely on: its own checks', then earlier runs'."""
    return [
        *(
            _Seen(a.capability_id, r, False)
            for a in _this_run(report)
            for r in view.results.get(a.run_id or "", ())
        ),
        *(
            _Seen(x.capability_id, r, True)
            for x in _earlier(report, view, runs, ordinal)
            for r in view.results.get(x.run_id, ())
        ),
    ]


def _relations(seen: Sequence[_Seen], hypothesis_id: str) -> list[tuple[_Seen, Relation]]:
    return [
        (s, rel) for s in seen for rel in s.result.relations if rel.hypothesis_id == hypothesis_id
    ]


def _person_actions(report: EpisodeReport | None) -> list[str]:
    """Checks a plan of this run chose that it did not execute and that are not blocked: a
    person's act, as the plan named it."""
    if report is None:
        return []
    done = {a.capability_id for a in report.completed}
    blocked = {p.capability_id for p in report.pending}
    chosen: list[str] = []
    for plan in report.plans:
        if plan.chosen and plan.chosen not in done | blocked and plan.chosen not in chosen:
            chosen.append(plan.chosen)
    return chosen


def _no_input(report: EpisodeReport) -> bool:
    """Verification was skipped because no verification input was given -- not because, say,
    the debate admitted no hypothesis (the service's own words for each)."""
    return any(
        s.stage == "verification"
        and s.status == "SKIPPED"
        and s.detail.startswith("no verification input")
        for s in report.stages
    )


def _stopped(report: EpisodeReport) -> StageStatus | None:
    """Where an unreached run stopped: its first failed or refused step, else its first skip."""
    return next(
        (s for s in report.stages if s.status in ("FAILED", "REFUSED")),
        next((s for s in report.stages if s.status == "SKIPPED"), None),
    )


def _ran(action: ActionLine) -> bool:
    """Whether a check of this run executed (`WorkflowStatus.EXECUTED`). A budget refusal or a
    wait for a seat is in `completed` too, and nothing executed."""
    return action.status == "EXECUTED"


def _not_run(report: EpisodeReport) -> list[tuple[str, str, str]]:
    """(check, kind, status) for every check this run planned that did not execute: blocked
    here, refused by the budget, or waiting for a resource -- its result unknown. A check that
    ran and failed is not among them (`_failed`)."""
    return [(p.capability_id, p.action_type, "BLOCKED") for p in report.pending] + [
        (a.capability_id, a.action_type, a.status)
        for a in report.completed
        if not _ran(a) and a.status != "FAILED"
    ]


def _failed(report: EpisodeReport) -> list[ActionLine]:
    return [a for a in report.completed if a.status == "FAILED"]


def _observed_about(x: HypothesisLine, seen: Sequence[_Seen]) -> bool:
    """Whether any observation the shown run relies on bears on this hypothesis's predictions."""
    return any(
        p.hypothesis_id == x.hypothesis_id
        for s in seen
        for p in (*s.result.matched, *s.result.unmatched, *s.result.incomparable)
    ) or bool(_relations(seen, x.hypothesis_id))


def _action_type(
    capability_id: str, report: EpisodeReport, view: EpisodeView, t: Terms
) -> str | None:
    return (
        view.action_types.get(capability_id)
        or t.kinds.get(capability_id)
        or next((p.action_type for p in report.pending if p.capability_id == capability_id), None)
        or next((a.action_type for a in report.completed if a.capability_id == capability_id), None)
    )


def _check_kind(capability_id: str, kind: str | None, t: Terms) -> Html:
    return mh(t.m, "v.check_kind", check=t.name(capability_id), kind=_kind(kind, t.m))


def _observation(s: _Seen, t: Terms) -> Html:
    return mh(
        t.m,
        "v.observation",
        check=t.name(s.capability_id),
        observable=t.name(s.result.observable),
        outcome=t.name(s.result.outcome),
    )


def _moves(relation: Relation, t: Terms) -> Html:
    """What the governed path did with one relation: its transitions, or why there were none."""
    m = t.m
    if relation.transitions:
        return cat(
            (
                mh(
                    m,
                    "v.moved",
                    mechanism=t.text(x.mechanism),
                    from_state=status("bs", x.from_state, m),
                    to_state=status("bs", x.to_state, m),
                    decision=_words("td", x.decision or "-", m),
                )
                for x in relation.transitions
            ),
            " ",
        )
    refused = [d for d in relation.decisions if d.result != "ALLOW"]
    if refused:
        return mh(
            m,
            "v.decided",
            mechanism=t.text(relation.mechanism),
            result=_words("td", refused[-1].result, m),
        )
    return mh(m, "v.no_decision", mechanism=t.text(relation.mechanism))


# -- L1, section by section ------------------------------------------------------------------------


def _result_html(
    episode: EpisodeRow,
    report: EpisodeReport | None,
    runs: Sequence[RunRow],
    ordinal: int | None,
    t: Terms,
) -> Html:
    m = t.m
    waiting = _waiting(episode.suspend_reason, t)
    parts: list[Html] = [
        h(
            '<div class="box"><strong>{}</strong> {}{}</div>',
            m("ep.state_now"),
            status("ep", episode.state, m),
            h(' <span class="purpose">{}</span>', waiting) if waiting else Html(""),
        )
    ]
    if report is None:
        parts.append(h('<p class="muted">{}</p>', m("ep.no_report")))
        return cat(parts)
    recorded = [r for r in runs if r.recorded and r.ordinal != ordinal]
    parts.append(
        h(
            '<p class="muted">{} {}</p>',
            m("v.run_shown", n=ordinal or "-", total=len(runs)),
            h(
                "{} {}",
                m("v.other_runs"),
                cat(
                    (
                        h(
                            '<a href="/episodes/{}?run={}">{}</a>',
                            episode.episode_id,
                            r.ordinal,
                            m("ep.run_n", n=r.ordinal),
                        )
                        for r in recorded
                    ),
                    " · ",
                ),
            )
            if recorded
            else Html(""),
        )
    )
    if report.continuation is not None:
        parts.append(h("<p>{}</p>", m("v.continued", n=report.continuation.run_ordinal)))
    c = report.conclusion
    confirmed = next(
        (x for x in report.hypotheses if x.hypothesis_id == c.confirmed_hypothesis), None
    )
    if c.status == "CONFIRMED":
        headline = mh(
            m,
            "v.conclusion.CONFIRMED",
            mechanism=t.text(confirmed.mechanism) if confirmed else m("v.unknown_cause"),
        )
    else:
        headline = e(_words("v.conclusion", c.status, m))
    lines = [
        h(
            "<p>{}{} <strong>{}</strong></p>",
            h("{} ", _tag("finding", m)) if c.status == "CONFIRMED" else Html(""),
            status("cs", c.status, m),
            headline,
        )
    ]
    if c.status != "CONFIRMED":
        lines.append(h("<p>{}</p>", m("v.no_root_cause")))
    if c.status == "NOT_REACHED":
        stopped = _stopped(report)
        if stopped is not None:
            lines.append(
                h(
                    "<p>{}</p>",
                    mh(
                        m,
                        "v.stopped_at",
                        stage=_words("stage", stopped.stage, m),
                        status=status("ss", stopped.status, m),
                    ),
                )
            )
    if report.hypotheses:
        supported, still_open, ruled_out = _groups(report)
        aside = [x for x in report.hypotheses if x.final_state in _SET_ASIDE]
        lines.append(
            h(
                '<ul class="standing"><li>{} {}</li><li>{} {}</li><li>{} {}</li>{}</ul>',
                m("v.supported"),
                _joined([t.text(x.mechanism) for x in supported], m),
                m("v.still_competing"),
                _joined([t.text(x.mechanism) for x in still_open], m),
                m("v.ruled_out"),
                _joined([t.text(x.mechanism) for x in ruled_out], m),
                h(
                    "<li>{} {}</li>",
                    m("v.set_aside"),
                    _joined([t.text(x.mechanism) for x in aside], m),
                )
                if aside
                else Html(""),
            )
        )
    parts.append(h('<div class="box conclusion">{}</div>', cat(lines)))
    return cat(parts)


def _evidence_status(
    x: HypothesisLine, report: EpisodeReport, view: EpisodeView, seen: Sequence[_Seen], t: Terms
) -> Html:
    """In one or two lines: what has been observed about this hypothesis, or why nothing has."""
    m = t.m
    found = _relations(seen, x.hypothesis_id)
    if found:
        return cat(
            h(
                "<div>{} {}{}</div>",
                _observation(s, t),
                mh(m, "v.ev.effect", effect=_words("rt", rel.relation_type, m)),
                # A relation the governed path did not act on leaves the state where it was.
                h(" {}", _moves(rel, t)) if not rel.transitions else Html(""),
            )
            for s, rel in found
        )
    over = [
        (s, any(p.hypothesis_id == x.hypothesis_id for p in s.result.matched))
        for s in seen
        if any(
            p.hypothesis_id == x.hypothesis_id
            for p in (*s.result.matched, *s.result.unmatched, *s.result.incomparable)
        )
    ]
    if over:
        return cat(
            h(
                "<div>{} {}</div>",
                _observation(s, t),
                e(m("v.ev.unrecorded" if matched else "v.ev.no_bearing")),
            )
            for s, matched in over
        )
    if not x.minimal_test:
        return e(m("v.ev.untested_unknown"))
    test = x.minimal_test
    ran = {s.capability_id for s in seen} | {a.capability_id for a in report.completed if _ran(a)}
    if test in {c for c, _, _ in _not_run(report)}:
        where = m("v.ev.blocked")
    elif test in {a.capability_id for a in _failed(report)}:
        where = m("v.ev.failed")
    elif test in _person_actions(report):
        where = m("v.ev.person")
    elif test in ran:
        where = m("v.ev.ran_no_observation")
    else:
        where = m("v.ev.unplanned")
    return mh(
        m,
        "v.ev.untested",
        check=t.name(test),
        kind=_kind(_action_type(test, report, view, t), m),
        where=where,
    )


def _hypotheses_html(
    report: EpisodeReport | None, view: EpisodeView, seen: Sequence[_Seen], t: Terms
) -> Html:
    """The comparison: every hypothesis, where it stands, and what has been observed about it."""
    m = t.m
    if report is None:
        # Run elsewhere (the command line): the workspace holds no report to read from.
        return h("<p>{}</p>", m("ep.no_report"))
    if not report.hypotheses:
        return h("<p>{}</p>", m("v.no_hypothesis"))
    return _table(
        (m("col.hypothesis"), m("col.standing"), m("col.evidence_status")),
        (
            (
                h("<strong>{}</strong>", t.text(x.mechanism)),
                status("bs", x.final_state, m),
                _evidence_status(x, report, view, seen, t),
            )
            for x in _ordered(report.hypotheses)
        ),
    )


def _explain(result: CheckResult, t: Terms) -> Html:
    """What one observed outcome did, from the typed records only -- see `research.episode_view`."""
    m = t.m
    obs, out = t.name(result.observable), t.name(result.outcome)
    lines: list[Html] = []
    if result.relations:
        declared = {
            p.prediction_id: p for p in (*result.matched, *result.unmatched, *result.incomparable)
        }
        for relation in result.relations:
            p = declared.get(relation.prediction_id or "")
            lines.append(
                h(
                    "<li>{}</li>",
                    mh(
                        m,
                        "v.matched",
                        observable=obs,
                        outcome=out,
                        mechanism=t.text(relation.mechanism),
                        expected=t.name(p.expected_outcome) if p else out,
                        effect=_words("rt", relation.relation_type, m),
                        designated=m("v.designated") if p and p.designated_falsifier else "",
                    ),
                )
            )
            lines.append(
                h(
                    '<li class="{}">{}</li>',
                    "moved" if relation.transitions else "",
                    _moves(relation, t),
                )
            )
        return cat(lines)
    if result.matched:
        return cat(
            h(
                "<li>{}</li>",
                mh(
                    m,
                    "v.matched_unrecorded",
                    observable=obs,
                    outcome=out,
                    mechanism=t.text(p.mechanism),
                ),
            )
            for p in result.matched
        )
    if result.unmatched or result.incomparable:
        # Same outcome string or not, a prediction in another OutcomeSpace says nothing here.
        apart = m("v.space_unrecorded") if result.outcome_space is None else m("v.not_comparable")
        declared_items = cat(
            h(
                "<li>{}{}</li>",
                mh(
                    m,
                    "v.declared_item",
                    mechanism=t.text(p.mechanism),
                    expected=t.name(p.expected_outcome),
                    effect=_effects(p.effects, m),
                    designated=m("v.designated") if p.designated_falsifier else "",
                ),
                apart if p in result.incomparable else "",
            )
            for p in (*result.unmatched, *result.incomparable)
        )
        return h(
            '<li class="no-match">{}<div>{}</div><ul>{}</ul></li>',
            mh(m, "v.no_match", observable=obs, outcome=out),
            mh(m, "v.declared_over", observable=obs),
            declared_items,
        )
    return h("<li>{}</li>", mh(m, "v.no_prediction", observable=obs))


def _checked(
    capability_id: str, kind: str | None, state: str, results: Sequence[CheckResult], t: Terms
) -> Html:
    """One executed check: what it observed, and what each observation did."""
    m = t.m
    observed = (
        cat(
            h(
                "<li>{} {}</li>{}",
                _tag("obs", m),
                mh(m, "v.observed", observable=t.name(r.observable), outcome=t.name(r.outcome)),
                _explain(r, t),
            )
            for r in results
        )
        if results
        else h('<li class="muted">{}</li><li>{}</li>', m("v.no_observation"), m("v.not_recorded"))
    )
    return h(
        "<li>{} {}<ul>{}</ul></li>",
        _check_kind(capability_id, kind, t),
        status("ws", state, m),
        observed,
    )


def _tested_html(
    report: EpisodeReport | None,
    view: EpisodeView,
    runs: Sequence[RunRow],
    ordinal: int | None,
    t: Terms,
) -> Html:
    m = t.m
    if report is None:
        return h("<p>{}</p>", m("v.run_unrecorded"))
    parts: list[Html] = []
    executed = [
        _checked(a.capability_id, a.action_type, a.status, view.results.get(a.run_id or "", ()), t)
        for a in _this_run(report)
        if _ran(a)
    ]
    parts.append(
        h(
            "<h3>{}</h3>{}",
            m("v.executed"),
            h("<ul>{}</ul>", cat(executed))
            if executed
            else h("<p>{}</p>", m("v.nothing_executed")),
        )
    )
    earlier = [
        _checked(
            x.capability_id,
            view.action_types.get(x.capability_id),
            x.status,
            view.results.get(x.run_id, ()),
            t,
        )
        for x in _earlier(report, view, runs, ordinal)
    ]
    if earlier:
        parts.append(h("<h3>{}</h3><ul>{}</ul>", m("v.earlier"), cat(earlier)))
    person = [
        h("<li>{}</li>", _check_kind(c, view.action_types.get(c), t))
        for c in _person_actions(report)
    ]
    if person:
        parts.append(h("<h3>{}</h3><ul>{}</ul>", m("v.needs_person"), cat(person)))
    unavailable = [
        h(
            "<li>{} {} {}</li>",
            _check_kind(capability, kind, t),
            status("ws", state, m),
            m("v.not_run_unknown"),
        )
        for capability, kind, state in _not_run(report)
    ] + [
        h(
            "<li>{} {} {}</li>",
            _check_kind(a.capability_id, a.action_type, t),
            status("ws", a.status, m),
            m("v.failed_no_result"),
        )
        for a in _failed(report)
    ]
    if unavailable:
        parts.append(h("<h3>{}</h3><ul>{}</ul>", m("v.unavailable"), cat(unavailable)))
    checks = [a for a in _this_run(report) if _ran(a)]
    moves = sum(len(r.transitions) for a in checks for r in view.results.get(a.run_id or "", ()))
    objections = sum(len(x.objections) for x in report.hypotheses)
    parts.append(
        h(
            "<p><strong>{}</strong></p>{}",
            m("v.summary_moves", n=moves)
            if moves
            else (m("v.summary_none") if checks else m("v.no_checks_learned")),
            h('<p class="muted">{}</p>', m("v.critique_note", n=objections))
            if objections
            else Html(""),
        )
    )
    return cat(parts)


def _prediction_word(p: DeclaredPrediction, seen: Sequence[_Seen], t: Terms) -> Html:
    """Has this prediction been observed, by the observations the shown run relies on (its own
    and earlier runs', never a later run's)? A match anywhere says so, whatever else was seen."""
    m = t.m
    results = [s.result for s in seen]
    if any(p in r.matched for r in results):
        return e(m("v.pred.observed"))
    other = [r for r in results if p in r.unmatched]
    if other:
        return mh(m, "v.pred.other", outcome=_joined([t.name(r.outcome) for r in other], m))
    if any(p in r.incomparable for r in results):
        return e(m("v.pred.not_comparable"))
    return e(m("v.pred.pending"))


def _support_html(
    report: EpisodeReport | None, view: EpisodeView, seen: Sequence[_Seen], t: Terms
) -> Html:
    """Per hypothesis: its claim, what it predicted, and the observations for and against it."""
    m = t.m
    if report is None:
        return h("<p>{}</p>", m("v.run_unrecorded"))
    if not report.hypotheses:
        return h("<p>{}</p>", m("v.no_hypothesis"))
    cards: list[Html] = []
    for x in _ordered(report.hypotheses):
        typed = view.predictions.get(x.hypothesis_id, ())
        if typed:
            predicted = [
                h(
                    '<li class="{}">{} {}</li>',
                    "machine" if p.designated_falsifier else "",
                    _tag("pred", m),
                    mh(
                        m,
                        "v.pred.item",
                        observable=t.name(p.observable),
                        expected=t.name(p.expected_outcome),
                        effect=_effects(p.effects, m),
                        designated=m("v.designated") if p.designated_falsifier else "",
                        status=_prediction_word(p, seen, t),
                    ),
                )
                for p in typed
            ]
        elif x.machine_falsifiers:
            predicted = [
                h('<li class="machine">{} <code>{}</code></li>', m("v.falsifier_recorded"), f)
                for f in x.machine_falsifiers
            ]
        else:
            predicted = [h('<li class="machine muted">{}</li>', m("v.falsifier_none"))]
        found = _relations(seen, x.hypothesis_id)

        def items(kind: str, found: list[tuple[_Seen, Relation]] = found) -> Html:
            chosen = [
                h("<li>{} {}<div>{}</div></li>", _tag("obs", m), _observation(s, t), _moves(rel, t))
                for s, rel in found
                if rel.relation_type == kind
            ]
            return cat(chosen) if chosen else h('<li class="muted">{}</li>', m("none"))

        cards.append(
            h(
                '<div class="card hypothesis"><h3>{} {}</h3><p>{} {}</p>'
                "<h4>{}</h4><ul>{}</ul><h4>{}</h4><ul>{}</ul><h4>{}</h4><ul>{}</ul>{}"
                '<p class="prose">{} {}</p></div>',
                t.text(x.mechanism),
                status("bs", x.final_state, m),
                _tag("hyp", m),
                t.text(x.statement),
                m("v.predicted"),
                cat(predicted),
                m("v.supporting"),
                items("SUPPORTS"),
                m("v.challenging"),
                items("CONTRADICTS"),
                h(
                    '<p class="muted">{} {}</p>',
                    _tag("interp", m),
                    m("v.objections", n=len(x.objections)),
                )
                if x.objections
                else Html(""),
                m("v.falsifier_prose"),
                t.text(x.falsifier),
            )
        )
    return cat(cards)


def _reasoner_line(report: EpisodeReport, t: Terms) -> Html:
    """Who proposed and criticised the hypotheses, as the run's inference provenance recorded."""
    m = t.m
    d = report.debate
    if d is None:
        return e(m("v.why.no_debate"))
    if d.reasoner.startswith("rules:"):
        return e(m("v.why.rules"))
    prefix = "language model: "
    if d.reasoner.startswith(prefix):
        from lab_brain.core.models.inference import LogicalSlot
        from lab_brain.interfaces.web.labels import SLOT_NAMES

        named: list[Html] = []
        for part in d.reasoner.removeprefix(prefix).split("; "):
            slot, _, model = part.partition(" -> ")
            names = SLOT_NAMES.get(LogicalSlot(slot)) if slot in LogicalSlot else None
            named.append(
                mh(
                    m,
                    "v.why.model_item",
                    role=names[LOCALES.index(m.locale)] if names else slot,
                    model=model,
                )
            )
        return mh(m, "v.why.models", models=_joined(named, m))
    return mh(m, "v.why.reasoner", reasoner=d.reasoner)


def _why_html(
    report: EpisodeReport | None,
    seen: Sequence[_Seen],
    t: Terms,
    view: EpisodeView,
    suspend_reason: str | None = None,
) -> Html:
    """Why the system can or cannot conclude, from the typed record: what is still open, what
    conflicts, what was never run -- never a verdict the record does not hold."""
    m = t.m
    if report is None:
        return h("<p>{}</p>", m("ep.no_report"))
    c = report.conclusion
    supported, still_open, ruled_out = _groups(report)

    def names(xs: Sequence[HypothesisLine]) -> Html:
        return _joined([t.text(x.mechanism) for x in xs], m)

    reasons: list[Html] = []
    if c.status == "CONFIRMED":
        lead = m("v.why.can")
        reasons += [
            mh(m, "v.why.basis", observation=_observation(s, t))
            for s, rel in _relations(seen, c.confirmed_hypothesis or "")
            if rel.relation_type == "SUPPORTS"
        ]
        stored = [x for x in view.conclusions if x.status == "CONFIRMED"]
        if any(x.not_relied_on for x in stored):
            reasons.append(e(m("v.why.not_relied")))
        elif any(x.warrant_refs for x in stored):
            n = max(len(x.warrant_refs) for x in stored)
            reasons.append(e(m("v.why.warranted", n=n)))
        if ruled_out:
            reasons.append(mh(m, "v.why.others_ruled_out", names=names(ruled_out)))
        rivals = [x for x in still_open if x.hypothesis_id != c.confirmed_hypothesis]
        untested = [x for x in rivals if not _observed_about(x, seen)]
        if untested:
            # A confirmation can rest on a diagnostic signature with rivals never tested: said.
            reasons.append(mh(m, "v.why.untested_rivals", names=names(untested)))
        tested = [x for x in rivals if x not in untested]
        if tested:
            reasons.append(mh(m, "v.why.open_rivals", names=names(tested)))
    else:
        lead = m("v.why.cannot")
        if not report.hypotheses:
            reasons.append(e(m("v.no_hypothesis")))
        if still_open:
            reasons.append(mh(m, "v.why.open", n=len(still_open), names=names(still_open)))
        if len(supported) > 1:
            reasons.append(mh(m, "v.why.competing", n=len(supported), names=names(supported)))
        # With a rival open, support is not confirmation; with none open, the governed path still
        # did not confirm it -- and the page says what it waits for, never an open rival.
        reasons += [
            mh(
                m,
                "v.why.supported_not_confirmed" if still_open else "v.why.supported_unconfirmed",
                mechanism=t.text(x.mechanism),
            )
            for x in supported
        ]
        if suspend_reason in _WAITS:
            reasons.append(mh(m, "v.why.waiting", reason=_waiting(suspend_reason, t)))
        if c.status == "INCONCLUSIVE":
            reasons.append(e(m("v.why.inconclusive")))
        stopped = _stopped(report) if c.status == "NOT_REACHED" else None
        if stopped is not None:
            reasons.append(
                mh(
                    m,
                    "v.why.stopped",
                    stage=_words("stage", stopped.stage, m),
                    status=status("ss", stopped.status, m),
                )
            )
    conflicting = [
        x
        for x in report.hypotheses
        if {"SUPPORTS", "CONTRADICTS"}
        <= {r.relation_type for _, r in _relations(seen, x.hypothesis_id)}
    ]
    reasons += [mh(m, "v.why.conflicting", mechanism=t.text(x.mechanism)) for x in conflicting]
    reasons += [
        mh(m, "v.why.challenged", mechanism=t.text(x.mechanism))
        for x in report.hypotheses
        if x.final_state == "CHALLENGED" and x not in conflicting
    ]
    if _no_input(report):
        reasons.append(e(m("v.why.no_input")))
    not_run = _not_run(report)
    if not_run:
        reasons.append(
            mh(
                m,
                "v.why.unperformed",
                checks=_joined([_check_kind(c, kind, t) for c, kind, _ in not_run], m),
            )
        )
    failed = _failed(report)
    if failed:
        reasons.append(
            mh(
                m,
                "v.why.failed",
                checks=_joined([_check_kind(a.capability_id, a.action_type, t) for a in failed], m),
            )
        )
    person = _person_actions(report)
    if person:
        reasons.append(mh(m, "v.why.person", checks=_joined([t.name(x) for x in person], m)))
    reasons.append(_reasoner_line(report, t))
    return h(
        '<p><strong>{}</strong></p><ul>{}</ul><p class="muted">{}</p>',
        lead,
        cat(h("<li>{}</li>", r) for r in reasons),
        m("v.why.rule"),
    )


#: The question classifications, most restrictive first (`SensitivityLabel`'s order).
_LABELS = ("RESTRICTED_NDA", "CONFIDENTIAL_LAB", "INTERNAL", "PUBLIC")


def _declare_label(cleared: frozenset[str] | None, m: Messages) -> Html:
    """For an episode opened before its question's classification was recorded (`012q`): the
    classification its continuation must declare, at a level the actor holds. Nothing to
    ask otherwise -- a continuation carries the recorded one."""
    if cleared is None:
        return Html("")
    return h(
        '<fieldset><legend>{}</legend><p class="muted">{}</p>{}</fieldset>',
        m("ep.continue.declare"),
        m("ep.continue.declare.hint"),
        cat(
            h(
                '<label><input type="radio" name="sensitivity" value="{}" required{}> {}{}'
                "</label><br>",
                label,
                Html("" if label in cleared else " disabled"),
                m(f"sens.{label}"),
                h(' <span class="muted">({})</span>', m("sens.not_cleared"))
                if label not in cleared
                else Html(""),
            )
            for label in _LABELS
        ),
    )


def _would_decide(p: PendingAction, report: EpisodeReport, view: EpisodeView, t: Terms) -> Html:
    """What a check that has not run would decide: the declared predictions over what it would
    observe. Without the pack's declaration of what it observes, nothing here: the run's own words
    stay in the full report."""
    m = t.m
    observes = t.observes.get(p.capability_id, ())
    lines = [
        h(
            "<li>{} {}</li>",
            _tag("pred", m),
            mh(
                m,
                "v.would.item",
                observable=t.name(q.observable),
                outcome=t.name(q.expected_outcome),
                effect=_effects(q.effects, m),
                mechanism=t.text(x.mechanism),
            ),
        )
        for x in report.hypotheses
        for q in view.predictions.get(x.hypothesis_id, ())
        if q.observable in observes
    ]
    if not lines:
        return Html("")
    return h("<div>{}</div><ul>{}</ul>", m("v.would_decide"), cat(lines))


def _next_html(
    episode: EpisodeRow,
    report: EpisodeReport | None,
    view: EpisodeView,
    csrf: str | None,
    continuable: bool,
    t: Terms,
    declare_label: frozenset[str] | None = None,
) -> Html:
    """What the researcher should do next. `csrf` None: no form (an exported summary)."""
    m = t.m
    parts: list[Html] = []
    if report is not None:
        for p in report.pending:
            if p.best_next:
                parts.append(
                    h(
                        '<div class="next"><p><strong>{}</strong></p><p>{}</p>{}</div>',
                        mh(
                            m,
                            "v.best_next",
                            check=t.name(p.capability_id),
                            kind=_kind(p.action_type, m),
                        ),
                        mh(
                            m,
                            "v.blocked_because",
                            reason=t.text(p.blocked_because),
                            requires=t.text(p.requires) if p.requires else m("none"),
                        ),
                        _would_decide(p, report, view, t),
                    )
                )
            else:
                parts.append(
                    h(
                        "<p>{}</p>",
                        mh(
                            m,
                            "v.also_blocked",
                            check=t.name(p.capability_id),
                            kind=_kind(p.action_type, m),
                        ),
                    )
                )
        for c in _person_actions(report):
            parts.append(
                h(
                    "<p>{}</p>",
                    mh(m, "v.person", check=t.name(c), kind=_kind(view.action_types.get(c), m)),
                )
            )
        if episode.suspend_reason == "awaiting a person's diagnostic warrant answer":
            parts.append(h('<p class="next">{}</p>', m("v.next.warrant")))
    if not parts:
        if report is None:
            parts.append(h("<p>{}</p>", m("ep.no_report")))
        elif _no_input(report):
            # Nothing was planned because nothing could be: no verification input was given.
            parts.append(h('<p class="box warn">{}</p>', m("v.no_verification_input")))
        else:
            parts.append(h("<p>{}</p>", m("v.nothing_next")))
    if csrf is None:
        return cat(parts)
    if continuable:
        parts.append(
            h(
                '<form method="post" action="/episodes/{}/continue" class="box">'
                '<input type="hidden" name="csrf" value="{}">'
                '<div>{}</div>{}<button type="submit" class="primary">{}</button></form>',
                episode.episode_id,
                csrf,
                m("ep.continue.text"),
                _declare_label(declare_label, m),
                m("ep.continue.button"),
            )
        )
    else:
        parts.append(
            h('<p class="box muted">{}</p>', m("ep.readonly", state=_words("ep", episode.state, m)))
        )
    return cat(parts)


def _effect(prediction: DeclaredPrediction) -> str:
    return "/".join(prediction.effects)


def _reasoning_html(
    report: EpisodeReport | None,
    view: EpisodeView,
    runs: Sequence[RunRow],
    ordinal: int | None,
    m: Messages,
) -> Html:
    if report is None:
        return h('<p class="muted">{}</p>', m("ep.no_report"))
    parts: list[Html] = [
        h(
            "<h3>{}</h3><p>{} -- {}</p>",
            m("v.l2.conclusion"),
            state(report.conclusion.status),
            rich(report.conclusion.statement),
        )
    ]
    observed = [
        h(
            "<li>{}</li>",
            m(
                "v.l2.observed_item",
                check=label(capability),
                observable=label(r.observable),
                outcome=r.outcome,
                epistemic=r.epistemic_type or "-",
            ),
        )
        for capability, run_id in (
            *((a.capability_id, a.run_id or "") for a in report.completed),
            *((x.capability_id, x.run_id) for x in _earlier(report, view, runs, ordinal)),
        )
        for r in view.results.get(run_id, ())
    ]
    recorded = [rich(o) for a in report.completed for o in a.outcomes]
    parts.append(
        h(
            "<h3>{}</h3>{}{}",
            m("v.l2.observed"),
            h("<ul>{}</ul>", cat(observed)) if observed else Html(""),
            _list(recorded) if recorded else (Html("") if observed else h("<p>{}</p>", m("none"))),
        )
    )
    matched = {p.prediction_id for rs in view.results.values() for r in rs for p in r.matched}
    # A prediction over an observable a check DID observe is not pending: either its OutcomeSpace
    # held another outcome, or the observation was in another (or an unrecorded) space and is not
    # comparable to it at all -- never read as agreeing or disagreeing.
    instead: dict[str, list[str]] = {}
    apart: dict[str, list[str]] = {}
    for rs in view.results.values():
        for r in rs:
            for p in r.unmatched:
                instead.setdefault(p.prediction_id, []).append(r.outcome)
            for p in r.incomparable:
                apart.setdefault(p.prediction_id, []).append(
                    r.outcome_space or m("v.l2.space_unrecorded")
                )

    def status(p: DeclaredPrediction) -> str:
        if p.prediction_id in matched:
            return m("v.l2.observed_now")
        if p.prediction_id in instead:
            return m("v.l2.observed_other", outcome=", ".join(instead[p.prediction_id]))
        if p.prediction_id in apart:
            return m(
                "v.l2.not_comparable",
                declared=p.outcome_space,
                observed=", ".join(apart[p.prediction_id]),
            )
        return m("v.l2.pending")

    declared = [
        h(
            "<li>{}<ul>{}</ul></li>",
            x.mechanism,
            cat(
                h(
                    "<li>{}</li>",
                    m(
                        "v.l2.declared_item",
                        observable=label(p.observable),
                        expected=p.expected_outcome,
                        effect=_effect(p),
                        designated=m("v.designated") if p.designated_falsifier else "",
                        status=status(p),
                    ),
                )
                for p in view.predictions.get(x.hypothesis_id, ())
            )
            if view.predictions.get(x.hypothesis_id)
            else cat(h("<li>{}</li>", rich(s)) for s in x.predictions),
        )
        for x in report.hypotheses
    ]
    if declared:
        parts.append(h("<h3>{}</h3><ul>{}</ul>", m("v.l2.declared"), cat(declared)))
    interpretations: list[Html] = []
    if report.debate is not None:
        d = report.debate
        interpretations += [h("{} {}", m("r.position"), p) for p in d.positions]
        interpretations.append(
            h("{}", m("r.critic_examined", n=d.critic_evidence, m=d.inverted_evidence))
        )
        if d.alternatives_named:
            interpretations.append(h("{} {}", m("r.alternatives"), ", ".join(d.alternatives_named)))
        interpretations.append(
            h("{} {}", m("r.contradicted"), ", ".join(d.contradicted) or m("none"))
        )
    interpretations += [
        h("{}", m("v.l2.objection", mechanism=x.mechanism, objection=o))
        for x in report.hypotheses
        for o in x.objections
    ]
    if interpretations:
        parts.append(
            h(
                '<h3>{}</h3>{}<p class="muted">{}</p>',
                m("v.l2.interpretations"),
                _list(interpretations),
                m("v.l2.critique_stage"),
            )
        )
    if report.plans:
        parts.append(
            h(
                "<h3>{}</h3><ol>{}</ol>",
                m("v.l2.candidates"),
                cat(
                    h(
                        "<li><strong>{}</strong>{}<div>{}</div>{}</li>",
                        p.decision,
                        h(" -&gt; {}", _named(p.chosen)) if p.chosen else Html(""),
                        rich(p.summary),
                        _list([rich(x) for x in p.candidates]),
                    )
                    for p in report.plans
                ),
            )
        )
    if report.evidence:
        # A literature passage keeps its source's publication status beside it: a RETRACTED
        # paper is admitted and recorded (EVI-008), and must not read as an ordinary one.
        status_of = {
            line.admitted_attestation_id: line.status
            for line in (report.literature.consulted if report.literature else ())
            if line.admitted_attestation_id
        }
        parts.append(
            h(
                "<h3>{}</h3><ul>{}</ul>",
                m("v.l2.evidence"),
                cat(
                    h(
                        "<li>{} [{}] ({}, {}){}<blockquote>{}</blockquote></li>",
                        x.source,
                        x.locator,
                        x.origin,
                        x.trust_class,
                        h(
                            ' <strong class="warn">{}</strong>',
                            m("v.source_status", status=status_of[x.attestation_id]),
                        )
                        if status_of.get(x.attestation_id, "ACTIVE") not in _ORDINARY_STATUS
                        else Html(""),
                        x.excerpt,
                    )
                    for x in report.evidence
                ),
            )
        )
    parts.append(
        h(
            "<h3>{}</h3>{}{}",
            m("v.l2.unavailable"),
            _list([rich(x) for x in report.not_performed]) if report.not_performed else Html(""),
            _table(
                (m("col.stage"), m("col.status"), m("col.detail")),
                ((s.stage, state(s.status), rich(s.detail)) for s in report.stages),
            ),
        )
    )
    if report.next_steps or report.human_actions:
        parts.append(
            h(
                "<h3>{}</h3>{}",
                m("v.l2.recorded_next"),
                _list([rich(x) for x in (*report.human_actions, *report.next_steps)]),
            )
        )
    return cat(parts)


def _records_html(view: EpisodeView) -> Html:
    rows = []
    for x in view.executed:
        for r in view.results.get(x.run_id, ()) or (None,):
            rows.append(
                (
                    h("<code>{}</code>", x.capability_id),
                    h("<code>{}</code>", x.run_id),
                    h("<code>{}</code>", r.observation_id) if r else "-",
                    h("<code>{}</code>", r.attestation_id or "-") if r else "-",
                    _list(
                        [
                            h(
                                "<code>{}</code> {} <code>{}</code> (<code>{}</code>){}{}",
                                rel.relation_id,
                                rel.relation_type,
                                rel.hypothesis_id,
                                rel.prediction_id or "-",
                                cat(
                                    h(
                                        "; <code>{}</code> {} -&gt; {} {} <code>{}</code> {}",
                                        t.event_id,
                                        t.from_state,
                                        t.to_state,
                                        t.policy,
                                        t.decision_id or "-",
                                        t.decision or "-",
                                    )
                                    for t in rel.transitions
                                ),
                                # Every decision that considered the relation, with or without
                                # an event: a refusal is as auditable as a move.
                                cat(
                                    h(
                                        "; decision <code>{}</code> {} <code>{}</code>"
                                        " <code>{}</code> {} -&gt; {}",
                                        d.decision_id,
                                        d.result,
                                        d.policy,
                                        d.hypothesis_id,
                                        d.from_state,
                                        d.to_state,
                                    )
                                    for d in rel.decisions
                                ),
                            )
                            for rel in r.relations
                        ]
                    )
                    if r and r.relations
                    else "-",
                )
            )
    return _table(("capability", "run", "observation", "attestation", "relations and events"), rows)


def _conclusion_notices_html(view: EpisodeView, m: Messages) -> Html:
    """L1: in words, what is recorded beside a stored confirmation -- a flag, or that nothing
    relies on it. The records themselves, with their identifiers, are in L3."""
    parts: list[Html] = []
    for c in view.conclusions:
        if c.status != "CONFIRMED":
            continue
        parts.extend(
            h(
                '<div class="box warn"><p>{}</p><p>{}</p><p>{}</p></div>',
                m("v.conclusion.flagged", kind=f.kind),
                c.failure_class,
                f.statement,
            )
            for f in c.flags
        )
        if c.not_relied_on and not c.flags:
            parts.append(
                h('<p class="muted">{} {}</p>', c.failure_class, m("v.conclusion.not_relied_l1"))
            )
    return cat(parts)


def _conclusion_records_html(view: EpisodeView, m: Messages) -> Html:
    """L3: every stored conclusion, its warrants and flags, and why nothing relies on it."""
    rows = [
        (
            h("<code>{}</code>", c.failure_analysis_id),
            c.status,
            h("<code>{}</code>", c.confirmed_root_cause or "-"),
            c.failure_class,
            h("<code>{}</code>", ", ".join(c.warrant_refs) or "-"),
            _list(
                [
                    h(
                        "{} -- {} ({}; {})",
                        f.kind,
                        f.statement,
                        f.recorded_by,
                        ", ".join(f.evidence_refs),
                    )
                    for f in c.flags
                ]
            )
            or "-",
            (
                m("v.conclusion.not_relied", why=c.not_relied_on)
                if c.not_relied_on
                else (m("v.conclusion.relied") if c.status == "CONFIRMED" else "-")
            ),
        )
        for c in view.conclusions
    ]
    return _table(("analysis", "status", "cause", "class", "warrants", "flags", "relied on"), rows)


def _question_html(episode: EpisodeRow, project_name: str | None, m: Messages) -> Html:
    return h(
        '<section id="v-question" class="view"><p class="muted">{}</p><h1>{}</h1>'
        '<p class="muted">{} {} · {} {} · {}</p></section>',
        m("ep.goal"),
        episode.goal,
        m("ep.project"),
        project_name or label(episode.project_id),
        m("ep.opened"),
        when(episode.start_time),
        m("ep.run_count", n=episode.runs),
    )


def _l1_html(
    episode: EpisodeRow,
    report: EpisodeReport | None,
    runs: Sequence[RunRow],
    ordinal: int | None,
    view: EpisodeView,
    t: Terms,
    *,
    csrf: str | None,
    continuable: bool,
    declare_label: frozenset[str] | None = None,
) -> Html:
    """L1 in the order a researcher asks: the conclusion; the hypotheses side by side; what was
    tested and observed; what supports or challenges each; why the system can or cannot
    conclude; what to do next."""
    m = t.m
    seen = _seen(report, view, runs, ordinal)
    return cat(
        [
            _section("result", m("v.result"), _result_html(episode, report, runs, ordinal, t)),
            _section("conclusions", m("v.conclusions"), _conclusion_notices_html(view, m))
            if any(
                c.status == "CONFIRMED" and (c.flags or c.not_relied_on) for c in view.conclusions
            )
            else Html(""),
            _section("hypotheses", m("v.hypotheses"), _hypotheses_html(report, view, seen, t)),
            _section("tested", m("v.tested"), _tested_html(report, view, runs, ordinal, t)),
            _section("support", m("v.support"), _support_html(report, view, seen, t)),
            _section("why", m("v.why"), _why_html(report, seen, t, view, episode.suspend_reason)),
            _section(
                "next",
                m("v.next"),
                _next_html(episode, report, view, csrf, continuable, t, declare_label),
            ),
        ]
    )


def _translation_notes(t: Terms) -> Html:
    """Beside the question: how many passages are shown untranslated, and what the curated
    renderings are (the pack's own note: who has reviewed them)."""
    notes: list[Html] = []
    if t.untranslated:
        notes.append(h('<p class="box notice">{}</p>', t.m("tr.notice", n=t.untranslated)))
    if t.note and any(rendering is not None for rendering in t.shown.values()):
        notes.append(h('<p class="muted">{}</p>', t.m("tr.curated_note", note=t.note)))
    return cat(notes)


def _originals_html(t: Terms) -> Html:
    """Every rendering the page showed beside the text it renders, and where it came from."""
    m = t.m
    if not t.shown:
        return h('<p class="muted">{}</p>', m("tr.as_written"))
    return cat(
        [
            h('<p class="muted">{}</p>', m("tr.provenance", ref=t.ref or m("none"))),
            _table(
                (m("col.shown"), m("col.original"), m("col.rendering")),
                (
                    (
                        rendering if rendering is not None else m("tr.none"),
                        h('<span lang="en">{}</span>', original),
                        m("tr.curated") if rendering is not None else m("tr.missing"),
                    )
                    for original, rendering in t.shown.items()
                ),
            ),
        ]
    )


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
    view: EpisodeView | None = None,
    declare_label: frozenset[str] | None = None,
    terms: Terms | None = None,
) -> bytes:
    """The research, in the order a researcher reads it.

    L1, open: the question and current conclusion, the hypotheses compared, what was tested and
    observed, what supports or challenges each, why the system can or cannot conclude, and what
    to do next -- in words, without identifiers. L2 (collapsed): the evidence and reasoning
    behind them. L3 (collapsed): every record id, the runs, each rendering beside its original,
    and the full report exactly as before. `view` is `research.episode_view`'s read of the stored
    records; without it, what it would have said is shown as not recorded, never filled in.
    `terms` is how the pack's declared words read in this locale; without it they are shown as
    written (and, outside English, marked untranslated).
    """
    frame = _chrome(actor_id, chrome, "episodes")
    m = frame.m
    view = view if view is not None else EpisodeView()
    t = terms if terms is not None and terms.locale == m.locale else Terms(m.locale)
    l1 = _l1_html(
        episode,
        report,
        runs,
        report_ordinal,
        view,
        t,
        csrf=csrf,
        continuable=continuable,
        declare_label=declare_label,
    )
    run_rows = []
    for r in runs:
        link = (
            h(
                '<a href="/episodes/{}?run={}">{}</a> · '
                '<a href="/episodes/{}/runs/{}/report.md">{}</a> · '
                '<a href="/episodes/{}/runs/{}/summary.html">{}</a>',
                episode.episode_id,
                r.ordinal,
                m("ep.report_link"),
                episode.episode_id,
                r.ordinal,
                m("ep.markdown"),
                episode.episode_id,
                r.ordinal,
                m("ep.summary_export"),
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
        (m("col.run"), m("col.started"), m("col.finished"), m("col.outcome"), m("col.report")),
        run_rows,
    )
    technical = h(
        "<table>{}</table>",
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
    audit = cat(
        [
            h("<h3>{}</h3>{}", m("ep.runs"), runs_table),
            h("<h3>{}</h3>{}", m("tech.details"), technical),
            h("<h3>{}</h3>{}", m("v.l3.records"), _records_html(view)),
            h("<h3>{}</h3>{}", m("v.l3.conclusions"), _conclusion_records_html(view, m))
            if view.conclusions
            else Html(""),
            h("<h3>{}</h3>{}", m("v.l3.originals"), _originals_html(t)),
            h(
                '<h3>{}</h3><p class="muted">{}</p><section class="report">{}</section>',
                m("ep.report_of", n=report_ordinal if report_ordinal else "-"),
                m("ep.report_language"),
                report_html(report, locale=m.locale),
            )
            if report is not None
            else Html(""),
        ]
    )
    body = cat(
        [
            _question_html(episode, project_name, m),
            h('<p class="box notice">{}</p>', notice) if notice else Html(""),
            _translation_notes(t),
            l1,
            _layer(
                "reasoning",
                m("v.reasoning"),
                _reasoning_html(report, view, runs, report_ordinal, m),
            ),
            _layer("audit", m("v.audit"), audit),
        ]
    )
    return page(f"{m('ep.title')}: {episode.goal[:60]}", body, chrome=frame)


def summary_document(
    *,
    episode: EpisodeRow,
    runs: Sequence[RunRow],
    report: EpisodeReport,
    report_ordinal: int,
    view: EpisodeView,
    terms: Terms,
    project_name: str | None,
    source_digest: str,
    exported_at: dt.datetime,
) -> bytes:
    """One run's research summary as a file to keep or print: L1 in the reader's language, then
    where it came from. A derived document: the record is the run's report, unchanged
    (`report.md`), and `source_digest` is that export's SHA-256 at the moment of this one."""
    t = terms
    m = t.m
    l1 = _l1_html(episode, report, runs, report_ordinal, view, t, csrf=None, continuable=False)
    provenance = _table(
        (m("col.item"), m("col.value")),
        (
            (m("sum.derived"), m("sum.derived_text", n=report_ordinal)),
            (m("sum.source"), h("<code>{}</code>", source_digest)),
            (m("sum.renderings"), t.ref or m("none")),
            (m("sum.untranslated"), t.untranslated),
            (m("sum.reasoner"), _reasoner_line(report, t)),
            (m("sum.exported"), when(exported_at)),
            (m("sum.episode"), h("<code>{}</code>", episode.episode_id)),
        ),
    )
    body = cat(
        [
            h('<p class="muted">{}</p>', m("sum.title")),
            _question_html(episode, project_name, m),
            _translation_notes(t),
            l1,
            h(
                '<section id="v-provenance" class="view"><h2>{}</h2>{}<h3>{}</h3>{}</section>',
                m("sum.provenance"),
                provenance,
                m("v.l3.originals"),
                _originals_html(t),
            ),
        ]
    )
    return h(
        '<!doctype html><html lang="{}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>{} - {}</title><style>{}</style></head><body><main>{}</main></body></html>",
        m.locale,
        m("sum.title"),
        episode.goal[:60],
        Html(_CSS),
        body,
    ).encode("utf-8")


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
                    *(
                        h("{} <code>{}</code>", m("r.falsifier_typed"), f)
                        for f in x.machine_falsifiers
                    ),
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
    "label",
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
