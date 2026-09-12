"""Shared Pydantic configuration for core scientific entities.

Two settings carry most of the weight.

``extra="forbid"`` -- an unrecognised field is an error, not silently dropped. A typo'd
``sensitivity_lable`` that is quietly discarded produces a record that looks classified and is
not.

``frozen=True`` -- core entities are immutable in memory (P2: append-only scientific record).
Correcting a record means writing a new one with provenance, not mutating the old one. This is
the in-process half of the same rule the event store enforces at the storage layer.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def utc_now() -> dt.datetime:
    """Timezone-aware current time. Naive timestamps are rejected below."""
    return dt.datetime.now(dt.UTC)


class CoreModel(BaseModel):
    """Base for every entity on the canonical scientific state path."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,
    )

    @field_validator("*", mode="after")
    @classmethod
    def _reject_naive_datetimes(cls, value: Any) -> Any:
        """A naive timestamp cannot be ordered against an aware one.

        `as_of` replay compares timestamps across records written by different processes, so a
        single naive value makes historical reconstruction wrong rather than merely awkward.
        """
        if isinstance(value, dt.datetime) and value.tzinfo is None:
            raise ValueError("datetime must be timezone-aware; naive timestamps break as_of replay")
        return value


__all__ = ["CoreModel", "utc_now"]
