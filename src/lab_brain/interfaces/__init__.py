"""User-facing entry points.

`pyproject.toml` has declared `lab-brain = "lab_brain.interfaces.cli:main"` since M0a, against a
module that did not exist -- the console script was reserved before the surface was built. M1's
scope names the CLI inbox, so this is where it lands, at the path the packaging already promised.

Nothing here computes anything. A command renders a projection or a catalog entry; the
derivations, the ACL and the catalog all live behind it and are tested on their own.
"""

from lab_brain.interfaces.cli import build_parser, main, run_explain, run_inbox

__all__ = ["build_parser", "main", "run_explain", "run_inbox"]
