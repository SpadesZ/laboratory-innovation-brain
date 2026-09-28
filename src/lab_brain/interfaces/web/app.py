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

FORGERY. Every state-changing request is a POST that must carry this process's CSRF token (and,
when the browser sends one, an Origin of this workspace), and every request must name an allowed
Host -- so another web page cannot drive the workspace, and a rebinding DNS name cannot reach it.
"""

from __future__ import annotations

import dataclasses
import hmac
import json
import re
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from lab_brain.composition import IngestionService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.repositories.external_sources import SqlExternalSourceStore
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.interfaces.cli import _DOCUMENT_KINDS, _MEDIA_TYPES
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.forms import Form, FormError, read_form
from lab_brain.research.continuation import (
    ContinuationRefused,
    EpisodeNotContinuable,
)
from lab_brain.research.literature import LiteratureRequest
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

_EPISODE_PATH = re.compile(r"^/episodes/([A-Za-z0-9:_.\-]{1,200})$")
_CONTINUE_PATH = re.compile(r"^/episodes/([A-Za-z0-9:_.\-]{1,200})/continue$")
_MARKDOWN_PATH = re.compile(r"^/episodes/([A-Za-z0-9:_.\-]{1,200})/runs/([0-9]{1,6})/report\.md$")

#: Shown in place of an evidence excerpt the actor can no longer read.
WITHHELD = "[withheld: this excerpt is not readable under your current clearance]"


@dataclass(frozen=True)
class Response:
    status: str
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


def _redirect(location: str) -> Response:
    return Response("303 See Other", b"", headers=(("Location", location),))


@dataclass(frozen=True)
class _Opened:
    """An episode this actor opened, as the ledger and the episode row hold it."""

    project_id: str
    row: pages.EpisodeRow


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
    ) -> None:
        self._actor = actor_id
        self._settings = settings
        self._connect = connect
        self._artifacts = LocalArtifactStore(artifact_root.resolve())
        self._factory = vertical_factory
        self._hosts = frozenset(allowed_hosts)
        self._csrf = csrf_token or secrets.token_urlsafe(32)

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
        form: Form | None = None
        if method == "POST":
            origin = environ.get("HTTP_ORIGIN")
            if origin is not None and origin not in {f"http://{h}" for h in self._hosts}:
                return self._forbidden()
            try:
                form = read_form(environ, limit=MAX_UPLOAD_BYTES)
            except FormError as refused:
                return self._message("400 Bad Request", "The request was refused", str(refused))
            if not hmac.compare_digest(form.value("csrf"), self._csrf):
                return self._forbidden()
        elif method != "GET":
            return Response("405 Method Not Allowed", b"", headers=(("Allow", "GET, POST"),))

        connection = self._connect(self._settings)
        try:
            connection.autocommit = True
            return self._route(connection, method, path, query, form)
        finally:
            connection.close()

    def _route(
        self,
        c: Any,
        method: str,
        path: str,
        query: Mapping[str, Sequence[str]],
        form: Form | None,
    ) -> Response:
        if path == "/" and method == "GET":
            return self._home(c)
        if path == "/runs/new" and method == "GET":
            return self._new_run(c)
        if path == "/runs" and method == "POST" and form is not None:
            return self._create_run(c, form)
        if (m := _EPISODE_PATH.match(path)) and method == "GET":
            return self._episode(c, m.group(1), query)
        if (m := _CONTINUE_PATH.match(path)) and method == "POST":
            return self._continue(c, m.group(1))
        if (m := _MARKDOWN_PATH.match(path)) and method == "GET":
            return self._markdown(c, m.group(1), int(m.group(2)))
        return self._message("404 Not Found", "Not found", "There is no such page.")

    # -- pages ------------------------------------------------------------------------------------

    def _home(self, c: Any) -> Response:
        projects = self._projects(c)
        allowed = {p.project_id for p in projects}
        episodes = [e for e in self._opened_episodes(c) if e.project_id in allowed]
        return Response(
            "200 OK", pages.home_page(actor_id=self._actor, projects=projects, episodes=episodes)
        )

    def _new_run(self, c: Any, *, error: str | None = None, status: str = "200 OK") -> Response:
        return Response(
            status,
            pages.new_run_page(
                actor_id=self._actor,
                projects=self._projects(c),
                csrf=self._csrf,
                sensitivities=[s.value for s in SensitivityLabel],
                error=error,
            ),
        )

    def _create_run(self, c: Any, form: Form) -> Response:
        try:
            request = self._research_request(form)
        except FormError as refused:
            return self._new_run(c, error=str(refused), status="400 Bad Request")
        try:
            report, run_id = self._run(c, request)
        except ScientificReadRefused:
            # One sentence for every reason, as the CLI says it.
            return self._message(
                "403 Forbidden",
                "No research",
                f"No research for {self._actor} in {request.project_id}.",
            )
        self._record(c, run_id, report)
        return _redirect(f"/episodes/{_path(report.episode_id)}")

    def _episode(
        self, c: Any, episode_id: str, query: Mapping[str, Sequence[str]], notice: str | None = None
    ) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(episode_id)
        runs = self._runs(c, opened.project_id, episode_id)
        recorded = {
            r.ordinal: r
            for r in SqlResearchReportStore(c).for_episode(
                project_id=opened.project_id, episode_id=episode_id
            )
        }
        runs = [dataclasses.replace(r, recorded=r.ordinal in recorded) for r in runs]
        chosen: RecordedReport | None = None
        wanted = query.get("run", [""])[0]
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
                notice=notice,
            ),
        )

    def _continue(self, c: Any, episode_id: str) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(episode_id)
        request = ResearchRequest(
            project_id=opened.project_id,
            actor_id=self._actor,
            goal="",
            documents=(),
            episode_id=episode_id,
        )
        try:
            report, run_id = self._run(c, request)
        except (ScientificReadRefused, EpisodeNotContinuable):
            return self._not_found(episode_id)
        except ContinuationRefused as refused:
            return self._message(
                "409 Conflict", "Not continued", str(refused), back=f"/episodes/{_path(episode_id)}"
            )
        self._record(c, run_id, report)
        (ordinal,) = (
            r.ordinal
            for r in self._runs(c, opened.project_id, episode_id)
            if r.research_run_id == run_id
        )
        return _redirect(f"/episodes/{_path(episode_id)}?run={ordinal}")

    def _markdown(self, c: Any, episode_id: str, ordinal: int) -> Response:
        opened = self._opened(c, episode_id)
        if opened is None:
            return self._not_found(episode_id)
        for recorded in SqlResearchReportStore(c).for_episode(
            project_id=opened.project_id, episode_id=episode_id
        ):
            if recorded.ordinal == ordinal:
                text = render_markdown(self._authorized(c, recorded.report))
                return Response(
                    "200 OK", text.encode("utf-8"), content_type="text/markdown; charset=utf-8"
                )
        return self._message("404 Not Found", "Not found", "That run has no recorded report.")

    # -- the service, unchanged -----------------------------------------------------------------

    def _run(self, c: Any, request: ResearchRequest) -> tuple[EpisodeReport, str]:
        """`ResearchEpisodeService.run`, observing only which research run id it minted."""
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
        )
        report = service.run(request)
        if len(minted) != 1:  # pragma: no cover - the service mints one per run
            raise RuntimeError(f"the research service minted {len(minted)} research run ids")
        return report, minted[0]

    def _record(self, c: Any, research_run_id: str, report: EpisodeReport) -> None:
        # `012d` refuses a report that is not this run's: episode, project, actor, the outcome the
        # ledger recorded for it, and the run's own id in its provenance.
        SqlResearchReportStore(c).record(research_run_id, report, at=utc_now())

    def _research_request(self, form: Form) -> ResearchRequest:
        project = form.value("project")
        goal = form.value("goal")
        if not project:
            raise FormError("Choose a project.")
        if not goal:
            raise FormError("A research run needs a goal.")
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
                raise FormError(
                    "A literature corpus and a literature query go together: a provider is only "
                    "searched with a query you declare public."
                )
            if form.value("literature_query_public") != "yes":
                raise FormError(
                    "Declare the literature query PUBLIC to send it to the provider, or leave the "
                    "literature fields empty."
                )
            literature = self._literature(corpus_uploads[0], query)
        sensitivity = form.value("sensitivity") or SensitivityLabel.INTERNAL.value
        if sensitivity not in {s.value for s in SensitivityLabel}:
            raise FormError(f"Unknown classification {sensitivity!r}.")
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
    def _literature(corpus: Any, query: str) -> LiteratureRequest:
        # A provider package, not a DomainPack: `interfaces -> tool_providers` is permitted.
        from lab_brain.tool_providers.literature import LiteratureCorpusAdapter
        from lab_brain.tool_providers.literature import declaration as literature_declaration

        try:
            papers = json.loads(corpus.data.decode("utf-8"))["papers"]
        except (ValueError, KeyError, TypeError) as exc:
            raise FormError(
                f"{corpus.filename} is not a literature corpus (a JSON object with 'papers')."
            ) from exc
        return LiteratureRequest(
            adapter=LiteratureCorpusAdapter(papers, now=utc_now),
            declaration=literature_declaration(),
            query=query,
            description=f"the local literature corpus file {corpus.filename} (no network)",
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

    def _message(self, status: str, title: str, message: str, back: str = "/") -> Response:
        return Response(
            status,
            pages.message_page(actor_id=self._actor, title=title, message=message, back=back),
        )

    def _not_found(self, episode_id: str) -> Response:
        # The same words for an unknown id, another project's episode and a colleague's.
        return self._message(
            "404 Not Found", "No such episode", f"No episode {episode_id} for {self._actor}."
        )

    def _forbidden(self) -> Response:
        return Response(
            "403 Forbidden",
            b"This request did not come from this workspace's own form.",
            content_type="text/plain; charset=utf-8",
        )


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


__all__ = ["LOOPBACK", "MAX_UPLOAD_BYTES", "WITHHELD", "Response", "Workspace", "allowed_hosts"]
