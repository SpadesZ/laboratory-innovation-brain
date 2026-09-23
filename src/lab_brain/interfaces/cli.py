"""`lab-brain inbox` and `lab-brain explain` (UX-001, UX-003, UX-006, §17.22, §17.23, §17.24).

M1's scope names *IngestionItem / ErrorRecord / MessageCatalog + CLI inbox*. This is the CLI, and
it is deliberately two commands.

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
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

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
    jobs_for: object = None,
    open_review_ids: frozenset[str] = frozenset(),
    blocking_conflict_ids: frozenset[str] = frozenset(),
) -> tuple[InboxRow, ...]:
    """Project items into rows. The state is DERIVED, never read off the item.

    `jobs_for` is accepted and unused at M1 because no CLI caller yet has a live job list to
    supply; passing it through would let a caller hand in a stale one, and a stale job list makes
    a finished item read as PROCESSING. When the CLI grows a job source it becomes a real
    parameter rather than a plausible-looking default.
    """
    rows = [
        InboxRow(
            item_id=item.item_id,
            state=derive_state(
                item,
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
    return parser


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """Entry point. Returns an exit code rather than calling `sys.exit`, so it is testable.

    Wiring a real database is deliberately NOT done here: this module is the presentation
    boundary, and a `psycopg.connect` at import time would make the CLI untestable without a
    backend and would put connection policy in the least reviewed file in the repository.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    stream = out or sys.stdout
    print(
        f"lab-brain {args.command}: wire a connection through "
        "lab_brain.interfaces.cli.run_* to use this command against a database",
        file=stream,
    )
    return 2


def run_inbox(
    items: Sequence[IngestionItem],
    *,
    open_review_ids: frozenset[str] = frozenset(),
    blocking_conflict_ids: frozenset[str] = frozenset(),
    out: TextIO,
) -> int:
    rows = build_inbox(
        items,
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
    "run_explain",
    "run_inbox",
    "summarise",
]
