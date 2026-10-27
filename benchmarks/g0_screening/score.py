"""Score a G0 screening matrix run against evaluator-only truth, AFTER the run.

    python benchmarks/g0_screening/score.py <outputs.json> [--markdown <out.md>] [--json <out.json>]

The research system never imports this file and never reads a truth file: the matrix harness
collects what each episode did from the database, writes it to `outputs.json`, and only then is
truth read -- here. Metric definitions and thresholds are `protocol.json`'s, frozen before any run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OBSERVABLE_OF = {
    "contact_discontinuity": "sp.contact_connectivity",
    "normalization_error": "sp.normalization_basis",
    "mesh_artifact": "sp.mesh_stability",
    "dopant_compensation": "sp.carrier_profile",
    "probe_artifact": "sp.probe_contact_resistance",
}
SCREENABLE_TYPES = {
    "ANALYTICAL_RULE_CHECK",
    "EXISTING_EVIDENCE_LOOKUP",
    "HISTORICAL_CASE_COMPARISON",
}


def load_truth() -> dict[str, dict[str, Any]]:
    truth: dict[str, dict[str, Any]] = {}
    for split in ("dev", "holdout"):
        data = json.loads((HERE / split / "truth.evaluator.json").read_text(encoding="utf-8"))
        truth.update(data["cases"])
    return truth


def truth_strings(truth: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """What must never reach a model: case ids, truth keys, evaluator rationales, fixture notes."""
    out = [*truth]
    for case in truth.values():
        out.extend(case["true_causes"])
        out.append(case["rationale"])
    fixture = json.loads(
        (HERE.parents[1] / "fixtures/vertical/sp_rs_root_cause_benchmark.json").read_text(
            encoding="utf-8"
        )
    )
    out.extend(c["note"] for c in fixture["cases"])
    out.extend(c["case_id"] for c in fixture["cases"])
    return [s for s in out if len(s) >= 6]


def score_case(record: Mapping[str, Any], truth: Mapping[str, Any]) -> dict[str, Any]:
    causes = [OBSERVABLE_OF[c] for c in truth["true_causes"]]
    hypotheses = record["hypotheses"]
    considered = {
        o: sorted({h["origin"] for h in hypotheses if o in h["discriminates_on"]}) for o in causes
    }
    unavailable = set(record.get("unavailable", []))
    decisive = [c for c in truth["decisive_cheap_checks"] if c not in unavailable]
    executed = set(record["screening_executed"]) | set(record["verification_executed"])
    abnormal = {r["observable"] for r in record["readings"] if r["finding"] == "ABNORMAL"}
    confirmed = record["confirmed"]
    false_confirmation = False
    if confirmed is not None:
        h = next((x for x in hypotheses if x["hypothesis_id"] == confirmed), None)
        false_confirmation = (
            h is None
            or h["origin"] == "POST_SCREENING"
            or not set(h["discriminates_on"]) & set(causes)
        )
    return {
        "considered_any": all(considered[o] for o in causes) if causes else True,
        "considered_pre_observation": all("PRE_OBSERVATION" in considered[o] for o in causes)
        if causes
        else True,
        "considered_post_screening_only": bool(causes)
        and all(considered[o] == ["POST_SCREENING"] for o in causes if considered[o])
        and all(considered[o] for o in causes),
        "cheap_visible": bool(decisive),
        "decisive_executed": bool(decisive) and all(c in executed for c in decisive),
        "false_abnormal": sorted(abnormal - set(truth["expected_abnormal_observables"])),
        "missed_abnormal": sorted(set(truth["expected_abnormal_observables"]) - abnormal)
        if record["screening_enabled"] and decisive
        else [],
        "false_confirmation": false_confirmation,
        "post_screening_support": sum(
            h["supports"] for h in hypotheses if h["origin"] == "POST_SCREENING"
        ),
        "repeated_screened_reading": sorted(
            set(record["screening_executed"]) & set(record["verification_executed"])
        ),
        "ineligible_screening": sorted(
            c
            for c, kind in record["screening_kinds"].items()
            if kind not in SCREENABLE_TYPES or c in unavailable
        ),
        "screening_checks": len(record["screening_executed"]),
        "normal_readings": sum(1 for r in record["readings"] if r["finding"] == "NORMAL"),
        "post_screening_rivals": sum(1 for h in hypotheses if h["origin"] == "POST_SCREENING"),
        "limitation_stated": (
            not any(h["origin"] == "POST_SCREENING" for h in hypotheses)
            or "cannot support it" in record["conclusion_statement"]
        ),
        "conclusion": record["conclusion"],
        "episode_state": record["episode_state"],
        "leaks": record.get("leaks", []),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    visible = [r for r in rows if r["cheap_visible"]]
    with_cause = [r for r in rows if r.get("_has_cause")]
    return {
        "cases": n,
        "considered_rate": _rate([r["considered_any"] for r in with_cause]),
        "considered_pre_observation_rate": _rate(
            [r["considered_pre_observation"] for r in with_cause]
        ),
        "considered_rate_on_cheap_visible": _rate([r["considered_any"] for r in visible]),
        "decisive_executed_rate": _rate([r["decisive_executed"] for r in visible]),
        "false_abnormal": sum(len(r["false_abnormal"]) for r in rows),
        "false_confirmation": sum(1 for r in rows if r["false_confirmation"]),
        "post_screening_support": sum(r["post_screening_support"] for r in rows),
        "repeated_screened_reading": sum(len(r["repeated_screened_reading"]) for r in rows),
        "ineligible_screening": sum(len(r["ineligible_screening"]) for r in rows),
        "mean_screening_checks_per_case": round(sum(r["screening_checks"] for r in rows) / n, 3)
        if n
        else 0.0,
        "normal_readings": sum(r["normal_readings"] for r in rows),
        "post_screening_rivals": sum(r["post_screening_rivals"] for r in rows),
        "limitation_stated_rate": _rate([r["limitation_stated"] for r in rows]),
        "confirmed": sum(1 for r in rows if r["conclusion"] == "CONFIRMED"),
        "leak": sum(len(r["leaks"]) for r in rows),
    }


def _rate(values: Sequence[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def evaluate(outputs: Mapping[str, Any]) -> dict[str, Any]:
    truth = load_truth()
    protocol = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
    result: dict[str, Any] = {"protocol": protocol["version"], "configurations": {}}
    for config, splits in outputs["configurations"].items():
        result["configurations"][config] = {}
        for split, records in splits.items():
            rows = []
            for case_id, record in records.items():
                row = score_case(record, truth[case_id])
                row["_has_cause"] = bool(truth[case_id]["true_causes"])
                row["case_id"] = case_id
                rows.append(row)
            result["configurations"][config][split] = {"summary": summarize(rows), "cases": rows}
    result["acceptance"] = acceptance(result, protocol)
    return result


def acceptance(result: Mapping[str, Any], protocol: Mapping[str, Any]) -> dict[str, Any]:
    thresholds = protocol["acceptance_thresholds"]
    verdicts: dict[str, Any] = {}
    for config, splits in result["configurations"].items():
        for split, block in splits.items():
            s = block["summary"]
            failures = [
                f"{k}={s[k]} (must be {v})"
                for k, v in thresholds["all_configurations"].items()
                if s[k] != v
            ]
            if config in ("screening", "combined"):
                t = thresholds["screening_and_combined"]
                if (s["decisive_executed_rate"] or 0) < t["decisive_executed_rate_min"]:
                    failures.append(f"decisive_executed_rate={s['decisive_executed_rate']}")
                if (s["considered_rate_on_cheap_visible"] or 0) < t[
                    "considered_rate_on_cheap_visible_min"
                ]:
                    failures.append(
                        f"considered_rate_on_cheap_visible={s['considered_rate_on_cheap_visible']}"
                    )
                if s["mean_screening_checks_per_case"] > t["mean_screening_checks_per_case_max"]:
                    failures.append(
                        f"mean_screening_checks_per_case={s['mean_screening_checks_per_case']}"
                    )
            verdicts[f"{config}/{split}"] = failures if failures else "PASS"
    return verdicts


#: Protocol amendment 1: the former holdout is development/regression evidence, not a blind split.
SPLIT_LABELS = {"dev": "dev", "holdout": "exposed-regression (former holdout)"}


def markdown(result: Mapping[str, Any]) -> str:
    keys = [
        "considered_rate",
        "considered_pre_observation_rate",
        "decisive_executed_rate",
        "false_abnormal",
        "false_confirmation",
        "post_screening_support",
        "repeated_screened_reading",
        "mean_screening_checks_per_case",
        "normal_readings",
        "post_screening_rivals",
        "confirmed",
        "leak",
    ]
    lines = [
        "| config / split | " + " | ".join(keys) + " | acceptance |",
        "|---" * (len(keys) + 2) + "|",
    ]
    for config, splits in result["configurations"].items():
        for split, block in splits.items():
            s = block["summary"]
            verdict = result["acceptance"][f"{config}/{split}"]
            lines.append(
                f"| {config} / {SPLIT_LABELS.get(split, split)} | "
                + " | ".join(str(s[k]) for k in keys)
                + f" | {'PASS' if verdict == 'PASS' else 'FAIL: ' + '; '.join(verdict)} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("outputs")
    parser.add_argument("--markdown")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    result = evaluate(json.loads(Path(args.outputs).read_text(encoding="utf-8")))
    table = markdown(result)
    if args.markdown:
        Path(args.markdown).write_text(table, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
