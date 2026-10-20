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

TWO AUTHORITIES OVER LANGUAGE MODELS (`012f`). LLM settings -- connections, models, locks,
runtimes, bindings -- are deployment configuration: open only to an actor the operator granted LLM
administration, and project membership grants none of it. Whether a PROJECT's evidence may reach
an external model route is that project's own policy (`/projects/<id>/egress`), declared by a
member holding its `LLM_EGRESS` approval scope; the active runtime supplies routes, never that
permission.

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

import base64
import binascii
import copy
import dataclasses
import hmac
import json
import os
import re
import secrets
import shutil
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from lab_brain.accounts.mail import Mailer
from lab_brain.accounts.oversight import EPISODE_REPORTS, Oversight, access_log
from lab_brain.accounts.passwords import (
    DEFAULT_COST,
    ScryptCost,
    keyed_digest,
    normalized_email,
    token_hash,
)
from lab_brain.accounts.projects import LABELS, LabProjects
from lab_brain.accounts.service import (
    SESSION_LIFETIME,
    Account,
    AccountRefused,
    AccountService,
)
from lab_brain.composition import IngestionService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.interfaces.cli import _DOCUMENT_KINDS, _MEDIA_TYPES
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.review_cli import _packet
from lab_brain.interfaces.web import (
    account_pages,
    admin_pages,
    credential_forms,
    egress_pages,
    lab_pages,
    llm_guide,
    pages,
    settings_pages,
    workspace_pages,
)
from lab_brain.interfaces.web.forms import Form, FormError, Upload, read_form
from lab_brain.interfaces.web.i18n import DEFAULT_LOCALE, LOCALES, Messages
from lab_brain.interfaces.web.pages import Chrome
from lab_brain.interfaces.web.workspace_pages import kind_key
from lab_brain.llm_runtime.authority import (
    LLM_EGRESS_SCOPE,
    AuthorityRefused,
    ProjectEgressPolicies,
)
from lab_brain.llm_runtime.capabilities import (
    BINDABLE_SLOTS,
    SLOT_REQUIREMENTS,
    Capability,
    roles_on,
)
from lab_brain.llm_runtime.provider import (
    DOCKER_HOST_GATEWAY,
    OpenAICompatibleClient,
    ProviderError,
)
from lab_brain.llm_runtime.readiness import hypothesis_fit_problem
from lab_brain.llm_runtime.registry import ModelRow, ProbeRow, RuntimeRow, SqlLLMRegistry
from lab_brain.llm_runtime.runtime import (
    DEFAULT_INFERENCE_DEADLINE_S,
    EXTERNAL_LABELS,
    LLMSettings,
    RuntimeUnavailable,
    SettingsRefused,
    checked_deadline,
    load_active_runtime,
)
from lab_brain.llm_runtime.secrets import DirectoryCredentialStore, SecretStore
from lab_brain.research.confirmation import confirmation_verifier
from lab_brain.research.continuation import (
    ContinuationRefused,
    EpisodeNotContinuable,
    SqlResearchRunStore,
)
from lab_brain.research.data import (
    MATERIAL_KINDS,
    DataItem,
    LabelNotCleared,
    NewFile,
    ResearchData,
    UsableData,
)
from lab_brain.research.episode_view import load_episode_view
from lab_brain.research.literature import LiteratureRequest
from lab_brain.research.reasoning import ReasoningRuntime
from lab_brain.research.render import render_markdown, render_recorded_since
from lab_brain.research.report import EpisodeReport, EvidenceLine
from lab_brain.research.report_store import RecordedReport, SqlResearchReportStore
from lab_brain.research.service import (
    InputDocument,
    ProjectData,
    ResearchEpisodeService,
    ResearchRequest,
)
from lab_brain.research.vertical import VerticalFactory
from lab_brain.security.reviewer_identity import ReviewerTrust
from lab_brain.storage.artifacts.interface import ArtifactStoreError
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.surface.disclosure import ErrorNotFound

#: The largest request body the workspace reads (all uploads of one run together).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: Host names a loopback-bound workspace answers to.
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")

#: The interface-language cookie. Its value is only ever compared against `LOCALES`.
LOCALE_COOKIE = "lb_locale"

#: With accounts: the session cookie (a random token; the database keeps its SHA-256), and
#: the signed-out browser's cookie its sign-in form's CSRF token is bound to.
SESSION_COOKIE = "lb_session"
ANONYMOUS_COOKIE = "lb_anon"

_ID = r"([A-Za-z0-9:_.\-]{1,200})"
_EPISODE_PATH = re.compile(rf"^/episodes/{_ID}$")
_CONTINUE_PATH = re.compile(rf"^/episodes/{_ID}/continue$")
_MARKDOWN_PATH = re.compile(rf"^/episodes/{_ID}/runs/([0-9]{{1,6}})/report\.md$")
_CONNECTION_PATH = re.compile(rf"^/settings/llm/connections/{_ID}(?:/([a-z]+))?$")
_MODEL_PATH = re.compile(rf"^/settings/llm/models/{_ID}(?:/([a-z]+))?$")
_RUNTIME_PATH = re.compile(rf"^/settings/llm/runtimes/{_ID}(?:/([a-z]+))?$")
_EGRESS_PATH = re.compile(rf"^/projects/{_ID}/egress$")
_PROJECT_PATH = re.compile(rf"^/projects/{_ID}$")
_MEMBERS_PATH = re.compile(rf"^/projects/{_ID}/members(?:/(remove|change))?$")
_ADMIN_ACCOUNT_PATH = re.compile(rf"^/admin/accounts/{_ID}$")
_ADMIN_ACTION_PATH = re.compile(
    rf"^/admin/accounts/{_ID}/(approve|reject|suspend|reactivate|role)$"
)
_ADMIN_PROJECT_PATH = re.compile(rf"^/admin/projects/{_ID}$")
_ADMIN_EPISODE_PATH = re.compile(rf"^/admin/episodes/{_ID}$")
_ADMIN_EXPORT_PATH = re.compile(rf"^/admin/episodes/{_ID}/runs/([0-9]{{1,6}})/report\.md$")
_ADMIN_MATERIAL_PATH = re.compile(rf"^/admin/projects/{_ID}/artifacts/{_ID}$")

#: Where a form posted to a collection path came from.
_POSTED_FROM = {
    "/runs": "/runs/new",
    "/runs/new": "/runs/new",
    "/runs/review": "/runs/new",
    "/data": "/data",
    "/status/check": "/status",
    "/settings/llm/assign": "/settings/llm",
    "/settings/llm/connections": "/settings/llm",
    "/settings/llm/runtimes": "/settings/llm",
}

#: The media type of an upload whose suffix is none the ingestion knows: the CLI's, so the one
#: authoritative path reads it the same way from both (and says why when it cannot).
_UNKNOWN_MEDIA = "application/octet-stream"

#: The one place a settings form may ask to be sent back to: the guided overview. Anything else a
#: form names is ignored -- a `next` field is never a redirect to wherever it says.
_OVERVIEW = "/settings/llm"

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
            if _EGRESS_PATH.match(self.path):
                return self.path
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


@dataclass(frozen=True)
class AccountsConfig:
    """Sign-in for a laboratory (`lab-brain web --accounts`).

    `mailer` None: mail fails closed -- registration and password reset are refused.
    `base_url` is what emailed links point at. `cookie_secure`: the workspace is reached over
    HTTPS (behind a TLS-terminating proxy), so its cookies are sent only over HTTPS.
    `answer_floor`: seconds a registration or a reset request takes at least, whatever the
    address -- so how long the work took (a new account's writes, a message to a real
    address) does not tell whether the address has an account."""

    mailer: Mailer | None
    base_url: str
    cookie_secure: bool = False
    cost: ScryptCost = DEFAULT_COST
    answer_floor: float = 1.0


class _Refused(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response


class Workspace:
    def __init__(
        self,
        *,
        actor_id: str | None = None,
        settings: Settings,
        connect: Callable[[Settings], Any],
        artifact_root: Path,
        vertical_factory: VerticalFactory,
        allowed_hosts: Iterable[str],
        csrf_token: str | None = None,
        secrets: SecretStore | None = None,
        default_locale: str = DEFAULT_LOCALE,
        local_hosts: Iterable[str] = (),
        ollama_url: str | None = None,
        credential_dir: Path | None = None,
        inference_deadline: float | None = None,
        accounts: AccountsConfig | None = None,
    ) -> None:
        # One of two trust models: one researcher, named at start-up (no login, loopback
        # only), or a laboratory's accounts, where each request is the person it signs in.
        if (actor_id is None) == (accounts is None):
            raise ValueError("a workspace serves one named actor or its accounts, not both")
        self._actor = actor_id or ""
        self._accounts_config = accounts
        self._account: Account | None = None
        self._session_token = ""
        #: Binds each form's CSRF token to its session (or signed-out browser): a token one
        #: person sees is useless in another's browser. Per process, never stored.
        self._csrf_key = os.urandom(32)
        #: How many competing hypotheses this deployment's research asks for: read once from its
        #: vertical (`ResearchEpisodeService.hypothesis_minimum`), then given to the settings
        #: service (what ROLE_HYPOTHESIS is probed at) and to the runtime loader (what a model on
        #: REASONING_PRIMARY must have demonstrated).
        self._hypotheses: int | None = None
        #: The deployment's inference deadline (`--inference-deadline`): the capability probes
        #: this workspace runs and the research calls its active runtime makes are held to it.
        self._deadline = checked_deadline(
            DEFAULT_INFERENCE_DEADLINE_S if inference_deadline is None else inference_deadline
        )
        #: Host names besides loopback that are this machine (the container deployment's Docker
        #: host): a model there may be declared LOCAL.
        self._local_hosts = tuple(local_hosts)
        #: This machine's Ollama, offered as the local model: the container host's when the
        #: deployment says the workspace runs in a container, else this machine's loopback.
        ollama_host = (
            DOCKER_HOST_GATEWAY if DOCKER_HOST_GATEWAY in self._local_hosts else "127.0.0.1"
        )
        self._ollama_url = (ollama_url or f"http://{ollama_host}:11434/v1").rstrip("/")
        self._settings = settings
        self._connect = connect
        self._artifact_root = artifact_root.resolve()
        self._artifacts = LocalArtifactStore(self._artifact_root)
        self._factory = vertical_factory
        self._hosts = frozenset(allowed_hosts)
        self._csrf = csrf_token or _token()
        # A pasted key goes to the deployment's credential directory when it names one (the
        # container deployment), else to the operating system's store where there is one.
        if secrets is None:
            secrets = (
                SecretStore(credentials=DirectoryCredentialStore(credential_dir))
                if credential_dir is not None
                else SecretStore()
            )
        self._secrets = secrets
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
        if self._accounts_config is not None:
            return self._respond_with_accounts(environ, method, path, query, locale)
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
        if path == "/healthz" and method == "GET":
            # For the container health check: the database answers. Nothing about any actor.
            try:
                connection.execute("SELECT 1").fetchone()
            finally:
                connection.close()
            return Response("200 OK", b"ok", content_type="text/plain; charset=utf-8")
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
        if path == "/data" and method == "GET":
            return self._data(c, req)
        if path == "/data" and method == "POST" and form is not None:
            return self._add_data(c, req, form)
        if path == "/episodes" and method == "GET":
            return self._episodes(c, req)
        if path == "/status" and method == "GET":
            return self._status(c, req)
        if path == "/status/check" and method == "POST":
            self._require_llm_admin(c, req)
            return self._recheck(c, req)
        if path == "/runs/new" and method == "GET":
            return self._new_run(c, req)
        if path == "/runs/new" and method == "POST" and form is not None:
            return self._switch_project(c, req, form)
        if path == "/runs/review" and method == "POST" and form is not None:
            return self._review(c, req, form)
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
        if m := _EGRESS_PATH.match(path):
            if method == "GET":
                return self._egress(c, req, m.group(1))
            if method == "POST" and form is not None:
                return self._declare_egress(c, req, m.group(1), form)
        if path.startswith("/settings/llm"):
            self._require_llm_admin(c, req)
            if path == "/settings/llm" and method == "GET":
                return self._overview(c, req)
            if path == "/settings/llm/connections" and method == "POST" and form is not None:
                return self._add_connection(c, req, form)
            if path == "/settings/llm/runtimes" and method == "POST" and form is not None:
                return self._create_runtime(c, req, form)
            if path == "/settings/llm/assign" and method == "POST" and form is not None:
                return self._assign(c, req, form)
            if path == "/settings/llm/ollama" and method == "POST" and form is not None:
                return self._add_ollama(c, req, form)
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
        target = _local_target(form.value("next"))
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
        if self._accounts_config is None:
            return Chrome(self._actor, req.locale, self._csrf, req.target, section)
        if self._account is None:
            return Chrome("", req.locale, self._csrf, req.target, section, signed_out=True)
        return Chrome(
            self._actor,
            req.locale,
            self._csrf,
            req.target,
            section,
            account_name=self._account.display_name,
            admin=self._account.is_admin,
        )

    # -- research ---------------------------------------------------------------------------------

    def _home(self, c: Any, req: _Req) -> Response:
        projects = self._projects(c)
        allowed = {p.project_id for p in projects}
        episodes = [e for e in self._opened_episodes(c) if e.project_id in allowed]
        recent: list[tuple[pages.ProjectRow, DataItem]] = []
        for project in projects:
            recent.extend((project, item) for item in self._data_items(c, project.project_id))
        recent.sort(key=lambda pair: (pair[1].submitted_at, pair[1].item_id), reverse=True)
        return Response(
            "200 OK",
            workspace_pages.home_page(
                self._chrome(req, "home"),
                projects=projects,
                recent=recent,
                counts=workspace_pages.DataCounts.of([item for _p, item in recent]),
                episodes=episodes,
                ai=self._ai_status(c, req.m),
                capabilities=self._capabilities(c),
            ),
        )

    def _episodes(self, c: Any, req: _Req) -> Response:
        names = {p.project_id: p.name for p in self._projects(c)}
        episodes = [e for e in self._opened_episodes(c) if e.project_id in names]
        return Response(
            "200 OK",
            workspace_pages.episodes_page(
                self._chrome(req, "episodes"), episodes=episodes, projects=names
            ),
        )

    # -- research data ----------------------------------------------------------------------------

    def _research_data(self, c: Any) -> ResearchData:
        return ResearchData(connection=c, artifact_store=self._artifacts)

    def _data_items(self, c: Any, project_id: str) -> list[DataItem]:
        try:
            return self._research_data(c).items(project_id=project_id, actor_id=self._actor)
        except ScientificReadRefused:  # pragma: no cover - the gate admitted the project just now
            return []

    def _cleared(self, c: Any, project_id: str) -> frozenset[str]:
        """The labels this actor may declare -- and read -- in the project."""
        held = self._research_data(c).clearance(project_id=project_id, actor_id=self._actor)
        return frozenset(label.value for label in held)

    def _chosen_project(
        self, c: Any, projects: Sequence[pages.ProjectRow], wanted: str
    ) -> pages.ProjectRow | None:
        """The project asked for if the gate admits this actor to it; with none asked for, the one
        whose research data arrived last (else the first) -- never a project the actor may not
        see."""
        asked = next((p for p in projects if p.project_id == wanted), None)
        if asked is not None or wanted or len(projects) < 2:
            return asked or (projects[0] if projects else None)
        latest = {
            p.project_id: max(i.submitted_at for i in items)
            for p in projects
            if (items := self._data_items(c, p.project_id))
        }
        dated = [p for p in projects if p.project_id in latest]
        return max(dated, key=lambda p: latest[p.project_id]) if dated else projects[0]

    def _data(
        self,
        c: Any,
        req: _Req,
        *,
        project_id: str = "",
        error: str | None = None,
        status: str = "200 OK",
    ) -> Response:
        projects = self._projects(c)
        project = self._chosen_project(c, projects, project_id or req.query.get("project", [""])[0])
        items = self._data_items(c, project.project_id) if project is not None else []
        data = self._research_data(c)
        # Why an item failed: the M1 message catalog's own summary, authorized as `explain` is.
        reasons: dict[str, tuple[str, ...]] = {}
        for item in items:
            sentences = []
            for error_id in item.error_ids:
                with suppress(ErrorNotFound):
                    code, summary = data.explain(
                        error_id,
                        project_id=project.project_id if project else "",
                        actor_id=self._actor,
                    )
                    sentences.append(workspace_pages.reason(code, summary, req.m))
            if sentences:
                reasons[item.item_id] = tuple(sentences)
        added = [x for x in req.query.get("added", [""])[0].split(",") if x] if not error else []
        return Response(
            status,
            workspace_pages.data_page(
                self._chrome(req, "data"),
                projects=projects,
                project=project,
                items=items,
                reasons=reasons,
                sensitivities=[s.value for s in reversed(SensitivityLabel)],
                cleared=self._cleared(c, project.project_id) if project else frozenset(),
                added=added,
                error=error,
            ),
        )

    def _add_data(self, c: Any, req: _Req, form: Form) -> Response:
        m = req.m
        project_id = form.value("project")
        if project_id not in {p.project_id for p in self._projects(c)}:
            return self._message(
                req,
                "403 Forbidden",
                m("msg.no_research"),
                m("msg.no_research_text", actor=self._actor, project=project_id),
            )
        try:
            files, kind, sensitivity = self._new_files(
                form,
                "files",
                "kind",
                "sensitivity",
                kind_error=m("data.need.kind"),
                sensitivity_error=m("data.need.sensitivity"),
            )
            if not files:
                raise FormError(m("data.need.files"))
            assert kind is not None and sensitivity is not None
            added = self._research_data(c).add(
                project_id=project_id,
                actor_id=self._actor,
                files=files,
                kind=kind,
                sensitivity=sensitivity,
            )
        except FormError as refused:
            return self._data(
                c, req, project_id=project_id, error=str(refused), status="400 Bad Request"
            )
        except LabelNotCleared as refused:
            return self._data(
                c,
                req,
                project_id=project_id,
                error=m("data.not_cleared", label=m(f"sens.{refused.label.value}")),
                status="403 Forbidden",
            )
        # Post/Redirect/Get: reloading the page shows the result again, it never imports twice.
        return _redirect(f"/data?project={quote(project_id)}&added={quote(','.join(added))}#result")

    @staticmethod
    def _new_files(
        form: Form,
        field: str,
        kind_field: str,
        sensitivity_field: str,
        *,
        kind_error: str,
        sensitivity_error: str,
    ) -> tuple[list[NewFile], TrustClass | None, SensitivityLabel | None]:
        """The files of a form and what the researcher DECLARED them to be. With files, both
        declarations are required: nothing is defaulted, nothing is guessed from the file."""
        files = [
            NewFile(
                name=u.filename,
                data=u.data,
                media_type=_MEDIA_TYPES.get(Path(u.filename).suffix.lower(), _UNKNOWN_MEDIA),
            )
            for u in form.uploads(field)
            if u.filename
        ]
        if not files:
            return [], None, None
        kind = form.value(kind_field)
        if kind not in MATERIAL_KINDS:
            raise FormError(kind_error)
        label = form.value(sensitivity_field)
        if label not in {s.value for s in SensitivityLabel}:
            raise FormError(sensitivity_error)
        return files, MATERIAL_KINDS[kind], SensitivityLabel(label)

    # -- new research: question, project, data, files, sources -> confirm -> start -----------

    @staticmethod
    def _draft(form: Form | None) -> workspace_pages.Draft:
        if form is None:
            return workspace_pages.Draft()
        return workspace_pages.Draft(
            goal=form.value("goal"),
            sensitivity=form.value("sensitivity"),
            symptom=form.value("symptom"),
            expected=form.value("expected"),
            observed=form.value("observed"),
            chosen={a: form.value(f"kind:{a}") for a in form.fields.get("use", ())},
            literature_query=form.value("literature_query"),
            literature_public=form.value("literature_query_public") == "yes",
        )

    def _new_run(
        self,
        c: Any,
        req: _Req,
        *,
        project_id: str = "",
        draft: workspace_pages.Draft | None = None,
        error: str | None = None,
        status: str = "200 OK",
    ) -> Response:
        projects = self._projects(c)
        project = self._chosen_project(c, projects, project_id or req.query.get("project", [""])[0])
        usable = (
            self._research_data(c).usable(project_id=project.project_id, actor_id=self._actor)
            if project is not None
            else []
        )
        return Response(
            status,
            workspace_pages.new_research_page(
                self._chrome(req, "new"),
                projects=projects,
                project=project,
                usable=usable,
                sensitivities=[s.value for s in reversed(SensitivityLabel)],
                cleared=self._cleared(c, project.project_id) if project else frozenset(),
                reasoner=self._reasoner_line(c, req.m),
                draft=draft or workspace_pages.Draft(),
                error=error,
            ),
        )

    def _switch_project(self, c: Any, req: _Req, form: Form) -> Response:
        """The researcher switched project on the new-research form: what they typed is kept;
        what they ticked is kept only if the project is the same -- another project's data is
        never carried across."""
        draft = self._draft(form)
        wanted = form.value("switch_to") or form.value("project")
        if wanted != form.value("project"):
            draft = dataclasses.replace(draft, chosen={})
        return self._new_run(c, req, project_id=wanted, draft=draft)

    def _review(self, c: Any, req: _Req, form: Form) -> Response:
        """Step 6: import any new files as research data, then show exactly what the research
        would use. Nothing is reasoned until the researcher starts it."""
        m = req.m
        project_id = form.value("project")
        project = next((p for p in self._projects(c) if p.project_id == project_id), None)
        if project is None:
            return self._message(
                req,
                "403 Forbidden",
                m("msg.no_research"),
                m("msg.no_research_text", actor=self._actor, project=project_id),
            )
        data = self._research_data(c)
        draft = self._draft(form)
        new_ids: list[str] = []
        try:
            # Everything is checked before anything is written: a refusal leaves no row behind.
            if not draft.goal:
                raise FormError(m("msg.needs_goal"))
            if draft.sensitivity not in {s.value for s in SensitivityLabel}:
                raise FormError(m("new.need.goal_sensitivity"))
            if draft.sensitivity not in self._cleared(c, project_id):
                raise FormError(m("new.goal.not_cleared", label=m(f"sens.{draft.sensitivity}")))
            usable = {
                u.artifact_id: u for u in data.usable(project_id=project_id, actor_id=self._actor)
            }
            chosen = self._chosen_data(form, m, usable)
            files, kind, label = self._new_files(
                form,
                "files",
                "files_kind",
                "files_sensitivity",
                kind_error=m("new.need.files_kind"),
                sensitivity_error=m("new.need.files_sensitivity"),
            )
            literature = self._carry_literature(form, m)
            devices = form.uploads("verification_input")
            verification = _carry(devices[0]) if devices else None
            if files:
                assert kind is not None and label is not None
                new_ids = data.add(
                    project_id=project_id,
                    actor_id=self._actor,
                    files=files,
                    kind=kind,
                    sensitivity=label,
                )
        except FormError as refused:
            return self._new_run(
                c,
                req,
                project_id=project_id,
                draft=draft,
                error=str(refused),
                status="400 Bad Request",
            )
        except LabelNotCleared as refused:
            return self._new_run(
                c,
                req,
                project_id=project_id,
                draft=draft,
                error=m("data.not_cleared", label=m(f"sens.{refused.label.value}")),
                status="403 Forbidden",
            )
        added: list[DataItem] = []
        excluded: list[DataItem] = []
        same_as: dict[str, str] = {}
        fresh: set[str] = set()
        if new_ids:
            items = {i.item_id: i for i in data.items(project_id=project_id, actor_id=self._actor)}
            usable = {
                u.artifact_id: u for u in data.usable(project_id=project_id, actor_id=self._actor)
            }
            assert kind is not None
            for item_id in new_ids:
                item = items[item_id]
                added.append(item)
                if item.artifact_id is None or item.artifact_id not in usable:
                    excluded.append(item)
                    continue
                if item.duplicate_of is not None:
                    # The same bytes are already in the project: THAT artifact is used, once.
                    same_as[item.artifact_id] = item.name
                else:
                    fresh.add(item.artifact_id)
                chosen.setdefault(item.artifact_id, kind_key(kind.value) or "note")
        selected = [
            workspace_pages.Selected(
                artifact_id=artifact_id,
                name=usable[artifact_id].name,
                kind=chosen_kind,
                sensitivity=usable[artifact_id].sensitivity,
                state=usable[artifact_id].state.value,
                new=artifact_id in fresh,
                same_as=same_as.get(artifact_id),
            )
            for artifact_id, chosen_kind in chosen.items()
        ]
        return Response(
            "200 OK",
            workspace_pages.review_page(
                self._chrome(req, "new"),
                project=project,
                draft=dataclasses.replace(draft, chosen=chosen),
                selected=selected,
                added=added,
                excluded=excluded,
                literature=literature,
                verification=verification,
                reasoner=self._reasoner_line(c, m),
                egress=self._egress_line(c, project_id, m),
                simulation=m("home.sim.none")
                if self._capabilities(c).blocked
                else m("home.sim.all"),
            ),
        )

    def _carry_literature(self, form: Form, m: Messages) -> workspace_pages.Carried | None:
        """The literature file and its query, checked as the start will check them, carried to
        the confirmation as the bytes that were sent."""
        uploads = form.uploads("literature_corpus")
        query = form.value("literature_query")
        if not uploads and not query:
            return None
        if not (uploads and query):
            raise FormError(m("msg.literature_together"))
        if form.value("literature_query_public") != "yes":
            raise FormError(m("msg.literature_public"))
        self._literature(uploads[0], query, m)
        return _carry(uploads[0])

    @staticmethod
    def _chosen_data(form: Form, m: Messages, usable: Mapping[str, UsableData]) -> dict[str, str]:
        """The project data a form selected, each with the kind the researcher chose for it.
        Only this project's usable data; a kind for each, or the form is refused."""
        chosen: dict[str, str] = {}
        for artifact_id in form.fields.get("use", ()):
            item = usable.get(artifact_id)
            if item is None:
                raise FormError(m("new.not_usable", name=artifact_id))
            key = form.value(f"kind:{artifact_id}")
            if key not in MATERIAL_KINDS:
                raise FormError(m("new.need.kind", name=item.name))
            chosen[artifact_id] = key
        return chosen

    def _reasoner_line(self, c: Any, m: Messages) -> pages.Html:
        try:
            runtime = self._load_runtime(c)
        except RuntimeUnavailable as unusable:
            return pages.e(m("new.reasoner.unusable", reason=str(unusable)))
        if runtime is None:
            return pages.e(m("new.reasoner.catalog"))
        return pages.h(
            '{} <a href="/runtime">{}</a>',
            m("new.reasoner.runtime", name=runtime.name),
            m("ai.detail"),
        )

    def _egress_line(self, c: Any, project_id: str, m: Messages) -> pages.Html:
        """Whether this project's evidence could leave, in the researcher's words."""
        if not self._external_routes(c):
            return pages.e(m("lbl.egress.local"))
        policies = ProjectEgressPolicies(c)
        connections = {x.connection_id: x for x in self._llm(c).registry.connections()}
        return pages.h(
            '{}: {} <a href="/projects/{}/egress">{}</a>',
            m("llm.egress"),
            egress_pages.summary(
                policies.current(project_id),
                policies.privacy_mode(project_id) or "PRIVATE",
                connections,
                m,
            ),
            project_id,
            m("eg.link"),
        )

    # -- the system's state -----------------------------------------------------------------------

    def _ai_status(self, c: Any, m: Messages) -> workspace_pages.AiStatus:
        llm = self._llm(c)
        admin = llm.is_administrator
        active = llm.registry.active_runtime()
        if active is None:
            return workspace_pages.AiStatus(
                m("ai.none"), m("ai.next.admin") if admin else m("ai.next.member"), admin
            )
        try:
            self._load_runtime(c)
        except RuntimeUnavailable as unusable:
            return workspace_pages.AiStatus(
                m("ai.unusable", name=active.name, reason=str(unusable)),
                m("ai.next.fix") if admin else m("ai.next.member"),
                admin,
                problem=True,
                configured=True,
            )
        return workspace_pages.AiStatus(
            m("ai.active", name=active.name), m("ai.next.ok"), admin, configured=True
        )

    def _capabilities(self, c: Any) -> workspace_pages.Capabilities:
        domain, backends, blocked = ResearchEpisodeService(
            connection=c, artifact_store=self._artifacts, vertical_factory=self._factory
        ).capabilities()
        return workspace_pages.Capabilities(
            domain,
            backends,
            [(b.capability_id, b.action_type, b.reason, b.requires) for b in blocked],
        )

    def _status(self, c: Any, req: _Req) -> Response:
        m = req.m
        projects = self._projects(c)
        llm = self._llm(c)
        policies = ProjectEgressPolicies(c)
        connections = llm.registry.connections()
        by_id = {x.connection_id: x for x in connections}
        capabilities = self._capabilities(c)
        parts: list[workspace_pages.Part] = []

        applied = c.execute("SELECT count(*) FROM schema_migrations").fetchone()
        parts.append(
            workspace_pages.Part(
                m("st.db"),
                "ok",
                pages.e(m("st.db.ok", n=int(applied[0]) if applied else 0)),
                f"schema_migrations={applied[0] if applied else 0}",
            )
        )
        root = self._artifact_root
        writable = root.is_dir() and os.access(root, os.W_OK)
        free = shutil.disk_usage(root).free if root.is_dir() else 0
        parts.append(
            workspace_pages.Part(
                m("st.storage"),
                "ok" if writable else "problem",
                pages.e(m("st.storage.ok", free=_size(free)))
                if writable
                else pages.e(m("st.storage.problem")),
                f"{root} writable={writable} free={free}",
            )
        )
        counts = [
            (p, workspace_pages.DataCounts.of(self._data_items(c, p.project_id))) for p in projects
        ]
        parts.append(
            workspace_pages.Part(
                m("st.data"),
                "ok",
                pages.h(
                    "{}{}",
                    pages.cat(
                        pages.h(
                            '<div><a href="/data?project={}">{}</a></div>',
                            p.project_id,
                            m("st.data.row", project=p.name, **vars(n)),
                        )
                        for p, n in counts
                    ),
                    pages.h('<div class="warn-line">{}</div>', m("st.data.attention"))
                    if any(n.attention for _p, n in counts)
                    else pages.Html(""),
                ),
            )
        )
        ai = self._ai_status(c, m)
        parts.append(
            workspace_pages.Part(
                m("st.ai"),
                "problem" if ai.problem else ("ok" if ai.configured else "missing"),
                pages.h(
                    '{}<div class="purpose">{} {}</div>', ai.sentence, m("home.next"), ai.next_step
                ),
            )
        )
        for reach, key in (("LOCAL", "st.local"), ("EXTERNAL", "st.external")):
            mine = [x for x in connections if x.reach == reach and x.lifecycle == "ENABLED"]
            if not mine:
                parts.append(workspace_pages.Part(m(key), "missing", pages.e(m(f"{key}.none"))))
                continue
            lines = []
            healthy = False
            for conn in mine:
                health = llm.registry.latest_health(conn.connection_id)
                problem = llm.credential_problem(conn)
                if health is None:
                    lines.append(m("st.local.never", name=conn.name))
                    continue
                healthy = healthy or (health.outcome == "REACHABLE" and problem is None)
                lines.append(
                    m(
                        "st.local.row",
                        name=conn.name,
                        outcome=m(f"llm.h.{health.outcome}"),
                        at=workspace_pages.status_when(health.checked_at),
                    )
                )
            parts.append(
                workspace_pages.Part(
                    m(key),
                    "ok" if healthy else "problem",
                    pages.cat(pages.h("<div>{}</div>", x) for x in lines),
                    "; ".join(f"{x.name} {x.base_url}" for x in mine),
                )
            )
        parts.append(
            workspace_pages.Part(
                m("st.sim"),
                "limit" if capabilities.blocked else "ok",
                pages.e(m("st.sim.cannot", why=m("st.sim.why")))
                if capabilities.blocked
                else pages.e(m("st.sim.can")),
                f"domain={capabilities.domain} blocked={len(capabilities.blocked)}",
            )
        )
        parts.append(
            workspace_pages.Part(
                m("st.checks"),
                "ok",
                pages.e(m("st.checks.ok", n=len(capabilities.backends))),
                ", ".join(sorted(capabilities.backends)),
            )
        )
        return Response(
            "200 OK",
            workspace_pages.status_page(
                self._chrome(req, "status"),
                parts=parts,
                capabilities=capabilities,
                egress=[
                    (
                        p.project_id,
                        p.name,
                        egress_pages.summary(
                            policies.current(p.project_id),
                            policies.privacy_mode(p.project_id) or "PRIVATE",
                            by_id,
                            m,
                        ),
                    )
                    for p in projects
                ],
                admin=llm.is_administrator,
                technical=self._accounts_config is None
                or (self._account is not None and self._account.is_admin),
            ),
        )

    def _recheck(self, c: Any, req: _Req) -> Response:
        """Ask every enabled model connection whether it answers, and record it. Administration:
        a health check is recorded, so it is the settings service's -- which refuses a
        non-administrator before anything is sent."""
        llm = self._llm(c)
        for conn in llm.registry.connections():
            if conn.lifecycle == "ENABLED":
                with suppress(SettingsRefused):
                    llm.check_health(conn.connection_id)
        return _redirect("/status")

    def _create_run(self, c: Any, req: _Req, form: Form) -> Response:
        project_id = form.value("project")
        allowed = {p.project_id for p in self._projects(c)}
        if project_id and project_id not in allowed:
            # Authorization first: one sentence for every reason, before the form is read.
            return self._message(
                req,
                "403 Forbidden",
                req.m("msg.no_research"),
                req.m("msg.no_research_text", actor=self._actor, project=project_id),
            )
        usable: dict[str, UsableData] = {}
        if form.fields.get("use") and project_id in allowed:
            usable = {
                u.artifact_id: u
                for u in self._research_data(c).usable(project_id=project_id, actor_id=self._actor)
            }
        try:
            request = self._research_request(form, req.m, usable)
            # The same rule as the confirmation step: the question's level is one this actor
            # holds in the project, or it could not read its own question back.
            asked = request.sensitivity
            if asked is None or asked.value not in self._cleared(c, request.project_id):
                level = asked.value if asked is not None else ""
                raise FormError(req.m("new.goal.not_cleared", label=req.m(f"sens.{level}")))
        except FormError as refused:
            return self._new_run(
                c,
                req,
                project_id=project_id,
                draft=self._draft(form),
                error=str(refused),
                status="400 Bad Request",
            )
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

    def _confirmation_verifier(self, c: Any) -> Any:
        """The reuse check the research service applies, for showing what relies on what."""
        vertical = self._factory(outputs=None, jobs=None, broker=None, now=utc_now)
        return confirmation_verifier(
            c,
            trust=ReviewerTrust.configured_at(self._settings.review_authorities),
            declaration_sets=vertical.declaration_sets,
            active=vertical.active_declarations,
            authority_policies=vertical.authority_policies,
        )

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
        # What the stored records say each executed check meant -- read, in the episode's own
        # project, which `_opened` has just authorised this actor for.
        view = load_episode_view(
            c,
            project_id=opened.project_id,
            episode_id=episode_id,
            verify=self._confirmation_verifier(c),
        )
        return Response(
            "200 OK",
            pages.episode_page(
                actor_id=self._actor,
                episode=opened.row,
                runs=runs,
                report=report,
                view=view,
                report_ordinal=chosen.ordinal if chosen is not None else None,
                csrf=self._csrf,
                # The episode's own state, as stored. Whether it may really continue is the
                # service's answer when the form is sent.
                continuable=opened.row.state not in ("COMPLETED", "ABANDONED"),
                # Opened before `012q`: continuing asks for the question's classification.
                declare_label=(
                    self._cleared(c, opened.project_id)
                    if SqlResearchRunStore(c).question_label(
                        project_id=opened.project_id, episode_id=episode_id
                    )
                    is None
                    else None
                ),
                chrome=self._chrome(req, "episodes"),
                project_name={p.project_id: p.name for p in self._projects(c)}.get(
                    opened.project_id
                ),
            ),
        )

    def _continue(self, c: Any, req: _Req, episode_id: str) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(req, episode_id)
        # A continuation carries the question's recorded classification (`012q`). An episode
        # opened before one was recorded continues only under one declared here, at a
        # level this actor holds -- the same rule as opening research.
        declared = req.form.value("sensitivity") if req.form is not None else ""
        if declared and (
            declared not in {s.value for s in SensitivityLabel}
            or declared not in self._cleared(c, opened.project_id)
        ):
            return self._message(
                req,
                "409 Conflict",
                req.m("ep.not_continued"),
                req.m("new.goal.not_cleared", label=req.m(f"sens.{declared}"))
                if declared in {s.value for s in SensitivityLabel}
                else req.m("msg.unknown_classification", value=repr(declared)),
                back=f"/episodes/{_path(episode_id)}",
            )
        request = ResearchRequest(
            project_id=opened.project_id,
            actor_id=self._actor,
            goal="",
            documents=(),
            episode_id=episode_id,
            sensitivity=SensitivityLabel(declared) if declared else None,
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
                # The report as its run wrote it, then what the record says about its
                # conclusions now: a flag recorded since must travel with the export.
                view = load_episode_view(
                    c,
                    project_id=opened.project_id,
                    episode_id=episode_id,
                    verify=self._confirmation_verifier(c),
                )
                text += render_recorded_since(view.conclusions)
                name = re.sub(r"[^A-Za-z0-9._-]+", "-", episode_id).strip("-")
                return Response(
                    "200 OK",
                    text.encode("utf-8"),
                    content_type="text/markdown; charset=utf-8",
                    headers=(
                        ("Content-Disposition", f'inline; filename="{name}-run-{ordinal}.md"'),
                    ),
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
            reviewer_trust=ReviewerTrust.configured_at(self._settings.review_authorities),
        )
        report = service.run(request)
        if len(minted) != 1:  # pragma: no cover - the service mints one per run
            raise RuntimeError(f"the research service minted {len(minted)} research run ids")
        return report, minted[0]

    def _load_runtime(self, c: Any) -> ReasoningRuntime | None:
        """The active runtime, judged under THIS deployment's declaration of which hosts are this
        machine (`--host-gateway`). Every page and the research path load it here, so none of them
        can load it without the declaration -- `load_active_runtime` requires it, and a host the
        deployment did not declare is refused there, before a credential is read."""
        return load_active_runtime(
            c,
            self._secrets,
            local_hosts=self._local_hosts,
            inference_deadline=self._deadline,
            hypothesis_minimum=self._hypothesis_minimum(c),
        )

    def _reasoning(self, c: Any, req: _Req) -> ReasoningRuntime | None:
        try:
            return self._load_runtime(c)
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

    def _research_request(
        self, form: Form, m: Messages, usable: Mapping[str, UsableData]
    ) -> ResearchRequest:
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
        # A file the confirmation carried is the bytes the researcher confirmed; a file sent with
        # the form (the direct form, or a client of it) is read as sent. Either is checked here.
        verification = None
        devices = [*_uncarry(form, "verification", m), *form.uploads("verification_input")]
        if devices:
            verification = (devices[0].filename or "verification input", devices[0].data)
        literature = None
        corpus_uploads = [
            *_uncarry(form, "literature_corpus", m),
            *form.uploads("literature_corpus"),
        ]
        query = form.value("literature_query")
        if corpus_uploads or query:
            if not (corpus_uploads and query):
                raise FormError(m("msg.literature_together"))
            if form.value("literature_query_public") != "yes":
                raise FormError(m("msg.literature_public"))
            literature = self._literature(corpus_uploads[0], query, m)
        # Declared, never defaulted: a request that does not say how sensitive the question is
        # is refused rather than filed under a label nobody chose.
        sensitivity = form.value("sensitivity")
        if not sensitivity:
            raise FormError(m("new.need.goal_sensitivity"))
        if sensitivity not in {s.value for s in SensitivityLabel}:
            raise FormError(m("msg.unknown_classification", value=repr(sensitivity)))
        chosen = self._chosen_data(form, m, usable)
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
            project_data=tuple(
                ProjectData(
                    artifact_id=artifact_id,
                    name=usable[artifact_id].name,
                    trust_class=MATERIAL_KINDS[key],
                )
                for artifact_id, key in chosen.items()
            ),
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

    def _hypothesis_minimum(self, c: Any) -> int:
        if self._hypotheses is None:
            self._hypotheses = ResearchEpisodeService(
                connection=c, artifact_store=self._artifacts, vertical_factory=self._factory
            ).hypothesis_minimum()
        return self._hypotheses

    def _unfit(self, c: Any, registry: SqlLLMRegistry) -> llm_guide.Unfit:
        """Why a confirmed model that proved what a use needs still cannot serve it here -- its
        lock was made under earlier test rules, or it demonstrated fewer competing hypotheses than
        this deployment's research asks for -- so the pages do not offer it (readiness and the
        runtime boundary refuse it regardless)."""
        required = self._hypothesis_minimum(c)
        stale = {
            m.model_profile_id
            for m in registry.models()
            if m.lifecycle == "LOCKED" and registry.lock_problem(m) is not None
        }

        def unfit(model: ModelRow, slot: LogicalSlot) -> str | None:
            if model.model_profile_id in stale:
                return "confirmed under earlier test rules; test it again and confirm it again"
            short = hypothesis_fit_problem(registry, model, slot, required)
            return short.removeprefix(f"model {model.model_name} ") if short else None

        return unfit

    def _llm(self, c: Any) -> LLMSettings:
        return LLMSettings(
            c,
            secrets=self._secrets,
            actor_id=self._actor,
            local_hosts=self._local_hosts,
            inference_deadline=self._deadline,
            hypothesis_minimum=self._hypothesis_minimum(c),
        )

    def _require_llm_admin(self, c: Any, req: _Req) -> None:
        """LLM settings are deployment administration (`012f`): membership of a project -- of
        every project -- grants none of it. Refused before anything is read or written. With
        accounts, only an active administrator holds it."""
        signed_in_admin = self._account is not None and self._account.is_admin
        if self._accounts_config is not None and not signed_in_admin:
            raise _Refused(
                self._message(
                    req, "403 Forbidden", req.m("msg.not_llm_admin.title"), req.m("admin.llm_only")
                )
            )
        if not self._llm(c).is_administrator:
            raise _Refused(
                self._message(
                    req,
                    "403 Forbidden",
                    req.m("msg.not_llm_admin.title"),
                    req.m("msg.not_llm_admin", actor=self._actor),
                )
            )

    # -- a project's own external-model egress ----------------------------------------------------

    def _egress(self, c: Any, req: _Req, project_id: str, *, error: str | None = None) -> Response:
        view = self._egress_view(c, project_id)
        if view is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        return Response(
            "409 Conflict" if error else "200 OK",
            egress_pages.egress_page(self._chrome(req, "status"), view, error=error),
        )

    def _declare_egress(self, c: Any, req: _Req, project_id: str, form: Form) -> Response:
        # The database decides who may declare (`012f`). A refusal re-renders the page, which an
        # actor the gate does not admit to the project gets as the unknown-project 404: nothing
        # about who belongs where.
        withdraw = form.value("withdraw") == "yes"
        try:
            ProjectEgressPolicies(c).declare(
                project_id,
                actor_id=self._actor,
                connection_ids=() if withdraw else form.fields.get("connections", ()),
                labels=() if withdraw else form.fields.get("labels", ()),
                at=utc_now(),
            )
        except AuthorityRefused as refused:
            return self._egress(c, req, project_id, error=str(refused))
        return _redirect(f"/projects/{_path(project_id)}/egress")

    def _egress_view(self, c: Any, project_id: str) -> egress_pages.EgressView | None:
        """The project's egress, for an actor the read gate admits to it -- else `None`."""
        admitted = {p.project_id: p for p in self._projects(c)}
        project = admitted.get(project_id)
        if project is None:
            return None
        row = c.execute(
            "SELECT p.privacy_mode, m.sensitivity_clearance, m.approval_scopes"
            " FROM projects p JOIN project_memberships m ON m.project_id = p.project_id"
            " WHERE p.project_id = %s AND m.actor_id = %s AND m.active",
            (project_id, self._actor),
        ).fetchone()
        if row is None:  # pragma: no cover - the gate just admitted this membership
            return None
        registry = self._llm(c).registry
        return egress_pages.EgressView(
            project_id=project_id,
            project_name=project.name,
            privacy_mode=str(row[0]),
            history=ProjectEgressPolicies(c).history(project_id),
            connections={x.connection_id: x for x in registry.connections()},
            routes=self._external_routes(c),
            may_declare=LLM_EGRESS_SCOPE in (row[2] or ()),
            clearance=[x for x in EXTERNAL_LABELS if x in set(row[1] or ())],
        )

    def _external_routes(self, c: Any) -> list[str]:
        """The connection ids of the active runtime's EXTERNAL routes."""
        registry = self._llm(c).registry
        active = registry.active_runtime()
        if active is None:
            return []
        ids = set()
        for binding in registry.bindings(active.runtime_id).values():
            model = registry.model(binding.model_profile_id)
            conn = registry.connection(model.connection_id) if model is not None else None
            if conn is not None and conn.reach == "EXTERNAL":
                ids.add(conn.connection_id)
        return sorted(ids)

    def _overview(self, c: Any, req: _Req, *, error: object = None) -> Response:
        llm = self._llm(c)
        registry = llm.registry
        connections = registry.connections()
        models = registry.models()
        runtimes = registry.runtimes()
        bound = {
            r.runtime_id: {
                slot: b.model_profile_id for slot, b in registry.bindings(r.runtime_id).items()
            }
            for r in runtimes
        }
        draft = next((r for r in runtimes if r.state == "DRAFT"), None)
        active_problem = None
        if registry.active_runtime() is not None:
            try:
                self._load_runtime(c)
            except RuntimeUnavailable as unusable:
                active_problem = str(unusable)
        guide = llm_guide.build(
            connections=connections,
            health={x.connection_id: registry.latest_health(x.connection_id) for x in connections},
            credential_problems={x.connection_id: llm.credential_problem(x) for x in connections},
            models=models,
            passed={
                x.model_profile_id: frozenset(
                    cap.value for cap in registry.verified_capabilities(x.model_profile_id)
                )
                for x in models
            },
            runtimes=runtimes,
            bindings=bound,
            readiness=llm.readiness(draft.runtime_id) if draft is not None else None,
            active_problem=active_problem,
            roles={slot: tuple(r.value for r in roles_on(slot)) for slot in BINDABLE_SLOTS},
            unfit=self._unfit(c, registry),
        )
        names = {x.model_profile_id: x.model_name for x in models}
        data = settings_pages.Overview(
            guide=guide,
            runtimes=runtimes,
            bindings={
                rid: {slot: names.get(mid, mid) for slot, mid in slots.items()}
                for rid, slots in bound.items()
            },
            secure_store=self._secrets.secure_store,
            store_protection=self._secrets.store_protection,
            ollama=self._ollama_state(connections),
        )
        return Response(
            "409 Conflict" if error else "200 OK",
            settings_pages.overview_page(self._chrome(req, "llm"), data, error=error),
        )

    def _ollama_state(self, connections: Sequence[Any]) -> credential_forms.OllamaState:
        """Whether this machine's Ollama answers right now -- one short model-list request to
        this machine, no credential -- and the connection already made to it, if any."""
        made = next(
            (
                x.name
                for x in connections
                if x.base_url.rstrip("/") == self._ollama_url and x.lifecycle != "RETIRED"
            ),
            None,
        )
        try:
            names = OpenAICompatibleClient(
                self._ollama_url, None, timeout=2.0, local_hosts=self._local_hosts
            ).list_models()
        except ProviderError:
            return credential_forms.OllamaState(self._ollama_url, False, 0, made)
        return credential_forms.OllamaState(self._ollama_url, True, len(names), made)

    @staticmethod
    def _back(form: Form, default: str, anchor: str = "") -> str:
        """Where a settings action returns: the guided overview when the form came from it (the
        only other place it may name), else the page of the thing it changed."""
        return f"{_OVERVIEW}{anchor}" if form.value("next") == _OVERVIEW else default

    def _refused(
        self, c: Any, req: _Req, form: Form | None, error: object, page: Callable[[], Response]
    ) -> Response:
        """A refused settings step answers on the page it was taken from."""
        if form is not None and form.value("next") == _OVERVIEW:
            return self._overview(c, req, error=error)
        return page()

    def _add_connection(self, c: Any, req: _Req, form: Form) -> Response:
        try:
            spec = (
                self._connection_spec(c, form, req.m)
                if form.value("provider")
                else {
                    "name": form.value("name"),
                    "base_url": form.value("base_url"),
                    "reach": form.value("reach"),
                    "secret_mode": form.value("secret_mode") or "none",
                    "env_name": form.value("env_name"),
                    # Read, used, and never echoed back into any page.
                    "secret_value": form.value("secret_value"),
                }
            )
            created = self._llm(c).add_connection(**spec)
        except SettingsRefused as refused:
            return self._overview(c, req, error=refused)
        if form.value("provider"):
            return _redirect(f"{_OVERVIEW}#c-{quote(created.connection_id, safe=':')}")
        return _redirect(f"/settings/llm/connections/{_path(created.connection_id)}")

    def _connection_spec(self, c: Any, form: Form, m: Messages) -> dict[str, str]:
        """The simple form -- provider, name, API key or a local model -- as the settings
        service's parameters. A preset only fills in the usual URL and reach; the service checks
        everything as it checks any connection (LOCAL only of this machine, and so on)."""
        preset = form.value("provider")
        if preset not in settings_pages.PROVIDERS:
            raise SettingsRefused(m("llm.bad_provider"))
        url, reach = settings_pages.PROVIDERS[preset]
        custom = form.value("base_url")
        if custom:
            url = custom
            reach = form.value("reach") or reach
        elif preset == "ollama":
            url = self._ollama_url
        if url is None:
            raise SettingsRefused(m("llm.need_url"))
        if preset == "ollama":
            # A local model takes no credential: whatever a form sent beside it is not read.
            secret_value = env_name = secret_ref = ""
            mode = "none"
        else:
            secret_value = form.value("secret_value")
            env_name = form.value("env_name")
            secret_ref = form.value("secret_ref")
            mode = _credential_mode(secret_value, env_name, secret_ref, m)
            if mode == "none" and preset != "custom":
                raise SettingsRefused(m("llm.need_key"), code="secret.needed")
        taken = {x.name for x in self._llm(c).registry.connections()}
        name = _slug(form.value("name")) or _free_name(preset, taken)
        return {
            "name": name,
            "base_url": url,
            "reach": reach,
            "secret_mode": mode,
            "env_name": env_name,
            "secret_value": secret_value,
            "secret_ref": secret_ref,
        }

    def _add_ollama(self, c: Any, req: _Req, form: Form) -> Response:
        """The local model in one step: this machine's Ollama -- checked to answer BEFORE anything
        is created -- made a LOCAL connection with no credential (made once; again it is reused),
        and its models fetched. The lifecycle from there is the ordinary one: test, confirm,
        assign, apply. The form has no credential field and none is read."""
        llm = self._llm(c)
        url = (form.value("base_url") or self._ollama_url).rstrip("/")
        try:
            try:
                OpenAICompatibleClient(
                    url, None, timeout=5.0, local_hosts=self._local_hosts
                ).list_models()
            except ProviderError:
                raise SettingsRefused(
                    f"this machine's Ollama does not answer at {url}", code="ollama.unreachable"
                ) from None
            connections = llm.registry.connections()
            made = next(
                (
                    x
                    for x in connections
                    if x.base_url.rstrip("/") == url and x.lifecycle != "RETIRED"
                ),
                None,
            )
            if made is None:
                made = llm.add_connection(
                    name=_free_name("ollama", {x.name for x in connections}),
                    base_url=url,
                    reach="LOCAL",
                    secret_mode="none",
                )
            llm.fetch_models(made.connection_id)
        except SettingsRefused as refused:
            return self._overview(c, req, error=refused)
        return _redirect(f"{_OVERVIEW}#c-{quote(made.connection_id, safe=':')}")

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
            elif action == "test":
                # From the guided overview: the model chosen in the connection's row.
                model = llm.registry.model(form.value("model_profile_id"))
                if model is None or model.connection_id != connection_id:
                    raise SettingsRefused(req.m("msg.no_page"))
                llm.test_model(model.model_profile_id)
            elif action == "declare":
                model = llm.declare_model(connection_id, form.value("model_name"))
                return _redirect(f"/settings/llm/models/{_path(model.model_profile_id)}")
            elif action == "lifecycle":
                llm.set_connection_lifecycle(connection_id, form.value("lifecycle"))
            elif action == "secret":
                if form.value("secret_mode"):
                    # The explicit form of the earlier page and of scripted clients.
                    mode = form.value("secret_mode")
                else:
                    mode = _credential_mode(
                        form.value("secret_value"),
                        form.value("env_name"),
                        form.value("secret_ref"),
                        req.m,
                    )
                    if mode == "none":
                        raise SettingsRefused(req.m("cred.replace.need"), code="secret.needed")
                llm.replace_secret(
                    connection_id,
                    secret_mode=mode,
                    env_name=form.value("env_name"),
                    secret_value=form.value("secret_value"),
                    secret_ref=form.value("secret_ref"),
                )
                # The connection check the researcher would run next, run now: the record then
                # says whether the NEW key is accepted, instead of still showing the refusal of
                # the old one and asking for a fix already made. It changes no lifecycle.
                llm.check_health(connection_id)
            else:
                raise SettingsRefused(req.m("msg.no_page"))
        except SettingsRefused as refused:
            problem = refused
            return self._refused(
                c,
                req,
                form,
                problem,
                lambda: self._connection_page(c, req, connection_id, error=problem),
            )
        assert form is not None
        return _redirect(self._back(form, here, f"#c-{quote(connection_id, safe=':')}"))

    def _connection_page(
        self, c: Any, req: _Req, connection_id: str, *, error: object = None
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
                store_protection=self._secrets.store_protection,
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
            problem = refused
            return self._refused(
                c,
                req,
                form,
                problem,
                lambda: self._model_page(c, req, model_id, error=problem),
            )
        model = llm.registry.model(model_id)
        anchor = f"#c-{quote(model.connection_id, safe=':')}" if model is not None else ""
        return _redirect(self._back(form, f"/settings/llm/models/{_path(model_id)}", anchor))

    def _model_page(self, c: Any, req: _Req, model_id: str, *, error: object = None) -> Response:
        registry = self._llm(c).registry
        model = registry.model(model_id)
        assert model is not None
        connection = registry.connection(model.connection_id)
        assert connection is not None
        history = c.execute(
            "SELECT probe_id, model_profile_id, capability, outcome, probe_version,"
            " response_digest, latency_ms, detail, probed_at, parameters FROM llm_capability_probes"
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
                stale=registry.lock_problem(model),
            ),
        )

    def _create_runtime(self, c: Any, req: _Req, form: Form) -> Response:
        try:
            runtime = self._llm(c).create_runtime(
                form.value("name"), form.fields.get("external_labels", ())
            )
        except SettingsRefused as refused:
            return self._overview(c, req, error=refused)
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
                if form.value("next") != _OVERVIEW:
                    return self._runtime_page(c, req, runtime_id, live=True)
                # From the overview: check live (recorded), then show the overview's list.
                llm.readiness(runtime_id, live=True)
            elif action == "activate":
                llm.activate(runtime_id)
            elif action == "retire":
                llm.retire_runtime(runtime_id)
            else:
                raise SettingsRefused(req.m("msg.no_page"))
        except SettingsRefused as refused:
            problem = refused
            return self._refused(
                c,
                req,
                form,
                problem,
                lambda: self._runtime_page(c, req, runtime_id, error=problem),
            )
        return _redirect(self._back(form, here, "#apply"))

    def _assign(self, c: Any, req: _Req, form: Form) -> Response:
        """Step 3 of the overview: a confirmed model to a use, in the configuration being
        prepared -- the newest DRAFT, or a new one started from the applied configuration (an
        ACTIVE configuration is never changed in place: `012e` binds only a DRAFT). The binding
        rules are the database's; this only finds the draft."""
        llm = self._llm(c)
        try:
            try:
                slot = LogicalSlot(form.value("slot"))
            except ValueError:
                raise SettingsRefused(form.value("slot")) from None
            if slot not in BINDABLE_SLOTS:
                raise SettingsRefused(slot.value)
            draft = self._draft_runtime(llm)
            if form.value("action") == "unassign":
                llm.unbind(draft.runtime_id, slot)
            else:
                llm.bind(draft.runtime_id, slot, form.value("model"))
        except SettingsRefused as refused:
            return self._overview(c, req, error=refused)
        return _redirect(f"{_OVERVIEW}#assign")

    @staticmethod
    def _draft_runtime(llm: LLMSettings) -> RuntimeRow:
        registry = llm.registry
        draft = next((r for r in registry.runtimes() if r.state == "DRAFT"), None)
        if draft is not None:
            return draft
        active = registry.active_runtime()
        # The most restrictive ceiling unless the applied configuration already allowed more:
        # an external route then carries PUBLIC evidence at most (each project's own policy and
        # each researcher's clearance still decide).
        draft = llm.create_runtime(
            f"config {utc_now().astimezone():%Y-%m-%d %H:%M:%S}",
            active.external_labels if active is not None else ["PUBLIC"],
        )
        if active is not None:
            for slot, binding in registry.bindings(active.runtime_id).items():
                with suppress(SettingsRefused):
                    llm.bind(draft.runtime_id, slot, binding.model_profile_id)
        return draft

    def _runtime_page(
        self,
        c: Any,
        req: _Req,
        runtime_id: str,
        *,
        error: object = None,
        live: bool = False,
    ) -> Response:
        llm = self._llm(c)
        registry = llm.registry
        runtime = registry.runtime(runtime_id)
        assert runtime is not None
        readiness = llm.readiness(runtime_id, live=live)
        connections = {x.connection_id: x for x in registry.connections()}
        unfit = self._unfit(c, registry)
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
                    else unfit(model, slot) or ""
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
                self._load_runtime(c)
            except RuntimeUnavailable as problem:
                unusable = str(problem)
        policies = ProjectEgressPolicies(c)
        connections = {x.connection_id: x for x in llm.registry.connections()}
        projects = [
            (
                p.project_id,
                p.name,
                egress_pages.summary(
                    policies.current(p.project_id),
                    policies.privacy_mode(p.project_id) or "PRIVATE",
                    connections,
                    req.m,
                ),
            )
            for p in self._projects(c)
        ]
        return Response(
            "200 OK",
            settings_pages.active_runtime_page(
                self._chrome(req, "status"),
                llm.readiness(active.runtime_id) if active is not None else None,
                unusable=unusable,
                admin=llm.is_administrator,
                projects=projects,
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

    # -- accounts ---------------------------------------------------------------------------------
    #
    # With `accounts` (`lab-brain web --accounts`), who a request is comes from its session cookie
    # and nothing else: the account it resolves to, re-read from the database on every request.
    # The request is then served by a per-request copy of this workspace whose actor is that
    # account's actor and whose CSRF token is bound to that session -- so every route below and
    # every existing one acts as the signed-in person, and a token one person sees in a form is
    # useless in another's browser. Signed out, only the sign-in pages answer.

    def _respond_with_accounts(
        self,
        environ: Mapping[str, Any],
        method: str,
        path: str,
        query: Mapping[str, Sequence[str]],
        locale: str,
    ) -> Response:
        assert self._accounts_config is not None
        cookies = _cookies(environ)
        session_token = cookies.get(SESSION_COOKIE, "")
        anonymous = cookies.get(ANONYMOUS_COOKIE, "")
        extra: list[tuple[str, str]] = []
        form: Form | None = None
        if method == "POST":
            origin = environ.get("HTTP_ORIGIN")
            if origin is not None and origin not in {f"http://{h}" for h in self._hosts} | {
                f"https://{h}" for h in self._hosts
            }:
                return self._forbidden()
            try:
                form = read_form(environ, limit=MAX_UPLOAD_BYTES)
            except FormError as refused:
                req = _Req(method, path, query, None, locale)
                return self._message(req, "400 Bad Request", req.m("msg.refused"), str(refused))
        elif method != "GET":
            return Response("405 Method Not Allowed", b"", headers=(("Allow", "GET, POST"),))
        connection = self._connect(self._settings)
        try:
            if path == "/healthz" and method == "GET":
                connection.execute("SELECT 1").fetchone()
                return Response("200 OK", b"ok", content_type="text/plain; charset=utf-8")
            connection.autocommit = True
            account = self._account_service(connection).session(session_token)
            if account is None:
                session_token = ""
                if not anonymous:
                    anonymous = _token()
                    extra.append(self._cookie(ANONYMOUS_COOKIE, anonymous, 86400))
                csrf = keyed_digest(self._csrf_key, "anonymous", anonymous)
            else:
                csrf = keyed_digest(self._csrf_key, "session", token_hash(session_token))
            view = copy.copy(self)
            view._csrf = csrf
            view._account = account
            view._actor = account.actor_id if account is not None else ""
            view._session_token = session_token
            req = _Req(method, path, query, form, locale)
            if form is not None and not hmac.compare_digest(form.value("csrf"), csrf):
                # Nothing of the form is acted on. Most often its session ended (it expired,
                # or the person signed out elsewhere) while the page stayed open: say so, and
                # offer the way back, instead of a bare refusal.
                stale = view._stale_form(environ, req)
                return dataclasses.replace(stale, headers=stale.headers + tuple(extra))
            try:
                response = view._account_route(connection, req)
                if response is None:
                    if account is None:
                        response = _redirect(f"/login?next={quote(req.target)}")
                    else:
                        response = view._route(connection, req)
            except _Refused as refused:
                response = refused.response
            return dataclasses.replace(response, headers=response.headers + tuple(extra))
        finally:
            connection.close()

    def _stale_form(self, environ: Mapping[str, Any], req: _Req) -> Response:
        if self._account is None:
            came_from = urlsplit(str(environ.get("HTTP_REFERER") or ""))
            back = "/"
            if came_from.netloc in self._hosts:
                back = _local_path(
                    came_from.path + (f"?{came_from.query}" if came_from.query else "")
                )
            return _redirect(f"/login?expired=1&next={quote(back)}")
        return self._message(
            req, "403 Forbidden", req.m("msg.refused"), req.m("acct.form_stale"), back=req.path
        )

    def _account_service(self, c: Any) -> AccountService:
        assert self._accounts_config is not None
        config = self._accounts_config
        return AccountService(c, mailer=config.mailer, base_url=config.base_url, cost=config.cost)

    def _cookie(self, name: str, value: str, max_age: int) -> tuple[str, str]:
        secure = "; Secure" if self._accounts_config and self._accounts_config.cookie_secure else ""
        return (
            "Set-Cookie",
            f"{name}={value}; Path=/; Max-Age={max_age}; SameSite=Strict; HttpOnly{secure}",
        )

    def _account_route(self, c: Any, req: _Req) -> Response | None:
        """The sign-in pages, a person's own account, projects, decisions and -- for an
        administrator -- the laboratory. None: an existing workspace route."""
        method, path, form = req.method, req.path, req.form
        if path == "/locale" and form is not None:
            return self._switch_locale(form)
        public = {
            "/login": (self._sign_in_form, self._sign_in),
            "/register": (self._register_form, self._register),
            "/verify": (self._verify_form, self._verify),
            "/password/forgot": (self._forgot_form, self._forgot),
            "/password/reset": (self._reset_form, self._reset),
        }
        if path in public:
            show, act = public[path]
            if method == "GET":
                if self._account is not None and path in ("/login", "/register"):
                    return _redirect("/")
                return show(c, req)
            if form is not None:
                started = time.monotonic()
                response = act(c, req, form)
                if path in ("/register", "/password/forgot"):
                    assert self._accounts_config is not None
                    floor = self._accounts_config.answer_floor
                    # ponytail: a blocking sleep holds a server thread; fine at a lab's volume.
                    time.sleep(max(0.0, floor - (time.monotonic() - started)))
                return response
        if path == "/logout" and method == "POST":
            self._account_service(c).sign_out(self._session_token)
            return _redirect("/login?signed_out=1", self._cookie(SESSION_COOKIE, "", 0))
        if self._account is None:
            return None
        if path == "/account" and method == "GET":
            return self._account_view(c, req)
        if path == "/account/password" and method == "POST" and form is not None:
            return self._change_password(c, req, form)
        if path == "/projects" and method == "GET":
            return self._lab_projects(c, req)
        if path == "/projects" and method == "POST" and form is not None:
            return self._create_project(c, req, form)
        if (m := _PROJECT_PATH.match(path)) and method == "GET":
            return self._project_overview(c, req, m.group(1))
        if (m := _MEMBERS_PATH.match(path)) and method == "POST" and form is not None:
            return self._change_members(c, req, m.group(1), m.group(2) or "add", form)
        if path == "/inbox" and method == "GET":
            return self._inbox(c, req)
        if path == "/admin" or path.startswith("/admin/"):
            if not self._account.is_admin:
                return self._message(
                    req, "403 Forbidden", req.m("msg.refused"), req.m("admin.only")
                )
            return self._admin_route(c, req)
        return None

    def _signed_out_chrome(self, req: _Req) -> Chrome:
        return Chrome("", req.locale, self._csrf, req.target, "", signed_out=True)

    # -- signing in -------------------------------------------------------------------------------

    def _sign_in_form(
        self, c: Any, req: _Req, *, error: str | None = None, email: str = ""
    ) -> Response:
        notice = None
        if req.query.get("signed_out"):
            notice = req.m("acct.signed_out")
        elif req.query.get("reset"):
            notice = req.m("acct.reset.done")
        elif req.query.get("expired"):
            notice = req.m("acct.expired")
        going = (req.query.get("next") or ["/"])[0]
        if req.form is not None:
            going = req.form.value("next") or "/"
        return Response(
            "200 OK" if error is None else "401 Unauthorized",
            account_pages.sign_in_page(
                self._signed_out_chrome(req),
                next_path=_local_path(going),
                error=error,
                notice=notice,
                email=email,
                no_admin=not self._account_service(c).has_admin(),
            ),
        )

    def _sign_in(self, c: Any, req: _Req, form: Form) -> Response:
        email = form.value("email")
        try:
            _account, token = self._account_service(c).sign_in(
                email=email, password=form.raw("password")
            )
        except AccountRefused as refused:
            return self._sign_in_form(
                c, req, error=account_pages.refusal(req.m, refused.code), email=email
            )
        return _redirect(
            _local_path(form.value("next") or "/"),
            self._cookie(SESSION_COOKIE, token, int(SESSION_LIFETIME.total_seconds())),
        )

    def _register_form(self, c: Any, req: _Req, **kw: Any) -> Response:
        closed = not self._account_service(c).mail_configured()
        return Response(
            "200 OK" if not kw.get("error") else "409 Conflict",
            account_pages.register_page(self._signed_out_chrome(req), closed=closed, **kw),
        )

    def _register(self, c: Any, req: _Req, form: Form) -> Response:
        email = form.value("email")
        try:
            self._account_service(c).register(email=email)
        except AccountRefused as refused:
            return self._register_form(
                c,
                req,
                error=account_pages.refusal(req.m, refused.code, refused.detail),
                email=email,
            )
        return Response(
            "200 OK",
            account_pages.notice_page(
                self._signed_out_chrome(req),
                title=req.m("acct.registered.title"),
                text=req.m("acct.registered"),
                link=("/login", req.m("acct.sign_in")),
            ),
        )

    def _verify_form(self, c: Any, req: _Req) -> Response:
        token = (req.query.get("token") or [""])[0]
        if self._account_service(c).token_purpose(token) != "VERIFY_EMAIL":
            return self._link_invalid(req, register=True)
        return Response(
            "200 OK", account_pages.verify_page(self._signed_out_chrome(req), token=token)
        )

    def _verify(self, c: Any, req: _Req, form: Form) -> Response:
        token, name = form.value("token"), form.value("name")
        service = self._account_service(c)
        if service.token_purpose(token) != "VERIFY_EMAIL":
            return self._link_invalid(req, register=True)

        def again(error: str) -> Response:
            # The link still works: nothing was consumed.
            return Response(
                "409 Conflict",
                account_pages.verify_page(
                    self._signed_out_chrome(req), token=token, name=name, error=error
                ),
            )

        if form.raw("password") != form.raw("repeat"):
            return again(req.m("acct.refused.passwords_differ"))
        try:
            service.verify_email(token, display_name=name, password=form.raw("password"))
        except AccountRefused as refused:
            if refused.code in ("weak_password", "invalid_name"):
                return again(account_pages.refusal(req.m, refused.code, refused.detail))
            return self._link_invalid(req, register=True)
        return Response(
            "200 OK",
            account_pages.notice_page(
                self._signed_out_chrome(req),
                title=req.m("acct.verify.title"),
                text=req.m("acct.verify.done"),
                link=("/login", req.m("acct.sign_in")),
            ),
        )

    def _forgot_form(self, c: Any, req: _Req, **kw: Any) -> Response:
        if not self._account_service(c).mail_configured():
            kw.setdefault("error", req.m("acct.refused.mail_unavailable"))
        return Response("200 OK", account_pages.forgot_page(self._signed_out_chrome(req), **kw))

    def _forgot(self, c: Any, req: _Req, form: Form) -> Response:
        try:
            self._account_service(c).request_password_reset(email=form.value("email"))
        except AccountRefused as refused:
            return self._forgot_form(c, req, error=account_pages.refusal(req.m, refused.code))
        return self._forgot_form(c, req, notice=req.m("acct.forgot.sent"))

    def _reset_form(
        self, c: Any, req: _Req, *, error: str | None = None, token: str | None = None
    ) -> Response:
        token = token if token is not None else (req.query.get("token") or [""])[0]
        if self._account_service(c).token_purpose(token) not in ("RESET_PASSWORD", "SET_PASSWORD"):
            return self._link_invalid(req)
        return Response(
            "200 OK" if error is None else "409 Conflict",
            account_pages.reset_page(self._signed_out_chrome(req), token=token, error=error),
        )

    def _reset(self, c: Any, req: _Req, form: Form) -> Response:
        token = form.value("token")
        if form.raw("password") != form.raw("repeat"):
            return self._reset_form(
                c, req, error=req.m("acct.refused.passwords_differ"), token=token
            )
        try:
            self._account_service(c).reset_password(token=token, password=form.raw("password"))
        except AccountRefused as refused:
            if refused.code == "weak_password":
                return self._reset_form(
                    c,
                    req,
                    error=account_pages.refusal(req.m, refused.code, refused.detail),
                    token=token,
                )
            return self._link_invalid(req)
        return _redirect("/login?reset=1", self._cookie(SESSION_COOKIE, "", 0))

    def _link_invalid(self, req: _Req, *, register: bool = False) -> Response:
        """A link that no longer works, and the way to a new one: a confirmation link is
        renewed by registering again, a password link by asking for a reset."""
        return Response(
            "410 Gone",
            account_pages.notice_page(
                self._signed_out_chrome(req),
                title=req.m("acct.link_invalid.title"),
                text=req.m("acct.link_invalid.verify" if register else "acct.link_invalid"),
                link=("/register", req.m("acct.register.again"))
                if register
                else ("/password/forgot", req.m("acct.forgot")),
            ),
        )

    # -- one's own account -------------------------------------------------------------------------

    def _account_view(
        self, c: Any, req: _Req, *, notice: str | None = None, error: str | None = None
    ) -> Response:
        account = self._account
        assert account is not None
        return Response(
            "200 OK" if error is None else "409 Conflict",
            account_pages.account_page(
                self._chrome(req, ""),
                name=account.display_name,
                email=account.email,
                role=account.system_role,
                status=account.status,
                since=account.created_at,
                projects=LabProjects(c).owned_or_assigned(account.actor_id),
                notice=notice,
                error=error,
            ),
        )

    def _change_password(self, c: Any, req: _Req, form: Form) -> Response:
        assert self._account is not None
        if form.raw("password") != form.raw("repeat"):
            return self._account_view(c, req, error=req.m("acct.refused.passwords_differ"))
        try:
            self._account_service(c).change_password(
                self._account,
                current=form.raw("current"),
                new=form.raw("password"),
                keep_session=self._session_token,
            )
        except AccountRefused as refused:
            return self._account_view(
                c, req, error=account_pages.refusal(req.m, refused.code, refused.detail)
            )
        return self._account_view(c, req, notice=req.m("acct.password_changed"))

    # -- projects ----------------------------------------------------------------------------------

    def _lab_projects(self, c: Any, req: _Req, *, error: str | None = None) -> Response:
        assert self._account is not None
        notice = req.m("proj.created") if req.query.get("created") else None
        return Response(
            "200 OK" if error is None else "409 Conflict",
            lab_pages.projects_page(
                self._chrome(req, "projects"),
                projects=LabProjects(c).owned_or_assigned(self._account.actor_id),
                notice=notice,
                error=error,
            ),
        )

    def _create_project(self, c: Any, req: _Req, form: Form) -> Response:
        assert self._account is not None
        try:
            project_id = LabProjects(c).create(
                self._account, name=form.value("name"), clearance=form.values("clearance")
            )
        except AccountRefused as refused:
            return self._lab_projects(c, req, error=_project_refusal(req.m, refused))
        return _redirect(f"/projects/{quote(project_id)}?created=1")

    def _project_overview(
        self,
        c: Any,
        req: _Req,
        project_id: str,
        *,
        notice: str | None = None,
        error: str | None = None,
    ) -> Response:
        assert self._account is not None
        projects = LabProjects(c)
        mine = projects.membership(project_id, self._account.actor_id)
        member = (
            mine is not None
            and mine.active
            and self._gate(c).authorize_project(actor_id=self._actor, project_id=project_id).allowed
        )
        if not member:
            if (
                self._account.is_admin
                and c.execute(
                    "SELECT 1 FROM projects WHERE project_id = %s", (project_id,)
                ).fetchone()
            ):
                return _redirect(f"/admin/projects/{quote(project_id)}")
            return self._message(
                req, "404 Not Found", req.m("msg.not_found"), req.m("proj.not_found")
            )
        row = c.execute(
            "SELECT name, privacy_mode, created_at FROM projects WHERE project_id = %s",
            (project_id,),
        ).fetchone()
        assert mine is not None
        view = lab_pages.ProjectOverview(
            project_id=project_id,
            name=str(row[0]),
            privacy_mode=str(row[1]),
            created_at=row[2],
            memberships=projects.memberships(project_id),
            mine=mine,
            can_manage=self._account.is_admin,
            oversight=access_log(c, project_id),
            actor_id=self._actor,
        )
        if req.query.get("created"):
            notice = req.m("proj.created")
        elif (done := (req.query.get("done") or [""])[0]) in _MEMBER_DONE:
            notice = req.m(_MEMBER_DONE[done])
        return Response(
            "200 OK" if error is None else "409 Conflict",
            lab_pages.project_page(self._chrome(req, "projects"), view, notice=notice, error=error),
        )

    def _change_members(
        self, c: Any, req: _Req, project_id: str, action: str, form: Form
    ) -> Response:
        """Add, change or remove a member. An administrator who is not a member works from
        the project's oversight page, and comes back to it."""
        assert self._account is not None
        projects = LabProjects(c)
        here = projects.membership(project_id, self._account.actor_id)
        from_oversight = self._account.is_admin and (here is None or not here.active)
        try:
            if action == "remove":
                projects.remove_member(project_id, by=self._account, actor_id=form.value("actor"))
            elif action == "change":
                projects.change_member(
                    project_id,
                    by=self._account,
                    actor_id=form.value("actor"),
                    clearance=form.values("clearance"),
                    owner=form.value("owner") == "1",
                )
            else:
                address = normalized_email(form.value("email"))
                target = (
                    None
                    if address is None
                    else c.execute(
                        "SELECT account_id FROM accounts WHERE email = %s", (address,)
                    ).fetchone()
                )
                if target is None:
                    raise AccountRefused("not_found")
                projects.add_member(
                    project_id,
                    by=self._account,
                    member_account_id=str(target[0]),
                    clearance=form.values("clearance"),
                    owner=form.value("owner") == "1",
                )
        except AccountRefused as refused:
            if refused.code == "not_permitted" and here is None and not self._account.is_admin:
                return self._message(
                    req, "404 Not Found", req.m("msg.not_found"), req.m("proj.not_found")
                )
            if from_oversight:
                return self._project_oversight(
                    c, req, project_id, error=_project_refusal(req.m, refused)
                )
            return self._project_overview(
                c, req, project_id, error=_project_refusal(req.m, refused)
            )
        done = {"add": "added", "change": "changed", "remove": "removed"}[action]
        if from_oversight:
            return _redirect(f"/admin/projects/{quote(project_id)}?done={done}")
        return _redirect(f"/projects/{quote(project_id)}?done={done}")

    # -- decisions ---------------------------------------------------------------------------------

    def _inbox(self, c: Any, req: _Req) -> Response:
        """What waits for this person: warrant questions they may answer, research they started
        that stopped for a person, and -- for an administrator -- confirmed registrations."""
        assert self._account is not None
        warrants = SqlDiagnosticWarrantStore(c)
        reviews: list[lab_pages.ReviewQuestion] = []
        hidden = not_enrolled = 0
        now = utc_now()
        for project in self._projects(c):
            outstanding = warrants.outstanding(project.project_id)
            if not outstanding:
                continue
            cleared = self._cleared(c, project.project_id)
            enrolled = any(
                not warrants.revocations(project.project_id, e.enrolment_id)
                for e in warrants.enrolments(project.project_id, self._actor)
            )
            for review in outstanding:
                question = _question_of(c, project.project_id, review.subject_id)
                if question is None or question.label not in cleared:
                    hidden += 1
                    continue
                if not enrolled:
                    not_enrolled += 1
                    continue
                reviews.append(
                    lab_pages.ReviewQuestion(
                        review_id=review.review_id,
                        project_name=project.name,
                        statement=question.statement,
                        mechanism=question.mechanism,
                        claim=req.m(
                            f"inbox.claim.{question.relation_type}",
                            observable=question.observable or req.m("inbox.observed"),
                            outcome=question.outcome,
                        ),
                        due=review.due_at,
                        overdue=review.due_at is not None and review.due_at < now,
                        command=(
                            f"lab-brain review show {review.review_id} --project "
                            f"{project.project_id} --actor {self._actor}\n"
                            f"lab-brain review resolve {review.review_id} --project "
                            f"{project.project_id} --actor {self._actor} --key <your key file>"
                            ' --outcome APPROVED|REJECTED --rationale "<why>"'
                        ),
                        packet=tuple(_packet(c, project.project_id, review.subject_id)),
                    )
                )
        names = {p.project_id: p.name for p in self._projects(c)}
        episodes = [
            lab_pages.WaitingEpisode(e.episode_id, names[e.project_id], e.goal, e.suspend_reason)
            for e in self._opened_episodes(c)
            if e.project_id in names
            and e.state not in ("COMPLETED", "ABANDONED")
            and e.suspend_reason
        ]
        pending = (
            sum(
                1
                for a in self._account_service(c).all()
                if a.status == "PENDING" and a.email_verified_at is not None
            )
            if self._account.is_admin
            else 0
        )
        return Response(
            "200 OK",
            lab_pages.inbox_page(
                self._chrome(req, "inbox"),
                reviews=reviews,
                hidden=hidden,
                not_enrolled=not_enrolled,
                episodes=episodes,
                pending=pending,
            ),
        )

    # -- the laboratory ----------------------------------------------------------------------------

    def _admin_route(self, c: Any, req: _Req) -> Response:
        assert self._account is not None and self._account.is_admin
        oversight = Oversight(c, self._account)
        method, path, form = req.method, req.path, req.form
        if path == "/admin" and method == "GET":
            return self._admin_dashboard(c, req, oversight)
        if (m := _ADMIN_ACCOUNT_PATH.match(path)) and method == "GET":
            return self._admin_member(c, req, oversight, m.group(1))
        if (m := _ADMIN_ACTION_PATH.match(path)) and method == "POST" and form is not None:
            return self._admin_action(c, req, oversight, m.group(1), m.group(2), form)
        if (m := _ADMIN_PROJECT_PATH.match(path)) and method == "GET":
            done = (req.query.get("done") or [""])[0]
            return self._project_oversight(
                c,
                req,
                m.group(1),
                notice=req.m(_MEMBER_DONE[done]) if done in _MEMBER_DONE else None,
            )
        if (m := _ADMIN_EPISODE_PATH.match(path)) and method == "GET":
            return self._admin_episode(c, req, oversight, m.group(1))
        if (m := _ADMIN_EXPORT_PATH.match(path)) and method == "GET":
            return self._admin_export(c, req, oversight, m.group(1), int(m.group(2)))
        if (m := _ADMIN_MATERIAL_PATH.match(path)) and method == "GET":
            return self._admin_material(c, req, oversight, m.group(1), m.group(2))
        return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))

    def _project_oversight(
        self,
        c: Any,
        req: _Req,
        project_id: str,
        *,
        notice: str | None = None,
        error: str | None = None,
    ) -> Response:
        assert self._account is not None and self._account.is_admin
        detail = Oversight(c, self._account).project(project_id)
        if detail is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        return Response(
            "200 OK" if error is None else "409 Conflict",
            admin_pages.project_oversight_page(
                self._chrome(req, "admin"),
                detail,
                actor_id=self._actor,
                allowed=LABELS,
                notice=notice,
                error=error,
            ),
        )

    def _admin_dashboard(
        self, c: Any, req: _Req, oversight: Oversight, *, error: str | None = None
    ) -> Response:
        return Response(
            "200 OK" if error is None else "409 Conflict",
            admin_pages.dashboard_page(
                self._chrome(req, "admin"),
                members=oversight.members(),
                projects=oversight.projects(),
                notice=req.m("admin.done") if req.query.get("done") else None,
                error=error,
            ),
        )

    def _admin_member(
        self,
        c: Any,
        req: _Req,
        oversight: Oversight,
        account_id: str,
        *,
        error: str | None = None,
    ) -> Response:
        found = oversight.member(account_id)
        if found is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        account, projects, episodes = found
        assert self._account is not None
        return Response(
            "200 OK" if error is None else "409 Conflict",
            admin_pages.member_page(
                self._chrome(req, "admin"),
                account=account,
                projects=projects,
                episodes=episodes,
                history=self._account_service(c).events(account_id),
                self_view=account.account_id == self._account.account_id,
                notice=req.m("admin.done") if req.query.get("done") else None,
                error=error,
            ),
        )

    def _admin_action(
        self, c: Any, req: _Req, oversight: Oversight, account_id: str, action: str, form: Form
    ) -> Response:
        assert self._account is not None
        service = self._account_service(c)
        by = self._account
        try:
            if action == "approve":
                service.approve(account_id, by=by)
            elif action == "reject":
                service.reject(account_id, by=by)
            elif action == "suspend":
                service.suspend(account_id, by=by, reason=form.value("reason"))
            elif action == "reactivate":
                service.reactivate(account_id, by=by)
            else:
                service.set_role(account_id, form.value("role"), by=by)
        except AccountRefused as refused:
            message = _admin_refusal(req.m, refused)
            if action in ("approve", "reject"):
                return self._admin_dashboard(c, req, oversight, error=message)
            return self._admin_member(c, req, oversight, account_id, error=message)
        if action in ("approve", "reject"):
            return _redirect("/admin?done=1")
        return _redirect(f"/admin/accounts/{quote(account_id)}?done=1")

    def _admin_episode(self, c: Any, req: _Req, oversight: Oversight, episode_id: str) -> Response:
        project_id = oversight.episode_project(episode_id)
        if project_id is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        # Recorded first: an administrator reads every report in full, classified excerpts
        # included, and the project's members are shown that they did.
        oversight.record(project_id, f"{EPISODE_REPORTS}{episode_id}")
        row = c.execute(
            "SELECT e.goal, p.name FROM research_episodes e JOIN projects p"
            " ON p.project_id = e.project_id WHERE e.episode_id = %s",
            (episode_id,),
        ).fetchone()
        reports = [
            (ordinal, text) for ordinal, text in self._full_reports(c, project_id, episode_id)
        ]
        return Response(
            "200 OK",
            admin_pages.episode_oversight_page(
                self._chrome(req, "admin"),
                episode_id=episode_id,
                goal=str(row[0]),
                project_name=str(row[1]),
                reports=reports,
            ),
        )

    def _full_reports(self, c: Any, project_id: str, episode_id: str) -> list[tuple[int, str]]:
        """Each recorded report as its run wrote it -- nothing withheld -- then what the record
        says about its conclusions now. For oversight only: the caller has recorded the
        look."""
        view = load_episode_view(
            c, project_id=project_id, episode_id=episode_id, verify=self._confirmation_verifier(c)
        )
        since = render_recorded_since(view.conclusions)
        return [
            (recorded.ordinal, render_markdown(recorded.report) + since)
            for recorded in SqlResearchReportStore(c).for_episode(
                project_id=project_id, episode_id=episode_id
            )
        ]

    def _admin_export(
        self, c: Any, req: _Req, oversight: Oversight, episode_id: str, ordinal: int
    ) -> Response:
        project_id = oversight.episode_project(episode_id)
        if project_id is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        oversight.record(project_id, f"{EPISODE_REPORTS}{episode_id}")
        for number, text in self._full_reports(c, project_id, episode_id):
            if number == ordinal:
                name = re.sub(r"[^A-Za-z0-9._-]+", "-", episode_id).strip("-")
                return Response(
                    "200 OK",
                    text.encode("utf-8"),
                    content_type="text/markdown; charset=utf-8",
                    headers=(
                        ("Content-Disposition", f'inline; filename="{name}-run-{ordinal}.md"'),
                    ),
                )
        return self._message(
            req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_recorded_run")
        )

    def _admin_material(
        self, c: Any, req: _Req, oversight: Oversight, project_id: str, artifact_id: str
    ) -> Response:
        material = oversight.material(project_id, artifact_id)
        if material is None:
            return self._message(req, "404 Not Found", req.m("msg.not_found"), req.m("msg.no_page"))
        name = c.execute(
            "SELECT name FROM projects WHERE project_id = %s", (project_id,)
        ).fetchone()
        try:
            text = self._artifacts.open(material.content_hash).decode("utf-8", errors="replace")
        except ArtifactStoreError:
            text = None
        return Response(
            "200 OK",
            admin_pages.material_page(
                self._chrome(req, "admin"),
                project_id=project_id,
                project_name=str(name[0]),
                material=material,
                text=text,
            ),
        )

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


def _credential_mode(secret_value: str, env_name: str, secret_ref: str, m: Messages) -> str:
    """Which one credential a form gave: a pasted key ("store"), an environment variable, a
    reference -- or none. More than one is refused: the page never picks for the researcher."""
    try:
        return credential_forms.one_source(secret_value, env_name, secret_ref)
    except ValueError:
        raise SettingsRefused(m("cred.one_source"), code="secret.one_source") from None


def _slug(name: str) -> str:
    """A connection name as `012e` accepts it: lower case, letters, digits, '.', '_', '-'."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.strip().lower()).strip("-._")
    return slug[:48]


def _free_name(base: str, taken: set[str]) -> str:
    base = "local-ollama" if base == "ollama" else base
    if base not in taken:
        return base
    return next(f"{base}-{n}" for n in range(2, 1000) if f"{base}-{n}" not in taken)


def _carry(upload: Upload) -> workspace_pages.Carried:
    """A file the confirmation page carries to the start, unchanged: its bytes, base64."""
    return workspace_pages.Carried(
        name=upload.filename or "unnamed",
        size=len(upload.data),
        encoded=base64.b64encode(upload.data).decode("ascii"),
    )


def _uncarry(form: Form, prefix: str, m: Messages) -> list[Upload]:
    """The file a confirmation carried under `prefix`, as it was sent; none if it carried none."""
    encoded = form.value(f"{prefix}_b64")
    if not encoded:
        return []
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise FormError(m("msg.refused")) from None
    return [Upload(filename=form.value(f"{prefix}_name") or prefix, data=data)]


def _size(n: int) -> str:
    """Bytes, for a person."""
    value = float(n)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


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


def _cookies(environ: Mapping[str, Any]) -> dict[str, str]:
    cookie: SimpleCookie = SimpleCookie()
    try:
        cookie.load(str(environ.get("HTTP_COOKIE") or ""))
    except CookieError:
        return {}
    return {name: morsel.value for name, morsel in cookie.items()}


def _local_target(target: str) -> str:
    """`target` if it is a path of this workspace, else "/" -- never another origin. A browser
    drops tabs and line breaks from a URL and reads a backslash as a slash, so `/<TAB>/x.example`
    would leave for `//x.example`: any control character or backslash, or anything but a
    single leading slash (a scheme, a host, `//`), sends the person home instead."""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in target) or "\\" in target:
        return "/"
    if not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def _local_path(target: str) -> str:
    """A path of this workspace to go to after signing in -- never another origin, never a
    sign-in page again."""
    target = _local_target(target)
    if target.startswith(("/login", "/logout", "/register", "/verify", "/password/")):
        return "/"
    return target


#: The notice after a change of membership, by the `done` it redirects with.
_MEMBER_DONE = {"added": "proj.added", "changed": "proj.changed", "removed": "proj.removed"}


def _project_refusal(m: Messages, refused: AccountRefused) -> str:
    try:
        return m(f"proj.refused.{refused.code}")
    except KeyError:
        return m("proj.refused.not_permitted")


def _admin_refusal(m: Messages, refused: AccountRefused) -> str:
    try:
        return m(f"admin.refused.{refused.code}", detail=refused.detail or "-")
    except KeyError:
        return m("admin.refused.not_permitted")


@dataclass(frozen=True)
class _Question:
    """What a warrant question is about, in words, and the classification of the research."""

    label: str | None
    statement: str
    mechanism: str
    relation_type: str
    outcome: str
    #: What was measured: the observable the prediction this relation matched names.
    observable: str = ""


def _question_of(c: Any, project_id: str, relation_id: str) -> _Question | None:
    row = c.execute(
        "SELECT (SELECT q.question_label FROM research_runs q WHERE q.episode_id = s.episode_id"
        "   AND q.question_label IS NOT NULL ORDER BY q.ordinal DESC LIMIT 1),"
        " h.statement, h.mechanism, r.relation_type, coalesce(r.attributes ->> 'outcome', ''),"
        " coalesce((SELECT p.observable_ref FROM predictions p"
        "   WHERE p.prediction_id = r.attributes ->> 'prediction_id'), '')"
        " FROM relation_judgments r"
        " JOIN hypotheses h ON h.project_id = r.project_id AND h.hypothesis_id = r.to_entity_id"
        " JOIN hypothesis_sets s ON s.project_id = h.project_id AND s.set_id = h.hypothesis_set_id"
        " WHERE r.project_id = %s AND r.relation_id = %s",
        (project_id, relation_id),
    ).fetchone()
    if row is None:
        return None
    return _Question(row[0], str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]))


def allowed_hosts(host: str, port: int) -> tuple[str, ...]:
    """The Host header values a workspace bound to `host:port` answers to."""
    names = LOOPBACK if host in LOOPBACK or host == "::1" else (host,)
    return tuple(f"{name}:{port}" for name in names)


__all__ = [
    "ANONYMOUS_COOKIE",
    "LOCALE_COOKIE",
    "LOOPBACK",
    "MAX_UPLOAD_BYTES",
    "SESSION_COOKIE",
    "WITHHELD",
    "AccountsConfig",
    "Response",
    "Workspace",
    "allowed_hosts",
]
