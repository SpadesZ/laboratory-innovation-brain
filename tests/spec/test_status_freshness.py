"""Repository hygiene: IMPLEMENTATION_STATUS.md must agree with the code (AGT-003).

Deliberately unmarked with requirement/spec_test markers. AGT-003 is an *agent operating
rule*, not one of the 52 Requirement IDs, and claiming a Requirement ID here would inflate
the traceability matrix with something the spec never asked for.
"""

from __future__ import annotations

import subprocess
import sys

from lab_brain.spec import repo_root


def test_requirement_status_table_is_current():
    result = subprocess.run(
        [sys.executable, "scripts/update_status.py", "--check"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "IMPLEMENTATION_STATUS.md is stale — run `python scripts/update_status.py`.\n"
        f"{result.stdout}{result.stderr}"
    )
