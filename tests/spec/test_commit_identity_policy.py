"""Commit authorship is checked on the Git identity too, against the Owner's explicit policy.

Deliberately unmarked, like `test_commit_message_hygiene.py`: a repository contribution rule, not a
Requirement, and the 59 <-> 59 traceability invariant is untouched.

WHY THIS EXISTS. The message rule alone passed the old `g0-exploratory-screening` branch. Its twelve
commits carry no trailer and no credit line -- their messages are ordinary engineering prose -- yet
every one was authored and committed as `Claude <noreply@anthropic.com>`. That branch is the
negative example here twice over: as a frozen record of its metadata (so the test survives the
branch being deleted), and live when the ref is present.

EVERY ADVERSARIAL SHAPE IS A REAL REPOSITORY. A merge that brings in an AI-authored commit from
another branch, a squash whose platform message credits an AI co-author, a cherry-pick whose
author was reset, and a force-push that rewrites history under an already-checked tip are each
built with git and run through the CLI, because "the pure function is right" is not the claim
"the gate refuses it".
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lab_brain.spec import repo_root
from tests.spec.test_commit_message_hygiene import GATE, _checker

POLICY = """version = 1

[[humans]]
id = "alice"
names = ["Alice Human"]
emails = ["alice@example.com"]

[[humans]]
id = "cody"
names = ["Cody Person"]
emails = ["cody@example.org"]

[[platform_committers]]
id = "github-web-flow"
names = ["GitHub"]
emails = ["noreply@github.com"]
"""

ALICE = ("Alice Human", "alice@example.com")
AI = ("Claude", "noreply@anthropic.com")
GITHUB = ("GitHub", "noreply@github.com")


def _policy():
    return _checker().parse_policy(POLICY)


def _record(author=ALICE, committer=ALICE, message="A change\n", sha="a" * 40):
    return _checker().CommitRecord(sha, *author, *committer, message)


# --------------------------------------------------------------------------------------------
# The pure rule: identities against the policy.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("author", "committer", "expected"),
    [
        (AI, AI, ["author Claude <noreply@anthropic.com> is an AI identity", "committer"]),
        (ALICE, AI, ["committer Claude <noreply@anthropic.com> is an AI identity"]),
        (AI, ALICE, ["author Claude <noreply@anthropic.com> is an AI identity"]),
        # The display-name evasion: the address still names the vendor.
        (("Pair Programmer", "noreply@anthropic.com"), ALICE, ["is an AI identity"]),
        (("Alice Human", "noreply@anthropic.com"), ALICE, ["is an AI identity"]),
        (("Copilot", "198982749+Copilot@users.noreply.github.com"), ALICE, ["is an AI identity"]),
        (
            ("copilot-swe-agent[bot]", "198982749+copilot-swe-agent[bot]@users.noreply.github.com"),
            ALICE,
            ["is an AI identity"],
        ),
        (("Devin", "158243242+devin-ai-integration[bot]@users.noreply.github.com"), ALICE, ["AI"]),
        (("Gemini Code Assist", "bot@example.com"), ALICE, ["is an AI identity"]),
        # Fail closed: a person nobody listed is refused until the Owner lists them.
        (("Mallory", "mallory@example.com"), ALICE, ["is not a human listed"]),
        # A listed name with another address, and a listed address under another name.
        (("Alice Human", "alice@evil.example"), ALICE, ["is not a human listed"]),
        (("Someone Else", "alice@example.com"), ALICE, ["is not a human listed"]),
        (ALICE, ("Mallory", "mallory@example.com"), ["committer Mallory"]),
        # The platform may commit for a person; it may never author.
        (GITHUB, GITHUB, ["is a platform committer, which may not author"]),
    ],
)
def test_an_ai_or_unlisted_identity_is_refused(author, committer, expected):
    problems = _checker().find_identity_problems(_record(author, committer), _policy())
    assert problems, f"{author} / {committer} passed"
    for needle in expected:
        assert any(needle in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("author", "committer"),
    [
        (ALICE, ALICE),
        # A web-UI merge or squash: the person authors, the platform commits.
        (ALICE, GITHUB),
        # A person whose given name is also an AI product's name is still a person.
        (("Cody Person", "cody@example.org"), ALICE),
        # Address case is not identity.
        (("Alice Human", "Alice@Example.com"), ALICE),
    ],
)
def test_a_listed_human_passes(author, committer):
    assert _checker().find_identity_problems(_record(author, committer), _policy()) == []


@pytest.mark.parametrize(
    ("policy", "why"),
    [
        (POLICY.replace("Alice Human", "Claude"), "names an AI"),
        (POLICY.replace("alice@example.com", "noreply@anthropic.com"), "names an AI"),
        (POLICY.replace('"noreply@github.com"', '"copilot@users.noreply.github.com"'), "an AI"),
        ("version = 1\n", "lists no human"),
        (POLICY.replace("version = 1", "version = 2"), "version = 1"),
        (POLICY.replace('emails = ["alice@example.com"]', "emails = []"), "needs an id"),
        ("version = 1\nhumans = 'x'\n", "must be a list"),
        ("not = [toml", "not valid TOML"),
    ],
)
def test_a_policy_cannot_authorise_an_ai_or_be_malformed(policy, why):
    with pytest.raises(_checker().PolicyError, match=why):
        _checker().parse_policy(policy)


def test_the_repository_policy_parses_and_lists_the_owner():
    policy = _checker().load_policy()
    assert policy.human("SpadesZ", "rickiekuo1203@gmail.com") is not None
    assert policy.platform(*GITHUB) is not None
    assert policy.human(*GITHUB) is None, "the platform must never be a listed author"


# --------------------------------------------------------------------------------------------
# The old branch, as recorded. Frozen here so the negative example outlives the branch.
# --------------------------------------------------------------------------------------------

#: `git log origin/main..origin/g0-exploratory-screening`, every commit not authored by the Owner.
#: Author and committer were both `Claude <noreply@anthropic.com>`; no message had a trailer.
OLD_BRANCH = (
    ("0c274eaf6910fa5f39c62c79df9e02a34fd0fa3f", "Name screening readings in the reader's words"),
    ("9e4f53ac6518f2595a0ac5eab744e722ebdea80a", "Let the live-model retest run each screening"),
    ("c07b7c961645a0eb9f1b4755eb9b91fef9347391", "Count the Gemini replies separately"),
    ("17a59b09091613179c4814f43b4eaf7431730831", "Correct the stale Gemini JSON-schema statement"),
    ("de6a7c694cc209f7aef8ec2e86bce1dbda7b4b37", "Give the class-label layer its own gate check"),
    ("c018054448fa27859181d1748763339234a46d84", "Format the screening tests"),
    ("e8584f3a17c1e5a4f982c1047baeb4e128bcfafa", "Add the offline G0 screening matrix"),
    ("8e65341875ffcc6a5856411b9f1c7866d4f634bc", "Freeze the offline G0 screening protocol"),
    ("3787909f3026c38563ce08cec11d1d80b9ace284", "Test exploratory screening offline"),
    ("c123a94f118cbd728494b3bb76502d96abcd3889", "Show exploratory screening on the episode page"),
    ("d491ed23d3e5f37e03936f6fee5f742a8d543326", "Add governed exploratory screening"),
    ("8a04c33aad57c0936a04b1a2a554d19ef61a6d20", "Seal the G0 screening holdout cases"),
)


def test_the_old_branch_passed_the_message_rule_and_fails_the_identity_rule():
    checker = _checker()
    records = [
        _record(AI, AI, f"{subject}\n\nOrdinary prose.\n", sha) for sha, subject in OLD_BRANCH
    ]
    assert all(checker.find_ai_attribution(record.message) == [] for record in records), (
        "the old branch's messages were clean; that is exactly why a message check was not enough"
    )
    failures, _ = checker.check_commits(records, records, checker.load_policy())
    for sha, _subject in OLD_BRANCH:
        assert any(line.startswith(sha[:12]) for line in failures), sha


OLD_REF = "refs/remotes/origin/g0-exploratory-screening"


def _has_ref(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", "-q", ref], cwd=repo_root(), capture_output=True
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _has_ref(OLD_REF), reason="the old branch is not fetched here")
def test_the_live_old_branch_is_refused_by_the_cli():
    result = subprocess.run(
        [sys.executable, str(repo_root() / GATE), "--tip", OLD_REF],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    refused = [line for line in result.stderr.splitlines() if "is an AI identity" in line]
    assert len(refused) == 2 * len(OLD_BRANCH), result.stderr


# --------------------------------------------------------------------------------------------
# Real repositories: merge, squash, cherry-pick, force-push.
# --------------------------------------------------------------------------------------------


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.policy = path.parent / "policy.toml"
        self.policy.write_text(POLICY, encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.commit("first", ALICE)

    def git(self, *args: str, who=ALICE, committer=None) -> str:
        committer = committer or who
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": who[0],
            "GIT_AUTHOR_EMAIL": who[1],
            "GIT_COMMITTER_NAME": committer[0],
            "GIT_COMMITTER_EMAIL": committer[1],
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        result = subprocess.run(
            ["git", "-C", str(self.path), "-c", "commit.gpgsign=false", *args],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def commit(self, name: str, who, committer=None, message=None) -> str:
        (self.path / f"{name}.txt").write_text(name, encoding="utf-8")
        self.git("add", "-A", who=who)
        self.git("commit", "-q", "-m", message or name, who=who, committer=committer)
        return self.git("rev-parse", "HEAD")

    def gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(repo_root() / GATE), "--policy", str(self.policy), *args],
            cwd=self.path,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    path = tmp_path / "repo"
    path.mkdir()
    return Repo(path)


def _whole_history(repo: Repo, tip: str = "HEAD") -> subprocess.CompletedProcess[str]:
    # `--range <tip>` walks everything the tip reaches, messages and identities alike -- the shape
    # the default mode has for identities in this repository, without its message floor.
    return repo.gate("--range", tip)


def test_a_clean_human_history_passes(repo):
    repo.commit("second", ALICE, GITHUB)
    result = _whole_history(repo)
    assert result.returncode == 0, result.stderr
    assert "no AI authorship found" in result.stdout


def test_an_ai_commit_inherited_through_a_merge_is_refused(repo):
    repo.git("checkout", "-q", "-b", "side")
    smuggled = repo.commit("from-the-ai", AI)
    repo.commit("tidy-up", ALICE)
    repo.git("checkout", "-q", "main")
    repo.commit("mainline", ALICE)
    repo.git("merge", "-q", "--no-ff", "side", "-m", "Merge the side branch")
    result = _whole_history(repo)
    assert result.returncode == 1
    assert smuggled[:12] in result.stderr and "is an AI identity" in result.stderr
    # The merge commit itself, and the human commits it brought, are not what failed.
    assert result.stderr.count("is an AI identity") == 2


def test_a_squash_crediting_an_ai_co_author_is_refused_and_a_clean_squash_passes(repo):
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit("work", AI)
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--squash", "feature")
    # The squash's author is the person and the committer is the platform, as on GitHub. The AI's
    # authorship survives only in the platform's generated trailer -- and the message rule reads it.
    repo.git(
        "commit",
        "-q",
        "-m",
        "Add the work (#7)\n\nCo-authored-by: Claude <noreply@anthropic.com>",
        who=ALICE,
        committer=GITHUB,
    )
    squash = repo.git("rev-parse", "HEAD")
    result = repo.gate("--range", f"{squash}~1..{squash}")
    assert result.returncode == 1 and "Co-authored-by" in result.stderr

    repo.git("commit", "-q", "--amend", "-m", "Add the work (#7)", who=ALICE, committer=GITHUB)
    result = repo.gate("--range", "HEAD~1..HEAD")
    assert result.returncode == 0, result.stderr


def test_a_cherry_pick_keeps_and_a_reset_author_does_not_launder_the_original(repo):
    repo.git("checkout", "-q", "-b", "elsewhere")
    original = repo.commit("ai-change", AI)
    repo.git("checkout", "-q", "main")

    # Kept author: the pick is itself an AI-authored commit.
    repo.git("cherry-pick", "-x", original, who=ALICE)
    result = repo.gate("--range", "HEAD~1..HEAD")
    assert result.returncode == 1 and "author Claude" in result.stderr

    # Reset author: the pick looks human, but `-x` names the original, which is present.
    repo.git("commit", "-q", "--amend", "--reset-author", "--no-edit", who=ALICE)
    result = repo.gate("--range", "HEAD~1..HEAD")
    assert result.returncode == 1, result.stderr
    assert f"cherry-picked from {original[:12]}: author Claude" in result.stderr


def test_a_cherry_pick_whose_origin_is_absent_is_a_warning_not_a_silent_pass(repo):
    repo.commit("picked", ALICE, message="Picked\n\n(cherry picked from commit " + "f" * 40 + ")")
    result = repo.gate("--range", "HEAD~1..HEAD")
    assert result.returncode == 0
    assert "not present here" in result.stderr


def test_a_force_push_cannot_slip_an_unexamined_commit_under_a_checked_tip(repo):
    repo.commit("second", ALICE)
    checked = repo.git("rev-parse", "HEAD")
    assert _whole_history(repo, checked).returncode == 0
    # Rewrite: an AI-authored commit inserted below a fresh human tip, as a force-push would.
    repo.git("reset", "-q", "--hard", "HEAD~1")
    hidden = repo.commit("inserted", AI)
    repo.commit("second", ALICE)
    rewritten = repo.git("rev-parse", "HEAD")
    assert rewritten != checked
    result = _whole_history(repo, rewritten)
    assert result.returncode == 1 and hidden[:12] in result.stderr


def test_an_ai_committer_alone_is_refused(repo):
    repo.commit("second", ALICE, committer=AI)
    result = _whole_history(repo)
    assert result.returncode == 1 and "committer Claude" in result.stderr


def test_a_missing_or_ai_listing_policy_refuses_everything(repo):
    repo.policy.write_text(POLICY.replace("Alice Human", "Claude"), encoding="utf-8")
    assert repo.gate("--range", "HEAD").returncode == 1
    repo.policy.unlink()
    result = repo.gate("--range", "HEAD")
    assert result.returncode == 1 and "no commit identity policy" in result.stderr


# --------------------------------------------------------------------------------------------
# CI wiring: the gate checks the pushed or proposed tip, and the negative control runs.
# --------------------------------------------------------------------------------------------


def _hygiene_job():
    workflow = yaml.safe_load((repo_root() / ".github/workflows/ci.yml").read_text("utf-8"))
    return workflow["jobs"]["commit-hygiene"]


def test_ci_checks_the_proposed_head_not_the_synthetic_merge():
    steps = _hygiene_job()["steps"]
    gate = [step for step in steps if GATE in str(step.get("run", "")) and "--tip" in step["run"]]
    assert gate, "the CI gate must pass --tip so a pull request's own commits are what is walked"
    env = gate[0].get("env", {})
    assert "pull_request.head.sha" in str(env.get("TIP", "")), env


def test_ci_runs_a_negative_control_against_a_known_ai_authored_tip():
    runs = " ".join(str(step.get("run", "")) for step in _hygiene_job()["steps"])
    assert "g0-exploratory-screening" in runs and "expected" in runs
