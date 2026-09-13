"""Refresh the occurrence-level obligation inventory against the specification.

The inventory's classifications are human judgements and live in the YAML, which is the source of
truth for them. This script does the mechanical half: re-extracts every hard-obligation keyword
occurrence from §6-§16, carries each existing classification forward by ``occurrence_id``, and
refreshes the quote, keyword and digest so they match the document again.

It refuses to guess. A new occurrence is reported and left unclassified; a removed one is reported
and dropped only with ``--prune``; a reworded one is reported as drift. In every case the exit
status is non-zero, because all three need a maintainer to re-adjudicate rather than a script to
decide.

    python scripts/rebuild_obligation_inventory.py            # refresh in place, report
    python scripts/rebuild_obligation_inventory.py --check    # report only, write nothing
    python scripts/rebuild_obligation_inventory.py --prune    # also drop rows the spec lost
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_brain.spec.coverage_audit import (
    hard_obligation_occurrences,
    load_obligation_inventory,
    obligation_inventory_path,
)

_FIELD_ORDER = (
    "occurrence_id",
    "section",
    "keyword",
    "quote_digest",
    "quote",
    "classification",
    "target",
    "note",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only; do not write")
    parser.add_argument("--prune", action="store_true", help="drop rows whose occurrence is gone")
    args = parser.parse_args(argv)

    path = obligation_inventory_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    existing = {row["occurrence_id"]: dict(row) for row in raw["occurrences"]}
    # Validate shape before touching anything, and learn which rows are hand-adjudicated: the
    # 需-phrased occurrences hold an extract rather than a whole line, so they are neither
    # re-extractable nor stale when the scan does not find them.
    manual = {row.occurrence_id for row in load_obligation_inventory(path) if row.is_manual}

    occurrences = {o.occurrence_id: o for o in hard_obligation_occurrences()}

    new = [oid for oid in occurrences if oid not in existing]
    gone = [oid for oid in existing if oid not in occurrences and oid not in manual]
    drifted: list[str] = []

    rows: list[dict[str, object]] = []
    for oid, occurrence in occurrences.items():
        row = existing.get(oid)
        if row is None:
            rows.append(
                {
                    "occurrence_id": oid,
                    "section": occurrence.section,
                    "keyword": occurrence.keyword,
                    "quote_digest": occurrence.quote_digest,
                    "quote": occurrence.quote,
                    "classification": "UNCLASSIFIED",
                    "note": "NEW OCCURRENCE -- adjudicate: REGISTERED / RESTATEMENT_OF / "
                    "NON_NORMATIVE_WITH_RATIONALE",
                }
            )
            continue
        if row.get("quote_digest") != occurrence.quote_digest:
            drifted.append(oid)
        row["section"] = occurrence.section
        row["keyword"] = occurrence.keyword
        row["quote_digest"] = occurrence.quote_digest
        row["quote"] = occurrence.quote
        rows.append(row)

    for oid in sorted(manual):
        rows.append(existing[oid])
    if not args.prune:
        for oid in gone:
            rows.append(existing[oid])

    def sort_key(row: dict[str, object]) -> tuple[list[int], int]:
        section, _, ordinal = str(row["occurrence_id"]).partition("#")
        return (
            [int(p) for p in section.split(".")],
            int(ordinal.lstrip("M")) + (1000 if ordinal.startswith("M") else 0),
        )

    rows.sort(key=sort_key)
    ordered = [
        {
            field: row[field]
            for field in _FIELD_ORDER
            if field in row and row[field] not in ("", None)
        }
        for row in rows
    ]

    if not args.check:
        header = path.read_text(encoding="utf-8").split("schema_version:")[0]
        raw["occurrences"] = ordered
        path.write_text(
            header + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )

    for label, ids in (("NEW (unclassified)", new), ("GONE from spec", gone), ("DRIFTED", drifted)):
        if ids:
            print(f"{label}: {', '.join(sorted(ids))}")
    if new or gone or drifted:
        print("\nRe-adjudicate the rows above. Classifications are not inherited across an edit.")
        return 1
    print(f"{len(ordered)} occurrences, all adjudicated and in sync with the spec.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
