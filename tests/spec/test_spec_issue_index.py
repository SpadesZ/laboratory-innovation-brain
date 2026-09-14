"""`docs/spec_issues/README.md`'s index must agree with the issue documents (AGT-003).

The index is a hand-written table beside eight machine-read documents, which is the shape of every
staleness bug this repository has already had once. It duly went stale: six issues were RESOLVED in
their own headers and in IMPLEMENTATION_STATUS.md on 2026-09-12/13, and the index still said OPEN
when P5 opened it on 2026-09-14.

Nothing objected, because the only consumer of a spec issue's status is
`lab_brain.spec.outcomes.load_spec_issues`, which reads the *documents*. The index is read by
people. A table that no check reads and that humans trust is worse than no table: the executed
coverage gate would have let an "OPEN GATE" row sit next to a DONE milestone indefinitely, and a
reviewer reading the index would have believed it.

So the two are compared. The document header stays the authority -- this test never edits, it only
refuses to let the summary disagree with what it summarises.

Deliberately unmarked with requirement/spec_test markers: AGT-003 is an agent operating rule, not
one of the §25.3 Requirement IDs, and claiming one here would inflate the traceability matrix.
"""

from __future__ import annotations

import re

from lab_brain.spec import repo_root, spec_issues_dir
from lab_brain.spec.outcomes import load_spec_issues

#: `| [009](SPEC-ISSUE-009-....md) | GATE | subject | M0b | **RESOLVED** -- ... |`
_ROW = re.compile(
    r"^\|\s*\[(\d{3})\]\(([^)]+)\)\s*\|\s*([A-Z]+)\s*\|[^|]*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*$",
    re.MULTILINE,
)


def _index_rows() -> dict[str, tuple[str, str, str, str]]:
    """Issue number -> (filename, severity, blocks gate, status cell)."""
    text = (repo_root() / "docs" / "spec_issues" / "README.md").read_text(encoding="utf-8")
    return {
        match.group(1): (match.group(2), match.group(3), match.group(4), match.group(5))
        for match in _ROW.finditer(text)
    }


def _state(cell: str) -> str:
    """The state word the prose cell asserts. Refuses a cell that asserts neither."""
    if "OPEN" in cell:
        return "OPEN"
    if "RESOLVED" in cell:
        return "RESOLVED"
    raise AssertionError(
        f"index status cell {cell!r} states neither OPEN nor RESOLVED, so it cannot be compared "
        "with the document header"
    )


def test_the_index_is_parseable_and_not_empty():
    """Guard the guard: a table format change must fail here, not silently compare nothing."""
    rows = _index_rows()
    issues = load_spec_issues(spec_issues_dir())
    assert len(rows) == len(issues), (
        f"parsed {len(rows)} index rows for {len(issues)} issue documents; the table format "
        "likely changed and this check would otherwise compare a subset"
    )


def test_every_issue_document_has_an_index_row_and_every_row_a_document():
    """Both directions. A new issue nobody indexed, and an index row for a deleted file."""
    rows = _index_rows()
    documents = {
        issue.path.name.split("-")[2]: issue for issue in load_spec_issues(spec_issues_dir())
    }

    assert set(rows) == set(documents), (
        f"indexed but no document: {sorted(set(rows) - set(documents))}; "
        f"document but not indexed: {sorted(set(documents) - set(rows))}"
    )
    for number, (filename, _, _, _) in rows.items():
        assert filename == documents[number].path.name, (
            f"index row {number} links {filename}, but the document is "
            f"{documents[number].path.name}"
        )


def test_the_index_status_matches_each_document_header():
    """The regression itself: six rows said OPEN while the headers said RESOLVED."""
    rows = _index_rows()
    for issue in load_spec_issues(spec_issues_dir()):
        number = issue.path.name.split("-")[2]
        _, severity, blocks_gate, status_cell = rows[number]
        assert _state(status_cell) == issue.status.upper(), (
            f"SPEC-ISSUE-{number}: the index says {_state(status_cell)}, the document header says "
            f"{issue.status.upper()}. The header is the authority -- fix the index"
        )
        assert severity == issue.severity.upper(), (
            f"SPEC-ISSUE-{number}: index severity {severity}, document {issue.severity}"
        )
        expected_gate = issue.blocks_gate or "—"
        assert blocks_gate == expected_gate, (
            f"SPEC-ISSUE-{number}: index blocks-gate {blocks_gate!r}, document {expected_gate!r}"
        )
