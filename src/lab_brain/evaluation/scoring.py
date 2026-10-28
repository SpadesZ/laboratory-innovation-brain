"""The deterministic per-case scorer and the honest-denominator summary.

SCORER_ID / SCORER_VERSION name these rules; the protocol manifest additionally pins the SHA-256 of
every source file of this package, so a rule edited after the freeze is refused even if nobody
bumped the version.

PER CASE, from the episode record the generator side collected (the shape
`tests/e2e/test_g0_screening_matrix_postgres.collect` writes) and the revealed truth:

    considered_pre_screening    every true cause's observable is discriminated by a hypothesis
                                formed BEFORE any screening reading (PRE_OBSERVATION); applies
                                when there is a true cause
    considered_with_screening   the same, by a hypothesis of either origin. Reported apart from the
                                first: a cause first named after the screening reading showed it is
                                screening's discovery, not the reasoning's, and the summary counts
                                those cases as `screening_discoveries`
    competing_pre_screening     at least two hypotheses formed before screening, discriminating on
                                different observables (SAI 3.4 G0-S: >= 2 competing hypotheses)
    refutable                   every hypothesis carries at least one CONTRADICTS prediction -- an
                                observable that could refute it (`refutable_on`); a run with no
                                hypothesis fails
    decisive_executed           every decisive cheap check the deployment offers ran (screening
                                or verification); applies when at least one is offered
    no_false_confirmation       no confirmation of a hypothesis that discriminates on no true
                                cause's observable, nor of a POST_SCREENING hypothesis without at
                                least one ADMISSIBLE support (below)
    no_false_abnormal           no ABNORMAL reading outside the expected abnormal observables
    no_inadmissible_post_screening_support
                                no SUPPORTS relation to a POST_SCREENING hypothesis whose basis is
                                inadmissible. A support is admissible only when it is prospective
                                and independent: it rests on observations only, and none of them is
                                the screened observation, observed before the hypothesis, a repeat
                                of the screened check, or the screened output content (the
                                012y/011m/011o rules, re-derived here from the facts the record
                                carries, never trusted as a verdict)
    no_input_leak               no truth string -- answer or secret -- in anything sent TO the model
                                (`record.prompts`): a leak is truth reaching the generator
    no_secret_in_output         no case id, and no long secret text (an evaluator rationale or note
                                of at least OUTPUT_SECRET_MIN_WORDS words), in what the run produced

WHY THE LEAK CHECK IS SPLIT (scorer 2.0.0). Scorer 1.0.0 scanned the whole record, outputs
included, for every truth string. A run that reasoned its way to the right answer and named it --
"most likely cause: contact_discontinuity" -- was scored as a leak. The answer is what the run is
FOR; finding it in the output is the success being measured. Truth in the INPUTS is a leak whatever
its length; in the OUTPUTS only material the run could not have derived counts: the case id, and an
evaluator's own long prose reproduced. A short rationale ("the via is open") is scanned in the
inputs only, because a correct conclusion may say the same few words.

MALFORMED OUTPUT. A record is validated before it is scored (`record_problems`): every field the
metrics read must be present with the right type, hypothesis ids unique, origins and findings from
their vocabularies, a confirmation naming a recorded hypothesis, and every support listing its
provenance facts. Anything else is MALFORMED with the first problem as its reason -- the scorer
never raises on a generator's output, and never guesses a missing fact in either direction.

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

from lab_brain.evaluation.packages import find_truth, normalize_text
from lab_brain.evaluation.stats import bootstrap, wilson

SCORER_ID = "g0-eval-screening-scorer"
SCORER_VERSION = "2.0.0"

METRICS: tuple[str, ...] = (
    "considered_pre_screening",
    "considered_with_screening",
    "competing_pre_screening",
    "refutable",
    "decisive_executed",
    "no_false_confirmation",
    "no_false_abnormal",
    "no_inadmissible_post_screening_support",
    "no_input_leak",
    "no_secret_in_output",
)
STATUSES = ("COMPLETED", "REFUSED", "CRASHED", "MALFORMED", "MISSING", "EXCLUDED")
ORIGINS = ("PRE_OBSERVATION", "POST_SCREENING")
FINDINGS = ("NORMAL", "ABNORMAL", "INCONCLUSIVE")

#: The provenance facts each SUPPORTS entry must carry. The scorer derives admissibility from them.
SUPPORT_FACTS: tuple[str, ...] = (
    "unobserved_basis",
    "screened_observation",
    "observed_before_hypothesis",
    "repeats_screened_check",
    "shares_screened_output",
)

#: Below this many words, a secret text is scanned in the inputs only (see the module docstring).
OUTPUT_SECRET_MIN_WORDS = 8

_LISTS_OF_STR = ("screening_executed", "verification_executed", "prompts")


def applicable(truth: Mapping[str, Any], unavailable: Sequence[str]) -> dict[str, bool]:
    """Which metrics a case can be scored on -- from the truth and the frozen inputs only."""
    decisive = [c for c in truth.get("decisive_cheap_checks", []) if c not in unavailable]
    has_cause = bool(truth.get("true_causes"))
    return {
        "considered_pre_screening": has_cause,
        "considered_with_screening": has_cause,
        "competing_pre_screening": True,
        "refutable": True,
        "decisive_executed": bool(decisive),
        "no_false_confirmation": True,
        "no_false_abnormal": True,
        "no_inadmissible_post_screening_support": True,
        "no_input_leak": True,
        "no_secret_in_output": True,
    }


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def record_problems(record: Any) -> str | None:
    """The first reason this record cannot be scored, or None. Never raises."""
    if not isinstance(record, Mapping):
        return "the record is not an object"
    for key in ("hypotheses", "readings", *_LISTS_OF_STR, "confirmed"):
        if key not in record:
            return f"record lacks `{key}`"
    for key in _LISTS_OF_STR:
        if not _is_str_list(record[key]):
            return f"`{key}` is not a list of strings"
    if "conclusion_statement" in record and not isinstance(record["conclusion_statement"], str):
        return "`conclusion_statement` is not a string"
    hypotheses = record["hypotheses"]
    if not isinstance(hypotheses, list):
        return "`hypotheses` is not a list"
    seen: set[str] = set()
    for i, h in enumerate(hypotheses):
        if not isinstance(h, Mapping):
            return f"hypotheses[{i}] is not an object"
        hid = h.get("hypothesis_id")
        if not isinstance(hid, str) or not hid:
            return f"hypotheses[{i}] has no hypothesis_id"
        if hid in seen:
            return f"hypothesis {hid} is recorded twice"
        seen.add(hid)
        if h.get("origin") not in ORIGINS:
            return f"hypothesis {hid}: origin {h.get('origin')!r} is not one of {ORIGINS}"
        for key in ("discriminates_on", "refutable_on"):
            if not _is_str_list(h.get(key)):
                return f"hypothesis {hid}: `{key}` is not a list of strings"
        supports = h.get("supports")
        if not isinstance(supports, list):
            # Scorer 1.0.0 records carried a bare count: it cannot say whether a support was
            # admissible, so it is not scored as either.
            return f"hypothesis {hid}: `supports` must list each relation's provenance"
        for j, support in enumerate(supports):
            if not isinstance(support, Mapping) or not isinstance(support.get("relation_id"), str):
                return f"hypothesis {hid}: supports[{j}] has no relation_id"
            missing = [f for f in SUPPORT_FACTS if not isinstance(support.get(f), bool)]
            if missing:
                return f"hypothesis {hid}: supports[{j}] lacks provenance facts {missing}"
    readings = record["readings"]
    if not isinstance(readings, list):
        return "`readings` is not a list"
    for i, r in enumerate(readings):
        if not isinstance(r, Mapping) or not isinstance(r.get("observable"), str):
            return f"readings[{i}] has no observable"
        if r.get("finding") not in FINDINGS:
            return f"readings[{i}]: finding {r.get('finding')!r} is not one of {FINDINGS}"
    confirmed = record["confirmed"]
    if confirmed is not None and (not isinstance(confirmed, str) or confirmed not in seen):
        return f"`confirmed` names {confirmed!r}, which is not a recorded hypothesis"
    return None


def admissible(support: Mapping[str, Any]) -> bool:
    """A prospective, independent support: none of the 012y/011m inadmissible bases holds."""
    return not any(bool(support[f]) for f in SUPPORT_FACTS)


def _output_texts(record: Mapping[str, Any]) -> dict[str, str]:
    return {k: v for k, v in _texts(dict(record)).items() if not k.startswith("record.prompts")}


def leak_counts(
    record: Mapping[str, Any],
    *,
    answers: Sequence[str],
    secrets: Sequence[str],
    case_ids: Sequence[str],
) -> tuple[int, int]:
    """(truth strings in the inputs, secrets in the outputs) -- counts only, never the strings."""
    inputs = {f"prompt[{i}]": p for i, p in enumerate(record["prompts"])}
    input_hits = len(find_truth(inputs, [*answers, *secrets, *case_ids])) if inputs else 0
    long_secrets = [s for s in secrets if len(normalize_text(s).split()) >= OUTPUT_SECRET_MIN_WORDS]
    output_hits = len(find_truth(_output_texts(record), [*case_ids, *long_secrets]))
    return input_hits, output_hits


def score_record(
    record: Mapping[str, Any],
    truth: Mapping[str, Any],
    *,
    unavailable: Sequence[str],
    observable_of: Mapping[str, str],
    input_leaks: int,
    output_leaks: int,
) -> dict[str, bool]:
    """Score a record `record_problems` accepted."""
    causes = [observable_of[c] for c in truth.get("true_causes", [])]
    hypotheses = record["hypotheses"]
    before = {
        o for h in hypotheses if h["origin"] == "PRE_OBSERVATION" for o in h["discriminates_on"]
    }
    anyone = {o for h in hypotheses for o in h["discriminates_on"]}
    decisive = [c for c in truth.get("decisive_cheap_checks", []) if c not in unavailable]
    executed = set(record["screening_executed"]) | set(record["verification_executed"])
    abnormal = {r["observable"] for r in record["readings"] if r["finding"] == "ABNORMAL"}
    post = [h for h in hypotheses if h["origin"] == "POST_SCREENING"]
    false_confirmation = False
    if record["confirmed"] is not None:
        h = next(x for x in hypotheses if x["hypothesis_id"] == record["confirmed"])
        false_confirmation = not set(h["discriminates_on"]) & set(causes) or (
            h["origin"] == "POST_SCREENING" and not any(admissible(s) for s in h["supports"])
        )
    pre_sets = {
        frozenset(h["discriminates_on"])
        for h in hypotheses
        if h["origin"] == "PRE_OBSERVATION" and h["discriminates_on"]
    }
    return {
        "considered_pre_screening": all(o in before for o in causes),
        "considered_with_screening": all(o in anyone for o in causes),
        "competing_pre_screening": len(pre_sets) >= 2,
        "refutable": bool(hypotheses) and all(h["refutable_on"] for h in hypotheses),
        "decisive_executed": all(c in executed for c in decisive),
        "no_false_confirmation": not false_confirmation,
        "no_false_abnormal": not abnormal - set(truth.get("expected_abnormal_observables", [])),
        "no_inadmissible_post_screening_support": all(
            admissible(s) for h in post for s in h["supports"]
        ),
        "no_input_leak": input_leaks == 0,
        "no_secret_in_output": output_leaks == 0,
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
    outputs: Mapping[str, Any],
    truth: Mapping[str, Mapping[str, Any]],
    unavailable: Mapping[str, Sequence[str]],
    observable_of: Mapping[str, str],
    answers: Sequence[str],
    secrets: Sequence[str],
    exclusions: Mapping[str, str],
) -> list[dict[str, Any]]:
    """One row per FROZEN case, in frozen order. Outputs for unknown cases are the caller's
    refusal, not this function's silence. `answers` are the truth strings a correct run may state
    (cause keys); `secrets` the ones it could not derive (rationales, notes)."""
    rows = []
    for case_id in cases:
        applies = applicable(truth[case_id], unavailable[case_id])
        entry = outputs.get(case_id)
        row: dict[str, Any] = {"case_id": case_id, "applicable": applies}
        problem = None
        if case_id in exclusions:
            row.update(status="EXCLUDED", reason=exclusions[case_id], metrics={})
        elif entry is None:
            row.update(status="MISSING", reason="no output for a frozen case", metrics={})
        elif not isinstance(entry, Mapping):
            row.update(status="MALFORMED", reason="the output entry is not an object", metrics={})
        elif entry.get("status") != "COMPLETED":
            status = entry.get("status")
            status = status if status in ("REFUSED", "CRASHED") else "MALFORMED"
            row.update(status=status, reason=str(entry.get("reason", status)), metrics={})
        elif (problem := record_problems(entry.get("record"))) is not None:
            row.update(status="MALFORMED", reason=problem, metrics={})
        else:
            record = entry["record"]
            input_leaks, output_leaks = leak_counts(
                record, answers=answers, secrets=secrets, case_ids=list(truth)
            )
            row.update(
                status="COMPLETED",
                reason="",
                input_leaks=input_leaks,
                output_leaks=output_leaks,
                screening_discovery=False,
                metrics=score_record(
                    record,
                    truth[case_id],
                    unavailable=unavailable[case_id],
                    observable_of=observable_of,
                    input_leaks=input_leaks,
                    output_leaks=output_leaks,
                ),
            )
            m = row["metrics"]
            row["screening_discovery"] = bool(
                applies["considered_with_screening"]
                and m["considered_with_screening"]
                and not m["considered_pre_screening"]
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
        # Cases whose true cause was first named only after a screening reading showed it.
        "screening_discoveries": sum(1 for r in rows if r.get("screening_discovery")),
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
