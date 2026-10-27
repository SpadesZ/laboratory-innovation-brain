"""Contamination checks: is a holdout case already known to the system's developers?

A holdout is only independent of what the generator was developed against if none of it appears
there. Three kinds of overlap are detected and REPORTED; whether a finding excludes the case or
fails the whole evaluation is the frozen protocol's `contamination_policy`, never this module's.

    exact_text            a holdout text (question, evidence document, or -- when the evaluator
                          supplies the sealed truth -- a secret truth string) equals, contains or is
                          contained in a reference text, after normalisation (lowercase, non-
                          alphanumerics collapsed); texts under `min_chars` normalised characters
                          are too short to mean anything and are skipped
    near_text             the share of the holdout text's word n-grams (n = `ngram`) found in one
                          reference text is at least `near_threshold`
    source_family         the case's declared source family, or device family, or device id, is one
    device_family         the reference corpus already has
    duplicate_unit_id     the experimental unit id occurs twice (within the holdout or across)
    duplicate_unit_content  two units with different ids have the same normalised content: the
                          merged device file without its `device_id`, plus the normalised evidence
                          texts. Renaming a device does not make it a new experimental unit

The reference corpus is the dev/regression generator packages plus, always, the EXPOSED
`benchmarks/g0_screening` cases (read-only): their devices, evidence documents and the truth
rationales that were shown to the implementer (protocol amendment 1). A finding names the holdout
case, the field and the reference unit -- never the matched text, so a contamination report can be
published without republishing a sealed answer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lab_brain.evaluation.packages import (
    SECRET_TRUTH_FIELDS,
    LoadedPackage,
    merged_device,
    normalize_text,
    string_leaves,
)

#: The exposed benchmark: development/regression evidence since protocol amendment 1.
EXPOSED_SCREENING = "benchmarks/g0_screening"
#: The evidence stem the exposed benchmark's harness maps to the default anomaly report.
EXPOSED_DEFAULT_EVIDENCE = "fixtures/evidence/rs_anomaly_report.md"
#: Protocol 1.0.0's disclosure: dev cases dv-01..dv-08 come from the VS-SP-001 benchmark.
EXPOSED_VS_SP_001 = frozenset(f"dv-{i:02d}" for i in range(1, 9))


@dataclass(frozen=True)
class Unit:
    """One experimental unit, as the contamination check sees it."""

    unit_id: str
    origin: str
    case_id: str
    source_family: str
    device_family: str
    device_id: str
    content_hash: str
    #: label -> text: question, evidence documents, and truth strings when supplied.
    texts: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    case_id: str
    kind: str
    field: str
    reference: str
    #: Overlap in permille (1000 for exact and identity findings); an int so it hashes canonically.
    score: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def content_hash(device: Mapping[str, Any], evidence: Iterable[str]) -> str:
    body = {
        "device": {k: v for k, v in device.items() if k != "device_id"},
        "evidence": sorted(normalize_text(text) for text in evidence),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def units_from_package(
    loaded: LoadedPackage,
    origin: str,
    truth: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Unit]:
    """Units of a generator package; with `truth`, its secret strings join the texts."""
    units = []
    for case in loaded.package.cases:
        device = merged_device(loaded, case)
        docs = {
            f"evidence:{ref.name}": loaded.evidence[ref.path].decode("utf-8", "replace")
            for ref in case.evidence
        }
        texts = {"question": case.question, **docs}
        if truth is not None and case.case_id in truth:
            for name in SECRET_TRUTH_FIELDS:
                for i, s in enumerate(string_leaves(truth[case.case_id].get(name))):
                    texts[f"truth:{name}[{i}]"] = s
        units.append(
            Unit(
                unit_id=case.provenance.unit_id,
                origin=origin,
                case_id=case.case_id,
                source_family=case.provenance.source_family,
                device_family=case.provenance.device_family,
                device_id=str(device.get("device_id", "")),
                content_hash=content_hash(device, docs.values()),
                texts=texts,
            )
        )
    return units


def units_from_exposed_screening(root: Path) -> list[Unit]:
    """The exposed G0 screening cases, read-only, as reference units (cases + truth rationales)."""
    bench = root / EXPOSED_SCREENING
    units = []
    for split in ("dev", "holdout"):
        data = json.loads((bench / split / "cases.json").read_text(encoding="utf-8"))
        truth = json.loads((bench / split / "truth.evaluator.json").read_text(encoding="utf-8"))
        nominal = data["nominal_device"]
        for case in data["cases"]:
            stem = case["evidence"]
            doc = (
                root / EXPOSED_DEFAULT_EVIDENCE
                if stem == "default"
                else bench / split / "evidence" / f"{stem}.md"
            )
            evidence = doc.read_text(encoding="utf-8")
            device = {**nominal, **case["device"]}
            texts = {f"evidence:{doc.name}": evidence}
            rationale = truth["cases"].get(case["case_id"], {}).get("rationale")
            if rationale:
                texts["truth:rationale"] = rationale
            cid = case["case_id"]
            units.append(
                Unit(
                    unit_id=f"g0_screening/{split}/{cid}",
                    origin=f"exposed:g0_screening/{split}",
                    case_id=cid,
                    source_family="VS-SP-001"
                    if split == "dev" and cid in EXPOSED_VS_SP_001
                    else f"g0_screening/{split}",
                    device_family=str(nominal["device_id"]),
                    device_id=str(device["device_id"]),
                    content_hash=content_hash(device, [evidence]),
                    texts=texts,
                )
            )
    return units


def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = normalize_text(text).split()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def check(
    holdout: Sequence[Unit],
    reference: Sequence[Unit],
    *,
    min_chars: int = 20,
    ngram: int = 8,
    near_threshold_permille: int = 500,
) -> list[Finding]:
    """Every overlap between the holdout and the reference corpus, and within the holdout."""
    findings: list[Finding] = []
    ref_texts = [
        (f"{u.unit_id}#{label}", normalize_text(t), _ngrams(t, ngram))
        for u in reference
        for label, t in u.texts.items()
    ]
    families = {u.source_family: u.unit_id for u in reference}
    device_families = {u.device_family: u.unit_id for u in reference}
    device_ids = {u.device_id: u.unit_id for u in reference if u.device_id}
    for unit in holdout:
        for label, text in unit.texts.items():
            mine = normalize_text(text)
            if len(mine) < min_chars:
                continue
            grams = _ngrams(text, ngram)
            for where, theirs, their_grams in ref_texts:
                if len(theirs) >= min_chars and (mine in theirs or theirs in mine):
                    findings.append(Finding(unit.case_id, "exact_text", label, where, 1000))
                elif grams:
                    share = len(grams & their_grams) * 1000 // len(grams)
                    if share >= near_threshold_permille:
                        findings.append(Finding(unit.case_id, "near_text", label, where, share))
        if unit.source_family in families:
            findings.append(
                Finding(
                    unit.case_id,
                    "source_family",
                    "provenance.source_family",
                    families[unit.source_family],
                    1000,
                )
            )
        if unit.device_family in device_families:
            findings.append(
                Finding(
                    unit.case_id,
                    "device_family",
                    "provenance.device_family",
                    device_families[unit.device_family],
                    1000,
                )
            )
        if unit.device_id and unit.device_id in device_ids:
            findings.append(
                Finding(
                    unit.case_id,
                    "device_family",
                    "device.device_id",
                    device_ids[unit.device_id],
                    1000,
                )
            )
    findings.extend(_duplicates(holdout, reference))
    return sorted(findings, key=lambda f: (f.case_id, f.kind, f.field, f.reference))


def _duplicates(holdout: Sequence[Unit], reference: Sequence[Unit]) -> list[Finding]:
    findings = []
    everything = [*holdout, *reference]
    for unit in holdout:
        for other in everything:
            if other is unit:
                continue
            where = f"{other.origin}:{other.unit_id}"
            if other.unit_id == unit.unit_id:
                findings.append(Finding(unit.case_id, "duplicate_unit_id", "unit_id", where, 1000))
            elif other.content_hash == unit.content_hash:
                findings.append(
                    Finding(unit.case_id, "duplicate_unit_content", "content", where, 1000)
                )
    return findings


def report(findings: Sequence[Finding]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    for f in findings:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    return {
        "findings": [f.as_dict() for f in findings],
        "by_kind": dict(sorted(by_kind.items())),
        "contaminated_cases": sorted({f.case_id for f in findings}),
    }
