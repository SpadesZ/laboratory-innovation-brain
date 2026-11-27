"""`run_simulation`, routed by capability: the runner a DomainPack is handed when it has several
backends (§24.2, §10.7, OPS-001).

A pack's `run_*` and recorded `inspect_*` tools reach the execution seam through one
`SimulationRunner` callable, which it is handed and never constructs (§24.2's dependency edge). With
one backend that callable is `run_simulation` partially applied; with several it must choose, and
the choice is made here by the request's `capability_id` -- the identity the dispatcher, the Job and
the tool's request class have already bound together. A request for a capability with no backend is
refused before anything happens; there is no default backend to fall back to.

THE RUN'S IDENTITIES ARE DERIVED FROM THE JOB. `run_id` and `lease_id` are functions of `job_id`,
the completion key is the one the Job was submitted under, and the reproducibility hash is the
canonical hash of the request.
A redelivered execution of one Job therefore proposes the same Run, and `JobStore.complete` returns
the authoritative one rather than minting a second (§12.4).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.repositories.jobs import JobStore
from lab_brain.tools.execution import ExecutionOutcome, run_simulation
from lab_brain.tools.resources import ResourceBroker
from lab_brain.tools.simulation import (
    BackendValidityRegistry,
    SimulationBackend,
    SimulationContractError,
    SimulationRequest,
)


class CapabilityRoutedRunner:
    def __init__(
        self,
        *,
        backends: Mapping[str, SimulationBackend],
        jobs: JobStore,
        broker: ResourceBroker | None,
        validity: BackendValidityRegistry,
        now: Callable[[], dt.datetime],
        domain: str | None,
    ) -> None:
        self._backends = dict(backends)
        self._jobs = jobs
        self._broker = broker
        self._validity = validity
        self._now = now
        self._domain = domain

    def __call__(self, request: SimulationRequest) -> ExecutionOutcome:
        backend = self._backends.get(request.capability_id)
        if backend is None:
            raise SimulationContractError(
                f"no backend is wired for {request.capability_id}; wired: "
                f"{sorted(self._backends)}. A runner that guessed would execute a capability on "
                "a backend its descriptor never named"
            )
        job = self._jobs.get(request.job_id)
        # The completion carries the key the Job was SUBMITTED under: `JobStore.complete` refuses
        # any other as a callback from a different submission (§12.4). A missing Job is left to
        # `run_simulation`, which refuses it with the reason.
        key = job.idempotency_key if job is not None else request.request_id
        suffix = request.job_id.split(":", 1)[-1]
        return run_simulation(
            request=request,
            backend=backend,
            jobs=self._jobs,
            broker=self._broker,
            validity=self._validity,
            run_id=f"run:{suffix}",
            lease_id=f"lse:{suffix}",
            idempotency_key=key,
            now=self._now,
            domain=self._domain,
            reproducibility_manifest_hash=canonical_hash(request.model_dump(mode="json")),
        )


__all__ = ["CapabilityRoutedRunner"]
