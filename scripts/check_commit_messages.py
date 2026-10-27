"""Commits MUST NOT carry AI authorship: not in the message, the author or the committer.

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

IDENTITY, NOT ONLY THE MESSAGE. A message check alone passed the old `g0-exploratory-screening`
branch: its commits carried no trailer, yet every one was authored and committed as
`Claude <noreply@anthropic.com>`. So each commit's Git author and committer are checked against an
Owner-controlled policy, `.github/commit-identity-policy.toml`:

    author       must be a listed human (email and name both match)
    committer    must be a listed human or a listed platform committer (`GitHub
                 <noreply@github.com>` records itself on web-UI merges, squashes and edits)
    anything     naming an AI, in the name or the address, is refused -- and a policy that lists
                 such an identity is itself refused, so editing the policy cannot authorise one
    unlisted     refused (fail closed); the Owner lists a legitimate contributor first

Metadata is checked as recorded and never rewritten to fit the policy.

THE WALK COVERS EVERYTHING A MERGE CAN BRING IN. Identity is checked over every commit reachable
from the tip (`rev-list <tip>`, merges and both parents' ancestry included), with no floor: the
whole history was verified human-authored when this was added, so nothing is grandfathered.
Messages keep their `ENFORCED_FROM` floor. Because both are recomputed from the tip on every run, a
force-push or a rewritten history cannot slip in an unexamined commit, and an AI-authored commit
inherited indirectly through a merge of another branch is reached through the merge's parents.

    merge         the merge commit and every commit it brings in are walked
    squash        the squash commit's author/committer are checked, and the platform's generated
                  `Co-authored-by:` trailers for each squashed author go through the message rule
    cherry-pick   the picked commit keeps the original author unless reset, so it is checked as
                  itself; and a `(cherry picked from commit <sha>)` line, when that commit is
                  present, has the ORIGINAL checked too -- a reset author does not launder it.
                  An origin that is not present locally is reported as a warning, not a pass.

USAGE

    python scripts/check_commit_messages.py                     # messages ENFORCED_FROM..HEAD,
                                                                # identities over all of HEAD
    python scripts/check_commit_messages.py --tip SHA           # the same, from another tip
    python scripts/check_commit_messages.py --range A..B        # an explicit range (both rules)
    python scripts/check_commit_messages.py --message-file PATH # one message (commit-msg hook)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
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


# --------------------------------------------------------------------------------------------
# Identity: the Git author and committer, against the Owner's policy.
# --------------------------------------------------------------------------------------------

#: The policy file. Owner-controlled; see its header.
POLICY_PATH = Path(__file__).resolve().parent.parent / ".github" / "commit-identity-policy.toml"

#: Words that are AI names but also ordinary human given names. In a trailer *value* the message
#: rule still matches them (its long-standing behaviour); in an identity they would refuse a person
#: called Cody or Devin -- `Cody Person <cody@example.org>` -- which this gate must not do. The AI
#: agents behind those names are matched by their account logins below instead.
_HUMAN_NAME_COLLISIONS = frozenset({"cody", "devin"})

#: AI agents' account logins, which name no AI the general rule matches on its own terms.
_AI_IDENTITY_EXTRA_RE = re.compile(
    r"(?<![\w-])(?:copilot-swe-agent|devin-ai-integration|sweep-ai|cognition-labs|deepmind)"
    r"(?![\w-])",
    re.IGNORECASE,
)


def _identity_names_an_ai(name: str, email: str) -> bool:
    """Whether a Git identity is an AI's, by its display name or its address."""
    for text in (name, email):
        hits = {match.group(0).lower() for match in _AI_NAME_RE.finditer(text)}
        if hits - _HUMAN_NAME_COLLISIONS or _AI_IDENTITY_EXTRA_RE.search(text):
            return True
    return False


@dataclass(frozen=True)
class Identity:
    id: str
    names: frozenset[str]
    emails: frozenset[str]

    def matches(self, name: str, email: str) -> bool:
        return email.strip().lower() in self.emails and name.strip() in self.names


@dataclass(frozen=True)
class IdentityPolicy:
    humans: tuple[Identity, ...]
    platform_committers: tuple[Identity, ...] = field(default=())

    def human(self, name: str, email: str) -> Identity | None:
        return next((who for who in self.humans if who.matches(name, email)), None)

    def platform(self, name: str, email: str) -> Identity | None:
        return next((who for who in self.platform_committers if who.matches(name, email)), None)


class PolicyError(ValueError):
    """The policy file is missing, malformed, or lists an identity that names an AI."""


def _identities(entries: object, kind: str) -> tuple[Identity, ...]:
    if not isinstance(entries, list):
        raise PolicyError(f"`{kind}` must be a list of tables")
    found = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise PolicyError(f"every `{kind}` entry must be a table")
        names, emails = entry.get("names"), entry.get("emails")
        if (
            not isinstance(entry.get("id"), str)
            or not isinstance(names, list)
            or not isinstance(emails, list)
            or not names
            or not emails
            or not all(isinstance(value, str) and value.strip() for value in [*names, *emails])
        ):
            raise PolicyError(f"`{kind}` entry {entry.get('id')!r} needs an id, names and emails")
        for name in names:
            for email in emails:
                if _identity_names_an_ai(name, email):
                    raise PolicyError(
                        f"`{kind}` entry {entry['id']!r} lists {name} <{email}>, which names an AI;"
                        " the policy cannot authorise AI authorship"
                    )
        found.append(
            Identity(
                id=entry["id"],
                names=frozenset(name.strip() for name in names),
                emails=frozenset(email.strip().lower() for email in emails),
            )
        )
    return tuple(found)


def parse_policy(text: str) -> IdentityPolicy:
    """Parse and validate the policy. Pure, so every refusal is testable without a file."""
    import tomllib  # local: the commit-msg hook never needs it, and may run on an older Python

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise PolicyError(f"the policy is not valid TOML: {error}") from error
    if data.get("version") != 1:
        raise PolicyError("the policy must declare `version = 1`")
    humans = _identities(data.get("humans", []), "humans")
    if not humans:
        raise PolicyError("the policy lists no human; every commit would be refused")
    return IdentityPolicy(
        humans=humans,
        platform_committers=_identities(data.get("platform_committers", []), "platform_committers"),
    )


def load_policy(path: Path = POLICY_PATH) -> IdentityPolicy:
    try:
        return parse_policy(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise PolicyError(f"no commit identity policy at {path}") from error


@dataclass(frozen=True)
class CommitRecord:
    """What the gate reads of one commit. Built from `git log`, or by hand in a test."""

    sha: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    message: str


def find_identity_problems(commit: CommitRecord, policy: IdentityPolicy) -> list[str]:
    """Every identity problem of one commit. Pure: a test needs no repository."""
    problems: list[str] = []
    author = f"{commit.author_name} <{commit.author_email}>"
    committer = f"{commit.committer_name} <{commit.committer_email}>"
    if _identity_names_an_ai(commit.author_name, commit.author_email):
        problems.append(f"author {author} is an AI identity")
    elif policy.human(commit.author_name, commit.author_email) is None:
        if policy.platform(commit.author_name, commit.author_email) is not None:
            problems.append(f"author {author} is a platform committer, which may not author")
        else:
            problems.append(f"author {author} is not a human listed in the identity policy")
    if _identity_names_an_ai(commit.committer_name, commit.committer_email):
        problems.append(f"committer {committer} is an AI identity")
    elif (
        policy.human(commit.committer_name, commit.committer_email) is None
        and policy.platform(commit.committer_name, commit.committer_email) is None
    ):
        problems.append(f"committer {committer} is not listed in the identity policy")
    return problems


_CHERRY_PICK_RE = re.compile(r"\(cherry picked from commit ([0-9a-f]{7,40})\)")


def cherry_pick_origins(message: str) -> list[str]:
    """The commits a message says it was cherry-picked from (`git cherry-pick -x`)."""
    return _CHERRY_PICK_RE.findall(message)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result.stdout


_FIELD = "\x1f"
_RECORD = "\x1e"


def _records(revisions: Sequence[str]) -> list[CommitRecord]:
    """Every commit `git rev-list <revisions>` reaches, with its identity and message.

    Merges included. `--no-merges` would read as tidiness -- a merge message is usually generated by
    the platform -- and would be a hole: `git merge -m "<anything>"` is a message a person writes,
    and a merge commit has an author and a committer like any other.
    """
    output = _git(
        "log",
        f"--format=%H{_FIELD}%an{_FIELD}%ae{_FIELD}%cn{_FIELD}%ce{_FIELD}%B{_RECORD}",
        *revisions,
        "--",
    )
    records = []
    for chunk in output.split(_RECORD):
        chunk = chunk.lstrip("\n")
        if not chunk:
            continue
        sha, an, ae, cn, ce, message = chunk.split(_FIELD, 5)
        records.append(CommitRecord(sha, an, ae, cn, ce, message))
    return records


def _exists(sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, text=True
        ).returncode
        == 0
    )


def _check_message(message: str, label: str) -> list[str]:
    violations = find_ai_attribution(message)
    if not violations:
        return []
    subject = message.strip().splitlines()[0] if message.strip() else "(empty message)"
    report = [f"{label}  {subject}"]
    report.extend(violation.render("    ") for violation in violations)
    return report


def check_commits(
    message_commits: Iterable[CommitRecord],
    identity_commits: Iterable[CommitRecord],
    policy: IdentityPolicy,
    *,
    origin: object = None,
) -> tuple[list[str], list[str]]:
    """(failures, warnings) over the walked commits. `origin(sha)` returns a cherry-pick's source
    record, or None when that commit is not present; injected so a test needs no repository."""
    failures: list[str] = []
    warnings: list[str] = []
    for commit in message_commits:
        failures.extend(_check_message(commit.message, commit.sha[:12]))
    for commit in identity_commits:
        subject = commit.message.strip().splitlines()[0] if commit.message.strip() else ""
        problems = find_identity_problems(commit, policy)
        for picked in cherry_pick_origins(commit.message):
            source = origin(picked) if callable(origin) else None
            if source is None:
                warnings.append(
                    f"{commit.sha[:12]}  cherry-picked from {picked}, which is not present here;"
                    " its original authorship could not be checked"
                )
                continue
            problems.extend(
                f"cherry-picked from {picked[:12]}: {problem}"
                for problem in find_identity_problems(source, policy)
            )
            problems.extend(
                f"cherry-picked from {picked[:12]}: {violation.reason}"
                for violation in find_ai_attribution(source.message)
            )
        if problems:
            failures.append(f"{commit.sha[:12]}  {subject}")
            failures.extend(f"    {problem}" for problem in problems)
    return failures, warnings


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
        help="validate the commits in a revision range, messages and identities alike",
    )
    source.add_argument(
        "--tip",
        default="HEAD",
        help=(
            f"messages over {ENFORCED_FROM[:12]}..TIP and identities over every commit TIP reaches"
            " (default: HEAD)"
        ),
    )
    parser.add_argument(
        "--policy", type=Path, default=POLICY_PATH, help="the commit identity policy file"
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
        if not failures:
            print("no AI attribution found")
            return 0
        _report_attribution(failures)
        return 1

    try:
        policy = load_policy(arguments.policy)
    except PolicyError as error:
        print(f"Refusing: {error}", file=sys.stderr)
        return 1

    if arguments.rev_range:
        message_commits = identity_commits = _records([arguments.rev_range])
        scope = arguments.rev_range
    else:
        message_commits = _records([f"{ENFORCED_FROM}..{arguments.tip}"])
        identity_commits = _records([arguments.tip])
        scope = (
            f"{ENFORCED_FROM[:12]}..{arguments.tip} (messages), all of {arguments.tip} (identities)"
        )
    if not identity_commits:
        print(f"no commits in {scope}; nothing to check")
        return 0

    def origin(sha: str) -> CommitRecord | None:
        if not _exists(sha):
            return None
        return _records(["-1", sha])[0]

    failures, warnings = check_commits(message_commits, identity_commits, policy, origin=origin)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not failures:
        print(
            f"{len(message_commits)} commit message(s) and {len(identity_commits)} commit "
            f"identit(ies) in {scope}: no AI authorship found"
        )
        return 0
    _report_attribution(failures)
    return 1


def _report_attribution(failures: list[str]) -> None:
    print(
        "Refusing: commits must not attribute authorship to an AI, in the message or the author/"
        "committer identity.\n",
        file=sys.stderr,
    )
    for line in failures:
        print(line, file=sys.stderr)
    print(
        "\nThis repository does not record AI authorship. Remove the trailer or credit line and"
        "\namend, or re-author the commit as the human who wrote it. An unlisted human must be"
        "\nadded to .github/commit-identity-policy.toml by the Owner first. Co-authorship trailers"
        "\nnaming a *person* are unaffected, and discussing AI in a message body is fine.",
        file=sys.stderr,
    )


def main() -> int:
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
