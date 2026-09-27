"""The GitHub wire boundary: what the connector asks a code host, and nothing about how.

`GitHubTransport` is the only place GitHub's API shape exists in this repository -- no SDK is used
(§19: "直接依賴 GitHub SDK" is the thing not taken). Two implementations:

    FixtureGitHubTransport   deterministic, from a JSON fixture of repositories, refs, commits and
                             files. Used by every test and by the benchmark-style e2e. It performs
                             no network access and says so in its `name`.
    HttpGitHubTransport      urllib against api.github.com. Wired only where a deployment opts in;
                             exercised only by the `network`-marked test, which is deselected unless
                             `LAB_BRAIN_TEST_NETWORK=1`. Nothing in this repository's verification
                             claims a live GitHub call happened.

A transport raises `TransportError` with a small vocabulary the connector maps onto §6.16's
structured connector errors. It never returns an empty body in place of a failure.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

NOT_FOUND = "not_found"
UNAUTHORIZED = "unauthorized"
RATE_LIMITED = "rate_limited"
GONE = "gone"
NETWORK = "network"


class TransportError(RuntimeError):
    def __init__(self, kind: str, detail: str, *, retry_after_s: int | None = None) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail
        self.retry_after_s = retry_after_s


@dataclass(frozen=True)
class RepoInfo:
    repo_id: int
    owner: str
    name: str
    private: bool
    default_branch: str
    license_spdx: str | None
    description: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class RateLimitStatus:
    remaining: int
    reset_after_s: int = 0


class GitHubTransport(Protocol):
    @property
    def name(self) -> str: ...

    def repository(self, owner: str, name: str, *, token: str | None) -> RepoInfo: ...

    def resolve_ref(self, owner: str, name: str, ref: str, *, token: str | None) -> str: ...

    def read_file(
        self, owner: str, name: str, commit: str, path: str, *, token: str | None
    ) -> bytes: ...

    def search_repositories(
        self, text: str, limit: int, *, token: str | None
    ) -> list[RepoInfo]: ...

    def rate_limit(self) -> RateLimitStatus: ...


@dataclass
class FixtureGitHubTransport:
    """A code host in a JSON file. Records every call it served, token presence included."""

    repositories: dict[str, dict[str, Any]]
    #: Tokens this fake host accepts, and which private repositories each may read.
    tokens: dict[str, tuple[str, ...]] = field(default_factory=dict)
    rate_limited: bool = False
    network_down: bool = False
    calls: list[tuple[str, str, bool]] = field(default_factory=list)

    name: str = "fixture-github (no network)"

    @classmethod
    def from_file(cls, path: Path) -> FixtureGitHubTransport:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            repositories={r["full_name"]: r for r in payload["repositories"]},
            tokens={t["token"]: tuple(t["can_read"]) for t in payload.get("tokens", ())},
        )

    def _gate(self, op: str, full_name: str, token: str | None) -> dict[str, Any]:
        self.calls.append((op, full_name, token is not None))
        if self.network_down:
            raise TransportError(NETWORK, "connection refused")
        if self.rate_limited:
            raise TransportError(RATE_LIMITED, "secondary rate limit", retry_after_s=60)
        if token is not None and token not in self.tokens:
            raise TransportError(UNAUTHORIZED, "bad credentials")
        repo = self.repositories.get(full_name)
        if repo is None:
            raise TransportError(NOT_FOUND, "no such repository")
        if repo.get("removed"):
            raise TransportError(GONE, "repository access blocked or removed")
        if repo.get("private") and (token is None or full_name not in self.tokens[token]):
            # A code host does not say "private": it says "not found".
            raise TransportError(NOT_FOUND, "no such repository")
        return repo

    def repository(self, owner: str, name: str, *, token: str | None) -> RepoInfo:
        return _info(self._gate("repository", f"{owner}/{name}", token))

    def resolve_ref(self, owner: str, name: str, ref: str, *, token: str | None) -> str:
        repo = self._gate("resolve_ref", f"{owner}/{name}", token)
        if ref in repo["commits"]:
            return ref
        sha = repo["refs"].get(ref)
        if sha is None:
            raise TransportError(NOT_FOUND, "no such ref")
        return str(sha)

    def read_file(
        self, owner: str, name: str, commit: str, path: str, *, token: str | None
    ) -> bytes:
        repo = self._gate("read_file", f"{owner}/{name}", token)
        files = repo["commits"].get(commit)
        if files is None:
            raise TransportError(NOT_FOUND, "no such commit")
        content = files.get(path)
        if content is None:
            raise TransportError(NOT_FOUND, "no such path at this commit")
        return str(content).encode("utf-8")

    def search_repositories(self, text: str, limit: int, *, token: str | None) -> list[RepoInfo]:
        self.calls.append(("search", text, token is not None))
        if self.network_down:
            raise TransportError(NETWORK, "connection refused")
        if self.rate_limited:
            raise TransportError(RATE_LIMITED, "search rate limit", retry_after_s=60)
        terms = {t for t in text.lower().split() if t}
        found = [
            _info(r)
            for key, r in sorted(self.repositories.items())
            if not r.get("private")
            and not r.get("removed")
            and terms
            & set((r.get("description", "") + " " + key.replace("/", " ")).lower().split())
        ]
        return found[:limit]

    def rate_limit(self) -> RateLimitStatus:
        if self.network_down:
            raise TransportError(NETWORK, "connection refused")
        return RateLimitStatus(remaining=0 if self.rate_limited else 5000, reset_after_s=60)

    # -- fixture controls, used by tests to model the world changing ---------------------

    def move_ref(self, full_name: str, ref: str, commit: str) -> None:
        self.repositories[full_name]["refs"][ref] = commit

    def remove(self, full_name: str) -> None:
        self.repositories[full_name]["removed"] = True


def _info(repo: dict[str, Any]) -> RepoInfo:
    owner, name = str(repo["full_name"]).split("/", 1)
    return RepoInfo(
        repo_id=int(repo["id"]),
        owner=owner,
        name=name,
        private=bool(repo.get("private", False)),
        default_branch=str(repo["default_branch"]),
        license_spdx=repo.get("license"),
        description=str(repo.get("description", "")),
    )


class HttpGitHubTransport:
    """api.github.com over urllib. Not exercised offline; see the module docstring."""

    name = "https://api.github.com"

    def __init__(self, *, base_url: str = "https://api.github.com", timeout_s: float = 20) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    def _get(self, path: str, token: str | None, query: dict[str, str] | None = None) -> Any:
        url = self._base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("User-Agent", "laboratory-innovation-brain")
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as failed:
            remaining = failed.headers.get("X-RateLimit-Remaining")
            if failed.code in (403, 429) and (remaining == "0" or failed.code == 429):
                reset = failed.headers.get("Retry-After") or "60"
                raise TransportError(
                    RATE_LIMITED, f"HTTP {failed.code}", retry_after_s=int(reset)
                ) from failed
            if failed.code == 401:
                raise TransportError(UNAUTHORIZED, "HTTP 401") from failed
            if failed.code in (410, 451):
                raise TransportError(GONE, f"HTTP {failed.code}") from failed
            if failed.code == 404:
                raise TransportError(NOT_FOUND, "HTTP 404") from failed
            raise TransportError(NETWORK, f"HTTP {failed.code}") from failed
        except urllib.error.URLError as unreachable:
            raise TransportError(NETWORK, str(unreachable.reason)) from unreachable

    def repository(self, owner: str, name: str, *, token: str | None) -> RepoInfo:
        body = self._get(f"/repos/{owner}/{name}", token)
        license_info = body.get("license") or {}
        return RepoInfo(
            repo_id=int(body["id"]),
            owner=str(body["owner"]["login"]),
            name=str(body["name"]),
            private=bool(body["private"]),
            default_branch=str(body["default_branch"]),
            license_spdx=license_info.get("spdx_id"),
            description=str(body.get("description") or ""),
        )

    def resolve_ref(self, owner: str, name: str, ref: str, *, token: str | None) -> str:
        return str(
            self._get(f"/repos/{owner}/{name}/commits/{urllib.parse.quote(ref)}", token)["sha"]
        )

    def read_file(
        self, owner: str, name: str, commit: str, path: str, *, token: str | None
    ) -> bytes:
        body = self._get(
            f"/repos/{owner}/{name}/contents/{urllib.parse.quote(path)}", token, {"ref": commit}
        )
        if body.get("encoding") != "base64":
            raise TransportError(NOT_FOUND, "content not returned inline")
        return base64.b64decode(body["content"])

    def search_repositories(self, text: str, limit: int, *, token: str | None) -> list[RepoInfo]:
        body = self._get("/search/repositories", token, {"q": text, "per_page": str(limit)})
        return [
            RepoInfo(
                repo_id=int(item["id"]),
                owner=str(item["owner"]["login"]),
                name=str(item["name"]),
                private=bool(item["private"]),
                default_branch=str(item["default_branch"]),
                license_spdx=(item.get("license") or {}).get("spdx_id"),
                description=str(item.get("description") or ""),
            )
            for item in body.get("items", [])
        ]

    def rate_limit(self) -> RateLimitStatus:
        core = self._get("/rate_limit", None)["resources"]["core"]
        return RateLimitStatus(remaining=int(core["remaining"]))


__all__ = [
    "GONE",
    "NETWORK",
    "NOT_FOUND",
    "RATE_LIMITED",
    "UNAUTHORIZED",
    "FixtureGitHubTransport",
    "GitHubTransport",
    "HttpGitHubTransport",
    "RateLimitStatus",
    "RepoInfo",
    "TransportError",
]
