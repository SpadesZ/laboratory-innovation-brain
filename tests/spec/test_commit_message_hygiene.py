"""Commit messages must not attribute authorship to an AI, and CI must be what says so.

Deliberately unmarked: this validates a **repository contribution rule**, not a Requirement. It
adds no Requirement or Test ID and the 59 <-> 59 traceability invariant is untouched -- the same
footing as `test_ci_workflow.py`, which validates the delivery pipeline rather than discharging a
normative obligation.

THE RULE HAS TWO FAILURE DIRECTIONS AND BOTH ARE TESTED. A rule of this kind is usually written
only against the thing it forbids, which is how it ends up also forbidding ordinary work. So the
cases below come in pairs: every prohibited shape has a permitted near-neighbour that differs only
in whether the credited author is a person.

    rejected                                     allowed
    an AI co-author trailer                      a human co-author trailer
    a key that declares AI authorship            a body paragraph about AI providers
    a bare "generated with <model>" footer        "Generated with care", "generated with the
                                                  <model> client, then checked by hand"

THE FIXTURES CONTAIN THE PROHIBITED PATTERNS ON PURPOSE, and that is safe: the gate reads commit
*messages*, never file contents. A test suite that could not name what it forbids would be checking
something else.

WHY THERE IS AN END-TO-END CASE AS WELL AS UNIT CASES. `find_ai_attribution` being correct is not
the same claim as "a commit is refused". The CLI, its exit status and the hook's delegation are
each a place the rule could be correct and still not hold, so each is exercised against a real
temporary repository.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from lab_brain.spec import repo_root

GATE = "scripts/check_commit_messages.py"


def _checker():
    """Load `scripts/check_commit_messages.py` as a module.

    Loaded from the file rather than imported, because `scripts/` is not a package -- the same
    arrangement `test_migration_numbering.py` uses for `migrate.py`, and for the same reason. The
    module is registered in `sys.modules` before execution so its dataclass can resolve its own
    annotations.
    """
    name = "lab_brain_check_commit_messages"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, repo_root() / GATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _violations(message: str) -> list[str]:
    return [violation.reason for violation in _checker().find_ai_attribution(message)]


# --------------------------------------------------------------------------------------------
# Rejected: explicit AI authorship attribution.
# --------------------------------------------------------------------------------------------

#: One entry per shape the rule names. Written out rather than generated, so that adding a shape is
#: a deliberate act and reading the list tells you exactly what is forbidden.
PROHIBITED = {
    "ai_co_author_with_vendor_email": (
        "Fix the retry backoff\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
    ),
    "ai_co_author_name_only": "Fix the retry backoff\n\nCo-Authored-By: Claude\n",
    "vendor_address_under_an_innocuous_display_name": (
        # THE EVASION THE NAME CHECK CANNOT SEE, and the only case that reaches the vendor-domain
        # rule. A display name is free text and renaming it is the obvious move; the bot account
        # behind it is the harder thing to change. Added because the mutation run showed that
        # disabling the email rule entirely left this suite green -- every other fixture carried
        # the vendor name as well as the address, so the rule was decorative.
        "Fix the retry backoff\n\nCo-Authored-By: Pair Programmer <noreply@anthropic.com>\n"
    ),
    "copilot_co_author": (
        "Fix the retry backoff\n\nCo-authored-by: Copilot <copilot@users.noreply.github.com>\n"
    ),
    "generated_by_trailer": "Fix the retry backoff\n\nGenerated-by: GPT-4\n",
    "generated_with_trailer": "Fix the retry backoff\n\nGenerated-with: Claude Code\n",
    "self_declaring_key": "Fix the retry backoff\n\nAI-generated: yes\n",
    "self_declaring_key_no_value": "Fix the retry backoff\n\nAI-generated:\n",
    "assisted_by_ai": "Fix the retry backoff\n\nAssisted-by: ChatGPT\n",
    "ai_assistant_assisted_by": "Fix the retry backoff\n\nAssisted-by: AI Assistant <ai@example.com>\n",
    "authored_by_model": "Fix the retry backoff\n\nAuthored-by: Gemini\n",
    "signed_off_by_model": "Fix the retry backoff\n\nSigned-off-by: Claude <claude@anthropic.com>\n",
    "emoji_credit_footer": (
        "Fix the retry backoff\n\n"
        "\N{ROBOT FACE} Generated with [Claude Code](https://claude.com/claude-code)\n"
    ),
    "plain_credit_footer": "Fix the retry backoff\n\nGenerated with Claude Code\n",
    "written_by_credit": "Fix the retry backoff\n\nWritten by ChatGPT\n",
}


@pytest.mark.parametrize("message", PROHIBITED.values(), ids=list(PROHIBITED))
def test_a_prohibited_ai_attribution_is_rejected(message):
    """Each named shape is refused, and the refusal says which line and why."""
    found = _violations(message)
    assert found, f"not rejected:\n{message}"


#: The same rule, typed the way people actually type. Git trailers are conventionally
#: `Key: value`, and none of casing, extra spaces, tabs or a missing space is a different rule.
CASE_AND_SPACING_VARIANTS = {
    "lowercase_key": "Subject\n\nco-authored-by: claude <noreply@anthropic.com>\n",
    "uppercase_key": "Subject\n\nCO-AUTHORED-BY: CLAUDE <NOREPLY@ANTHROPIC.COM>\n",
    "mixed_case_key": "Subject\n\nCo-AuThOrEd-By: ClAuDe\n",
    "no_space_after_colon": "Subject\n\nCo-Authored-By:Claude <noreply@anthropic.com>\n",
    "extra_spaces_after_colon": "Subject\n\nCo-Authored-By:    Claude\n",
    "space_before_colon": "Subject\n\nCo-Authored-By : Claude\n",
    "leading_whitespace": "Subject\n\n   Co-Authored-By: Claude\n",
    "trailing_whitespace": "Subject\n\nCo-Authored-By: Claude   \n",
    "no_hyphens_variant": "Subject\n\nCoauthored-by: Claude\n",
    "uppercase_self_declaring": "Subject\n\nAI-GENERATED: TRUE\n",
    "lowercase_self_declaring": "Subject\n\nai-generated: true\n",
    "chat_gpt_spaced": "Subject\n\nAssisted-by: Chat GPT\n",
    "open_ai_spaced": "Subject\n\nGenerated-by: Open AI\n",
    "credit_footer_lowercase": "Subject\n\ngenerated with claude code\n",
}


@pytest.mark.parametrize(
    "message", CASE_AND_SPACING_VARIANTS.values(), ids=list(CASE_AND_SPACING_VARIANTS)
)
def test_case_and_spacing_variants_are_rejected(message):
    """Casing and whitespace are not a loophole.

    Worth its own block rather than folded into the one above: a rule matched with a literal
    string passes the first block and fails every line here, which is the most likely way an
    implementation of this would be wrong.
    """
    found = _violations(message)
    assert found, f"variant not rejected:\n{message}"


# --------------------------------------------------------------------------------------------
# Allowed: ordinary human attribution, and ordinary prose.
# --------------------------------------------------------------------------------------------

PERMITTED = {
    "ordinary_commit": (
        "011g: bind a GovernanceEvent to the chain it closes\n\n"
        "The typed pair proved the two halves agree. It did not prove the story was this\n"
        "review's, because nothing loaded the referenced event to ask.\n"
    ),
    "human_co_author": (
        "Fix the retry backoff\n\nCo-Authored-By: Jane Doe <jane.doe@example.com>\n"
    ),
    "two_human_co_authors": (
        "Fix the retry backoff\n\n"
        "Co-Authored-By: Jane Doe <jane.doe@example.com>\n"
        "Co-Authored-By: Wei Chen <wei.chen@ntust.edu.tw>\n"
    ),
    "human_co_author_github_noreply": (
        # The address GitHub gives every contributor who keeps their email private. Matching the
        # DOMAIN here would refuse ordinary human co-authorship, which is the one thing this rule
        # must never do.
        "Fix the retry backoff\n\nCo-Authored-By: Jane Doe <12345+janedoe@users.noreply.github.com>\n"
    ),
    "human_signed_off": "Fix the retry backoff\n\nSigned-off-by: Wei Chen <wei.chen@ntust.edu.tw>\n",
    "human_reviewed_by": "Fix the retry backoff\n\nReviewed-by: Wei Chen <wei.chen@ntust.edu.tw>\n",
    "research_assistant_is_a_person": (
        # In a laboratory repository a research assistant is a human being. A rule that keyed on a
        # bare "assistant" would refuse a real person's credit.
        "Record the Q3 sweep\n\nReviewed-by: Research Assistant <ra@ntust.edu.tw>\n"
    ),
    "prose_about_ai_providers": (
        "Add the Anthropic provider adapter\n\n"
        "The Claude and OpenAI adapters normalise to one contract, so SourceRouter depends on\n"
        "capabilities and policy rather than on which model answered. An LLM verdict still has\n"
        "nowhere to go: EPI-005 forbids direct status assignment.\n"
    ),
    "prose_about_this_very_rule": (
        # The rule must not make its own implementation uncommittable.
        "Enforce the no-AI-attribution contribution rule\n\n"
        "Rejects authorship trailers naming a model, and credit footers of the generated-with\n"
        "form. Human co-authorship trailers are untouched, and discussing AI in prose is fine.\n"
    ),
    "prose_naming_a_model_in_a_benchmark": (
        "Pin the retrieval benchmark fixtures\n\n"
        "The baseline uses a fixed-token splitter; the comparison set was scored with Claude and\n"
        "with a local Llama build so the metric is not tied to one vendor.\n"
    ),
    "generated_with_something_that_is_not_an_ai": (
        "Regenerate the status tables\n\nGenerated with scripts/update_status.py\n"
    ),
    "generated_with_care": "Hand-tune the queue policy fixtures\n\nGenerated with care.\n",
    "sentence_beginning_like_a_credit": (
        # Begins like a footer and continues past the identity, so it is prose, not attribution.
        "Document the provider seam\n\n"
        "Generated with the Claude API client, then checked by hand against the stored bundle.\n"
    ),
    "colon_in_an_ordinary_sentence": (
        "Explain the expiry path\n\nNote: the assistant role in §14.4 is a human reviewer.\n"
    ),
    "url_line": "Link the ruling\n\nSee: https://example.com/claude-notes\n",
}


@pytest.mark.parametrize("message", PERMITTED.values(), ids=list(PERMITTED))
def test_ordinary_commit_messages_are_allowed(message):
    """The rule is about attribution, not about vocabulary.

    Every case here is work somebody legitimately does. If any of them fails, the rule is not
    narrow and will be routed around rather than followed -- which is worse than not having it.
    """
    found = _violations(message)
    assert not found, f"wrongly rejected:\n{message}\n-> {found}"


def test_the_violation_report_names_the_line_and_the_reason():
    """A refusal a contributor cannot act on is a refusal they will work around."""
    module = _checker()
    message = "Subject\n\nBody text.\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
    (violation,) = module.find_ai_attribution(message)

    assert violation.line_number == 5
    assert "Co-Authored-By" in violation.reason
    assert "Claude" in violation.render()


def test_every_prohibited_shape_differs_from_a_permitted_one_only_in_the_author():
    """The pairing the module docstring claims, asserted rather than asserted-in-prose.

    Same trailer key, same shape, same spacing -- only the credited author changes.
    """
    assert _violations("S\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
    assert not _violations("S\n\nCo-Authored-By: Jane Doe <jane@example.com>\n")


# --------------------------------------------------------------------------------------------
# End to end: the CLI refuses a real commit, and the hook delegates to it.
# --------------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    """A throwaway repository, so the range walk is exercised against real commits."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test Person")
    _git(repo, "config", "user.email", "test.person@example.com")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first commit")
    return repo


def _run_gate(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo_root() / GATE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_the_cli_exits_non_zero_on_a_real_offending_commit(scratch_repo):
    """`find_ai_attribution` being right is not the same claim as "the commit is refused"."""
    base = _git(scratch_repo, "rev-parse", "HEAD").stdout.strip()
    (scratch_repo / "b.txt").write_text("two\n", encoding="utf-8")
    _git(scratch_repo, "add", "-A")
    _git(
        scratch_repo,
        "commit",
        "-q",
        "-m",
        "Second commit\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    )

    result = _run_gate(scratch_repo, "--range", f"{base}..HEAD")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Co-Authored-By" in result.stderr
    assert "must not attribute authorship to an AI" in result.stderr


def test_the_cli_exits_zero_on_a_real_clean_commit(scratch_repo):
    """The positive control. Without it, a gate that refused everything would look like success."""
    base = _git(scratch_repo, "rev-parse", "HEAD").stdout.strip()
    (scratch_repo / "b.txt").write_text("two\n", encoding="utf-8")
    _git(scratch_repo, "add", "-A")
    _git(
        scratch_repo,
        "commit",
        "-q",
        "-m",
        "Second commit\n\nCo-Authored-By: Jane Doe <jane@example.com>",
    )

    result = _run_gate(scratch_repo, "--range", f"{base}..HEAD")

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_message_file_mode_ignores_comment_lines(tmp_path):
    """Git strips `#` lines before storing a message, so the hook must not trip on them.

    The editor template is full of them, and a reviewer pasting the rule into one as a reminder
    would otherwise be unable to commit.
    """
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(
        "Subject line\n\n# Please enter the commit message.\n"
        "# Reminder: Co-Authored-By: Claude is refused by the commit-hygiene gate.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(repo_root() / GATE), "--message-file", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_message_file_mode_rejects_an_offending_message(tmp_path):
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text("Subject line\n\nAI-generated: true\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(repo_root() / GATE), "--message-file", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 1
    assert "AI-generated" in result.stderr


# --------------------------------------------------------------------------------------------
# The gate must be wired in, and the hook must not be the only thing holding it.
# --------------------------------------------------------------------------------------------


def test_this_repositorys_enforced_history_is_clean():
    """The rule, applied to this repository, right now.

    The audit that prompted this gate was done by hand. This is the machine-checked version of the
    same claim, and unlike the audit it re-runs on every commit.
    """
    result = subprocess.run(
        [sys.executable, str(repo_root() / GATE)],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_enforcement_floor_is_a_real_commit_in_this_repository():
    """A floor that resolves to nothing would make the range empty and the gate vacuous."""
    floor = _checker().ENFORCED_FROM
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{floor}^{{commit}}"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ENFORCED_FROM {floor} is not a commit in this repository"


def test_ci_runs_the_commit_message_gate():
    """A local hook alone is insufficient, and this is what says so.

    `core.hooksPath` is opt-in, `--no-verify` skips it, a fresh clone has it unset and a web-UI
    commit never runs one. If the workflow stops invoking the checker, the rule is held by nothing
    -- and nothing else in this suite would notice. The same reasoning, and the same shape of test,
    as `test_ci_workflow.py`'s guard over the executed-coverage ratchet.
    """
    path = repo_root() / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))

    jobs = {
        name: job
        for name, job in workflow["jobs"].items()
        if any(GATE in str(step.get("run", "")) for step in job.get("steps", []))
    }
    assert jobs, (
        f"no CI job runs {GATE}. The no-AI-attribution rule would then be held only by an opt-in "
        "local hook, which --no-verify skips and a fresh clone does not have."
    )


def test_the_ci_job_checks_out_enough_history_to_walk_a_range():
    """`fetch-depth: 0`, or the gate has nothing to check and passes vacuously.

    This is the failure that would be hardest to notice: with a depth-1 checkout the range walk
    finds no commits, the script reports "nothing to check" and exits 0. A green gate enforcing
    nothing is worse than no gate, because it is believed.
    """
    path = repo_root() / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))

    for name, job in workflow["jobs"].items():
        steps = job.get("steps", [])
        if not any(GATE in str(step.get("run", "")) for step in steps):
            continue
        checkouts = [
            step for step in steps if str(step.get("uses", "")).startswith("actions/checkout")
        ]
        assert checkouts, f"job {name} runs the gate without checking the repository out"
        assert any(step.get("with", {}).get("fetch-depth") == 0 for step in checkouts), (
            f"job {name} runs {GATE} on a shallow checkout. The range walk would find no commits "
            "and the gate would pass without checking anything."
        )


def test_the_tracked_commit_msg_hook_delegates_to_the_same_checker():
    """One rule, two callers. A hook with its own copy of the patterns would drift from the gate."""
    hook = repo_root() / ".githooks" / "commit-msg"
    assert hook.is_file(), "the tracked commit-msg hook is missing"

    body = hook.read_text(encoding="utf-8")
    assert GATE in body, "the hook must call the same checker CI runs, not reimplement the rule"
    assert "--message-file" in body, "the hook must pass git's message file to the checker"


def test_the_hook_is_committed_executable_and_lf_terminated():
    """Mode and line endings, because both make it silently not run.

    A hook without the executable bit is ignored by git on POSIX, and a CRLF `#!/bin/sh` fails with
    a confusing "bad interpreter". `.gitattributes` normalises to LF; this asserts the mode, which
    nothing else does.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-s", ".githooks/commit-msg"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert listing, ".githooks/commit-msg is not tracked, so a clone would not receive it"
    assert listing.startswith("100755"), (
        f"the hook must be committed executable, got: {listing.split()[0]}"
    )
