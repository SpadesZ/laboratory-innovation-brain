"""Assert a refusal by its MESSAGE, whichever wrapper happens to carry it.

WHY THIS EXISTS. A `CoreModel` validator that raises `ValueError` (or a subclass such as
`ToolContractError`) is re-raised by pydantic as its own `ValidationError`, with the original
sentence embedded. The same refusal raised from a plain function arrives as the declared type. So a
test written as `pytest.raises(ToolContractError)` passes or fails depending on *where* the guard
happens to live, which is not what the test is about.

MATCHING ON THE SENTENCE IS THE STRONGER CHECK ANYWAY. These guards are distinguished by their
reason, not by their type -- several of them raise the same exception class for different reasons,
and a refusal that changed its reason would sail through a type-only assertion while no longer
refusing the thing it was written to refuse.

    with refused("the prefix declares the contract"):
        ToolDescriptor(tool_class=ToolClass.RUN, name="extract_thing", ...)
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from pydantic import ValidationError


@contextmanager
def refused(match: str, *types: type[BaseException]) -> Iterator[None]:
    """Require the block to raise, and the message to contain ``match``.

    ``types`` narrows what is accepted beyond the default (`ValueError` / `ValidationError`). Pass
    it when the exception class is itself part of the claim -- otherwise the message is, and
    over-specifying the type makes the test fail on a refactor that moved a guard into a model.
    """
    expected: tuple[type[BaseException], ...] = types or (ValueError, ValidationError)
    with pytest.raises(expected) as raised:
        yield
    assert match in str(raised.value), f"expected {match!r} in the refusal, got: {raised.value}"


__all__ = ["refused"]
