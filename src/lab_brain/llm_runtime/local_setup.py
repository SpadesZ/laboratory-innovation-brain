"""Set up the lightweight LOCAL model routes a deployment can configure by itself -- and no more.

    python -m lab_brain.llm_runtime.local_setup --actor ACT --base-url URL [--host-gateway NAME]

Run by the container deployment once per start (`compose.yaml`, service `local-models`), as the
deployment's LLM administrator, through the ORDINARY LLM settings workflow (`LLMSettings`): the same
connection rules, the same fixed capability probes judged by the same typed parsers, the same locks
and binding rules the database enforces. It adds no inference path and no provider-specific logic:
the host's Ollama is one more OpenAI-compatible endpoint (`/v1`).

THE POLICY. Deterministic, and it never guesses:

  1. One LOCAL connection to `--base-url`, named `ollama`, with no credential -- created if no
     connection has that name; an existing one is used as it is, never altered.
  2. Its model list is fetched (recorded as a health check). A model never tested is probed for
     every capability; a TESTED model that proved CHAT is locked with exactly what it proved (the
     database's rule). A model that did not prove CHAT stays TESTED, visible, unbound.
  3. Lightweight slots only -- FAST_UTILITY (the Evidence Researcher's query rewriting) and
     PRIVATE_LOCAL -- in a DRAFT runtime named `local-first`, created if there is none and no
     runtime is ACTIVE. A slot already bound is left as it is.
  4. For each such unbound slot: the candidates are the LOCKED models on this LOCAL connection that
     proved the slot's requirements. Exactly one: it is bound. More than one: nothing is bound --
     the candidates proved the same requirements, so there is no meaningful basis to choose, and
     they are listed for the researcher. None: nothing is bound.
  5. REASONING_PRIMARY and REASONING_ADVERSARIAL are NEVER bound here: they are the researcher's
     choice, a local or an external model, in LLM settings. CODE and VISION are not bound either:
     no role routes to them in this version.
  6. Nothing is activated. Activation needs REASONING_PRIMARY, which only the researcher binds;
     the runtime's readiness says exactly what remains.

With an ACTIVE runtime present it probes and locks new models and changes no runtime.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.config import ConfigurationError, open_connection, read_settings
from lab_brain.llm_runtime.capabilities import SLOT_REQUIREMENTS
from lab_brain.llm_runtime.registry import ModelRow
from lab_brain.llm_runtime.runtime import LLMSettings, SettingsRefused
from lab_brain.llm_runtime.secrets import SecretStore

CONNECTION_NAME = "ollama"
RUNTIME_NAME = "local-first"

#: The slots this setup may bind: lightweight structured work, and the private local slot.
LIGHTWEIGHT_SLOTS: tuple[LogicalSlot, ...] = (LogicalSlot.FAST_UTILITY, LogicalSlot.PRIVATE_LOCAL)


def candidates(models: Sequence[ModelRow], connection_id: str, slot: LogicalSlot) -> list[ModelRow]:
    """LOCKED models on this connection that proved what `slot` requires, by name."""
    required = {c.value for c in SLOT_REQUIREMENTS[slot]}
    return sorted(
        (
            m
            for m in models
            if m.connection_id == connection_id
            and m.lifecycle == "LOCKED"
            and required <= set(m.locked_capabilities or ())
        ),
        key=lambda m: m.model_name,
    )


def configure(llm: LLMSettings, base_url: str, *, out: TextIO) -> int:
    registry = llm.registry
    connection = next((c for c in registry.connections() if c.name == CONNECTION_NAME), None)
    if connection is None:
        connection = llm.add_connection(
            name=CONNECTION_NAME, base_url=base_url, reach="LOCAL", secret_mode="none"
        )
        print(f"connection {CONNECTION_NAME}: created, LOCAL, {base_url}", file=out)
    else:
        print(f"connection {CONNECTION_NAME}: kept as configured ({connection.base_url})", file=out)
    if connection.lifecycle != "ENABLED":
        print(f"connection {CONNECTION_NAME} is {connection.lifecycle}: nothing to do", file=out)
        return 0
    try:
        llm.fetch_models(connection.connection_id)
    except SettingsRefused as unreachable:
        print(f"local models: unavailable -- {unreachable}", file=out)
        return 0
    health = registry.latest_health(connection.connection_id)
    print(
        f"health: {health.outcome if health else '-'} ({health.detail if health else ''})", file=out
    )

    for model in registry.models(connection.connection_id):
        if model.lifecycle == "DISCOVERED":
            rows = llm.test_model(model.model_profile_id)
            proved = sorted(r.capability for r in rows if r.outcome == "PASSED")
            failed = sorted(f"{r.capability}={r.outcome}" for r in rows if r.outcome != "PASSED")
            print(
                f"probed {model.model_name}: passed {', '.join(proved) or 'nothing'}"
                + (f"; not proven {', '.join(failed)}" if failed else ""),
                file=out,
            )
            model = registry.model(model.model_profile_id) or model
        if model.lifecycle == "TESTED":
            if "CHAT" in {c.value for c in registry.verified_capabilities(model.model_profile_id)}:
                locked = llm.lock(model.model_profile_id)
                print(
                    f"locked {locked.model_name}: {', '.join(locked.locked_capabilities or ())}",
                    file=out,
                )
            else:
                print(f"not locked {model.model_name}: it did not prove CHAT", file=out)

    if registry.active_runtime() is not None:
        print("an LLM runtime is ACTIVE: no runtime is changed", file=out)
        return 0
    runtime = next(
        (r for r in registry.runtimes() if r.state == "DRAFT" and r.name == RUNTIME_NAME), None
    )
    if runtime is None:
        runtime = llm.create_runtime(RUNTIME_NAME, ["PUBLIC"])
        print(f"runtime {RUNTIME_NAME}: created as a DRAFT", file=out)
    bound = registry.bindings(runtime.runtime_id)
    models = registry.models()
    for slot in LIGHTWEIGHT_SLOTS:
        if slot in bound:
            kept = registry.model(bound[slot].model_profile_id)
            print(f"{slot.value}: kept ({kept.model_name if kept else '?'})", file=out)
            continue
        eligible = candidates(models, connection.connection_id, slot)
        if len(eligible) == 1:
            llm.bind(runtime.runtime_id, slot, eligible[0].model_profile_id)
            print(
                f"{slot.value}: bound to {eligible[0].model_name} (the one local model that "
                "proved what it requires)",
                file=out,
            )
        elif eligible:
            print(
                f"{slot.value}: NOT bound -- {len(eligible)} local models proved what it requires "
                f"({', '.join(m.model_name for m in eligible)}); no basis to choose, the "
                "researcher decides in LLM settings",
                file=out,
            )
        else:
            print(f"{slot.value}: NOT bound -- no local model proved what it requires", file=out)
    readiness = llm.readiness(runtime.runtime_id)
    print("still needed before activation:", file=out)
    for blocker in readiness.blockers or ("nothing",):
        print(f"  - {blocker}", file=out)
    print(readiness.critic, file=out)
    return 0


def main(
    argv: Sequence[str] | None = None, *, out: TextIO | None = None, connect: Any = None
) -> int:
    parser = argparse.ArgumentParser(prog="python -m lab_brain.llm_runtime.local_setup")
    parser.add_argument("--actor", required=True, help="an LLM administrator of this deployment")
    parser.add_argument("--base-url", required=True, help="the local OpenAI-compatible endpoint")
    parser.add_argument("--host-gateway", action="append", default=[], metavar="NAME")
    args = parser.parse_args(argv)
    stream = out or sys.stdout
    try:
        settings = read_settings(os.environ)
        connection = (connect or open_connection)(settings)
    except ConfigurationError as exc:
        print(f"local models: {exc}", file=stream)
        return 2
    try:
        connection.autocommit = True
        llm = LLMSettings(
            connection,
            secrets=SecretStore(credentials=None),
            actor_id=args.actor,
            local_hosts=args.host_gateway,
            timeout=300.0,
        )
        return configure(llm, args.base_url.rstrip("/"), out=stream)
    except SettingsRefused as refused:
        print(f"local models: refused -- {refused}", file=stream)
        return 2
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
