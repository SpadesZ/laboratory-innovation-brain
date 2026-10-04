"""`lab-brain inbox`, `explain`, `episode open`, `research run`, `web` (UX-001/003/006, §17.22-24).

`research run` is the product vertical: a research goal plus local files in, one report out. It is
a thin entry point over `lab_brain.research.ResearchEpisodeService`, which composes the existing
authorities (ingestion, evidence admission, external literature, the M3 debate, the M4 verification
loop) and decides nothing itself; this module parses arguments, opens the connection, selects the
domain's product vertical BY NAME (the `lab_brain.domain_verticals` entry points -- no pack is
imported here), and prints the rendered report. Without `--episode` it opens a new episode; with
`--episode E` it CONTINUES E -- the actor's own suspended episode in that project, over its own
inputs and hypotheses -- and refuses everything else (`lab_brain.research.continuation`). `web`
serves the same workflow, unchanged, as a browser workspace on this machine
(`lab_brain.interfaces.web`).

M1's scope names *IngestionItem / ErrorRecord / MessageCatalog + CLI inbox*, and M4's VS-SP-001
definition of done adds one sentence: "CLI 可從一個 project/fixture 建立 episode". So there are
three commands. `episode open` starts a ResearchEpisode and ingests the files it is given into it
through the same `IngestionService` production uses -- raw bytes hashed and stored before any
parsing stage (UX-004), each file one IngestionItem in the Knowledge Inbox -- and prints the
episode and the derived inbox rows. It runs no model and no solver: diagnosing is the loop's.

IT IS NOT A DASHBOARD, and the restraint is the design. Every line it prints comes from a
projection or a catalog entry that already exists and is already tested:

    inbox    `derive_state` over the authoritative rows -- the same function UX-001's contract
             tests exercise. The CLI does not compute state; if it did, there would be two
             derivations and the terminal would eventually disagree with everything else.
    explain  `DiagnosticsService`, which owns the ACL scope check, the clearance redaction and
             the cross-project not-found semantics. The CLI passes an actor and prints what comes
             back.

WHY `--actor` IS REQUIRED ON BOTH. §14.4: 沒有「誰」就沒有真 governance. A CLI that defaulted to
an implicit identity would be the one surface where an unidentified request gets an answer, and
`explain` in particular is an authorization decision.

TECHNICAL EXPANSION STAYS SERVER-SIDE. `--technical` does not toggle rendering; it asks the
service to expand, and the service decides. A flag that formatted more of an already-loaded
payload would mean the detail had crossed the boundary before anything decided it could.

NO LLM ANYWHERE. §17.24 forbids model-generated failure text at render time, and this module
imports nothing that could produce any.

IT IS NOW WIRED, AND THE WIRING IS ONE FUNCTION. `main` reads a DSN through
`lab_brain.interfaces.config`, opens a connection, builds the same `IngestionService` the rest of
production uses, and closes the connection on every path. It previously printed a message and
exited 2, which made "the CLI exists" true and "the CLI works" false -- the projections were
proven against items a test constructed and nothing had ever read a row.

WHAT STAYS OUT OF `main`. Every decision. `inbox` renders `service.inbox(...)` through
`derive_state`; `explain` renders `service.diagnostics()`. If a behaviour is worth asserting, it
is asserted against the service, and `main` is tested for the wiring -- which is the part that
was missing and the part a unit test of `run_inbox` cannot reach.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from lab_brain.composition import IngestionService
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.job import Job
from lab_brain.core.repositories.episodes import EpisodeStoreError
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.interfaces.config import (
    ConfigurationError,
    Settings,
    open_connection,
    read_settings,
)
from lab_brain.research.continuation import ContinuationRefused
from lab_brain.research.literature import LiteratureRequest
from lab_brain.research.reasoning import active_runtime_name
from lab_brain.research.render import render_markdown
from lab_brain.research.service import InputDocument, ResearchEpisodeService, ResearchRequest
from lab_brain.research.vertical import ENTRY_POINT_GROUP, VerticalNotFound, load_vertical_factory
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.surface.catalog import MessageCatalog, Severity, default_catalog
from lab_brain.surface.disclosure import DiagnosticsService, ErrorNotFound
from lab_brain.surface.ingestion_item import IngestionItem, ItemState, derive_state

#: Column widths for the inbox table. Fixed rather than computed from the data: a table whose
#: columns move when a long filename arrives is one nobody can grep or diff between runs.
_ID_WIDTH = 24
_STATE_WIDTH = 13


@dataclass(frozen=True)
class InboxRow:
    """One rendered line. Separated from printing so a test asserts on data, not on a string."""

    item_id: str
    state: ItemState
    display_name: str
    error_ids: tuple[str, ...] = ()

    def render(self) -> str:
        errors = f"  [{', '.join(self.error_ids)}]" if self.error_ids else ""
        return (
            f"{self.item_id:<{_ID_WIDTH}}"
            f"{self.state.value:<{_STATE_WIDTH}}"
            f"{self.display_name}{errors}"
        )


def build_inbox(
    items: Sequence[IngestionItem],
    *,
    jobs_for: Callable[[str], Sequence[Job]] | None = None,
    open_review_ids: frozenset[str] = frozenset(),
    blocking_conflict_ids: frozenset[str] = frozenset(),
) -> tuple[InboxRow, ...]:
    """Project items into rows. The state is DERIVED, never read off the item.

    `jobs_for` is now a REAL parameter. It was accepted and ignored while no CLI caller had a
    live job list, which meant PROCESSING was unreachable from the terminal: a document still
    being parsed read as READY, which is the one answer a user must not be given about work that
    has not finished. `InboxView` carries the jobs alongside the items so the two are read in one
    pass and cannot disagree about which run is in flight.
    """
    rows = [
        InboxRow(
            item_id=item.item_id,
            state=derive_state(
                item,
                jobs=() if jobs_for is None else jobs_for(item.item_id),
                open_review_ids=open_review_ids,
                blocking_conflict_ids=blocking_conflict_ids,
            ),
            display_name=item.display_name,
            error_ids=item.error_ids,
        )
        for item in items
    ]
    # Sorted by submission, stable on id. A listing whose order depends on the query plan cannot
    # be compared between two runs, which is the first thing anyone does when triaging.
    order = {item.item_id: (item.submitted_at, item.item_id) for item in items}
    return tuple(sorted(rows, key=lambda r: order[r.item_id]))


def summarise(rows: Sequence[InboxRow]) -> dict[ItemState, int]:
    """Counts per state, for the summary line. Every state appears, including the zeroes.

    Zeroes are printed: "BLOCKED 0" is information, and a summary that omitted empty states would
    make "nothing is blocked" and "the column was dropped" look identical.
    """
    counts = dict.fromkeys(ItemState, 0)
    for row in rows:
        counts[row.state] += 1
    return counts


def render_inbox(rows: Sequence[InboxRow], *, out: TextIO) -> None:
    header = f"{'ITEM':<{_ID_WIDTH}}{'STATE':<{_STATE_WIDTH}}NAME"
    print(header, file=out)
    print("-" * len(header), file=out)
    for row in rows:
        print(row.render(), file=out)
    counts = summarise(rows)
    print("", file=out)
    print(
        "  ".join(f"{state.value}={counts[state]}" for state in ItemState),
        file=out,
    )


def render_explanation(
    service: DiagnosticsService,
    error_id: str,
    *,
    actor_id: str,
    project_id: str,
    technical: bool,
    out: TextIO,
) -> int:
    """Print what the user is allowed to see. Returns a process exit code.

    THE SERVICE DECIDES, not this function. `technical` selects which service call is made; it
    does not select how much of an already-loaded payload to show. And `ErrorNotFound` is printed
    identically whether the id never existed or belongs to another project -- §17.24 forbids the
    difference, because an attacker enumerating ids learns which exist from any distinction.
    """
    try:
        payload = (
            service.expand(error_id, actor_id=actor_id, project_id=project_id)
            if technical
            else service.default_payload(error_id, actor_id=actor_id, project_id=project_id)
        )
    except ErrorNotFound:
        print(f"No such error reference in this project: {error_id}", file=out)
        return 1

    message = payload.message
    marker = "!" if message.severity in (Severity.ERROR, Severity.BLOCKED) else "-"
    print(f"{marker} {message.summary}", file=out)
    print(f"  {message.cause}", file=out)
    for step in message.next_steps:
        print(f"  * {step}", file=out)
    print("", file=out)
    print(f"  reference : {message.error_id}", file=out)
    print(f"  trace     : {payload.trace_id}", file=out)
    if payload.job_id:
        print(f"  job       : {payload.job_id}", file=out)
    if payload.span_id:
        print(f"  span      : {payload.span_id}", file=out)
    print(f"  catalog   : {message.catalog_version}", file=out)

    if payload.technical_withheld:
        print("", file=out)
        print(
            f"  technical detail withheld: {payload.withheld_reason_code}",
            file=out,
        )
    elif payload.technical is not None:
        print("", file=out)
        print(f"  component : {payload.technical.component}", file=out)
        print(f"  detail    : {payload.technical.message}", file=out)
        if payload.technical.source_path:
            print(f"  source    : {payload.technical.source_path}", file=out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lab-brain", description="Laboratory Innovation Brain")
    sub = parser.add_subparsers(dest="command", required=True)

    inbox = sub.add_parser("inbox", help="list ingestion items and their derived state")
    inbox.add_argument("--project", required=True)
    # Required, not defaulted. §14.4: 沒有「誰」就沒有真 governance.
    inbox.add_argument("--actor", required=True)

    explain = sub.add_parser("explain", help="explain an error reference")
    explain.add_argument("error_id")
    explain.add_argument("--project", required=True)
    explain.add_argument("--actor", required=True)
    explain.add_argument(
        "--technical",
        action="store_true",
        help=(
            "request technical detail. Requires the VIEW_TECHNICAL_DIAGNOSTICS scope, checked "
            "server-side; the flag asks, it does not grant"
        ),
    )
    episode = sub.add_parser("episode", help="research episodes")
    episode_sub = episode.add_subparsers(dest="episode_command", required=True)
    opened = episode_sub.add_parser(
        "open", help="open an episode and ingest a project's fixture files into it"
    )
    opened.add_argument("fixtures", nargs="+", help="files to ingest into the episode")
    opened.add_argument("--project", required=True)
    opened.add_argument("--actor", required=True)
    opened.add_argument("--goal", required=True)
    opened.add_argument("--trace", required=True)
    opened.add_argument("--episode", help="episode id; minted when omitted")
    # Required, not defaulted: where raw bytes are stored is a deployment decision, and a
    # command that picked a temp directory would store evidence nobody can find again.
    opened.add_argument("--artifact-root", required=True)
    opened.add_argument(
        "--sensitivity",
        default=SensitivityLabel.INTERNAL.value,
        choices=[label.value for label in SensitivityLabel],
    )

    research = sub.add_parser("research", help="research episodes, end to end")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    ran = research_sub.add_parser(
        "run",
        help=(
            "open an episode for a research goal, read the given files, debate competing "
            "hypotheses, run the verification this deployment can run, and report"
        ),
    )
    ran.add_argument("--project", required=True)
    ran.add_argument("--actor", required=True)
    ran.add_argument(
        "--goal",
        help="the research question, in your own words (required unless --episode continues one)",
    )
    ran.add_argument("--artifact-root", required=True, help="where raw bytes are stored")
    ran.add_argument(
        "--domain",
        help=f"the product vertical (an entry point in {ENTRY_POINT_GROUP}); "
        "optional when exactly one is installed",
    )
    # The trust class each file's statements carry is DECLARED by the user, never inferred.
    ran.add_argument(
        "--measurement",
        action="append",
        default=[],
        metavar="FILE",
        help="a record of the lab's measurements (statements retrieved as INTERNAL_MEASUREMENT)",
    )
    ran.add_argument(
        "--run-record",
        action="append",
        default=[],
        metavar="FILE",
        help="a record of earlier simulations or runs (INTERNAL_RUN)",
    )
    ran.add_argument(
        "--note",
        action="append",
        default=[],
        metavar="FILE",
        help="notes or expert heuristics (EXPERT_HEURISTIC)",
    )
    ran.add_argument(
        "--verification-input",
        metavar="FILE",
        help="the domain's verification input (silicon_photonics: a device project JSON)",
    )
    ran.add_argument(
        "--literature-corpus",
        metavar="FILE",
        help="a local literature corpus to search (requires --literature-query)",
    )
    ran.add_argument(
        "--literature-query",
        help="the query to send to the literature provider, which you declare PUBLIC",
    )
    ran.add_argument("--symptom")
    ran.add_argument("--expected")
    ran.add_argument("--observed")
    ran.add_argument(
        "--episode",
        help=(
            "CONTINUE this suspended episode of yours in --project: resumed through its lifecycle, "
            "over its own hypotheses and inputs (no new inputs are taken). Omit to open a new "
            "episode, whose id is minted"
        ),
    )
    ran.add_argument("--trace", help="trace id; minted when omitted")
    ran.add_argument(
        "--sensitivity",
        choices=[label.value for label in SensitivityLabel],
        help="the classification of the goal and the files in this project (default INTERNAL)",
    )
    ran.add_argument("--report", metavar="FILE", help="also write the report (Markdown) here")

    web = sub.add_parser(
        "web",
        help=(
            "the research workspace: start and continue research runs in a browser, on this "
            "machine, as --actor"
        ),
    )
    web.add_argument("--actor", required=True, help="the actor every request is made as")
    web.add_argument("--artifact-root", required=True, help="where raw bytes are stored")
    web.add_argument(
        "--domain",
        help=f"the product vertical (an entry point in {ENTRY_POINT_GROUP}); "
        "optional when exactly one is installed",
    )
    web.add_argument("--host", default="127.0.0.1", help="loopback only (default 127.0.0.1)")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument(
        "--locale",
        default="en",
        choices=["en", "zh-TW"],
        help="the interface language a browser starts in (each browser may switch)",
    )
    web.add_argument(
        "--in-container",
        action="store_true",
        help=(
            "the container deployment: listen on 0.0.0.0 inside a container whose port is "
            "published on the host's loopback only; refused anywhere but inside a container"
        ),
    )
    web.add_argument(
        "--published-port",
        type=int,
        help="with --in-container: the host loopback port the browser uses (default --port)",
    )
    web.add_argument(
        "--host-gateway",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "with --in-container: a host name that is the machine running the container "
            "(host.docker.internal), so a model there may be declared LOCAL"
        ),
    )
    web.add_argument(
        "--credential-dir",
        metavar="DIR",
        help=(
            "keep model-provider keys a researcher pastes in this directory (the container "
            "deployment's credentials volume): one file per key, 0600, never in the database. "
            "Filesystem isolation, not encryption. Without it, a pasted key goes to the "
            "operating system's credential store where there is one, and is refused elsewhere"
        ),
    )
    web.add_argument(
        "--ollama-url",
        metavar="URL",
        help=(
            "this machine's Ollama (OpenAI-compatible /v1), offered as the local model in AI "
            "model settings (default http://127.0.0.1:11434/v1, or the container host's)"
        ),
    )

    admin = sub.add_parser(
        "admin",
        help=(
            "the deployment operator: actors, projects, memberships and LLM administrators "
            "(whoever holds the database credentials)"
        ),
    )
    admin_sub = admin.add_subparsers(dest="admin_command", required=True)
    actor = admin_sub.add_parser("actor", help="create or rename a person (a HUMAN actor)")
    actor.add_argument("actor_id")
    actor.add_argument("--name", required=True, help="display name")
    project = admin_sub.add_parser("project", help="create or update a project")
    project.add_argument("project_id")
    project.add_argument("--name", required=True)
    project.add_argument(
        "--privacy-mode",
        choices=["PRIVATE", "RESEARCH", "NOVELTY_AUDIT"],
        help="§14.2; a new project is PRIVATE (no egress) unless named",
    )
    member = admin_sub.add_parser(
        "member", help="set an actor's membership: exactly the clearance and scopes named"
    )
    member.add_argument("project_id")
    member.add_argument("actor_id")
    member.add_argument("--role", default="researcher")
    member.add_argument(
        "--clearance",
        default="",
        help="comma-separated sensitivity labels the actor may read (default none)",
    )
    member.add_argument(
        "--scope",
        action="append",
        default=[],
        help="an approval scope, e.g. LLM_EGRESS (repeatable; default none)",
    )
    llm_admin = admin_sub.add_parser(
        "llm-admin", help="grant (or --revoke) administration of the deployment's LLM routes"
    )
    llm_admin.add_argument("actor_id")
    llm_admin.add_argument("--revoke", action="store_true")
    admin_sub.add_parser("show", help="list actors, projects, memberships, LLM administrators")
    return parser


_MEDIA_TYPES: Mapping[str, str] = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
}


def run_episode_open(
    service: IngestionService,
    *,
    project_id: str,
    actor_id: str,
    goal: str,
    trace_id: str,
    episode_id: str | None,
    fixtures: Sequence[Path],
    sensitivity: SensitivityLabel,
    out: TextIO,
) -> int:
    """Open the episode, ingest each file under its own Job, then print the derived inbox.

    One Job per file, keyed by the episode and the file's content hash, so re-running the same
    command resumes the same Jobs rather than creating duplicates (UX-001's idempotency).
    """
    try:
        episode = service.open_episode(
            project_id=project_id, goal=goal, trace_id=trace_id, episode_id=episode_id
        )
    except EpisodeStoreError as taken:
        # The id names another episode. Nothing of it is printed and nothing is ingested into it.
        print(f"lab-brain: {taken}", file=out)
        return 1
    print(f"episode   {episode.episode_id}", file=out)
    print(f"trace     {episode.trace_id}", file=out)
    print(f"project   {episode.project_id}", file=out)
    failed = 0
    for path in fixtures:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        job = service.submit(
            project_id=project_id,
            actor_id=actor_id,
            idempotency_key=f"episode:{episode.episode_id}:{digest}",
            trace_id=trace_id,
            episode_id=episode.episode_id,
        )
        result = service.ingest(
            data,
            job_id=job.job_id,
            actor_id=actor_id,
            sensitivity_label=sensitivity,
            uri=path.resolve().as_uri(),
            media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        )
        artifact = result.artifact.artifact_id if result.artifact is not None else "-"
        state = "SUCCEEDED" if result.succeeded else "NOT SUCCEEDED"
        print(f"ingested  {path.name}  job={job.job_id}  artifact={artifact}  {state}", file=out)
        failed += 0 if result.succeeded else 1
    print("", file=out)
    try:
        view = service.inbox(actor_id=actor_id, project_id=project_id)
    except ScientificReadRefused:
        print(f"No inbox for {actor_id} in {project_id}.", file=out)
        return 1
    run_inbox(
        view.items,
        jobs_for=view.jobs_for,
        open_review_ids=view.open_review_ids,
        blocking_conflict_ids=view.blocking_conflict_ids,
        out=out,
    )
    return 0 if failed == 0 else 1


_DOCUMENT_KINDS: Mapping[str, TrustClass] = {
    "measurement": TrustClass.INTERNAL_MEASUREMENT,
    "run_record": TrustClass.INTERNAL_RUN,
    "note": TrustClass.EXPERT_HEURISTIC,
}


def run_research(
    service: ResearchEpisodeService,
    request: ResearchRequest,
    *,
    out: TextIO,
    report_path: Path | None = None,
) -> int:
    """Run one episode and print its report. The service decides everything; this prints it."""
    try:
        report = service.run(request)
    except ScientificReadRefused:
        # One message for every refusal reason -- see `inbox`.
        print(f"No research for {request.actor_id} in {request.project_id}.", file=out)
        return 1
    except ContinuationRefused as refused:
        # `EpisodeNotContinuable` is one message for an unknown id, another project's episode and
        # another actor's; the others are about the actor's own episode.
        print(str(refused), file=out)
        return 1
    text = render_markdown(report)
    if report_path is not None:
        report_path.write_text(text, encoding="utf-8")
    _emit(out, text)
    return 0


def _emit(out: TextIO, text: str) -> None:
    """Write the report even to a console that cannot encode every character in it.

    The report quotes the user's documents, which may be in any language; a terminal whose code
    page lacks a character gets a replacement rather than a traceback. `--report` is always UTF-8.
    """
    try:
        out.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(out, "encoding", None) or "ascii"
        out.write(text.encode(encoding, errors="replace").decode(encoding) + "\n")


#: What a continuation cannot carry: it resumes the episode's own inputs and framing.
_NEW_INPUTS: tuple[tuple[str, str], ...] = (
    ("measurement", "--measurement"),
    ("run_record", "--run-record"),
    ("note", "--note"),
    ("verification_input", "--verification-input"),
    ("literature_corpus", "--literature-corpus"),
    ("literature_query", "--literature-query"),
    ("symptom", "--symptom"),
    ("expected", "--expected"),
    ("observed", "--observed"),
    ("sensitivity", "--sensitivity"),
)


def _research_request(args: argparse.Namespace) -> ResearchRequest:
    if args.episode:
        given = [flag for attribute, flag in _NEW_INPUTS if getattr(args, attribute)]
        if given:
            raise ConfigurationError(
                f"--episode continues an episode over its own inputs; {', '.join(given)} "
                "cannot be added to it. New evidence to debate is a new episode: omit --episode."
            )
    elif not args.goal:
        raise ConfigurationError("--goal is required to open an episode")
    documents: list[InputDocument] = []
    for option, trust_class in _DOCUMENT_KINDS.items():
        for name in getattr(args, option):
            path = Path(name)
            documents.append(
                InputDocument(
                    name=path.name,
                    data=path.read_bytes(),
                    media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                    uri=path.resolve().as_uri(),
                    trust_class=trust_class,
                )
            )
    verification = None
    if args.verification_input:
        path = Path(args.verification_input)
        verification = (path.name, path.read_bytes())
    literature = None
    if args.literature_corpus or args.literature_query:
        if not (args.literature_corpus and args.literature_query):
            raise ConfigurationError(
                "--literature-corpus and --literature-query go together: a provider is only "
                "searched with a query you declare public"
            )
        # A provider package, not a DomainPack: `interfaces -> tool_providers` is permitted.
        from lab_brain.tool_providers.literature import LiteratureCorpusAdapter
        from lab_brain.tool_providers.literature import declaration as literature_declaration

        corpus = Path(args.literature_corpus)
        literature = LiteratureRequest(
            adapter=LiteratureCorpusAdapter.from_file(corpus, now=utc_now),
            declaration=literature_declaration(),
            query=args.literature_query,
            description=f"the local literature corpus file {corpus.name} (no network)",
        )
    return ResearchRequest(
        project_id=args.project,
        actor_id=args.actor,
        goal=args.goal or "",
        documents=tuple(documents),
        verification_input=verification,
        literature=literature,
        episode_id=args.episode,
        trace_id=args.trace,
        sensitivity=SensitivityLabel(args.sensitivity or SensitivityLabel.INTERNAL.value),
        symptom=args.symptom,
        expected_behavior=args.expected,
        observed_behavior=args.observed,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    env: Mapping[str, str] | None = None,
    connect: Callable[[Settings], Any] | None = None,
) -> int:
    """Entry point. Returns an exit code rather than calling `sys.exit`, so it is testable.

    THE CONNECTION IS OPENED HERE AND NOWHERE ELSE, and never at import time: `--help` must not
    need a database, and importing this module must not either. `env` and `connect` are
    parameters so an integration test can drive the real `main` against a real database without
    mutating the process environment -- which is the difference between testing the entry point
    and testing a function the entry point happens to call.

    A configuration problem exits 2 with a sentence naming the variable. `explain` exits 1 for a
    reference this actor cannot see, which is the same answer for an id that never existed and an
    id in another project (§17.24).

    THE CONNECTION IS CLOSED ON EVERY PATH. A CLI that leaks one is a CLI that holds a server-side
    transaction open until the shell exits, and `inbox` is exactly the command somebody leaves
    running in a loop.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    stream = out or sys.stdout
    opener = connect or open_connection

    try:
        settings = read_settings(os.environ if env is None else env)
    except ConfigurationError as exc:
        print(f"lab-brain: {exc}", file=stream)
        return 2

    try:
        connection = opener(settings)
    except ConfigurationError as exc:
        print(f"lab-brain: {exc}", file=stream)
        return 2

    if args.command == "web":
        # The database answered; the workspace opens its own connection per request.
        connection.close()
        return run_web(args, settings=settings, connect=opener, out=stream)

    try:
        if args.command == "admin":
            connection.autocommit = True
            return run_admin(args, connection, out=stream)
        if args.command == "research":
            try:
                factory = load_vertical_factory(args.domain or _only_vertical())
                request = _research_request(args)
            except (VerticalNotFound, ConfigurationError, OSError) as exc:
                print(f"lab-brain: {exc}", file=stream)
                return 2
            # The verification stores require autocommit, as every M4 caller runs them; the
            # ingestion writes keep their own explicit transactions either way.
            connection.autocommit = True
            # The CLI never reaches a language model (T-UX-006): it reasons only with the local
            # catalog reasoner. While an LLM runtime is ACTIVE for this deployment, a CLI run
            # would silently reason with something other than what is active -- so it refuses,
            # exit 2, before anything is written.
            active = active_runtime_name(connection)
            if active is not None:
                print(
                    f"lab-brain: the LLM runtime {active!r} is active in this deployment, and the "
                    "command line never calls a language model. Run this research from the "
                    "workspace (lab-brain web), or deactivate the runtime to use the local "
                    "catalog reasoner.",
                    file=stream,
                )
                return 2
            return run_research(
                ResearchEpisodeService(
                    connection=connection,
                    artifact_store=LocalArtifactStore(Path(args.artifact_root).resolve()),
                    vertical_factory=factory,
                ),
                request,
                out=stream,
                report_path=Path(args.report) if args.report else None,
            )
        if args.command == "episode":
            return run_episode_open(
                IngestionService(
                    connection=connection,
                    artifact_store=LocalArtifactStore(Path(args.artifact_root).resolve()),
                ),
                project_id=args.project,
                actor_id=args.actor,
                goal=args.goal,
                trace_id=args.trace,
                episode_id=args.episode,
                fixtures=tuple(Path(f) for f in args.fixtures),
                sensitivity=SensitivityLabel(args.sensitivity),
                out=stream,
            )
        service = IngestionService(connection=connection, artifact_store=_NoArtifactStore())
        if args.command == "inbox":
            try:
                view = service.inbox(actor_id=args.actor, project_id=args.project)
            except ScientificReadRefused:
                # ONE MESSAGE FOR EVERY REFUSAL. An unknown actor, a disabled account, a revoked
                # membership and a member of some other project all get this sentence, and it
                # says nothing about whether the project exists or holds anything. Naming the
                # reason would be a directory of projects and of who belongs to them.
                print(
                    f"No inbox for {args.actor} in {args.project}.",
                    file=stream,
                )
                return 1
            return run_inbox(
                view.items,
                jobs_for=view.jobs_for,
                open_review_ids=view.open_review_ids,
                blocking_conflict_ids=view.blocking_conflict_ids,
                out=stream,
            )
        return run_explain(
            service.diagnostics(),
            args.error_id,
            actor_id=args.actor,
            project_id=args.project,
            technical=args.technical,
            out=stream,
        )
    finally:
        connection.close()


def run_web(
    args: argparse.Namespace,
    *,
    settings: Settings,
    connect: Callable[[Settings], Any],
    out: TextIO,
    serve: Callable[..., None] | None = None,
) -> int:
    """Start the research workspace (`lab_brain.interfaces.web`) and serve until interrupted."""
    from lab_brain.interfaces.web import Workspace, allowed_hosts
    from lab_brain.interfaces.web import serve as serve_workspace

    try:
        factory = load_vertical_factory(args.domain or _only_vertical())
    except (VerticalNotFound, ConfigurationError) as exc:
        print(f"lab-brain: {exc}", file=out)
        return 2
    container = bool(getattr(args, "in_container", False))
    gateways = tuple(getattr(args, "host_gateway", ()) or ())
    if gateways and not container:
        print(
            "lab-brain: --host-gateway names the machine a container runs on, and applies only "
            "with --in-container",
            file=out,
        )
        return 2
    # In a container the browser reaches the workspace through the host's loopback port, so that
    # is the Host it must name; outside one, the port it binds.
    published = getattr(args, "published_port", None) or args.port
    credential_dir = getattr(args, "credential_dir", None)
    workspace = Workspace(
        actor_id=args.actor,
        settings=settings,
        connect=connect,
        artifact_root=Path(args.artifact_root),
        vertical_factory=factory,
        allowed_hosts=allowed_hosts("127.0.0.1" if container else args.host, published),
        default_locale=args.locale,
        local_hosts=gateways,
        credential_dir=Path(credential_dir) if credential_dir else None,
        ollama_url=getattr(args, "ollama_url", None) or None,
    )
    print(
        f"Research workspace for {args.actor}: http://"
        f"{'127.0.0.1' if container else args.host}:{published}/ (Ctrl+C stops it)",
        file=out,
    )
    try:
        # `container` only when set: the accepted call is exactly the loopback one.
        extra = {"container": True} if container else {}
        (serve or serve_workspace)(workspace, host=args.host, port=args.port, **extra)
    except ConfigurationError as exc:
        print(f"lab-brain: {exc}", file=out)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    return 0


def run_admin(args: argparse.Namespace, connection: Any, *, out: TextIO) -> int:
    """`lab-brain admin ...`: the operator's decisions, explicit and recorded (`deployment`)."""
    from lab_brain.interfaces import deployment

    try:
        if args.admin_command == "actor":
            lines = [deployment.ensure_actor(connection, args.actor_id, args.name)]
        elif args.admin_command == "project":
            lines = [
                deployment.ensure_project(connection, args.project_id, args.name, args.privacy_mode)
            ]
        elif args.admin_command == "member":
            lines = [
                deployment.set_membership(
                    connection,
                    args.project_id,
                    args.actor_id,
                    role=args.role,
                    clearance=[x.strip() for x in args.clearance.split(",") if x.strip()],
                    scopes=args.scope,
                )
            ]
        elif args.admin_command == "llm-admin":
            change = deployment.revoke_llm_admin if args.revoke else deployment.grant_llm_admin
            lines = [change(connection, args.actor_id, utc_now())]
        else:
            lines = deployment.describe(connection)
    except deployment.OperatorRefused as refused:
        print(f"lab-brain: {refused}", file=out)
        return 2
    for line in lines:
        print(line, file=out)
    return 0


def _only_vertical() -> str:
    from importlib.metadata import entry_points

    names = sorted(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP))
    if len(names) != 1:
        raise VerticalNotFound(
            f"--domain is required: installed product verticals are {names or 'none'}"
        )
    return names[0]


class _NoArtifactStore:
    """An artifact store that refuses every operation, for read-only commands.

    `IngestionService` requires one because ingesting is what it mostly does. Neither `inbox` nor
    `explain` touches bytes, so wiring a real store here would mean the CLI needed object-storage
    credentials to print a table -- and a command that holds credentials it never uses is a
    credential nobody notices has leaked.

    REFUSES LOUDLY RATHER THAN RETURNING SOMETHING EMPTY, including `discard`, which the real
    protocol requires to be total and non-raising. That requirement is about a compensating action
    after bytes were staged; nothing here ever stages any, so reaching `discard` would mean a
    read-only command had taken the write path -- which is worth a traceback rather than a silent
    success.
    """

    def stage(self, data: bytes) -> Any:
        return self._refuse()

    def promote(self, staging_id: str, content_hash: str) -> str:
        return str(self._refuse())

    def discard(self, staging_id: str) -> None:
        self._refuse()

    def open(self, content_hash: str) -> Any:
        return self._refuse()

    def exists(self, content_hash: str) -> bool:
        return bool(self._refuse())

    def list_staged(self) -> Any:
        return self._refuse()

    def _refuse(self) -> Any:
        raise NotImplementedError(
            "the read-only CLI has no artifact store; `inbox` and `explain` read durable rows "
            "and never bytes"
        )


def run_inbox(
    items: Sequence[IngestionItem],
    *,
    jobs_for: Callable[[str], Sequence[Job]] | None = None,
    open_review_ids: frozenset[str] = frozenset(),
    blocking_conflict_ids: frozenset[str] = frozenset(),
    out: TextIO,
) -> int:
    rows = build_inbox(
        items,
        jobs_for=jobs_for,
        open_review_ids=open_review_ids,
        blocking_conflict_ids=blocking_conflict_ids,
    )
    render_inbox(rows, out=out)
    return 0


def run_explain(
    service: DiagnosticsService,
    error_id: str,
    *,
    actor_id: str,
    project_id: str,
    technical: bool = False,
    out: TextIO,
) -> int:
    return render_explanation(
        service,
        error_id,
        actor_id=actor_id,
        project_id=project_id,
        technical=technical,
        out=out,
    )


def catalog() -> MessageCatalog:
    return default_catalog()


__all__ = [
    "InboxRow",
    "build_inbox",
    "build_parser",
    "catalog",
    "main",
    "render_explanation",
    "render_inbox",
    "run_episode_open",
    "run_explain",
    "run_inbox",
    "run_research",
    "run_web",
    "summarise",
]
