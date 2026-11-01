"""The generator side of a blind evaluation: run each frozen case, write outputs bound to it.

Until now the workflow had the evaluator's tools (seal, contamination check, freeze, score) and no
runner, so "run every case blind" was a description, not a program an independent evaluator could
reproduce. This is the program. It is product-agnostic: the caller supplies how ONE case is run
(`run_case`, e.g. through the web workspace) and how a finished episode is read back
(`collect_record`, e.g. `lab_brain.evaluation.collect` via the matrix harness).

WHAT THE RUNNER GUARANTEES

    the frozen inputs    before anything runs, the manifest must hash to itself and EVERY file it
                         froze -- the generator package and each evidence file -- is read once and
                         checked against its SHA-256. The package and its evidence are then parsed
                         from those same bytes, never read from disk again: a file changed or
                         swapped after the check is not what runs. A changed file, or an evidence
                         file the manifest did not freeze, is a different experiment and is refused.
    blind                the runner never receives truth: no parameter takes a truth file, and each
                         case is fed `research_inputs` -- the allowlisted projection that carries
                         no case id, provenance or truth.
    every case           every frozen case gets an entry, in frozen order. A case whose run raises
                         is CRASHED with the error's type and message; nothing is retried or
                         dropped, so the scorer's denominator is the frozen one.
    prompts              when the caller can see what was sent to the model (`prompts_of`), the
                         record carries it and `prompts_captured` is true. A live deployment
                         stores no prompt text, so a live run records `prompts_captured: false` --
                         and its input-leak check is then NOT VERIFIED, never a pass.
    environment          given the recorded environment manifest (`lab_brain.evaluation.
                         environment`) and a way to observe the environment now, the runner refuses
                         to start on any drift, and checks again after the last case: drift during
                         the run is written into the outputs, and the scorer refuses such a run.
                         Without one, the outputs say the environment was NOT verified -- a bare
                         hash string proves nothing, so the runner no longer accepts one.
    bound                the outputs document names the manifest hash and the environment's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_brain.evaluation.environment import environment_hash, verify
from lab_brain.evaluation.manifest import OUTPUTS_KIND, manifest_hash
from lab_brain.evaluation.packages import (
    LoadedPackage,
    ResearchInputs,
    load_generator_package,
    research_inputs,
)

#: Longest error text kept with a CRASHED case: enough to diagnose, too short to carry a payload.
CRASH_DETAIL = 300


class RunnerRefused(ValueError):
    """The package or manifest is not the frozen one; nothing was run."""


def _frozen_inputs(manifest: Mapping[str, Any], root: Path) -> LoadedPackage:
    """The generator package and its evidence, parsed from the bytes checked against the freeze."""
    if manifest_hash(manifest) != manifest.get("manifest_sha256"):
        raise RunnerRefused("the manifest does not hash to its own manifest_sha256")
    rel = manifest.get("generator_package")
    files = manifest.get("input_files", {})
    if not isinstance(rel, str) or rel not in files:
        raise RunnerRefused("the manifest names no frozen generator package")
    base = root.resolve()
    snapshot: dict[str, bytes] = {}

    def read(path: Path) -> bytes:
        try:
            name = path.resolve().relative_to(base).as_posix()
        except ValueError:
            raise RunnerRefused(f"{path} is outside the evaluation root") from None
        if name in snapshot:
            return snapshot[name]
        if name not in files:
            raise RunnerRefused(f"{name} was not frozen by the manifest")
        target = base / name
        if not target.is_file():
            raise RunnerRefused(f"{name} is missing")
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != files[name]:
            raise RunnerRefused(f"{name} is not the file the manifest froze")
        snapshot[name] = data
        return data

    return load_generator_package(root / rel, read=read)


def _environment_drift(
    environment: Mapping[str, Any], observe: Callable[[], Mapping[str, Any]]
) -> list[str]:
    try:
        return verify(environment, observe())
    except Exception as failed:  # an environment that cannot be observed is not the recorded one
        return [f"the environment could not be observed: {type(failed).__name__}: {failed}"[:300]]


def run_blind(
    *,
    manifest: Mapping[str, Any],
    root: Path,
    run_case: Callable[[ResearchInputs], str],
    collect_record: Callable[[str], dict[str, Any]],
    prompts_of: Callable[[str], Sequence[str]] | None = None,
    environment: Mapping[str, Any] | None = None,
    observe_environment: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run every frozen case and return the outputs document (`g0-eval/outputs@1`)."""
    if environment is not None:
        if observe_environment is None:
            raise RunnerRefused(
                "a recorded environment needs a way to observe the environment now "
                "(observe_environment); a recorded hash alone proves nothing"
            )
        if environment_hash(environment) != environment.get("environment_sha256"):
            raise RunnerRefused("the recorded environment does not hash to its environment_sha256")
        before = _environment_drift(environment, observe_environment)
        if before:
            raise RunnerRefused("the environment is not the one recorded: " + "; ".join(before))
    loaded = _frozen_inputs(manifest, root)
    cases: dict[str, Any] = {}
    for case_id in manifest["cases"]:
        try:
            inputs = research_inputs(loaded, case_id)
            episode = run_case(inputs)
            record = dict(collect_record(episode))
            if prompts_of is not None:
                record["prompts"] = list(prompts_of(episode))
                record["prompts_captured"] = True
            else:
                record.setdefault("prompts", [])
                record["prompts_captured"] = False
        except Exception as crashed:  # a case that did not run demonstrated nothing
            cases[case_id] = {
                "status": "CRASHED",
                "reason": f"{type(crashed).__name__}: {crashed}"[:CRASH_DETAIL],
            }
            continue
        cases[case_id] = {"status": "COMPLETED", "record": record}
    outputs: dict[str, Any] = {
        "kind": OUTPUTS_KIND,
        "manifest_sha256": manifest["manifest_sha256"],
        "cases": cases,
    }
    if environment is not None and observe_environment is not None:
        outputs["environment"] = {
            "sha256": environment["environment_sha256"],
            "verified_before": True,
            "drift_after": _environment_drift(environment, observe_environment),
        }
    else:
        outputs["environment"] = {"verified_before": False, "drift_after": None}
    return outputs


__all__ = ["CRASH_DETAIL", "RunnerRefused", "run_blind"]
