"""A GitHub provider behind the ExternalSourceAdapter boundary (GH-001, GH-002, GH-003).

Registered by a deployment; never imported by core, cognition or verification (AGT-008).
"""

from lab_brain.tool_providers.github.connector import (
    PROVIDER_ID,
    GitHubAccessPolicy,
    GitHubConnector,
    StaticCredentials,
    declaration,
)
from lab_brain.tool_providers.github.transport import (
    FixtureGitHubTransport,
    HttpGitHubTransport,
    TransportError,
)

__all__ = [
    "PROVIDER_ID",
    "FixtureGitHubTransport",
    "GitHubAccessPolicy",
    "GitHubConnector",
    "HttpGitHubTransport",
    "StaticCredentials",
    "TransportError",
    "declaration",
]
