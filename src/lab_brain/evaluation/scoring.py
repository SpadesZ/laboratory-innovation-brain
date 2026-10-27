"""The deterministic per-case scorer and the honest-denominator summary.

SCORER_ID / SCORER_VERSION name these rules; the protocol manifest additionally pins the SHA-256 of
every source file of this package, so a rule edited after the freeze is refused even if nobody
bumped the version.

PER CASE, from the episode record the generator side collected (the shape
`tests/e2e/test_g0_screening_matrix_postgres.collect` writes) and the revealed truth:

    considered                  every true cause's observable is discriminated by some
                                hypothesis (SUPPORTS/CONTRADICTS prediction); applies when there
                                is a true cause
    decisive_executed           every decisive cheap check the deployment offers ran (screening
                                or verification); applies when at least one is offered
    no_false_confirmation       no confirmation of a hypothesis that discriminates on no true
                                cause's observable, or of a POST_SCREENING hypothesis
    no_false_abnormal           no ABNORMAL reading outside the expected abnormal observables
    no_post_screening_support   no SUPPORTS relation to a POST_SCREENING hypothesis
    no_leak                     no secret truth string in the record or in the prompts it carries

DENOMINATOR HONESTY. Every frozen case appears in the per-case table with a status:

    COMPLETED   scored on its record
    REFUSED, CRASHED, MALFORMED, MISSING
                the run did not produce a scoreable record; it FAILS every applicable metric,
                with the status as the reason -- a case that did not run demonstrated nothing
    EXCLUDED    removed by a reason frozen in the manifest (an evaluator-declared exclusion, or a
                contamination finding under the `exclude` policy)

Each metric reports `n` (applicable, not excluded), `k`, the rate, the Wilson 95% interval and the
seeded bootstrap interval, AND a `conservative` block that keeps excluded cases in the denominator
as failures, so an exclusion can never make a number look better than the full frozen set allows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lab_brain.evaluation.packages import find_truth
from lab_brain.evaluation.stats import bootstrap, wilson

SCORER_ID = "g0-eval-screening-scorer"
SCORER_VERSION = "1.0.0"

METRICS: tuple[str, ...] = (
    "considered",
    "decisive_executed",
    "no_false_confirmation",
    "no_false_abnormal",
    "no_post_screening_support",
    "no_leak",
)
STATUSES = ("COMPLETED", "REFUSED", "CRASHED", "MALFORMED", "MISSING", "EXCLUDED")
_REQUIRED = ("hypotheses", "screening_executed", "verification_executed", "readings", "confirmed")


def applicable(truth: Mapping[str, Any], unavailable: Sequence[str]) -> dict[str, bool]:
    """Which metrics a case can be scored on -- from the truth and the frozen inputs only."""
    decisive = [c for c in truth.get("decisive_cheap_checks", []) if c not in unavailable]
    return {
        "considered": bool(truth.get("true_causes")),
        "decisive_executed": bool(decisive),
        "no_false_confirmation": True,
        "no_false_abnormal": True,
        "no_post_screening_support": True,
        "no_leak": True,
    }


def score_record(
    record: Mapping[str, Any],
    truth: Mapping[str, Any],
    *,
    unavailable: Sequence[str],
    observable_of: Mapping[str, str],
    leaks: int,
) -> dict[str, bool]:
    causes = [observable_of[c] for c in truth.get("true_causes", [])]
    hypotheses = record["hypotheses"]
    discriminated = {o for h in hypotheses for o in h["discriminates_on"]}
    decisive = [c for c in truth.get("decisive_cheap_checks", []) if c not in unavailable]
    executed = set(record["screening_executed"]) | set(record["verification_executed"])
    abnormal = {r["observable"] for r in record["readings"] if r["finding"] == "ABNORMAL"}
    false_confirmation = False
    if record["confirmed"] is not None:
        h = next((x for x in hypotheses if x["hypothesis_id"] == record["confirmed"]), None)
        false_confirmation = (
            h is None
            or h["origin"] == "POST_SCREENING"
            or not set(h["discriminates_on"]) & set(causes)
        )
    return {
        "considered": all(o in discriminated for o in causes),
        "decisive_executed": all(c in executed for c in decisive),
        "no_false_confirmation": not false_confirmation,
        "no_false_abnormal": not abnormal - set(truth.get("expected_abnormal_observables", [])),
        "no_post_screening_support": not any(
            h.get("supports", 0) for h in hypotheses if h["origin"] == "POST_SCREENING"
        ),
        "no_leak": leaks == 0,
    }


def _texts(value: Any, path: str = "record") -> dict[str, str]:
    if isinstance(value, str):
        return {path: value}
    out: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key, inner in value.items():
            out.update(_texts(inner, f"{path}.{key}"))
    elif isinstance(value, list | tuple):
        for i, inner in enumerate(value):
            out.update(_texts(inner, f"{path}[{i}]"))
    return out


def score_cases(
    *,
    cases: Sequence[str],
    outputs: Mapping[str, Mapping[str, Any]],
    truth: Mapping[str, Mapping[str, Any]],
    unavailable: Mapping[str, Sequence[str]],
    observable_of: Mapping[str, str],
    forbidden: Sequence[str],
    exclusions: Mapping[str, str],
) -> list[dict[str, Any]]:
    """One row per FROZEN case, in frozen order. Outputs for unknown cases are the caller's
    refusal, not this function's silence."""
    rows = []
    for case_id in cases:
        applies = applicable(truth[case_id], unavailable[case_id])
        entry = outputs.get(case_id)
        row: dict[str, Any] = {"case_id": case_id, "applicable": applies}
        if case_id in exclusions:
            row.update(status="EXCLUDED", reason=exclusions[case_id], metrics={})
        elif entry is None:
            row.update(status="MISSING", reason="no output for a frozen case", metrics={})
        elif entry.get("status") != "COMPLETED":
            status = entry.get("status")
            status = status if status in ("REFUSED", "CRASHED") else "MALFORMED"
            row.update(status=status, reason=str(entry.get("reason", status)), metrics={})
        elif not isinstance(entry.get("record"), Mapping) or any(
            k not in entry["record"] for k in _REQUIRED
        ):
            row.update(status="MALFORMED", reason="record lacks required fields", metrics={})
        else:
            record = entry["record"]
            leaks = len(find_truth(_texts(dict(record)), forbidden))
            row.update(
                status="COMPLETED",
                reason="",
                leaks=leaks,
                metrics=score_record(
                    record,
                    truth[case_id],
                    unavailable=unavailable[case_id],
                    observable_of=observable_of,
                    leaks=leaks,
                ),
            )
        if row["status"] not in ("COMPLETED", "EXCLUDED"):
            row["metrics"] = {m: False for m, a in applies.items() if a}
        rows.append(row)
    return rows


def _proportion(values: Sequence[bool], *, seed: int, resamples: int, label: str) -> dict[str, Any]:
    n, k = len(values), sum(values)
    interval = wilson(k, n)
    boot = bootstrap(values, seed=seed, resamples=resamples, label=label)
    return {
        "n": n,
        "k": k,
        "rate": round(k / n, 4) if n else None,
        "wilson95": list(interval) if interval else None,
        "bootstrap95": list(boot) if boot else None,
    }


def summarize(rows: Sequence[Mapping[str, Any]], *, seed: int, resamples: int) -> dict[str, Any]:
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    metrics: dict[str, Any] = {}
    for metric in METRICS:
        applies = [r for r in rows if r["applicable"][metric]]
        scored = [bool(r["metrics"][metric]) for r in applies if r["status"] != "EXCLUDED"]
        excluded = sum(1 for r in applies if r["status"] == "EXCLUDED")
        conservative = [
            bool(r["metrics"][metric]) if r["status"] != "EXCLUDED" else False for r in applies
        ]
        metrics[metric] = {
            **_proportion(scored, seed=seed, resamples=resamples, label=metric),
            "applicable": len(applies),
            "excluded": excluded,
            "not_completed": sum(
                1 for r in applies if r["status"] not in ("COMPLETED", "EXCLUDED")
            ),
            "conservative": _proportion(
                conservative, seed=seed, resamples=resamples, label=f"{metric}/conservative"
            ),
        }
    return {
        "frozen_cases": len(rows),
        "status_counts": counts,
        "excluded": [
            {"case_id": r["case_id"], "reason": r["reason"]}
            for r in rows
            if r["status"] == "EXCLUDED"
        ],
        "not_completed": [
            {"case_id": r["case_id"], "status": r["status"], "reason": r["reason"]}
            for r in rows
            if r["status"] not in ("COMPLETED", "EXCLUDED")
        ],
        "metrics": metrics,
    }
