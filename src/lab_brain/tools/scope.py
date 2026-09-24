"""One execution, one scope — the identities every layer of a tool call must agree on (§17.16).

THE DEFECT THIS MODULE CLOSES. A tool call is described four times on its way to a backend, and
until now nothing compared the descriptions:

    ToolAction.project_id          what `dispatch_action` budgets against
    ToolRequest.project_id         what the registry hands the implementation
    SimulationRequest.project_id   what the backend is asked to run
    Job.project_id                 what the durable record says was submitted

Four independent strings for one fact. A request carrying `A`, `B`, `C` and `D` was representable,
and the layer that *paid* was not the layer that *ran*: project A's caps admitted an action, the
implementation executed inside project B, and the Run landed on project D's Job. The same holds for
`trace_id`, which is what OPS-003 uses to reassemble a call from its spans -- a trace that changes
halfway down is a trace that reassembles into two unrelated halves -- and for `capability_id`,
which is what §9.5 planned and §17.18 priced.

NEITHER SIDE WINS, AND THAT IS THE DIFFERENCE FROM `_require_bound_demand`. A ResourceDemand has an
authoritative copy: the durable Job's, because a resumer may legitimately restate a requirement and
one of the two readings has to be the requirement. An identity has no such reading. If the layer
that was budgeted and the layer that will execute disagree about the project, there is no rule that
makes one of them correct -- so no preference is expressed and the execution does not happen.

WHY THIS IS A RAISE AND NOT A GOVERNANCE OUTCOME. A budget refusal is a normal, recorded result: a
project ran out of money, someone with authority can release it, and the BLOCKED span is the
record. A scope mismatch is neither normal nor releasable. It is an invalid execution envelope, and
an approval that "released" one would be an approval to execute inside a project nobody checked.
Keeping the two outcomes in different channels is the same line `ToolDispatchRefused` and
`DispatchRefused` already draw, for the same reason: a caller that cannot tell them apart routes
the second to a supervisor and waits.

WHERE THE CHECKS ARE MADE, and why not here. This module compares; it does not know who to compare.
The three bindings live at the boundaries that own the values -- `BudgetedToolDispatcher` for
action <-> request, `ChargeAcSweepRequest` for the envelope <-> its nested execution, and
`run_simulation` for request <-> Job -- because each of them has both sides in hand at a moment
when nothing has happened yet, and no later stage does.

DOMAIN-FREE. `ExecutionScope` holds three strings and a label. Which capability a silicon photonics
run tool is bound to is the pack's business, and it stays there.
"""

from __future__ import annotations

from dataclasses import dataclass


class ExecutionScopeMismatch(ValueError):
    """Two layers describing one execution name different scopes (§17.16, COST-001, OPS-003).

    A `ValueError` so that a binding expressed at a pydantic model boundary raises the same type it
    would raise anywhere else: pydantic re-raises it as a `ValidationError` carrying this message,
    which is how every other `CoreModel` refusal in this repository already reads.
    """


@dataclass(frozen=True)
class ExecutionScope:
    """Who is executing, under which trace, against which capability.

    ``layer`` names the thing the values were read off, and exists so the refusal can say *which
    two* descriptions disagreed. "project_id mismatch" sends a reader looking through four
    candidates; "ToolAction.project_id is 'prj:a' but ToolRequest.project_id is 'prj:b'" does not.

    ``capability_id`` is optional because not every layer carries one -- `ToolAction` deliberately
    does not, and §17.17 gives no reason for it to: the capability is the *descriptor's* identity,
    and a second copy on the action would be one more field that could disagree. A layer that has
    none compares as `None`, which agrees with another `None` and disagrees with a named
    capability. That direction is deliberate: one side naming a capability the other has never
    heard of is a disagreement, not a permission to skip the dimension.
    """

    layer: str
    project_id: str
    trace_id: str
    capability_id: str | None = None


def require_same_scope(first: ExecutionScope, second: ExecutionScope, *, detail: str) -> None:
    """Refuse unless the two layers name the same execution. Raises `ExecutionScopeMismatch`.

    Reports EVERY dimension that disagrees rather than the first, because the interesting case is a
    request whose project and trace both drifted -- one message naming both says "this envelope was
    assembled wrong", where two successive single-field failures read like two unrelated bugs.

    ``detail`` is the caller's sentence about what would have happened next. It is required rather
    than optional: the value of raising here instead of failing later is entirely in being able to
    say what was about to be spent, mutated or executed, and a generic "scope mismatch" thrown from
    three different boundaries would lose exactly that.
    """
    dimensions = (
        ("project_id", first.project_id, second.project_id),
        ("trace_id", first.trace_id, second.trace_id),
        ("capability_id", first.capability_id, second.capability_id),
    )
    disagreements = [
        f"{first.layer}.{name} is {left!r} but {second.layer}.{name} is {right!r}"
        for name, left, right in dimensions
        if left != right
    ]
    if disagreements:
        raise ExecutionScopeMismatch("; ".join(disagreements) + ". " + detail)


__all__ = ["ExecutionScope", "ExecutionScopeMismatch", "require_same_scope"]
