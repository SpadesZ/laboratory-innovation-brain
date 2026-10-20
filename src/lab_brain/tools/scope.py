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

AND FOR `episode_id`, WHICH IS THE ONE COST-001 ACTUALLY BUDGETS BY. §17.17's gate checks
"project/episode caps", the ESTIMATED and ACTUAL rows carry `episode_id`, and a `BudgetApproval`
releases one action in ONE episode -- all of it read off `ToolAction.episode_id`. The execution
belongs to `Job.episode_id`. With project, trace and capability bound, those two could still
differ: two episodes of one project may share a trace (nothing makes a trace unique to an
episode), so a Job submitted under episode E2 could be run on episode E1's budget, E1's approval
and E1's ledger, with every other dimension agreeing. The episode is therefore a dimension of the
scope like the other three, carried EXPLICITLY by every layer that describes the call:

    ToolAction.episode_id          what COST-001 prices, attributes and releases
    ToolRequest.episode_id         what the registry hands the implementation
    SimulationRequest.episode_id   what the execution boundary compares against the Job
    Job.episode_id                 the Episode the durable execution belongs to (§17.16)

It is never inferred. "The episode of this project on this trace" is exactly the reading that
admitted the defect: two episodes can satisfy it, and an inference picks one of them silently.

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
The bindings live at the boundaries that own the values -- `BudgetedToolDispatcher` for
action <-> request, `ChargeAcSweepRequest` for the envelope <-> its nested execution, and
`run_simulation` for request <-> Job -- because each of them has both sides in hand at a moment
when nothing has happened yet, and no later stage does.

THE REQUEST <-> JOB LINK IS CHECKED TWICE, and the two checks are not redundant. `run_simulation`'s
step 0 is the check made at the moment of execution, against the Job row as it is then. But it runs
inside `perform`, and `core.dispatch.dispatch_action` has already consumed the approval claim and
written the ESTIMATED row by the time `perform` is called -- so a Job whose episode differs from the
budgeted one would spend the approval and be charged to the wrong episode before being refused. A
request that executes a durable Job therefore says which one (`JobBinding`), and the dispatcher
resolves it and makes the same comparison BEFORE the gate. The early check is what keeps the
approval unspent and the ledger clean; the late one is what holds if the row changed in between.

DOMAIN-FREE. `ExecutionScope` holds four identities and a label. Which capability a silicon
photonics run tool is bound to is the pack's business, and it stays there.
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

    ``episode_id`` HAS NO DEFAULT, so no caller can compare scopes and forget it. It is typed
    ``str | None`` for one layer only: `Job.episode_id` is nullable in the model (§17.3 predates
    it; see `Job`'s docstring). Every other layer requires one, so a Job that names no Episode
    compares as `None` against a named Episode and is refused -- an execution with no Episode is
    not one any Episode's budget admitted.
    """

    layer: str
    project_id: str
    trace_id: str
    episode_id: str | None
    capability_id: str | None = None


@dataclass(frozen=True)
class JobBinding:
    """The durable Job a request will execute, and the scope it will execute it under (§17.16).

    Declared BY THE REQUEST, because only the request knows it executes a Job at all -- the
    dispatcher is domain-free and cannot see that a `ChargeAcSweepRequest` wraps a
    `SimulationRequest` naming one. ``scope`` is the scope of the thing that will actually run (the
    nested execution, not the envelope), so the comparison the dispatcher makes before the gate is
    the same comparison `run_simulation` makes at step 0, with the same two layers named.
    """

    job_id: str
    scope: ExecutionScope


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
        ("episode_id", first.episode_id, second.episode_id),
        ("capability_id", first.capability_id, second.capability_id),
    )
    disagreements = [
        f"{first.layer}.{name} is {left!r} but {second.layer}.{name} is {right!r}"
        for name, left, right in dimensions
        if left != right
    ]
    if disagreements:
        raise ExecutionScopeMismatch("; ".join(disagreements) + ". " + detail)


__all__ = ["ExecutionScope", "ExecutionScopeMismatch", "JobBinding", "require_same_scope"]
