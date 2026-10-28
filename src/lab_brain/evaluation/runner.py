"""The generator side of a blind evaluation: run each frozen case, write outputs bound to it.

Until now the workflow had the evaluator's tools (seal, contamination check, freeze, score) and no
runner, so "run every case blind" was a description, not a program an independent evaluator could
reproduce. This is the program. It is product-agnostic: the caller supplies how ONE case is run
(`run_case`, e.g. through the web workspace) and how a finished episode is read back
(`collect_record`, e.g. `lab_brain.evaluation.collect` via the matrix harness).

WHAT THE RUNNER GUARANTEES

    the frozen package   before anything runs, the manifest must hash to itself and the generator
                         package on disk must be the one it froze (SHA-256 of the file). A changed
                         package is a different experiment and is refused.
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
    bound                the outputs document names the manifest hash and, when given, the
                         environment manifest's hash (`lab_brain.evaluation.environment`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_brain.evaluation.manifest import OUTPUTS_KIND, manifest_hash, sha256_file
from lab_brain.evaluation.packages import ResearchInputs, load_generator_package, research_inputs

#: Longest error text kept with a CRASHED case: enough to diagnose, too short to carry a payload.
CRASH_DETAIL = 300


class RunnerRefused(ValueError):
    """The package or manifest is not the frozen one; nothing was run."""


def _frozen_package(manifest: Mapping[str, Any], root: Path) -> Path:
    if manifest_hash(manifest) != manifest.get("manifest_sha256"):
        raise RunnerRefused("the manifest does not hash to its own manifest_sha256")
    rel = manifest.get("generator_package")
    files = manifest.get("input_files", {})
    if not isinstance(rel, str) or rel not in files:
        raise RunnerRefused("the manifest names no frozen generator package")
    path = root / rel
    if not path.is_file() or sha256_file(path) != files[rel]:
        raise RunnerRefused(f"{rel} is not the generator package the manifest froze")
    return path


def run_blind(
    *,
    manifest: Mapping[str, Any],
    root: Path,
    run_case: Callable[[ResearchInputs], str],
    collect_record: Callable[[str], dict[str, Any]],
    prompts_of: Callable[[str], Sequence[str]] | None = None,
    environment_sha256: str | None = None,
) -> dict[str, Any]:
    """Run every frozen case and return the outputs document (`g0-eval/outputs@1`)."""
    loaded = load_generator_package(_frozen_package(manifest, root))
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
    if environment_sha256 is not None:
        outputs["environment_sha256"] = environment_sha256
    return outputs


__all__ = ["CRASH_DETAIL", "RunnerRefused", "run_blind"]
