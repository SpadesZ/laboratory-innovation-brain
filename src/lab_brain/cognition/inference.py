"""The one production scientific-inference operation (LLM-001, §7.6, §17.14).

WHY THE TWO-CALL SHAPE WAS NOT ENOUGH.

`ScientificLLM.invoke` produced an output and `IngestionService.record_inference` made it durable,
and both were correct. What made the pair wrong is the gap between them:

    output = llm.invoke(...)        # the model has been called, money is spent, text exists
    #  <- a crash here leaves a scientific model output with NO durable provenance
    service.record_inference(...)

The M1 exit gate says *all scientific LLM calls persist bundle+provenance*. Under the two-call
shape that sentence was true of every call that completed and false of every call that did not --
which is the only interesting case, because the text still existed in the caller's hands. §7.6
then has nothing to judge: a belief founded on that output rests on an inference nobody can
replay, and `BeliefBasisGate` cannot refuse what was never written.

So there is one operation, and it does not return until the record is durable.

    classify + authorize   (inside `ScientificLLM.invoke` -- SEC-001, derived classification)
    invoke                 the external call
    write                  `003d`, append-only, committed
    reload                 through a fresh read, and compared for exact equality
    return                 `DurableInference`, which is the only object carrying the text

DURABILITY IS THE RETURN TYPE, NOT A POSTCONDITION. `DurableInference` is constructed at exactly
one place -- after the reload compared equal -- and `ScientificOutput` is never handed back out of
this module. A caller therefore cannot hold usable text that was not durably recorded, rather than
being trusted to check whether it was. When persistence fails, `InferenceNotDurable` is raised and
it carries the inference id and the trace id and **not the text**: an exception that quoted the
model output would put exactly the unusable string back into the caller's reach, usually via a log.

THE MODEL MAY STILL HAVE BEEN CALLED, AND THAT IS ACCEPTED. There is no distributed transaction
across an external provider and PostgreSQL, and faking one would be worse than acknowledging it.
What is guaranteed is narrower and is the thing that matters scientifically: no output escapes
into hypothesis, critique or relation input unless its provenance is durable. Budget may have been
spent on an inference nobody can use -- which is a cost problem, and `007a`'s ledger is where a
cost problem belongs.

THE RELOADED RECORD IS WHAT IS RETURNED, not the in-memory one. They compare equal or the call
raises; returning the reloaded object means the value a caller cites is the value the database
holds, so a serialization that round-trips imperfectly fails here rather than three slices later.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from lab_brain.cognition.llm import ScientificLLM, ScientificOutput
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.identifiers import new_id
from lab_brain.core.models.inference import InferenceProvenance, LogicalSlot
from lab_brain.core.repositories.inference import InferenceProvenanceStore


class Transactional(Protocol):
    """The one method this service needs from a connection.

    Structural, for the reason every other `_Connection` protocol in this repository is: AGT-007
    requires the suite to be verifiable with no database, and a top-level driver import would
    break collection wherever psycopg is absent. Narrow to one method, which also keeps the
    service honest about what it does with a connection -- one transaction around one write,
    never held across the external call.
    """

    def transaction(self) -> AbstractContextManager[Any]: ...


class InferenceNotDurable(Exception):
    """The model may have been called; its provenance is not durable.

    CARRIES NO OUTPUT TEXT, deliberately. The whole point of raising is that the text may not be
    used, and an exception quoting it would hand it straight back -- into a log, a traceback, or
    an error surface, all of which are read by the code that was about to consume the inference.
    """

    def __init__(self, inference_id: str, trace_id: str, detail: str) -> None:
        super().__init__(
            f"inference {inference_id} (trace {trace_id}) has no durable provenance: {detail}. "
            "The model may have been called and the output is not usable: §7.6 admits a belief "
            "only on an inference that can be replayed, and nothing was recorded to replay"
        )
        self.inference_id = inference_id
        self.trace_id = trace_id
        self.detail = detail


@dataclass(frozen=True)
class DurableInference:
    """A scientific output whose provenance is durably recorded.

    The ONLY object in this module carrying model text, constructed at exactly one place -- after
    a reload from the store compared equal to what was submitted. Holding one is the proof; there
    is no flag to check and no way to obtain the text without it.
    """

    text: str
    #: Reloaded from the store, not the object `invoke` built. See the module docstring.
    provenance: InferenceProvenance

    @property
    def inference_id(self) -> str:
        return self.provenance.inference_id

    @property
    def basis_ref(self) -> str:
        """How this inference is named when it founds a belief (§7.6).

        Here rather than at each call site because `BeliefBasisGate` recognises inferences by
        this prefix, and a caller that built the reference by hand could produce one the gate
        does not recognise -- which would be a bypass shaped exactly like a typo.
        """
        return self.provenance.inference_id


class ScientificInferenceService:
    """Authorized call + durable provenance, as one operation.

    Every collaborator is required. A service holding an optional store would be the two-call
    shape with a longer signature: the branch where it is `None` is precisely the deployment that
    calls a model and records nothing.
    """

    def __init__(
        self,
        *,
        llm: ScientificLLM,
        store: InferenceProvenanceStore,
        commit: Transactional,
    ) -> None:
        self._llm = llm
        self._store = store
        self._commit = commit

    def infer(
        self,
        *,
        slot: LogicalSlot,
        role: str,
        prompt_id: str,
        bundle: EvidenceBundle | None,
        trace_id: str,
        project_id: str,
        actor_id: str,
        inference_id: str | None = None,
        escalate: frozenset[SensitivityLabel] = frozenset(),
        parameters: dict[str, object] | None = None,
        now: dt.datetime | None = None,
        context: Mapping[str, object] | None = None,
    ) -> DurableInference:
        """One scientific inference, durable or not returned at all.

        The id is minted HERE rather than accepted from the caller by default. It has to exist
        before the call so the refusal can name it, and a caller-supplied id would let two calls
        share one -- which `003d` would refuse on the second write, after the second model call
        had already been paid for.
        """
        identifier = inference_id or new_id("inference")
        output = self._llm._invoke(
            inference_id=identifier,
            slot=slot,
            role=role,
            prompt_id=prompt_id,
            bundle=bundle,
            trace_id=trace_id,
            project_id=project_id,
            actor_id=actor_id,
            escalate=escalate,
            parameters=parameters,
            now=now,
            context=context,
        )
        return self._persist(output, project_id=project_id, trace_id=trace_id)

    def critique(
        self,
        *,
        original: InferenceProvenance,
        prompt_id: str,
        bundle: EvidenceBundle | None,
        trace_id: str,
        project_id: str,
        actor_id: str,
        inference_id: str | None = None,
        slot: LogicalSlot = LogicalSlot.CRITIQUE,
        escalate: frozenset[SensitivityLabel] = frozenset(),
        now: dt.datetime | None = None,
        context: Mapping[str, object] | None = None,
    ) -> DurableInference:
        """§7.6's independent critique, durable on the same terms as any other inference.

        THE INDEPENDENCE CHECK HAPPENS BEFORE THE WRITE AND AFTER THE CALL, which is the only
        place it can. The route is not known until the slot and prompt resolve, and a critique
        whose route matches the original is not a critique -- so it must not become a durable
        record that a later reader would count as independent corroboration.

        The consequence is deliberate and is the same trade the fault-injection path makes: the
        model may have been called and nothing usable escapes. Budget was spent on an inference
        that turned out not to be independent, which is a cost problem and belongs in `007a`'s
        ledger -- not a reason to persist a record that would misdescribe the evidence.
        """
        identifier = inference_id or new_id("inference")
        output = self._llm._critique(
            original=original,
            inference_id=identifier,
            prompt_id=prompt_id,
            bundle=bundle,
            trace_id=trace_id,
            project_id=project_id,
            actor_id=actor_id,
            escalate=escalate,
            slot=slot,
            now=now,
            context=context,
        )
        return self._persist(output, project_id=project_id, trace_id=trace_id)

    def _persist(
        self, output: ScientificOutput, *, project_id: str, trace_id: str
    ) -> DurableInference:
        """Write, commit, reload, compare. Every failure is `InferenceNotDurable`.

        One exception type for four different failures -- the write raised, the commit failed, the
        row was absent afterwards, the row disagreed -- because the caller's decision is the same
        in all four: the text may not be used. Distinguishing them in the *message* is useful;
        distinguishing them in the *type* would invite a caller to handle one of them leniently.
        """
        identifier = output.provenance.inference_id
        try:
            with self._commit.transaction():
                self._store.record(output, project_id=project_id)
        except Exception as exc:
            raise InferenceNotDurable(identifier, trace_id, f"the write failed ({exc})") from exc

        # Read AFTER the commit, which is what makes this a durability check rather than a read of
        # the transaction's own uncommitted work.
        stored = self._store.get(identifier)
        if stored is None:
            raise InferenceNotDurable(
                identifier, trace_id, "no row is present after the write committed"
            )
        if stored != output.provenance:
            raise InferenceNotDurable(
                identifier,
                trace_id,
                f"the stored record differs from what was submitted (stored model "
                f"{stored.model_ref}, submitted {output.provenance.model_ref})",
            )
        return DurableInference(text=output.text, provenance=stored)


__all__ = [
    "DurableInference",
    "InferenceNotDurable",
    "ScientificInferenceService",
    "Transactional",
]
