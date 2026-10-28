"""The frozen protocol manifest, and the scoring entry point that refuses anything that drifted.

FREEZE (`freeze`), by the evaluator, BEFORE any run:

    protocol            id, version, contamination policy, statistics (bootstrap seed, resamples),
                        the rubric's cause -> observable map -- from the evaluator's protocol file
    input_files         SHA-256 of the protocol file, the generator package, every evidence file,
                        every reference (dev/regression) package and every exposed-benchmark file
                        the contamination check read -- paths relative to the freeze root
    cases               the frozen case list; nothing outside it is scored, nothing in it is dropped
    commitments         the per-case truth commitments and their root (`sealing.py`) -- never truth
    scorer              SCORER_ID, SCORER_VERSION and the SHA-256 of every source file of
                        `lab_brain.evaluation`, so an edited rule is refused even if unversioned
    contamination       the parameters, the policy and the findings (labels, never matched text)
    exclusions          case id -> reason, fixed now: the contamination policy's exclusions plus any
                        the evaluator declares; an exclusion cannot be added after results exist
    manifest_sha256     canonical hash of all of the above

The generator side receives the generator package and the manifest hash; its outputs document
carries that hash. SCORE (`score_run`), by the evaluator, AFTER the run, refuses -- raising
`ScoringRefused` and scoring nothing -- when the manifest's own hash does not verify, when any
frozen input or scorer source file has a different hash now, when the outputs were produced
against another manifest or name a case that was not frozen, when the revealed truth does not match
its commitment, or when the policy is `fail` and contamination was found.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.evaluation import contamination, scoring
from lab_brain.evaluation.packages import (
    ANSWER_TRUTH_FIELDS,
    PRIVATE_TRUTH_FIELDS,
    LoadedPackage,
    load_generator_package,
    truth_strings,
)
from lab_brain.evaluation.sealing import (
    CommitmentMismatch,
    SealedTruth,
    commitment_root,
    verify_reveal,
)

MANIFEST_KIND = "g0-eval/protocol-manifest@1"
OUTPUTS_KIND = "g0-eval/outputs@1"
POLICIES = ("exclude", "fail")
PACKAGE_DIR = Path(__file__).resolve().parent


class FreezeDrift(ValueError):
    """Something the manifest froze is not what it was at freeze time."""


class ScoringRefused(ValueError):
    """The scorer will not produce a number for this run; the message says why."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scorer_sources() -> dict[str, str]:
    """SHA-256 of every source file of this package -- the scoring rules as they are now."""
    return {
        f"lab_brain/evaluation/{p.name}": sha256_file(p) for p in sorted(PACKAGE_DIR.glob("*.py"))
    }


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    return canonical_hash({k: v for k, v in manifest.items() if k != "manifest_sha256"})


def freeze(
    *,
    root: Path,
    protocol_path: Path,
    package_path: Path,
    commitments: Mapping[str, Any],
    references: Sequence[Path] = (),
    include_exposed_screening: bool = True,
    truth: SealedTruth | None = None,
    declared_exclusions: Mapping[str, str] | None = None,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    """Build the manifest. `truth`, when the evaluator passes it, lets the contamination check
    compare secret truth strings too; nothing from it is written except finding labels."""
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    policy = protocol["contamination_policy"]
    if policy not in POLICIES:
        raise ValueError(f"contamination_policy must be one of {POLICIES}")
    loaded = load_generator_package(package_path)
    cases = [c.case_id for c in loaded.package.cases]
    if sorted(commitments["cases"]) != sorted(cases):
        raise CommitmentMismatch("the commitments do not cover exactly the package's cases")
    if commitment_root(commitments["cases"]) != commitments["root"]:
        raise CommitmentMismatch("the commitments file does not hash to its own root")
    if truth is not None:
        verify_reveal(truth, commitments["cases"], commitments["root"])
    files = _input_files(root, protocol_path, loaded)
    reference_units: list[contamination.Unit] = []
    for ref in references:
        ref_loaded = load_generator_package(ref)
        files.update(_input_files(root, None, ref_loaded))
        reference_units.extend(
            contamination.units_from_package(ref_loaded, f"reference:{ref.name}")
        )
    if include_exposed_screening:
        reference_units.extend(contamination.units_from_exposed_screening(root))
        bench = root / contamination.EXPOSED_SCREENING
        for p in sorted(bench.glob("*/**/*")):
            if p.is_file() and "__pycache__" not in p.parts:
                files[_rel(p, root)] = sha256_file(p)
        default = root / contamination.EXPOSED_DEFAULT_EVIDENCE
        files[_rel(default, root)] = sha256_file(default)
    params = dict(protocol.get("contamination_params", {}))
    holdout_units = contamination.units_from_package(
        loaded, "holdout", truth.truth() if truth else None
    )
    findings = contamination.check(holdout_units, reference_units, **params)
    exclusions = dict(declared_exclusions or {})
    if policy == "exclude":
        for f in findings:
            exclusions.setdefault(f.case_id, f"contamination: {f.kind} ({f.field} ~ {f.reference})")
    unknown = sorted(set(exclusions) - set(cases))
    if unknown:
        raise ValueError(f"exclusions name cases that are not frozen: {unknown}")
    manifest: dict[str, Any] = {
        "kind": MANIFEST_KIND,
        "protocol": {
            "id": protocol["protocol"],
            "version": protocol["version"],
            "contamination_policy": policy,
            "statistics": {
                "confidence": "0.95",
                "interval": "Wilson score; seeded percentile bootstrap over cases",
                "bootstrap_seed": int(protocol["statistics"]["bootstrap_seed"]),
                "bootstrap_resamples": int(protocol["statistics"]["bootstrap_resamples"]),
            },
            "rubric": {"observable_of": dict(protocol["rubric"]["observable_of"])},
        },
        "frozen_at": frozen_at or dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "suite": loaded.package.suite,
        "synthetic": loaded.package.synthetic,
        "generator_package": _rel(package_path, root),
        "input_files": dict(sorted(files.items())),
        "cases": cases,
        "commitments": {"cases": dict(commitments["cases"]), "root": commitments["root"]},
        "scorer": {
            "id": scoring.SCORER_ID,
            "version": scoring.SCORER_VERSION,
            "metrics": list(scoring.METRICS),
            "source_sha256": scorer_sources(),
        },
        "contamination": {
            "policy": policy,
            "params": params,
            "truth_compared": truth is not None,
            "exposed_screening_compared": include_exposed_screening,
            "references": [_rel(r, root) for r in references],
            **contamination.report(findings),
        },
        "exclusions": dict(sorted(exclusions.items())),
    }
    manifest["manifest_sha256"] = manifest_hash(manifest)
    return manifest


def _input_files(root: Path, protocol_path: Path | None, loaded: LoadedPackage) -> dict[str, str]:
    files = {_rel(loaded.path, root): sha256_file(loaded.path)}
    if protocol_path is not None:
        files[_rel(protocol_path, root)] = sha256_file(protocol_path)
    base = loaded.path.resolve().parent
    for rel in loaded.evidence:
        p = base / rel
        files[_rel(p, root)] = sha256_file(p)
    return files


def verify_frozen(manifest: Mapping[str, Any], root: Path) -> None:
    """Raise `FreezeDrift` listing every difference between the freeze and now."""
    drift: list[str] = []
    if manifest.get("kind") != MANIFEST_KIND:
        raise FreezeDrift(f"not a protocol manifest ({MANIFEST_KIND})")
    if manifest_hash(manifest) != manifest.get("manifest_sha256"):
        drift.append("manifest: content does not hash to manifest_sha256 (edited after freeze)")
    for rel, digest in manifest["input_files"].items():
        p = root / rel
        if not p.is_file():
            drift.append(f"{rel}: missing")
        elif sha256_file(p) != digest:
            drift.append(f"{rel}: hash changed")
    now = scorer_sources()
    frozen = manifest["scorer"]["source_sha256"]
    for name in sorted(set(now) | set(frozen)):
        if now.get(name) != frozen.get(name):
            drift.append(f"scorer {name}: source changed since freeze")
    if manifest["scorer"]["version"] != scoring.SCORER_VERSION:
        drift.append("scorer version changed since freeze")
    if commitment_root(manifest["commitments"]["cases"]) != manifest["commitments"]["root"]:
        drift.append("commitments: list does not hash to the frozen root")
    if sorted(manifest["commitments"]["cases"]) != sorted(manifest["cases"]):
        drift.append("commitments: do not cover exactly the frozen cases")
    if drift:
        raise FreezeDrift("; ".join(drift))


def score_run(
    *,
    manifest: Mapping[str, Any],
    root: Path,
    outputs: Mapping[str, Any],
    truth: SealedTruth,
) -> dict[str, Any]:
    """Verify everything, then score every frozen case. Raises `ScoringRefused` otherwise."""
    try:
        verify_frozen(manifest, root)
    except FreezeDrift as exc:
        raise ScoringRefused(f"freeze drift: {exc}") from exc
    if outputs.get("kind") != OUTPUTS_KIND:
        raise ScoringRefused(f"outputs are not {OUTPUTS_KIND}")
    if outputs.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ScoringRefused("outputs were produced against a different protocol manifest")
    records: Mapping[str, Any] = outputs["cases"]
    unknown = sorted(set(records) - set(manifest["cases"]))
    if unknown:
        raise ScoringRefused(f"outputs name cases that were not frozen: {unknown}")
    try:
        verify_reveal(truth, manifest["commitments"]["cases"], manifest["commitments"]["root"])
    except CommitmentMismatch as exc:
        raise ScoringRefused(f"truth reveal: {exc}") from exc
    found = manifest["contamination"]["findings"]
    if manifest["contamination"]["policy"] == "fail" and found:
        cases = manifest["contamination"]["contaminated_cases"]
        raise ScoringRefused(f"contamination policy 'fail' and findings for {cases}")
    loaded = load_generator_package(root / manifest["generator_package"])
    unavailable = {c.case_id: list(c.deployment.unavailable) for c in loaded.package.cases}
    stats = manifest["protocol"]["statistics"]
    rows = scoring.score_cases(
        cases=manifest["cases"],
        outputs=records,
        truth=truth.truth(),
        unavailable=unavailable,
        observable_of=manifest["protocol"]["rubric"]["observable_of"],
        answers=[
            a
            for a in truth_strings(truth.truth(), fields=ANSWER_TRUTH_FIELDS)
            if a not in manifest["cases"]
        ],
        secrets=[
            p
            for p in truth_strings(truth.truth(), fields=PRIVATE_TRUTH_FIELDS)
            if p not in manifest["cases"]
        ],
        exclusions=manifest["exclusions"],
    )
    return {
        "kind": "g0-eval/score@1",
        "manifest_sha256": manifest["manifest_sha256"],
        "protocol": manifest["protocol"]["id"],
        "protocol_version": manifest["protocol"]["version"],
        "suite": manifest["suite"],
        "synthetic": manifest["synthetic"],
        "scorer": {"id": scoring.SCORER_ID, "version": scoring.SCORER_VERSION},
        "bootstrap_seed": stats["bootstrap_seed"],
        "bootstrap_resamples": stats["bootstrap_resamples"],
        "contamination_findings": len(found),
        "summary": scoring.summarize(
            rows, seed=stats["bootstrap_seed"], resamples=stats["bootstrap_resamples"]
        ),
        "cases": rows,
    }
