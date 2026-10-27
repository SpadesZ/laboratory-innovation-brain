# Commit integrity gate (no AI authorship)

Owner rule: nothing merged into `main` carries AI authorship -- not in a commit message, not in the
Git author, not in the Git committer.

## What the gate checks

`scripts/check_commit_messages.py`, run by the `commit-hygiene` CI job on every push and pull
request (`fetch-depth: 0`):

| Check | Scope | Policy |
|---|---|---|
| Message attribution (trailers, `AI-generated:`, "Generated with X" credits) | `ENFORCED_FROM..tip` | unchanged rule |
| Git **author** | every commit the tip reaches, no floor | must be a human listed in `.github/commit-identity-policy.toml` |
| Git **committer** | the same | a listed human, or a listed platform committer (`GitHub <noreply@github.com>`) |
| AI identity in name or address | the same | always refused; a policy listing one is itself refused |
| Unlisted identity | the same | refused (fail closed); the Owner adds the person first |
| Cherry-pick origin (`-x` line) | when the origin commit is present | the original is checked too, so a reset author does not launder it; an absent origin is a printed warning |

The tip is the pushed commit, or on a pull request the PR head (`github.event.pull_request.head.sha`),
not the synthetic merge. Merges, squashes and cherry-picks are covered because the walk is every
commit reachable from the tip, recomputed on each run: an AI commit brought in through another
branch's merge is reached through the merge's parents, a squash's generated `Co-authored-by:` goes
through the message rule, and a force-push cannot hide a commit under an already-checked tip.

Negative control: the same job runs the gate against `origin/g0-exploratory-screening` (12 commits
authored and committed as `Claude <noreply@anthropic.com>`, messages clean) and fails if the gate
passes it. If the Owner deletes that branch the step reports it absent; the frozen copy of its
metadata in `tests/spec/test_commit_identity_policy.py` keeps the case.

History is never rewritten to fit the policy. Before this change the whole history of the checked
branch (144 commits) was verified: author and committer `SpadesZ <rickiekuo1203@gmail.com>`.

## Adding a contributor

The Owner adds an entry to `.github/commit-identity-policy.toml` (`id`, `names`, `emails`) in a
reviewed commit. Name and email must both match. GitHub's private address
(`<id>+<login>@users.noreply.github.com`) is an ordinary entry.

## Owner settings still needed (not changed here)

The CI job reports; only branch protection makes it a merge gate. Settings -> Rules -> Rulesets (or
Branches -> Branch protection) for `main`:

1. Require a pull request before merging.
2. Require status checks to pass, with **Commit hygiene (no AI authorship attribution)** (and the
   other CI jobs) as required checks; require the branch to be up to date.
3. Block force pushes and deletions.
4. Require review from Code Owners (`.github/CODEOWNERS` covers the policy, the gate, the hook and
   the workflows).
5. Do not allow bypass, or limit bypass to the Owner.

Without (2), a failing gate does not block a merge. Without (3), `main` itself could be rewritten
(the next push would still be checked, but the rewritten history would already be on `main`).

## Known limits

- A cherry-pick without `-x` and with a reset author leaves no trace of its origin in Git; nothing
  in Git metadata can detect it.
- An absent cherry-pick origin is a warning, not a failure, so a deleted source branch cannot block
  `main` forever.
- The gate trusts Git metadata as recorded; it does not judge who really wrote the content.
