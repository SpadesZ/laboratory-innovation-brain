"""G0 independent-holdout workflow: contamination against dev packages and the EXPOSED cases.

ALL HOLDOUT CASES HERE ARE SYNTHETIC, built to trip one detector each; several are deliberately
derived from the exposed `benchmarks/g0_screening` cases (read here, never modified) to prove that
a "new" holdout recycled from what the implementer has seen is caught:

    recycled        an exposed dev case's device and default evidence, renamed     -> duplicate
                                                                                     unit content,
                                                                                     exact text
    near copy       an exposed evidence document with a few words changed         -> near text
    same family     a fresh case declaring the VS-SP-001 source / PS-500 devices  -> family overlap
    same unit       two holdout cases sharing one experimental unit id            -> duplicate id
    truth reuse     a sealed rationale copied from an exposed truth file          -> exact text on
                                                                                     a truth field
    clean           a fresh synthetic case                                         -> nothing
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab_brain.evaluation import contamination
from lab_brain.evaluation.packages import load_generator_package

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "benchmarks" / "g0_screening"


def _package(tmp: Path, name: str, cases: list[dict[str, Any]], docs: dict[str, str]) -> Path:
    base = tmp / name
    (base / "evidence").mkdir(parents=True)
    for doc, text in docs.items():
        (base / "evidence" / doc).write_text(text, encoding="utf-8")
    path = base / "generator-package.json"
    path.write_text(
        json.dumps(
            {
                "kind": "g0-eval/generator-package@1",
                "suite": f"synthetic-{name}",
                "synthetic": True,
                "nominal_device": {},
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    return path


def _case(
    case_id: str, device: dict[str, Any], doc: str, unit: str, family: str, devfam: str
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "question": f"SYNTHETIC question for {case_id}: what explains the reported resistance?",
        "device": device,
        "evidence": [{"name": doc, "path": f"evidence/{doc}"}],
        "provenance": {"unit_id": unit, "source_family": family, "device_family": devfam},
    }


def test_recycled_near_family_duplicate_and_truth_reuse_are_all_found(tmp_path):
    dev = json.loads((BENCH / "dev" / "cases.json").read_text(encoding="utf-8"))
    exposed_truth = json.loads((BENCH / "dev" / "truth.evaluator.json").read_text())
    dv04 = next(c for c in dev["cases"] if c["case_id"] == "dv-04")
    recycled_device = {**dev["nominal_device"], **dv04["device"], "device_id": "SYN-404"}
    default_report = (REPO / "fixtures" / "evidence" / "rs_anomaly_report.md").read_text()
    claimed = (BENCH / "dev" / "evidence" / "continuity_claimed.md").read_text()
    words = claimed.split()
    near = " ".join(w if i % 25 else "SYNTHETICALLY" for i, w in enumerate(words))
    fresh = (
        "SYNTHETIC evidence written for this test only: the cryogenic probe card on wafer "
        "lot Q9 drifted during an overnight soak, and nobody logged the chuck temperature."
    )
    holdout_path = _package(
        tmp_path,
        "holdout",
        [
            _case("syn-recycled", recycled_device, "a.md", "u-recycled", "syn-f1", "syn-d1"),
            _case("syn-near", {"device_id": "SYN-501"}, "b.md", "u-near", "syn-f2", "syn-d2"),
            _case(
                "syn-family", {"device_id": "SYN-502"}, "c.md", "u-family", "VS-SP-001", "PS-500"
            ),
            _case("syn-unit-a", {"device_id": "SYN-503"}, "d.md", "u-shared", "syn-f4", "syn-d4"),
            _case(
                "syn-unit-b",
                {"device_id": "SYN-504", "x": "1"},
                "e.md",
                "u-shared",
                "syn-f5",
                "syn-d5",
            ),
            _case("syn-clean", {"device_id": "SYN-505"}, "f.md", "u-clean", "syn-f6", "syn-d6"),
        ],
        {
            "a.md": default_report,
            "b.md": near,
            "c.md": "SYNTHETIC: a fresh report about structure SYN-502 and its odd sheet values.",
            "d.md": "SYNTHETIC: a fresh report about structure SYN-503, unrelated to anything.",
            "e.md": "SYNTHETIC: a fresh report about structure SYN-504, also new and unrelated.",
            "f.md": fresh,
        },
    )
    sealed_truth = {
        "syn-clean": {"rationale": "SYNTHETIC rationale nobody has seen: the chuck drifted"},
        "syn-unit-a": {"rationale": exposed_truth["cases"]["dv-07"]["rationale"]},
    }
    holdout = contamination.units_from_package(
        load_generator_package(holdout_path), "holdout", sealed_truth
    )
    reference = contamination.units_from_exposed_screening(REPO)
    findings = contamination.check(holdout, reference)
    kinds: dict[str, set[str]] = {}
    for f in findings:
        kinds.setdefault(f.case_id, set()).add(f.kind)

    assert {"duplicate_unit_content", "exact_text"} <= kinds["syn-recycled"]
    recycled = [f for f in findings if f.case_id == "syn-recycled"]
    assert any(f.reference.endswith("g0_screening/dev/dv-04") for f in recycled)
    assert kinds["syn-near"] == {"near_text"}
    assert next(f for f in findings if f.case_id == "syn-near").score < 1000
    assert kinds["syn-family"] == {"source_family", "device_family"}
    assert kinds["syn-unit-b"] == {"duplicate_unit_id"}
    assert kinds["syn-unit-a"] == {"duplicate_unit_id", "exact_text"}
    assert any(f.field == "truth:rationale[0]" for f in findings if f.case_id == "syn-unit-a")
    assert "syn-clean" not in kinds

    # A report names fields and reference units, never the matched text.
    published = json.dumps(contamination.report(findings))
    assert exposed_truth["cases"]["dv-07"]["rationale"] not in published
    assert "chuck" not in published


def test_a_dev_regression_package_is_a_reference_too(tmp_path):
    text = (
        "SYNTHETIC development evidence: the access region mesh was refined twice and the "
        "simulated resistance moved by a third each time, which nobody expected at all."
    )
    dev_path = _package(
        tmp_path,
        "dev",
        [_case("syn-dev-1", {"device_id": "SYN-700"}, "a.md", "u-dev", "syn-devfam", "syn-dd")],
        {"a.md": text},
    )
    holdout_path = _package(
        tmp_path,
        "holdout",
        [_case("syn-h-1", {"device_id": "SYN-800"}, "a.md", "u-h", "syn-devfam", "syn-hd")],
        {"a.md": text.upper()},
    )
    findings = contamination.check(
        contamination.units_from_package(load_generator_package(holdout_path), "holdout"),
        contamination.units_from_package(load_generator_package(dev_path), "reference:dev"),
    )
    # Same text in other case, same declared source family, and -- the device differing only by
    # its id -- the same experimental unit under another name.
    assert {f.kind for f in findings} == {"exact_text", "source_family", "duplicate_unit_content"}
