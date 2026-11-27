"""Upgrade a COPY of a V1 development database to the branch's migrations; prove no row changed.

Usage (repo root of the commit under test, PYTHONPATH="src;."):
    python upgrade_check.py <source database> <copy name>
The source is copied with CREATE DATABASE ... TEMPLATE and never written. Every table's rows are
fingerprinted over the columns that existed before the upgrade, before and after it.
"""

from __future__ import annotations

import subprocess
import sys

import psycopg

BASE = "postgresql://lab_brain:lab_brain@localhost:5433/"
source, copy = sys.argv[1], sys.argv[2]


def fingerprints(url: str, columns: dict[str, list[str]] | None = None):  # type: ignore[no-untyped-def]
    with psycopg.connect(url, autocommit=True) as c:
        if columns is None:
            columns = {}
            for (table,) in c.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"
            ).fetchall():
                columns[table] = [
                    r[0]
                    for r in c.execute(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                        (table,),
                    ).fetchall()
                ]
        out = {}
        for table, cols in columns.items():
            listed = ", ".join(f'"{x}"' for x in cols)
            row = c.execute(
                f"SELECT count(*), md5(coalesce(string_agg(r::text, '|' ORDER BY r::text), ''))"
                f' FROM (SELECT ROW({listed}) AS r FROM "{table}") s'
            ).fetchone()
            out[table] = row
        return columns, out


with psycopg.connect(BASE + "postgres", autocommit=True) as admin:
    admin.execute(f'DROP DATABASE IF EXISTS "{copy}" WITH (FORCE)')
    admin.execute(f'CREATE DATABASE "{copy}" TEMPLATE "{source}"')

columns, before = fingerprints(BASE + copy)
print(f"{source} -> copy {copy}: {len(columns)} tables, {sum(v[0] for v in before.values())} rows")
for argv in ((), (), ("--status",)):
    result = subprocess.run(
        [sys.executable, "scripts/migrate.py", "--database-url", BASE + copy, *argv],
        capture_output=True,
        text=True,
    )
    print(f"$ migrate.py {' '.join(argv)} -> exit {result.returncode}")
    print("  " + "\n  ".join((result.stdout + result.stderr).strip().splitlines()[-4:]))
_, after = fingerprints(BASE + copy, columns)
changed = [t for t in columns if before[t] != after[t]]
print(f"rows in pre-existing tables changed by the upgrade: {changed or 'none'}")
with psycopg.connect(BASE + copy, autocommit=True) as c:
    for sql in (
        "SELECT grant_id, enrolment_id IS NULL, signature IS NULL FROM diagnostic_warrant_grants",
        "SELECT failure_analysis_id, resolution_status, warrant_refs FROM failure_analyses"
        " WHERE resolution_status = 'CONFIRMED'",
        "SELECT count(*) FROM failure_analysis_flags",
        "SELECT count(*) FROM schema_migrations",
    ):
        print(f"{sql[:70]}... -> {c.execute(sql).fetchall()}")
