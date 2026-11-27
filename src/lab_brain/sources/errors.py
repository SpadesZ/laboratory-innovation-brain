"""§6.16's connector failure policy, as a type.

    §6.16  rate limit、authentication failure、repository removed、ref drift、network unavailable
           都必須回傳 structured connector error；不得由 LLM 猜測缺失內容。若某 prior-art conclusion
           依賴的 GitHub material 已消失，狀態改為 SOURCE_UNAVAILABLE 並保留既有 snapshot。

A CONNECTOR THAT CANNOT ANSWER RAISES, AND SAYS WHICH OF THE NAMED FAILURES IT HIT. There is no
empty-result fallback and no "best effort" content: a record whose bytes did not arrive is not a
record, and anything a caller filled in would be the guess §6.16 forbids. Every kind maps to one of
§17.23's error classes, so the Knowledge Inbox and the retry policy (UX-002) read the same fact the
connector reported -- a policy refusal is never retried, a network failure may be.

THE ERROR CARRIES NO PAYLOAD. `detail` is written by the connector from its own state (a status
code, a retry-after); it never quotes the query text or anything the caller sent, because an error
is logged and surfaced more widely than the material that caused it (GH-002, SEC-001).
"""

from __future__ import annotations

from enum import StrEnum


class ConnectorErrorKind(StrEnum):
    #: The provider throttled the request. Retryable after `retry_after_s`.
    RATE_LIMITED = "RATE_LIMITED"
    #: Credentials were presented and refused by the provider.
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    #: The deployment's own access policy refused the request before anything was sent (GH-002).
    NOT_AUTHORIZED = "NOT_AUTHORIZED"
    #: The repository, record or file does not exist -- or is not visible to this caller, which a
    #: provider deliberately does not distinguish.
    NOT_FOUND = "NOT_FOUND"
    #: It existed (a snapshot or an earlier record says so) and is gone now.
    SOURCE_REMOVED = "SOURCE_REMOVED"
    #: A pinned version no longer resolves, or a ref resolves to something other than expected.
    REF_DRIFT = "REF_DRIFT"
    #: The provider could not be reached at all.
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"


#: §17.23's error class for each kind. POLICY_BLOCK is never auto-retried (UX-002).
ERROR_CLASS: dict[ConnectorErrorKind, str] = {
    ConnectorErrorKind.RATE_LIMITED: "EXTERNAL_SERVICE_ERROR",
    ConnectorErrorKind.AUTHENTICATION_FAILED: "POLICY_BLOCK",
    ConnectorErrorKind.NOT_AUTHORIZED: "POLICY_BLOCK",
    ConnectorErrorKind.NOT_FOUND: "USER_INPUT_ERROR",
    ConnectorErrorKind.SOURCE_REMOVED: "EXTERNAL_SERVICE_ERROR",
    ConnectorErrorKind.REF_DRIFT: "EXTERNAL_SERVICE_ERROR",
    ConnectorErrorKind.NETWORK_UNAVAILABLE: "EXTERNAL_SERVICE_ERROR",
}

RETRYABLE = frozenset({ConnectorErrorKind.RATE_LIMITED, ConnectorErrorKind.NETWORK_UNAVAILABLE})


class ConnectorError(RuntimeError):
    """One structured connector failure. See the module docstring."""

    def __init__(
        self,
        kind: ConnectorErrorKind,
        *,
        provider_id: str,
        detail: str,
        retry_after_s: int | None = None,
        audited: bool = False,
        pinned_ref: str | None = None,
    ) -> None:
        super().__init__(f"{provider_id}: {kind.value}: {detail}")
        self.kind = kind
        self.provider_id = provider_id
        self.detail = detail
        self.retry_after_s = retry_after_s
        #: The connector already recorded this as an access refusal -- by locator DIGEST. A
        #: caller must not record it again with the locator, which would put a private
        #: repository's name into the log the digest exists to keep it out of (GH-002).
        self.audited = audited
        #: The immutable version the connector had resolved when the failure occurred, if it got
        #: that far. A path missing AT a resolved version is not the removal of another version:
        #: an earlier snapshot pinned elsewhere still names material that exists (§6.16).
        self.pinned_ref = pinned_ref

    @property
    def error_class(self) -> str:
        return ERROR_CLASS[self.kind]

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE


__all__ = ["ERROR_CLASS", "RETRYABLE", "ConnectorError", "ConnectorErrorKind"]
