"""Commit messages MUST NOT carry AI authorship attribution.

WHAT THIS IS, AND WHAT IT IS NOT. This is a **repository contribution rule**, not a SAI
Requirement. It adds no Requirement or Test ID, changes no normative statement, and the 59 <-> 59
traceability invariant is untouched. The tests that cover it live in `tests/spec/` unmarked, for
the reason `test_ci_workflow.py` gives about itself: they validate the delivery pipeline rather
than discharging an obligation the specification imposes.

WHY IT IS ENFORCED IN CI RATHER THAN BY AGREEMENT. A local hook is advice. `core.hooksPath` is
opt-in, `--no-verify` skips it, a fresh clone has it unset, and a web-UI commit never runs it. This
repository has written down four times -- `011a`, `011c`, `011d`, `011g` -- that a guard only
reached by a cooperative caller is a guard nothing holds. The same sentence applies here, so the
hook exists for fast feedback and the CI job is the authority.

THE RULE IS NARROW ON PURPOSE. It rejects *attribution*: a trailer or a signature line that names
an AI as an author of the commit. It does **not** reject prose. A commit that explains an AI
provider adapter, names a model in a benchmark, or discusses this very rule is ordinary engineering
writing and passes. Two consequences follow, and both are deliberate:

  * `Co-Authored-By: <a human> <human@example.com>` is untouched. Co-authorship is a normal and
    useful trailer, and a rule that broke it would be routed around rather than followed.
  * A line is only a violation if it is *shaped* like attribution -- a `Key: value` trailer with an
    attribution key, or a line that is nothing but a "generated with X" credit. A vendor name
    appearing in a sentence is not attribution and is not matched.

Two kinds of key are treated differently, because they answer different questions:

    self-declaring    `AI-generated:` and friends announce AI authorship by the key alone, so the
                      value is irrelevant and any value is refused.
    attribution       `Co-Authored-By:`, `Assisted-by:`, `Signed-off-by:` and friends are ordinary
                      human trailers. These are refused only when the *value* names an AI.

PROSPECTIVE, AND THE FLOOR IS WRITTEN DOWN. `ENFORCED_FROM` is the last commit that predates this
rule. History before it was verified clean by hand and is **not** rewritten -- rewriting published
history to satisfy a rule introduced afterwards costs every collaborator a reset and proves nothing
that the audit did not already establish. Enforcement therefore covers `ENFORCED_FROM..HEAD`, which
includes the commit that introduces the rule: a gate that exempted its own arrival would be a gate
with a hole at exactly the moment somebody was thinking about it.

Recomputing the whole range on every run rather than only the pushed commits is the point. The
range is what a force-push would otherwise be able to slip a commit into, and commit messages are
cheap to read.

USAGE

    python scripts/check_commit_messages.py                     # ENFORCED_FROM..HEAD
    python scripts/check_commit_messages.py --range A..B        # an explicit range
    python scripts/check_commit_messages.py --message-file PATH # one message (commit-msg hook)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: The last commit written before this rule existed. See the module docstring: history at or below
#: this SHA is out of scope and is not rewritten. Everything after it is checked.
ENFORCED_FROM = "1fc43c28a58225480505997896edd586291227fa"

#: Names that identify an AI author rather than a person. Matched case-insensitively and only
#: inside the *value* of an attribution trailer, never against free prose.
#:
#: Kept as a list of whole words rather than substrings: "codex" must not fire on "codexample",
#: and a contributor whose surname contains one of these fragments is a person, not a model.
_AI_NAMES = (
    r"anthropic",
    r"claude",
    r"chat\s*gpt",
    r"open\s*ai",
    r"gpt-?\d+(?:\.\d+)?(?:-\w+)?",
    r"gpt-?[45o]\w*",
    r"copilot",
    r"codex",
    r"codewhisperer",
    r"cursor",
    r"devin",
    r"windsurf",
    r"aider",
    r"cody",
    r"tabnine",
    r"gemini",
    r"bard",
    r"duet\s*ai",
    r"llama",
    r"mistral",
    r"deep\s*seek",
    r"qwen",
    r"grok",
    r"perplexity",
    # `ai assistant` and not a bare `assistant`. In a laboratory repository a *research assistant*
    # is a person, and `Reviewed-by: Research Assistant <ra@lab.edu>` is a credit this rule has no
    # business refusing. Narrowing here costs nothing: an AI signing itself "assistant" with no
    # other marker is not a shape anything emits.
    r"ai[\s-]+assistant",
    r"language\s+model",
    r"\bllm\b",
)

_AI_NAME_RE = re.compile(r"(?<![\w-])(?:" + "|".join(_AI_NAMES) + r")(?![\w-])", re.IGNORECASE)

# THE ADDRESS IS ALREADY COVERED, AND A SEPARATE RULE FOR IT WAS DELETED. The obvious evasion is to
# keep the bot account and rename the display name -- `Pair Programmer <noreply@anthropic.com>`
# carries no AI name in the part a human reads. It is still refused, because `_AI_NAME_RE` matches
# `anthropic` inside the domain: the lookarounds are `[\w-]`, and `@` and `.` are neither, so a
# vendor name in an address is matched exactly like one in a display name.
#
# A second `_AI_EMAIL_RE` covering `@anthropic.com` and `@openai.com` was written first. Two
# mutation runs showed it rejecting nothing the name rule did not already reject -- both domains
# *contain* the vendor name -- so it was decorative, and this project treats a branch no test can
# reach as a defect rather than as insurance. `test_a_prohibited_ai_attribution_is_rejected
# [vendor_address_under_an_innocuous_display_name]` is what holds this case now.
#
# `users.noreply.github.com` is deliberately not special-cased. It is the address GitHub gives
# every contributor who keeps their email private, so treating it as AI-owned would refuse ordinary
# human co-authorship -- the one thing this rule must not do.

#: Keys that announce AI authorship by their own name. The value does not matter -- there is no
#: value of `AI-generated:` that is not a declaration of AI authorship.
_SELF_DECLARING_KEYS = (
    "ai-generated",
    "ai-assisted",
    "ai-authored",
    "ai-co-authored",
    "ai-author",
    "generated-by-ai",
    "written-by-ai",
)

#: Ordinary attribution trailers. Refused only when the value names an AI, so human co-authorship,
#: human sign-off and human review credits are all unaffected.
_ATTRIBUTION_KEYS = (
    "co-authored-by",
    "co-author",
    "coauthored-by",
    "authored-by",
    "author",
    "assisted-by",
    "generated-by",
    "generated-with",
    "created-by",
    "written-by",
    "signed-off-by",
    "on-behalf-of",
    "reviewed-by",
    "helped-by",
)

#: `Key: value`, tolerant of the spacing and casing people actually type. The key may not contain
#: spaces, which is what keeps an ordinary sentence containing a colon from being read as a
#: trailer -- "Note: the assistant pattern is unrelated" has a key of "Note" and is not in either
#: list above, so it is never examined.
_TRAILER_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")

#: The footer form of a credit -- "Generated with X" as a line of its own, rather than a trailer.
#: Matching the opening is not sufficient on its own; see `_is_bare_ai_credit`.
_CREDIT_LINE_RE = re.compile(
    r"^\W{0,4}\s*(?:generated|created|authored|written|made|built|produced)"
    r"\s+(?:with|by|using)\s+(?P<credit>.+?)\s*$",
    re.IGNORECASE,
)

#: A credit names its author and stops. Four words is comfortably more than "Claude Code" or
#: "GPT-4" and comfortably fewer than a sentence, and the punctuation test below does most of the
#: work anyway.
_MAX_CREDIT_WORDS = 4


def _is_bare_ai_credit(credit: str) -> bool:
    """Whether this line is a signature crediting an AI, rather than a sentence mentioning one.

    THE FIRST DRAFT OF THIS RULE WAS A REGEX ANCHORED AT BOTH ENDS, and its comment claimed that a
    sentence beginning "Generated with ..." would not match because it continues past the identity.
    That was not true -- `.+?$` happily swallowed the rest of the line -- and the test asserting the
    permitted near-neighbour is what caught it. The distinction has to be made explicitly:

        Generated with Claude Code                                  a signature
        Generated with the Claude API client, then checked by hand   a sentence
    """
    text = credit.strip().rstrip(".")
    if not _names_an_ai(text):
        return False

    # Prose continues; a signature does not. Internal sentence punctuation followed by more words
    # is the reliable signal, and it is what separates the two lines above.
    if re.search(r"[,;.]\s+\S", text):
        return False

    # Markdown links and bare URLs are decoration on a credit rather than content, so they are
    # removed before counting: `[Claude Code](https://…)` is two words, not eight.
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    words = [word for word in text.split() if word.strip("()<>[]{}\"'")]
    return len(words) <= _MAX_CREDIT_WORDS


@dataclass(frozen=True)
class Violation:
    """One offending line, with enough context for the author to fix it without guessing."""

    line_number: int
    line: str
    reason: str

    def render(self, prefix: str = "") -> str:
        return f"{prefix}line {self.line_number}: {self.reason}\n{prefix}    {self.line.strip()}"


def _names_an_ai(value: str) -> bool:
    """Whether a trailer value credits an AI rather than a person.

    One regex covers both the display name and the address; see the note above `_AI_NAMES` about
    the rule that used to cover the address separately.
    """
    return bool(_AI_NAME_RE.search(value))


def find_ai_attribution(message: str) -> list[Violation]:
    """Every AI authorship marker in one commit message.

    Pure, and takes a string rather than a path or a SHA, so the rule can be tested exhaustively
    without a repository. Both callers -- the hook and the CI gate -- are thin wrappers over this.
    """
    violations: list[Violation] = []

    for number, line in enumerate(message.splitlines(), start=1):
        trailer = _TRAILER_RE.match(line)
        if trailer is not None:
            key, value = trailer.group(1).lower(), trailer.group(2)

            if key in _SELF_DECLARING_KEYS:
                violations.append(
                    Violation(
                        number,
                        line,
                        f"`{trailer.group(1)}:` declares AI authorship of this commit",
                    )
                )
                continue

            if key in _ATTRIBUTION_KEYS and _names_an_ai(value):
                violations.append(
                    Violation(
                        number,
                        line,
                        f"`{trailer.group(1)}:` credits an AI as an author of this commit",
                    )
                )
                continue

            # A recognised attribution key naming a person is exactly what these trailers are for.
            continue

        credit = _CREDIT_LINE_RE.match(line)
        if credit is not None and _is_bare_ai_credit(credit.group("credit")):
            violations.append(
                Violation(number, line, "credit line attributing this commit to an AI")
            )

    return violations


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


def _commits_in(rev_range: str) -> list[str]:
    # Merges included. `--no-merges` would read as tidiness -- a merge message is usually generated
    # by the platform -- and would be a hole: `git merge -m "<anything>"` is a commit message a
    # person writes. The generated ones pass trivially, so including them costs nothing.
    output = _git("rev-list", rev_range)
    return [line for line in output.split() if line]


def _check_message(message: str, label: str) -> list[str]:
    violations = find_ai_attribution(message)
    if not violations:
        return []
    subject = message.strip().splitlines()[0] if message.strip() else "(empty message)"
    report = [f"{label}  {subject}"]
    report.extend(violation.render("    ") for violation in violations)
    return report


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--message-file",
        type=Path,
        help="validate a single commit message file (the commit-msg hook's argument)",
    )
    source.add_argument(
        "--range",
        dest="rev_range",
        help=f"validate the commits in a revision range (default: {ENFORCED_FROM[:12]}..HEAD)",
    )
    arguments = parser.parse_args(argv)

    if arguments.message_file is not None:
        # The hook passes a path git owns; read it in the encoding git wrote it in.
        message = arguments.message_file.read_text(encoding="utf-8", errors="replace")
        # Comment lines are stripped by git before the message is stored, so a reviewer pasting the
        # rule into the editor as a `#` comment must not trip it.
        message = "\n".join(
            line for line in message.splitlines() if not line.lstrip().startswith("#")
        )
        failures = _check_message(message, "commit message:")
    else:
        rev_range = arguments.rev_range or f"{ENFORCED_FROM}..HEAD"
        commits = _commits_in(rev_range)
        if not commits:
            print(f"no commits in {rev_range}; nothing to check")
            return 0
        failures = []
        for sha in commits:
            failures.extend(_check_message(_git("log", "-1", "--format=%B", sha), f"{sha[:12]}"))
        if not failures:
            print(f"{len(commits)} commit message(s) in {rev_range}: no AI attribution found")
            return 0

    if not failures:
        print("no AI attribution found")
        return 0

    print("Refusing: commit messages must not attribute authorship to an AI.\n", file=sys.stderr)
    for line in failures:
        print(line, file=sys.stderr)
    print(
        "\nThis repository does not record AI authorship in commit attribution. Remove the"
        "\ntrailer or credit line and amend. Co-authorship trailers naming a *person* are"
        "\nunaffected, and discussing AI in the body of a message is fine -- only attribution"
        "\nis refused.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
