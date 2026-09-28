"""The research workspace: `lab-brain research run` in a browser, and nothing it does not do.

A WSGI application over the accepted product vertical. It adds no scientific logic: a research run
is `ResearchEpisodeService.run` with the request a form describes; a continuation is the same call
with `episode_id` (the accepted continuation path, unchanged); what an episode shows is the
`EpisodeReport` the service returned for each run -- recorded as returned (`012d`) -- beside the
episode's live state from `research_episodes` and `research_runs`.

WHO. The workspace serves ONE actor, named when it is started (`lab-brain web --actor A`), the same
trust model as the CLI's `--actor`: whoever runs the process is that actor. The browser never names
an actor. It binds to the loopback interface only and answers only for the host names it was
started under -- there is no login, so it must not be reachable from anywhere else.

AUTHORIZATION IS THE SERVER'S, ON EVERY REQUEST. Projects are those `ScientificReadGate` admits for
the actor now. An episode is shown or continued only if this actor OPENED it (`012c`'s opening run)
and the gate still admits the actor to its project; every other id -- unknown, another project's,
a colleague's -- gets one answer, a 404 that names only the id asked for. A stored report's
evidence excerpts are re-authorized against the actor's CURRENT clearance each time they are shown.
LLM settings are open to an actor who is an active member of at least one project here.

FORGERY. Every state-changing request is a POST that must carry this process's CSRF token (and,
when the browser sends one, an Origin of this workspace), and every request must name an allowed
Host -- so another web page cannot drive the workspace, and a rebinding DNS name cannot reach it.

REASONING (V2). A new research run is reasoned by the ACTIVE LLM runtime if there is one
(`llm_runtime.load_active_runtime`), through the research service's one `ScientificLLM`; with none
active, by the local catalog reasoner -- the explicit fallback. An active runtime that cannot be
used refuses the run before anything is written; it is never silently replaced by the fallback.

LANGUAGE. The interface follows a per-browser locale (cookie `lb_locale`, switched by a form in the
header); stored text and identifiers are shown as stored (`i18n`).
"""

from __future__ import annotations

import dataclasses
import hmac
import json
import re
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from lab_brain.composition import IngestionService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.interfaces.cli import _DOCUMENT_KINDS, _MEDIA_TYPES
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import pages, settings_pages
from lab_brain.interfaces.web.forms import Form, FormError, read_form
from lab_brain.interfaces.web.i18n import DEFAULT_LOCALE, LOCALES, Messages
from lab_brain.interfaces.web.pages import Chrome
from lab_brain.llm_runtime.capabilities import BINDABLE_SLOTS, SLOT_REQUIREMENTS, Capability
from lab_brain.llm_runtime.registry import ModelRow, ProbeRow
from lab_brain.llm_runtime.runtime import (
    LLMSettings,
    RuntimeUnavailable,
    SettingsRefused,
    load_active_runtime,
)
from lab_brain.llm_runtime.secrets import SecretStore
from lab_brain.research.continuation import (
    ContinuationRefused,
    EpisodeNotContinuable,
)
from lab_brain.research.literature import LiteratureRequest
from lab_brain.research.reasoning import ReasoningRuntime
from lab_brain.research.render import render_markdown
from lab_brain.research.report import EpisodeReport, EvidenceLine
from lab_brain.research.report_store import RecordedReport, SqlResearchReportStore
from lab_brain.research.service import InputDocument, ResearchEpisodeService, ResearchRequest
from lab_brain.research.vertical import VerticalFactory
from lab_brain.storage.artifacts.local import LocalArtifactStore

#: The largest request body the workspace reads (all uploads of one run together).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Host names a loopback-bound workspace answers to.
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")

#: The interface-language cookie. Its value is only ever compared against `LOCALES`.
LOCALE_COOKIE = "lb_locale"

_ID = r"([A-Za-z0-9:_.\-]{1,200})"
_EPISODE_PATH = re.compile(rf"^/episodes/{_ID}$")
_CONTINUE_PATH = re.compile(rf"^/episodes/{_ID}/continue$")
_MARKDOWN_PATH = re.compile(rf"^/episodes/{_ID}/runs/([0-9]{{1,6}})/report\.md$")
_CONNECTION_PATH = re.compile(rf"^/settings/llm/connections/{_ID}(?:/([a-z]+))?$")
_MODEL_PATH = re.compile(rf"^/settings/llm/models/{_ID}(?:/([a-z]+))?$")
_RUNTIME_PATH = re.compile(rf"^/settings/llm/runtimes/{_ID}(?:/([a-z]+))?$")

#: Where a form posted to a collection path came from.
_POSTED_FROM = {
    "/runs": "/runs/new",
    "/settings/llm/connections": "/settings/llm",
    "/settings/llm/runtimes": "/settings/llm",
}

#: Shown in place of an evidence excerpt the actor can no longer read.
WITHHELD = "[withheld: this excerpt is not readable under your current clearance]"


@dataclass(frozen=True)
class Response:
    status: str
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


def _redirect(location: str, *headers: tuple[str, str]) -> Response:
    return Response("303 See Other", b"", headers=(("Location", location), *headers))


@dataclass(frozen=True)
class _Req:
    method: str
    path: str
    query: Mapping[str, Sequence[str]]
    form: Form | None
    locale: str

    @property
    def m(self) -> Messages:
        return Messages(self.locale)

    @property
    def target(self) -> str:
        """The page to come back to after switching language: this one, or -- after a form was
        sent -- the page that form belongs to (an action URL answers only POST)."""
        if self.method == "POST":
            return _POSTED_FROM.get(self.path) or (
                self.path.rsplit("/", 1)[0] if self.path.count("/") >= 4 else "/"
            )
        query = "&".join(f"{k}={quote(v[0])}" for k, v in self.query.items() if v)
        return self.path + (f"?{query}" if query else "")


@dataclass(frozen=True)
class _Opened:
    """An episode this actor opened, as the ledger and the episode row hold it."""

    project_id: str
    row: pages.EpisodeRow


class _Refused(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response


class Workspace:
    def __init__(
        self,
        *,
        actor_id: str,
        settings: Settings,
        connect: Callable[[Settings], Any],
        artifact_root: Path,
        vertical_factory: VerticalFactory,
        allowed_hosts: Iterable[str],
        csrf_token: str | None = None,
        secrets: SecretStore | None = None,
        default_locale: str = DEFAULT_LOCALE,
    ) -> None:
        self._actor = actor_id
        self._settings = settings
        self._connect = connect
        self._artifacts = LocalArtifactStore(artifact_root.resolve())
        self._factory = vertical_factory
        self._hosts = frozenset(allowed_hosts)
        self._csrf = csrf_token or _token()
        self._secrets = secrets if secrets is not None else SecretStore()
        self._locale = default_locale if default_locale in LOCALES else DEFAULT_LOCALE

    # -- WSGI -------------------------------------------------------------------------------------

    def __call__(
        self, environ: Mapping[str, Any], start_response: Callable[..., Any]
    ) -> Iterable[bytes]:
        response = self._respond(environ)
        headers = [
            ("Content-Type", response.content_type),
            ("Content-Length", str(len(response.body))),
            # No script, no framing, forms only to this workspace.
            (
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "frame-ancestors 'none'; base-uri 'none'",
            ),
            ("X-Content-Type-Options", "nosniff"),
            # `same-origin`, not `no-referrer`: under `no-referrer` a browser sends `Origin: null`
            # on this workspace's own form posts, which the forgery check rightly refuses.
            ("Referrer-Policy", "same-origin"),
            ("Cache-Control", "no-store"),
            *response.headers,
        ]
        start_response(response.status, headers)
        return [response.body]

    def _respond(self, environ: Mapping[str, Any]) -> Response:
        host = str(environ.get("HTTP_HOST") or "")
        if host not in self._hosts:
            return Response(
                "400 Bad Request", b"Unknown host.", content_type="text/plain; charset=utf-8"
            )
        method = str(environ.get("REQUEST_METHOD") or "GET")
        path = str(environ.get("PATH_INFO") or "/")
        query = parse_qs(str(environ.get("QUERY_STRING") or ""))
        locale = self._requested_locale(environ)
        form: Form | None = None
        if method == "POST":
            origin = environ.get("HTTP_ORIGIN")
            if origin is not None and origin not in {f"http://{h}" for h in self._hosts}:
                return self._forbidden()
            try:
                form = read_form(environ, limit=MAX_UPLOAD_BYTES)
            except FormError as refused:
                req = _Req(method, path, query, None, locale)
                return self._message(req, "400 Bad Request", req.m("msg.refused"), str(refused))
            if not hmac.compare_digest(form.value("csrf"), self._csrf):
                return self._forbidden()
        elif method != "GET":
            return Response("405 Method Not Allowed", b"", headers=(("Allow", "GET, POST"),))
        req = _Req(method, path, query, form, locale)
        if path == "/locale" and form is not None:
            return self._switch_locale(form)

        connection = self._connect(self._settings)
        try:
            connection.autocommit = True
            return self._route(connection, req)
        except _Refused as refused:
            return refused.response
        finally:
            connection.close()

    def _route(self, c: Any, req: _Req) -> Response:
        method, path, form = req.method, req.path, req.form
        if path == "/" and method == "GET":
            return self._home(c, req)
        if path == "/runs/new" and method == "GET":
            return self._new_run(c, req)
        if path == "/runs" and method == "POST" and form is not None:
            return self._create_run(c, req, form)
        if (m := _EPISODE_PATH.match(path)) and method == "GET":
            return self._episode(c, req, m.group(1))
        if (m := _CONTINUE_PATH.match(path)) and method == "POST":
            return self._continue(c, req, m.group(1))
        if (m := _MARKDOWN_PATH.match(path)) and method == "GET":
            return self._markdown(c, req, m.group(1), int(m.group(2)))
        if path == "/runtime" and method == "GET":
            return self._active_runtime(c, req)
        if path.startswith("/settings/llm"):
            self._require_researcher(c, req)
            if path == "/settings/llm" and method == "GET":
                return self._overview(c, req)
            if path == "/settings/llm/connections" and method == "POST" and form is not None:
                return self._add_connection(c, req, form)
            if path == "/settings/llm/runtimes" and method == "POST" and form is not None:
                return self._create_runtime(c, req, form)
            if m := _CONNECTION_PATH.match(path):
                return self._connection_route(c, req, m.group(1), m.group(2))
            if m := _MODEL_PATH.match(path):
                return self._model_route(c, req, m.group(1), m.group(2))
            if m := _RUNTIME_PATH.match(path):
                return self._runtime_route(c, req, m.group(1), m.group(2))
        return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))

    # -- language ---------------------------------------------------------------------------------

    def _requested_locale(self, environ: Mapping[str, Any]) -> str:
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(str(environ.get("HTTP_COOKIE") or ""))
        except CookieError:
            return self._locale
        morsel = cookie.get(LOCALE_COOKIE)
        return morsel.value if morsel is not None and morsel.value in LOCALES else self._locale

    @staticmethod
    def _switch_locale(form: Form) -> Response:
        chosen = form.value("locale")
        target = form.value("next")
        # Only a path of this workspace: never another origin, never a protocol-relative URL.
        if not target.startswith("/") or target.startswith("//") or "\\" in target:
            target = "/"
        if chosen not in LOCALES:
            return _redirect(target)
        return _redirect(
            target,
            (
                "Set-Cookie",
                f"{LOCALE_COOKIE}={chosen}; Path=/; Max-Age=31536000; SameSite=Strict; HttpOnly",
            ),
        )

    def _chrome(self, req: _Req, section: str) -> Chrome:
        return Chrome(self._actor, req.locale, self._csrf, req.target, section)

    # -- research ---------------------------------------------------------------------------------

    def _home(self, c: Any, req: _Req) -> Response:
        projects = self._projects(c)
        allowed = {p.project_id for p in projects}
        episodes = [e for e in self._opened_episodes(c) if e.project_id in allowed]
        return Response(
            "200 OK",
            pages.home_page(
                actor_id=self._actor,
                projects=projects,
                episodes=episodes,
                chrome=self._chrome(req, "episodes"),
            ),
        )

    def _new_run(
        self, c: Any, req: _Req, *, error: str | None = None, status: str = "200 OK"
    ) -> Response:
        return Response(
            status,
            pages.new_run_page(
                actor_id=self._actor,
                projects=self._projects(c),
                csrf=self._csrf,
                sensitivities=[s.value for s in SensitivityLabel],
                error=error,
                reasoner=self._reasoner_line(c, req.m),
                chrome=self._chrome(req, "new"),
            ),
        )

    def _reasoner_line(self, c: Any, m: Messages) -> pages.Html:
        try:
            runtime = load_active_runtime(c, self._secrets)
        except RuntimeUnavailable as unusable:
            return pages.e(m("new.reasoner.unusable", reason=str(unusable)))
        if runtime is None:
            return pages.e(m("new.reasoner.catalog"))
        return pages.h(
            '{} <a href="/runtime">{}</a>',
            m("new.reasoner.runtime", name=runtime.name),
            m("nav.runtime"),
        )

    def _create_run(self, c: Any, req: _Req, form: Form) -> Response:
        try:
            request = self._research_request(form, req.m)
        except FormError as refused:
            return self._new_run(c, req, error=str(refused), status="400 Bad Request")
        try:
            report, run_id = self._run(c, req, request)
        except ScientificReadRefused:
            # One sentence for every reason, as the CLI says it.
            return self._message(
                req,
                "403 Forbidden",
                req.m("msg.no_research"),
                req.m("msg.no_research_text", actor=self._actor, project=request.project_id),
            )
        self._record(c, run_id, report)
        return _redirect(f"/episodes/{_path(report.episode_id)}")

    def _episode(self, c: Any, req: _Req, episode_id: str) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(req, episode_id)
        runs = self._runs(c, opened.project_id, episode_id)
        recorded = {
            r.ordinal: r
            for r in SqlResearchReportStore(c).for_episode(
                project_id=opened.project_id, episode_id=episode_id
            )
        }
        runs = [dataclasses.replace(r, recorded=r.ordinal in recorded) for r in runs]
        chosen: RecordedReport | None = None
        wanted = req.query.get("run", [""])[0]
        if wanted.isdigit() and int(wanted) in recorded:
            chosen = recorded[int(wanted)]
        elif recorded:
            chosen = recorded[max(recorded)]
        report = self._authorized(c, chosen.report) if chosen is not None else None
        return Response(
            "200 OK",
            pages.episode_page(
                actor_id=self._actor,
                episode=opened.row,
                runs=runs,
                report=report,
                report_ordinal=chosen.ordinal if chosen is not None else None,
                csrf=self._csrf,
                # The episode's own state, as stored. Whether it may really continue is the
                # service's answer when the form is sent.
                continuable=opened.row.state not in ("COMPLETED", "ABANDONED"),
                chrome=self._chrome(req, "episodes"),
            ),
        )

    def _continue(self, c: Any, req: _Req, episode_id: str) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(req, episode_id)
        request = ResearchRequest(
            project_id=opened.project_id,
            actor_id=self._actor,
            goal="",
            documents=(),
            episode_id=episode_id,
        )
        try:
            report, run_id = self._run(c, req, request)
        except (ScientificReadRefused, EpisodeNotContinuable):
            return self._not_found(req, episode_id)
        except ContinuationRefused as refused:
            return self._message(
                req,
                "409 Conflict",
                req.m("ep.not_continued"),
                str(refused),
                back=f"/episodes/{_path(episode_id)}",
            )
        self._record(c, run_id, report)
        (ordinal,) = (
            r.ordinal
            for r in self._runs(c, opened.project_id, episode_id)
            if r.research_run_id == run_id
        )
        return _redirect(f"/episodes/{_path(episode_id)}?run={ordinal}")

    def _markdown(self, c: Any, req: _Req, episode_id: str, ordinal: int) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(req, episode_id)
        for recorded in SqlResearchReportStore(c).for_episode(
            project_id=opened.project_id, episode_id=episode_id
        ):
            if recorded.ordinal == ordinal:
                text = render_markdown(self._authorized(c, recorded.report))
                return Response(
                    "200 OK", text.encode("utf-8"), content_type="text/markdown; charset=utf-8"
                )
        return self._message(
            req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_recorded_run")
        )

    # -- the service, unchanged -----------------------------------------------------------------

    def _run(self, c: Any, req: _Req, request: ResearchRequest) -> tuple[EpisodeReport, str]:
        """`ResearchEpisodeService.run`, observing only which research run id it minted, reasoned
        by the active runtime -- or refused, before anything is written, if it cannot be used."""
        reasoning = self._reasoning(c, req)
        minted: list[str] = []

        def mint(kind: str) -> str:
            value = new_id(kind)
            if kind == "research_run":
                minted.append(value)
            return value

        service = ResearchEpisodeService(
            connection=c,
            artifact_store=self._artifacts,
            vertical_factory=self._factory,
            mint=mint,
            reasoning=reasoning,
        )
        report = service.run(request)
        if len(minted) != 1:  # pragma: no cover - the service mints one per run
            raise RuntimeError(f"the research service minted {len(minted)} research run ids")
        return report, minted[0]

    def _reasoning(self, c: Any, req: _Req) -> ReasoningRuntime | None:
        try:
            return load_active_runtime(c, self._secrets)
        except RuntimeUnavailable as unusable:
            raise _Refused(
                self._message(
                    req, "409 Conflict", req.m("msg.runtime_unusable.title"), str(unusable)
                )
            ) from None

    def _record(self, c: Any, research_run_id: str, report: EpisodeReport) -> None:
        # `012d` refuses a report that is not this run's: episode, project, actor, the outcome the
        # ledger recorded for it, and the run's own id in its provenance.
        SqlResearchReportStore(c).record(research_run_id, report, at=utc_now())

    def _research_request(self, form: Form, m: Messages) -> ResearchRequest:
        project = form.value("project")
        goal = form.value("goal")
        if not project:
            raise FormError(m("msg.choose_project"))
        if not goal:
            raise FormError(m("msg.needs_goal"))
        documents: list[InputDocument] = []
        for field, trust_class in _DOCUMENT_KINDS.items():
            for upload in form.uploads(field):
                suffix = Path(upload.filename).suffix.lower()
                documents.append(
                    InputDocument(
                        name=upload.filename or "unnamed",
                        data=upload.data,
                        media_type=_MEDIA_TYPES.get(suffix, "application/octet-stream"),
                        uri=f"workspace-upload:{quote(upload.filename or 'unnamed')}",
                        trust_class=trust_class,
                    )
                )
        verification = None
        devices = form.uploads("verification_input")
        if devices:
            verification = (devices[0].filename or "verification input", devices[0].data)
        literature = None
        corpus_uploads = form.uploads("literature_corpus")
        query = form.value("literature_query")
        if corpus_uploads or query:
            if not (corpus_uploads and query):
                raise FormError(m("msg.literature_together"))
            if form.value("literature_query_public") != "yes":
                raise FormError(m("msg.literature_public"))
            literature = self._literature(corpus_uploads[0], query, m)
        sensitivity = form.value("sensitivity") or SensitivityLabel.INTERNAL.value
        if sensitivity not in {s.value for s in SensitivityLabel}:
            raise FormError(m("msg.unknown_classification", value=repr(sensitivity)))
        return ResearchRequest(
            project_id=project,
            actor_id=self._actor,
            goal=goal,
            documents=tuple(documents),
            verification_input=verification,
            literature=literature,
            sensitivity=SensitivityLabel(sensitivity),
            symptom=form.value("symptom") or None,
            expected_behavior=form.value("expected") or None,
            observed_behavior=form.value("observed") or None,
        )

    @staticmethod
    def _literature(corpus: Any, query: str, m: Messages) -> LiteratureRequest:
        # A provider package, not a DomainPack: `interfaces -> tool_providers` is permitted.
        from lab_brain.tool_providers.literature import LiteratureCorpusAdapter
        from lab_brain.tool_providers.literature import declaration as literature_declaration

        try:
            papers = json.loads(corpus.data.decode("utf-8"))["papers"]
        except (ValueError, KeyError, TypeError) as exc:
            raise FormError(m("msg.not_corpus", name=corpus.filename)) from exc
        return LiteratureRequest(
            adapter=LiteratureCorpusAdapter(papers, now=utc_now),
            declaration=literature_declaration(),
            query=query,
            description=f"the local literature corpus file {corpus.filename} (no network)",
        )

    # -- LLM settings -----------------------------------------------------------------------------

    def _llm(self, c: Any) -> LLMSettings:
        return LLMSettings(c, secrets=self._secrets, actor_id=self._actor)

    def _require_researcher(self, c: Any, req: _Req) -> None:
        if not self._projects(c):
            raise _Refused(
                self._message(
                    req,
                    "403 Forbidden",
                    req.m("msg.no_research"),
                    req.m("home.no_projects", actor=self._actor),
                )
            )

    def _overview(self, c: Any, req: _Req, *, error: str | None = None) -> Response:
        llm = self._llm(c)
        registry = llm.registry
        connections = registry.connections()
        models = registry.models()
        runtimes = registry.runtimes()
        bindings = {
            r.runtime_id: {
                slot: (registry.model(b.model_profile_id) or _missing()).model_name
                for slot, b in registry.bindings(r.runtime_id).items()
            }
            for r in runtimes
        }
        verified = {
            m.model_profile_id: registry.verified_capabilities(m.model_profile_id) for m in models
        }
        drafts = [r for r in runtimes if r.state in ("ACTIVE", "DRAFT")]
        ready = any(llm.readiness(r.runtime_id).ready for r in drafts[:1])
        progress = (
            bool(connections),
            bool(models),
            any(m.lifecycle in ("TESTED", "LOCKED") for m in models),
            any(m.lifecycle == "LOCKED" for m in models),
            any(bindings[r.runtime_id] for r in runtimes),
            ready or any(r.state == "ACTIVE" for r in runtimes),
            any(r.state == "ACTIVE" for r in runtimes),
        )
        data = settings_pages.Overview(
            connections=connections,
            health={x.connection_id: registry.latest_health(x.connection_id) for x in connections},
            models=models,
            verified=verified,
            runtimes=runtimes,
            bindings=bindings,
            secure_store=self._secrets.secure_store,
            progress=progress,
        )
        return Response(
            "409 Conflict" if error else "200 OK",
            settings_pages.overview_page(self._chrome(req, "llm"), data, error=error),
        )

    def _add_connection(self, c: Any, req: _Req, form: Form) -> Response:
        try:
            created = self._llm(c).add_connection(
                name=form.value("name"),
                base_url=form.value("base_url"),
                reach=form.value("reach"),
                secret_mode=form.value("secret_mode") or "none",
                env_name=form.value("env_name"),
                # Read, used, and never echoed back into any page.
                secret_value=form.value("secret_value"),
            )
        except SettingsRefused as refused:
            return self._overview(c, req, error=str(refused))
        return _redirect(f"/settings/llm/connections/{_path(created.connection_id)}")

    def _connection_route(
        self, c: Any, req: _Req, connection_id: str, action: str | None
    ) -> Response:
        llm = self._llm(c)
        connection = llm.registry.connection(connection_id)
        if connection is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        here = f"/settings/llm/connections/{_path(connection_id)}"
        form = req.form
        try:
            if action is None and req.method == "GET":
                return self._connection_page(c, req, connection_id)
            if form is None or req.method != "POST":
                raise SettingsRefused(req.m("msg.no_page"))
            if action == "health":
                llm.check_health(connection_id)
            elif action == "fetch":
                llm.fetch_models(connection_id)
            elif action == "declare":
                model = llm.declare_model(connection_id, form.value("model_name"))
                return _redirect(f"/settings/llm/models/{_path(model.model_profile_id)}")
            elif action == "lifecycle":
                llm.set_connection_lifecycle(connection_id, form.value("lifecycle"))
            elif action == "secret":
                llm.replace_secret(
                    connection_id,
                    secret_mode=form.value("secret_mode") or "none",
                    env_name=form.value("env_name"),
                    secret_value=form.value("secret_value"),
                )
            else:
                raise SettingsRefused(req.m("msg.no_page"))
        except SettingsRefused as refused:
            return self._connection_page(c, req, connection_id, error=str(refused))
        return _redirect(here)

    def _connection_page(
        self, c: Any, req: _Req, connection_id: str, *, error: str | None = None
    ) -> Response:
        registry = self._llm(c).registry
        connection = registry.connection(connection_id)
        assert connection is not None
        return Response(
            "409 Conflict" if error else "200 OK",
            settings_pages.connection_page(
                self._chrome(req, "llm"),
                connection,
                registry.health(connection_id, limit=20),
                registry.models(connection_id),
                secure_store=self._secrets.secure_store,
                error=error,
            ),
        )

    def _model_route(self, c: Any, req: _Req, model_id: str, action: str | None) -> Response:
        llm = self._llm(c)
        if llm.registry.model(model_id) is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        form = req.form
        try:
            if action is None and req.method == "GET":
                return self._model_page(c, req, model_id)
            if form is None or req.method != "POST":
                raise SettingsRefused(req.m("msg.no_page"))
            if action == "test":
                wanted = [
                    Capability(v) for v in form.fields.get("capabilities", ()) if v in Capability
                ]
                llm.test_model(model_id, wanted or None)
            elif action == "lock":
                llm.lock(model_id)
            elif action == "unlock":
                llm.unlock(model_id)
            elif action == "retire":
                llm.retire_model(model_id)
            else:
                raise SettingsRefused(req.m("msg.no_page"))
        except SettingsRefused as refused:
            return self._model_page(c, req, model_id, error=str(refused))
        return _redirect(f"/settings/llm/models/{_path(model_id)}")

    def _model_page(
        self, c: Any, req: _Req, model_id: str, *, error: str | None = None
    ) -> Response:
        registry = self._llm(c).registry
        model = registry.model(model_id)
        assert model is not None
        connection = registry.connection(model.connection_id)
        assert connection is not None
        history = c.execute(
            "SELECT probe_id, model_profile_id, capability, outcome, probe_version,"
            " response_digest, latency_ms, detail, probed_at FROM llm_capability_probes"
            " WHERE model_profile_id = %s ORDER BY probed_at DESC, probe_id DESC LIMIT 40",
            (model_id,),
        ).fetchall()
        return Response(
            "409 Conflict" if error else "200 OK",
            settings_pages.model_page(
                self._chrome(req, "llm"),
                model,
                connection,
                registry.latest_probes(model_id),
                [ProbeRow(*r) for r in history],
                error=error,
            ),
        )

    def _create_runtime(self, c: Any, req: _Req, form: Form) -> Response:
        try:
            runtime = self._llm(c).create_runtime(
                form.value("name"), form.fields.get("external_labels", ())
            )
        except SettingsRefused as refused:
            return self._overview(c, req, error=str(refused))
        return _redirect(f"/settings/llm/runtimes/{_path(runtime.runtime_id)}")

    def _runtime_route(self, c: Any, req: _Req, runtime_id: str, action: str | None) -> Response:
        llm = self._llm(c)
        if llm.registry.runtime(runtime_id) is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        form = req.form
        here = f"/settings/llm/runtimes/{_path(runtime_id)}"
        try:
            if action is None and req.method == "GET":
                return self._runtime_page(c, req, runtime_id)
            if form is None or req.method != "POST":
                raise SettingsRefused(req.m("msg.no_page"))
            if action in ("bind", "unbind"):
                try:
                    slot = LogicalSlot(form.value("slot"))
                except ValueError:
                    raise SettingsRefused(form.value("slot")) from None
                if action == "bind":
                    llm.bind(runtime_id, slot, form.value("model"))
                else:
                    llm.unbind(runtime_id, slot)
            elif action == "check":
                return self._runtime_page(c, req, runtime_id, live=True)
            elif action == "activate":
                llm.activate(runtime_id)
            elif action == "retire":
                llm.retire_runtime(runtime_id)
            else:
                raise SettingsRefused(req.m("msg.no_page"))
        except SettingsRefused as refused:
            return self._runtime_page(c, req, runtime_id, error=str(refused))
        return _redirect(here)

    def _runtime_page(
        self,
        c: Any,
        req: _Req,
        runtime_id: str,
        *,
        error: str | None = None,
        live: bool = False,
    ) -> Response:
        llm = self._llm(c)
        registry = llm.registry
        runtime = registry.runtime(runtime_id)
        assert runtime is not None
        readiness = llm.readiness(runtime_id, live=live)
        connections = {x.connection_id: x for x in registry.connections()}
        eligible: dict[LogicalSlot, list[tuple[ModelRow, str]]] = {}
        ineligible: dict[LogicalSlot, list[tuple[ModelRow, str]]] = {}
        for model in registry.models():
            if model.lifecycle != "LOCKED":
                continue
            conn = connections[model.connection_id]
            proven = set(model.locked_capabilities or ())
            for slot in BINDABLE_SLOTS:
                missing = sorted({x.value for x in SLOT_REQUIREMENTS[slot]} - proven)
                reason = (
                    f"not proven: {', '.join(missing)}"
                    if missing
                    else f"connection {conn.name} is {conn.lifecycle}"
                    if conn.lifecycle != "ENABLED"
                    else "PRIVATE_LOCAL needs a LOCAL connection"
                    if slot is LogicalSlot.PRIVATE_LOCAL and conn.reach != "LOCAL"
                    else ""
                )
                bucket = ineligible if reason else eligible
                bucket.setdefault(slot, []).append((model, reason or conn.name))
        return Response(
            "409 Conflict" if error else "200 OK",
            settings_pages.runtime_page(
                self._chrome(req, "llm"),
                runtime,
                readiness,
                eligible,
                ineligible,
                error=error,
            ),
        )

    def _active_runtime(self, c: Any, req: _Req) -> Response:
        llm = self._llm(c)
        active = llm.registry.active_runtime()
        unusable = None
        if active is not None:
            try:
                load_active_runtime(c, self._secrets)
            except RuntimeUnavailable as problem:
                unusable = str(problem)
        return Response(
            "200 OK",
            settings_pages.active_runtime_page(
                self._chrome(req, "runtime"),
                llm.readiness(active.runtime_id) if active is not None else None,
                unusable=unusable,
            ),
        )

    # -- reads, scoped to this actor --------------------------------------------------------------

    def _gate(self, c: Any) -> Any:
        return IngestionService(connection=c, artifact_store=self._artifacts).read_gate()

    def _projects(self, c: Any) -> list[pages.ProjectRow]:
        """The projects the read gate admits this actor to, now."""
        rows = c.execute(
            "SELECT p.project_id, p.name FROM project_memberships m"
            " JOIN projects p ON p.project_id = m.project_id"
            " WHERE m.actor_id = %s ORDER BY p.project_id",
            (self._actor,),
        ).fetchall()
        gate = self._gate(c)
        return [
            pages.ProjectRow(str(r[0]), str(r[1]))
            for r in rows
            if gate.authorize_project(actor_id=self._actor, project_id=str(r[0])).allowed
        ]

    def _opened_episodes(self, c: Any) -> list[pages.EpisodeRow]:
        rows = c.execute(
            "SELECT e.episode_id, e.project_id, e.trace_id, e.goal, e.state, e.outcome_status,"
            " e.suspend_reason, e.start_time, e.end_time,"
            " (SELECT count(*) FROM research_runs x WHERE x.episode_id = e.episode_id)"
            " FROM research_runs r JOIN research_episodes e ON e.episode_id = r.episode_id"
            " WHERE r.ordinal = 1 AND r.actor_id = %s ORDER BY e.start_time DESC",
            (self._actor,),
        ).fetchall()
        return [_episode_row(r) for r in rows]

    def _opened(self, c: Any, episode_id: str) -> _Opened | None:
        """The episode, if THIS actor opened it and may still act in its project. One scoped read;
        every miss is the same `None`."""
        row = c.execute(
            "SELECT e.episode_id, e.project_id, e.trace_id, e.goal, e.state, e.outcome_status,"
            " e.suspend_reason, e.start_time, e.end_time,"
            " (SELECT count(*) FROM research_runs x WHERE x.episode_id = e.episode_id)"
            " FROM research_runs r JOIN research_episodes e ON e.episode_id = r.episode_id"
            " WHERE r.episode_id = %s AND r.ordinal = 1 AND r.actor_id = %s",
            (episode_id, self._actor),
        ).fetchone()
        if row is None:
            return None
        episode = _episode_row(row)
        if (
            not self._gate(c)
            .authorize_project(actor_id=self._actor, project_id=episode.project_id)
            .allowed
        ):
            return None
        return _Opened(episode.project_id, episode)

    def _runs(self, c: Any, project_id: str, episode_id: str) -> list[pages.RunRow]:
        rows = c.execute(
            "SELECT ordinal, research_run_id, actor_id, started_at, finished_at, outcome"
            " FROM research_runs WHERE project_id = %s AND episode_id = %s ORDER BY ordinal",
            (project_id, episode_id),
        ).fetchall()
        return [
            pages.RunRow(int(r[0]), str(r[1]), str(r[2]), r[3], r[4], r[5], recorded=False)
            for r in rows
        ]

    def _authorized(self, c: Any, report: EpisodeReport) -> EpisodeReport:
        """The stored report, with every evidence excerpt re-authorized against the actor's
        CURRENT clearance: a report is kept, a clearance is not."""
        gate = self._gate(c)
        external = SqlExternalSourceStore(c)
        lines: list[EvidenceLine] = []
        for line in report.evidence:
            row = c.execute(
                "SELECT source_artifact_id FROM attestations"
                " WHERE attestation_id = %s AND project_id = %s",
                (line.attestation_id, report.project_id),
            ).fetchone()
            artifact = (
                row[0]
                if row is not None and row[0]
                else external.snapshot_artifact_of_attestation(
                    line.attestation_id, report.project_id
                )
            )
            readable = (
                artifact is not None
                and gate.authorize_artifact(
                    actor_id=self._actor, project_id=report.project_id, artifact_id=str(artifact)
                ).allowed
            )
            lines.append(line if readable else dataclasses.replace(line, excerpt=WITHHELD))
        return dataclasses.replace(report, evidence=tuple(lines))

    # -- answers ----------------------------------------------------------------------------------

    def _message(
        self, req: _Req, status: str, title: str, message: str, back: str = "/"
    ) -> Response:
        return Response(
            status,
            pages.message_page(
                actor_id=self._actor,
                title=title,
                message=message,
                back=back,
                chrome=self._chrome(req, ""),
            ),
        )

    def _not_found(self, req: _Req, episode_id: str) -> Response:
        # The same words for an unknown id, another project's episode and a colleague's.
        return self._message(
            req,
            "404 Not Found",
            req.m("ep.not_found.title"),
            req.m("ep.not_found", episode=episode_id, actor=self._actor),
        )

    @staticmethod
    def _forbidden() -> Response:
        return Response(
            "403 Forbidden",
            b"This request did not come from this workspace's own form.",
            content_type="text/plain; charset=utf-8",
        )


def _token() -> str:
    return secrets.token_urlsafe(32)


def _missing() -> ModelRow:  # pragma: no cover - a binding's model is a foreign key
    raise RuntimeError("a binding names a model that does not exist")


def _path(identifier: str) -> str:
    """An id as a URL path segment. `:` stays readable; everything else unsafe is encoded."""
    return quote(identifier, safe=":")


def _episode_row(r: Sequence[Any]) -> pages.EpisodeRow:
    return pages.EpisodeRow(
        episode_id=str(r[0]),
        project_id=str(r[1]),
        trace_id=str(r[2]),
        goal=str(r[3]),
        state=str(r[4]),
        outcome_status=r[5],
        suspend_reason=r[6],
        start_time=r[7],
        end_time=r[8],
        runs=int(r[9]),
    )


def allowed_hosts(host: str, port: int) -> tuple[str, ...]:
    """The Host header values a workspace bound to `host:port` answers to."""
    names = LOOPBACK if host in LOOPBACK or host == "::1" else (host,)
    return tuple(f"{name}:{port}" for name in names)


__all__ = [
    "LOCALE_COOKIE",
    "LOOPBACK",
    "MAX_UPLOAD_BYTES",
    "WITHHELD",
    "Response",
    "Workspace",
    "allowed_hosts",
]
