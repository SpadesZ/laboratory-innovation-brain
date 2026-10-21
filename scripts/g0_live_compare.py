"""Score real-model research runs, the earlier ones and a new one, on the same G0 measures.

    python scripts/g0_live_compare.py <run dir> [<run dir> ...] [-- <new run dir> ...]

Each run dir is what `tests/e2e/test_research_live_model_postgres.py` writes with
`LAB_BRAIN_LIVE_EVIDENCE` (`<case>.provenance.json`, and `outcomes.json` when the run recorded
one). Nothing here calls a model, a provider or a database: it reads recorded replies and records.

THE TRUTH IS USED FOR SCORING ONLY. Which mechanism each acceptance device really has comes from the
benchmark fixture's `truth` and its diagnostic signature from the same fixture -- read here,
after the fact, and never by anything a run executes.

Measures, per case:

    reached         the run got through the debate to verification
    replies         recorded role replies, and how many a parser refused (structured-output
                    failures); for a run recorded before reply attempts were, the refusals are the
                    stopped stages, and each reply is also REPLAYED: parsed as the earlier code did
                    (bare JSON) and as this code does (`normalize_reply` first)
    covered         some admitted (or, for an earlier run, proposed) hypothesis makes a SUPPORTS or
                    CONTRADICTS prediction over the true mechanism's diagnostic observable
    executed        the checks that ran; `cheap_discriminating` says whether the true signature's
                    check was among them
    confirmed       the confirmed hypothesis, and whether it declared the true signature as SUPPORTS
                    (a confirmation that did not is a FALSE confirmation)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lab_brain.cognition.roles import normalize_reply

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "fixtures/vertical/sp_rs_root_cause_benchmark.json").read_text(encoding="utf-8")
)
#: The live test's cases and the fixture case each one runs.
CASES = {
    "sufficient": "contact-open-via",
    "insufficient": "probe-artifact",
    "competing": "contact-open-via",
}
#: Each benchmark mechanism's signature: its one SUPPORTS prediction, as the fixture states it.
SIGNATURES = {
    key: next(
        (p["observable_ref"], p["expected_outcome"])
        for p in m["predictions"]
        if p["relation_effect"] == "SUPPORTS"
    )
    for key, m in FIXTURE["mechanisms"].items()
}
CHECK_OF = {
    "sp.contact_connectivity": "cap:sp.inspect_contact_connectivity",
    "sp.normalization_basis": "cap:sp.extraction_consistency",
    "sp.probe_contact_resistance": "cap:sp.fourpoint_probe",
    "sp.mesh_stability": "cap:sp.mesh_sensitivity",
    "sp.carrier_profile": "cap:sp.charge_dc_sweep",
}


def truth(case: str) -> tuple[str, str]:
    fixture_case = next(c for c in FIXTURE["cases"] if c["case_id"] == CASES[case])
    return SIGNATURES[fixture_case["truth"]]


def _bare(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _engine_predictions(provenance: list[dict[str, Any]], *, repaired: bool) -> list[tuple]:
    """(observable, outcome, effect) of every hypothesis a Hypothesis Engine reply proposed."""
    out = []
    for row in provenance:
        if row["role"] != "HYPOTHESIS_ENGINE":
            continue
        text = normalize_reply(row["output_text"])[0] if repaired else row["output_text"]
        reply = _bare(text)
        for h in (reply or {}).get("hypotheses", []) if isinstance(reply, dict) else []:
            for p in h.get("predictions", []):
                out.append(
                    (p.get("observable_ref"), p.get("expected_outcome"), p.get("relation_effect"))
                )
    return out


def score(run: Path, case: str) -> dict[str, Any] | None:
    path = run / f"{case}.provenance.json"
    if not path.exists():
        return None
    provenance = json.loads(path.read_text(encoding="utf-8"))
    outcomes_path = run / "outcomes.json"
    outcome = (
        json.loads(outcomes_path.read_text(encoding="utf-8")).get(case)
        if outcomes_path.exists()
        else None
    )
    observable, signature = truth(case)
    stages = (outcome or {}).get("stages", [])
    reliability = (outcome or {}).get("reliability")
    if outcome is not None:
        reached = any(s == "verification" and st in ("DONE", "PARTIAL") for s, st, _ in stages)
    else:
        # Recorded before outcomes were: a run that reached verification had a critique.
        reached = any(r["role"] == "critic" for r in provenance)
    if reliability is not None:
        refused = reliability["refused"]
        replies = reliability["replies"]
    else:
        refused = sum(1 for _, st, d in stages if st == "FAILED" and "RoleOutputRefused" in d)
        replies = len(provenance)
        if outcome is None and not reached:
            # Recorded before outcomes were, and stopped before a critique: the one such run
            # (`live_model_gemini_run1`) stopped at a refused specialist reply, as its report says.
            refused = 1
    if outcome is not None and outcome.get("predictions"):
        declared = [tuple(p[1:]) for p in outcome["predictions"]]
        source = "admitted"
    else:
        declared = _engine_predictions(provenance, repaired=False)
        source = "proposed, parsed as recorded"
    discriminating = [
        d for d in declared if d[0] == observable and d[2] in ("SUPPORTS", "CONTRADICTS")
    ]
    replay_strict = _engine_predictions(provenance, repaired=False)
    replay_repaired = _engine_predictions(provenance, repaired=True)
    executed = (outcome or {}).get("executed")
    confirmed = (outcome or {}).get("confirmed")
    confirmed_right = None
    if confirmed:
        mine = [p for p in (outcome or {}).get("predictions", []) if p[0]]
        confirmed_right = any(
            p[1] == observable and p[2] == signature and p[3] == "SUPPORTS" for p in mine
        )
    return {
        "reached_verification": reached,
        "replies": replies,
        "refused_replies": refused,
        "true_signature": f"{observable} = {signature}",
        "true_cause_covered": bool(discriminating),
        "coverage_source": source,
        "replay": {
            "covered_if_parsed_strictly": any(d[0] == observable for d in replay_strict),
            "covered_if_envelope_repaired": any(d[0] == observable for d in replay_repaired),
        },
        "executed": executed,
        "cheap_discriminating_check_ran": None
        if executed is None
        else CHECK_OF.get(observable) in executed,
        "confirmed": confirmed,
        "false_confirmation": None if confirmed is None else not confirmed_right,
        "coverage_review": (reliability or {}).get("coverage_status"),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    earlier = argv[: argv.index("--")] if "--" in argv else argv
    new = argv[argv.index("--") + 1 :] if "--" in argv else []
    table: dict[str, dict[str, Any]] = {}
    for label, runs in (("earlier", earlier), ("new", new)):
        for run in runs:
            for case in CASES:
                scored = score(Path(run), case)
                if scored is not None:
                    table[f"{label}:{Path(run).name}:{case}"] = scored
    print(json.dumps(table, indent=1, ensure_ascii=False))
    for label in ("earlier", "new"):
        rows = [v for k, v in table.items() if k.startswith(label)]
        if not rows:
            continue
        print(
            f"{label}: {len(rows)} case run(s); reached verification "
            f"{sum(r['reached_verification'] for r in rows)}; refused replies "
            f"{sum(r['refused_replies'] for r in rows)}/{sum(r['replies'] for r in rows)}; true "
            f"cause covered {sum(r['true_cause_covered'] for r in rows)}; confirmations "
            f"{sum(1 for r in rows if r['confirmed'])}; false confirmations "
            f"{sum(1 for r in rows if r['false_confirmation'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
