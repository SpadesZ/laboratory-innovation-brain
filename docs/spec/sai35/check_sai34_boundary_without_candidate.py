"""OD-10 proposal A' (PROPOSAL, pending Owner decision OD-10): hold the SAI 3.4 change boundary
on the tree WITHOUT the SAI 3.5 candidate, using the UNMODIFIED SAI 3.4 activation checker.

Run (this is the CI command):

    python docs/spec/sai35/check_sai34_boundary_without_candidate.py --self-test \
        -- python docs/spec/sai34/check_activation.py --self-test

What it does, in order:

1. Reads `docs/spec/sai35/candidate-paths.txt`: every path the SAI 3.5 candidate adds relative to
   the SAI 3.4 integration commit `a38ad63` (`.github/workflows/ci.yml` excluded: SAI 3.4 already
   allows it).
2. Refuses, before touching anything, when
   - a candidate path is a SAI 3.3 or SAI 3.4 protected path (or lies under `docs/spec/sai34/`);
   - a candidate path lies under `src/`, `migrations/`, `tests/`, `scripts/` or `.github/`;
   - a candidate path already existed at `a38ad63` (the candidate may only ADD files, so that
     deleting it restores the `a38ad63` tree exactly);
   - the set of paths that HEAD changes relative to `a38ad63` is not exactly
     candidate-paths + {`.github/workflows/ci.yml`};
   - any file under `docs/spec/sai34/` differs from `a38ad63` (the SAI 3.4 checker must be the
     unmodified one);
   - the inner command is anything other than `python docs/spec/sai34/check_activation.py
     [--self-test]`.
3. Creates a temporary detached `git worktree` of HEAD, deletes exactly the candidate paths from
   its working tree (no commit: the SAI 3.4 checker compares the working tree with its
   integration base and lists untracked files), runs the SAI 3.4 checker from inside that
   worktree, removes the worktree, and exits with the checker's status.

With `--self-test` it also (a) rejects a set of in-memory negative mutations of the refusal rules
and (b) runs a control: the same SAI 3.4 checker on a worktree of HEAD WITH the candidate present
MUST fail. The control shows that the SAI 3.4 boundary still sees and rejects the candidate; only
the candidate's own, enumerated paths are set aside, and nothing else.

What it proves: the tree minus the listed candidate paths satisfies the unmodified SAI 3.4
checker, and the candidate touches no protected, runtime, migration, test or script path.
What it does not prove: anything about the candidate's content. That is
`docs/spec/sai35/check_candidate.py`. Uncommitted changes in the invoking working tree are not
part of the check (the temporary worktree is HEAD).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[3]
BASE_REVISION = "a38ad63a4f4ad83c895cbd1e32b2e760d878f356"
CANDIDATE_PATHS = "docs/spec/sai35/candidate-paths.txt"
WORKFLOW = ".github/workflows/ci.yml"
SAI34_DIR = "docs/spec/sai34/"
SAI34_CHECKER = "docs/spec/sai34/check_activation.py"
SAI34_ACTIVATION = "docs/spec/sai34/activation.yaml"
FORBIDDEN_PREFIXES = ("src/", "migrations/", "tests/", "scripts/", ".github/")
# SAI 3.3 / SAI 3.4 files that no SAI 3.5 candidate path may be. The SAI 3.4 registry's frozen
# candidate files and inherited baselines are added from activation.yaml at run time.
PROTECTED_FIXED = frozenset(
    {
        "docs/spec/ACTIVE_SPEC.yaml",
        "docs/spec/SAI_3.3.md",
        "docs/spec/SAI_3.4.md",
        "docs/spec/SAI_3.4_Candidate.md",
        "docs/normative_statements.yaml",
        "docs/milestones.yaml",
        "docs/architecture/sai34-autonomous-modeling.md",
        "docs/adr/ADR-0013-autonomous-scientific-modeling-candidate.md",
        "docs/adr/ADR-0014-phased-sai34-activation.md",
    }
)
ALLOWED_INNER = (
    ("python", SAI34_CHECKER, "--self-test"),
    ("python", SAI34_CHECKER),
)


class Refused(Exception):
    """The mechanism refuses to run: the candidate is not a pure, documentation-only addition."""


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, encoding="utf-8").strip()


def read_candidate_paths(text: str) -> list[str]:
    paths = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            paths.append(line)
    return paths


def protected_paths() -> frozenset[str]:
    registry = yaml.safe_load(git("show", f"{BASE_REVISION}:{SAI34_ACTIVATION}"))
    extra = set(registry["frozen_candidate_files"]) | set(
        registry["inherited_profile"]["file_hashes"]
    )
    return PROTECTED_FIXED | extra


def validate(
    candidate: list[str],
    changed: set[str],
    existed_at_base: set[str],
    protected: frozenset[str],
    sai34_changed: set[str],
    inner: tuple[str, ...],
) -> None:
    """Every refusal rule of the module docstring, as a pure function (self-tested below)."""
    if not candidate:
        raise Refused("candidate-paths.txt lists no path")
    if len(candidate) != len(set(candidate)):
        raise Refused("candidate-paths.txt lists a path twice")
    if candidate != sorted(candidate):
        raise Refused("candidate-paths.txt is not sorted")
    for path in candidate:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or path != pure.as_posix():
            raise Refused(f"not a normalized relative path: {path}")
        if path == WORKFLOW:
            raise Refused(f"{WORKFLOW} is allowed by SAI 3.4 and must not be a candidate path")
        if path in protected or path.startswith(SAI34_DIR):
            raise Refused(f"candidate path is a SAI 3.3/3.4 protected path: {path}")
        if path.startswith(FORBIDDEN_PREFIXES):
            raise Refused(f"candidate path is runtime, migration, test, script or CI: {path}")
        if path in existed_at_base:
            raise Refused(f"candidate path existed at {BASE_REVISION[:7]}; only additions: {path}")
    expected = set(candidate) | {WORKFLOW}
    if changed != expected:
        raise Refused(
            "paths changed vs base are not exactly candidate-paths + ci.yml: "
            f"unlisted {sorted(changed - expected)}, "
            f"listed but unchanged {sorted(expected - changed)}"
        )
    if sai34_changed:
        raise Refused(f"SAI 3.4 files differ from base (not unmodified): {sorted(sai34_changed)}")
    if inner not in ALLOWED_INNER:
        raise Refused(f"inner command must be one of {ALLOWED_INNER}, got {inner}")


def run_in_worktree(
    inner: tuple[str, ...], delete: list[str], capture: bool = False
) -> tuple[int, str]:
    """Run the SAI 3.4 checker in a temporary detached worktree of HEAD minus `delete`."""
    parent = Path(tempfile.mkdtemp(prefix="sai34-boundary-"))
    tree = parent / "tree"
    git("worktree", "add", "--detach", "--quiet", str(tree), "HEAD")
    try:
        for path in delete:
            target = tree / path
            if not target.is_file():
                raise Refused(f"candidate path missing from HEAD's tree: {path}")
            target.unlink()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, str(tree / inner[1]), *inner[2:]]
        done = subprocess.run(
            command, cwd=tree, env=env, check=False, capture_output=capture, text=True
        )
        output = (done.stdout or "") + (done.stderr or "")
        return done.returncode, output
    finally:
        git("worktree", "remove", "--force", str(tree))
        shutil.rmtree(parent, ignore_errors=True)


def gather(inner: tuple[str, ...]) -> dict:
    candidate_text = git("show", f"HEAD:{CANDIDATE_PATHS}")
    candidate = read_candidate_paths(candidate_text)
    changed = set(git("diff", "--name-only", BASE_REVISION, "HEAD").splitlines())
    base_tree = set(git("ls-tree", "-r", "--name-only", BASE_REVISION).splitlines())
    sai34 = set(git("diff", "--name-only", BASE_REVISION, "HEAD", "--", SAI34_DIR).splitlines())
    return {
        "candidate": candidate,
        "changed": changed,
        "existed_at_base": base_tree & set(candidate),
        "protected": protected_paths(),
        "sai34_changed": sai34,
        "inner": inner,
    }


def _mutations() -> dict[str, Callable[[dict], None]]:
    def add(path: str) -> Callable[[dict], None]:
        def mutate(state: dict) -> None:
            state["candidate"] = sorted([*state["candidate"], path])
            state["changed"] = state["changed"] | {path}

        return mutate

    def setter(key: str, value: object) -> Callable[[dict], None]:
        return lambda state: state.__setitem__(key, value)

    return {
        "runtime_src": add("src/lab_brain/discovery/loop.py"),
        "migration": add("migrations/099_sai35.sql"),
        "test": add("tests/spec/test_sai35.py"),
        "script": add("scripts/sai35.py"),
        "ci_workflow_listed": add(WORKFLOW),
        "github_other": add(".github/workflows/other.yml"),
        "protected_sai34_spec": add("docs/spec/SAI_3.4.md"),
        "protected_sai33_spec": add("docs/spec/SAI_3.3.md"),
        "protected_active_spec": add("docs/spec/ACTIVE_SPEC.yaml"),
        "protected_registry": add("docs/normative_statements.yaml"),
        "under_sai34_dir": add("docs/spec/sai34/sai35-note.md"),
        "parent_escape": add("docs/spec/sai35/../../../src/x.py"),
        "duplicate": lambda s: s.__setitem__("candidate", s["candidate"] + s["candidate"][:1]),
        "unsorted": lambda s: s.__setitem__("candidate", list(reversed(s["candidate"]))),
        "unlisted_change": lambda s: s.__setitem__("changed", s["changed"] | {"docs/x.md"}),
        "listed_unchanged": lambda s: s.__setitem__("changed", s["changed"] - {s["candidate"][0]}),
        "ci_unchanged": lambda s: s.__setitem__("changed", s["changed"] - {WORKFLOW}),
        "existed_at_base": lambda s: s.__setitem__("existed_at_base", {s["candidate"][0]}),
        "sai34_checker_edited": setter("sai34_changed", {SAI34_CHECKER}),
        "other_inner_command": setter("inner", ("python", "-c", "pass")),
        "empty": setter("candidate", []),
    }


def self_test(state: dict) -> int:
    rejected = 0
    for name, mutate in _mutations().items():
        damaged = {
            key: (set(value) if isinstance(value, set) else value) for key, value in state.items()
        }
        damaged["candidate"] = list(state["candidate"])
        mutate(damaged)
        try:
            validate(**damaged)
        except Refused:
            rejected += 1
            continue
        raise AssertionError(f"self-test: mutation {name!r} was not refused")
    return rejected


def parse_inner(argv: list[str]) -> tuple[str, ...]:
    if "--" in argv:
        return tuple(argv[argv.index("--") + 1 :])
    return ALLOWED_INNER[0]


def main(argv: list[str]) -> int:
    own = argv[: argv.index("--")] if "--" in argv else argv
    inner = parse_inner(argv)
    state = gather(inner)
    try:
        validate(**state)
    except Refused as refusal:
        print(f"REFUSED (OD-10 proposal A'): {refusal}", file=sys.stderr)
        return 2
    dirty = git("status", "--porcelain", "--untracked-files=normal")
    if dirty:
        print("NOTE: the invoking working tree has uncommitted changes; they are not checked.")
    if "--self-test" in own:
        count = self_test(state)
        print(f"self-test: all {count} refusal mutations refused")
        control, output = run_in_worktree(inner, delete=[], capture=True)
        if control == 0:
            print(
                "self-test FAILED: the SAI 3.4 checker accepted HEAD WITH the candidate; "
                "the control must fail",
                file=sys.stderr,
            )
            return 1
        last = (output.strip().splitlines() or [""])[-1][:300]
        print(
            "self-test: control OK, the unmodified SAI 3.4 checker on HEAD WITH the candidate "
            f"exits {control}: {last}"
        )
    status, _ = run_in_worktree(inner, delete=state["candidate"])
    head = git("rev-parse", "--short", "HEAD")
    if status == 0:
        print(
            f"SAI 3.4 boundary OK on HEAD {head} without the SAI 3.5 candidate: "
            f"{len(state['candidate'])} candidate paths set aside, docs/spec/sai34 unmodified, "
            "no protected/runtime/migration/test/script path in the candidate "
            "(OD-10 proposal A', pending Owner decision)."
        )
    else:
        print(f"SAI 3.4 checker FAILED (exit {status}) on HEAD {head} without the candidate.")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
