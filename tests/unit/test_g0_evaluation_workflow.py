"""G0 independent-holdout workflow, backend-free: visibility, sealing, freeze, honest scoring.

ALL DATA HERE IS SYNTHETIC. The cases, devices, evidence and truths below are invented for these
interface tests (every one says so in its text); they are not a holdout, not a benchmark and not
evidence about the research system. No genuine independent holdout exists.

    visibility      the generator loader refuses evaluator material (by kind, by name, by truth
                    key at any depth, by unknown field) and the research inputs carry no truth
    sealing         a reveal verifies against its commitment; any tampering is refused
    freeze          a changed input, manifest field or scorer source is drift; scoring refuses
    binding         outputs produced against another manifest, or naming an unfrozen case, are
                    refused
    denominator     crashes, refusals, malformed and missing outputs fail every applicable metric
                    and stay counted; exclusions are listed with their reason and counted as
                    failures in the conservative figure
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from lab_brain.evaluation import manifest as manifest_module
from lab_brain.evaluation import scoring
from lab_brain.evaluation.manifest import (
    OUTPUTS_KIND,
    FreezeDrift,
    ScoringRefused,
    freeze,
    score_run,
    verify_frozen,
)
from lab_brain.evaluation.packages import (
    TruthLeak,
    VisibilityViolation,
    assert_no_truth,
    load_generator_package,
    research_inputs,
    truth_strings,
)
from lab_brain.evaluation.sealing import (
    CommitmentMismatch,
    SealedTruth,
    commitments_document,
    load_sealed_truth,
    seal,
    truth_location,
    verify_reveal,
)

REPO = Path(__file__).resolve().parents[2]
PROTOCOL = REPO / "benchmarks" / "g0_evaluation" / "protocol.example.json"

CONTACT = "cap:sp.inspect_contact_connectivity"
EXTRACTION = "cap:sp.extraction_consistency"

#: SYNTHETIC cases: case id -> (question, device overrides, evidence text, truth).
SYNTHETIC: dict[str, tuple[str, dict[str, Any], str, dict[str, Any]]] = {
    "syn-k7q2": (
        "SYNTHETIC question: why is the series resistance of test structure SYN-201 so high?",
        {"device_id": "SYN-201", "contacts": [{"contact_id": "drain", "via_to_metal": False}]},
        "SYNTHETIC evidence. Sheet resistance on SYN-201 reads forty times the design value "
        "while the junction capacitance trend looks ordinary across the bias sweep.",
        {
            "true_causes": ["contact_discontinuity"],
            "decisive_cheap_checks": [CONTACT],
            "expected_abnormal_observables": ["sp.contact_connectivity"],
            "rationale": "SYNTHETIC rationale quokka-zeta: the drain via never lands on metal",
        },
    ),
    "syn-m3x9": (
        "SYNTHETIC question: why does SYN-202 extract a resistance twice the simulated one?",
        {"device_id": "SYN-202", "extraction_normalization_length_um": "900"},
        "SYNTHETIC evidence. The extracted per-length resistance of SYN-202 is roughly double the "
        "simulation, and the ratio is constant across every wafer site measured last week.",
        {
            "true_causes": ["normalization_error"],
            "decisive_cheap_checks": [EXTRACTION],
            "expected_abnormal_observables": ["sp.normalization_basis"],
            "rationale": "SYNTHETIC rationale walrus-epsilon: normalised on 900 um not 450 um",
        },
    ),
    "syn-p5r1": (
        "SYNTHETIC question: is anything wrong with test structure SYN-203 at all?",
        {"device_id": "SYN-203"},
        "SYNTHETIC evidence. Every measured quantity on SYN-203 sits inside its control band; the "
        "report was filed only because a new operator ran the line for the first time.",
        {
            "true_causes": [],
            "decisive_cheap_checks": [],
            "expected_abnormal_observables": [],
            "rationale": "SYNTHETIC rationale pelican-omicron: a sound control device",
        },
    ),
    "syn-t8w4": (
        "SYNTHETIC question: why did the SYN-204 resistance jump after the mask revision?",
        {"device_id": "SYN-204", "contacts": [{"contact_id": "source", "via_to_metal": False}]},
        "SYNTHETIC evidence. After the mask revision SYN-204 resistance rose sharply on all dies, "
        "and the capacitance did not move, which the process engineer found puzzling.",
        {
            "true_causes": ["contact_discontinuity"],
            "decisive_cheap_checks": [CONTACT],
            "expected_abnormal_observables": ["sp.contact_connectivity"],
            "rationale": "SYNTHETIC rationale ibis-kappa: the revised mask dropped the source via",
        },
    ),
    "syn-v6d3": (
        "SYNTHETIC question: what explains the outlier resistance of structure SYN-205?",
        {"device_id": "SYN-205", "extraction_normalization_length_um": "1200"},
        "SYNTHETIC evidence. Structure SYN-205 is the only one on the reticle whose resistance is "
        "an outlier, and its layout was drawn by hand rather than by the generator script.",
        {
            "true_causes": ["normalization_error"],
            "decisive_cheap_checks": [EXTRACTION],
            "expected_abnormal_observables": ["sp.normalization_basis"],
            "rationale": "SYNTHETIC rationale heron-sigma: a 1200 um basis for a 600 um device",
        },
    ),
}


def build(root: Path, cases: dict[str, Any] | None = None) -> dict[str, Path]:
    """Write a SYNTHETIC generator package, its unsealed truth and a protocol under `root`."""
    cases = SYNTHETIC if cases is None else cases
    holdout = root / "holdout"
    (holdout / "evidence").mkdir(parents=True)
    entries = []
    for i, (case_id, (question, device, text, _truth)) in enumerate(cases.items()):
        doc = holdout / "evidence" / f"report_{i}.md"
        doc.write_text(text, encoding="utf-8")
        entries.append(
            {
                "case_id": case_id,
                "question": question,
                "device": device,
                "evidence": [{"name": f"report_{i}.md", "path": f"evidence/report_{i}.md"}],
                "allowed_sources": ["the attached measurement report"],
                "deployment": {"unavailable": []},
                "provenance": {
                    "unit_id": f"synthetic-unit-{i}",
                    "source_family": f"synthetic-source-{i}",
                    "device_family": "synthetic-SYN-200",
                },
            }
        )
    package = holdout / "generator-package.json"
    package.write_text(
        json.dumps(
            {
                "kind": "g0-eval/generator-package@1",
                "suite": "synthetic-interface-test",
                "synthetic": True,
                "nominal_device": {"format": "sp.device_project@1", "device_id": "SYN-200"},
                "cases": entries,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    outside = root / "evaluator-only"
    outside.mkdir()
    raw = outside / "truth.json"
    raw.write_text(
        json.dumps(
            {
                "kind": "g0-eval/evaluator-truth@1",
                "suite": "synthetic-interface-test",
                "cases": {cid: {"truth": spec[3]} for cid, spec in cases.items()},
            }
        ),
        encoding="utf-8",
    )
    sealed = outside / "truth.sealed.json"
    sealed.write_text(json.dumps(seal(json.loads(raw.read_text()))), encoding="utf-8")
    commitments = holdout / "commitments.json"
    commitments.write_text(
        json.dumps(commitments_document(load_sealed_truth(sealed))), encoding="utf-8"
    )
    protocol = holdout / "protocol.json"
    shutil.copy(PROTOCOL, protocol)
    return {
        "package": package,
        "sealed": sealed,
        "commitments": commitments,
        "protocol": protocol,
    }


def frozen(root: Path, paths: dict[str, Path], **kwargs: Any) -> dict[str, Any]:
    return freeze(
        root=root,
        protocol_path=paths["protocol"],
        package_path=paths["package"],
        commitments=json.loads(paths["commitments"].read_text()),
        include_exposed_screening=False,
        frozen_at="2026-10-27T00:00:00+00:00",
        **kwargs,
    )


def record(
    *,
    discriminates: list[str],
    executed: list[str],
    abnormal: list[str],
    confirmed: bool,
    prompts: list[str] | None = None,
) -> dict[str, Any]:
    """A SYNTHETIC episode record in the matrix harness's `collect` shape."""
    return {
        "hypotheses": [
            {
                "hypothesis_id": "hyp:1",
                "origin": "PRE_OBSERVATION",
                "discriminates_on": discriminates,
                "supports": 0,
            }
        ],
        "screening_executed": executed,
        "verification_executed": [],
        "readings": [{"observable": o, "finding": "ABNORMAL"} for o in abnormal],
        "confirmed": "hyp:1" if confirmed else None,
        "prompts": prompts or [],
    }


def good(case_id: str) -> dict[str, Any]:
    truth = SYNTHETIC[case_id][3]
    observable = {
        "contact_discontinuity": "sp.contact_connectivity",
        "normalization_error": "sp.normalization_basis",
    }
    return {
        "status": "COMPLETED",
        "record": record(
            discriminates=[observable[c] for c in truth["true_causes"]],
            executed=list(truth["decisive_cheap_checks"]),
            abnormal=list(truth["expected_abnormal_observables"]),
            confirmed=False,
        ),
    }


def outputs(manifest: dict[str, Any], cases: dict[str, Any]) -> dict[str, Any]:
    return {"kind": OUTPUTS_KIND, "manifest_sha256": manifest["manifest_sha256"], "cases": cases}


# --- visibility ---------------------------------------------------------------------------------


def test_the_generator_loader_refuses_evaluator_material(tmp_path):
    paths = build(tmp_path)
    # By name, before a byte is parsed.
    with pytest.raises(VisibilityViolation, match="evaluator material"):
        load_generator_package(paths["sealed"])
    # By kind, when the name is innocent.
    disguised = tmp_path / "holdout" / "cases.json"
    shutil.copy(paths["sealed"], disguised)
    with pytest.raises(VisibilityViolation, match="evaluator material"):
        load_generator_package(disguised)
    data = json.loads(paths["package"].read_text())
    # A truth key anywhere -- even inside the free-form device file -- is refused.
    planted = copy.deepcopy(data)
    planted["cases"][0]["device"]["notes"] = {"rationale": "SYNTHETIC"}
    (tmp_path / "holdout" / "p1.json").write_text(json.dumps(planted))
    with pytest.raises(VisibilityViolation, match="truth fields"):
        load_generator_package(tmp_path / "holdout" / "p1.json")
    # An unknown field is refused until someone decides which side it belongs to.
    extra = copy.deepcopy(data)
    extra["cases"][0]["hint"] = "SYNTHETIC"
    (tmp_path / "holdout" / "p2.json").write_text(json.dumps(extra))
    with pytest.raises(ValidationError):
        load_generator_package(tmp_path / "holdout" / "p2.json")
    # Evidence that is evaluator material, by name or by content, or outside the package.
    for i, ref in enumerate(
        [
            {"name": "x.md", "path": "../evaluator-only/truth.sealed.json"},
            {"name": "answers.md", "path": "evidence/report_0.md"},
        ]
    ):
        bad = copy.deepcopy(data)
        bad["cases"][0]["evidence"] = [ref]
        (tmp_path / "holdout" / f"q{i}.json").write_text(json.dumps(bad))
        with pytest.raises(VisibilityViolation):
            load_generator_package(tmp_path / "holdout" / f"q{i}.json")
    shutil.copy(paths["sealed"], tmp_path / "holdout" / "evidence" / "plain.md")
    content = copy.deepcopy(data)
    content["cases"][0]["evidence"] = [{"name": "plain.md", "path": "evidence/plain.md"}]
    (tmp_path / "holdout" / "q9.json").write_text(json.dumps(content))
    with pytest.raises(VisibilityViolation, match="evaluator material"):
        load_generator_package(tmp_path / "holdout" / "q9.json")


def test_the_research_inputs_carry_no_truth_and_a_planted_leak_is_caught(tmp_path):
    paths = build(tmp_path)
    loaded = load_generator_package(paths["package"])
    sealed = load_sealed_truth(paths["sealed"])
    forbidden = truth_strings(sealed.truth())
    assert {"syn-k7q2", "contact_discontinuity"} <= set(forbidden)
    for case in loaded.package.cases:
        inputs = research_inputs(loaded, case.case_id)
        assert_no_truth(inputs.texts(), forbidden)
        flat = json.dumps(inputs.texts())
        assert case.provenance.unit_id not in flat and case.provenance.source_family not in flat
    # Fail closed: an empty scan is not a pass, and a planted rationale is found even reworded
    # in case and punctuation.
    with pytest.raises(TruthLeak, match="empty scan"):
        assert_no_truth({"q": "anything"}, [])
    rationale = SYNTHETIC["syn-k7q2"][3]["rationale"]
    with pytest.raises(TruthLeak, match="evidence"):
        assert_no_truth(
            {"evidence:x": "notes -- " + rationale.upper().replace(" ", "\n")}, forbidden
        )


# --- sealing ------------------------------------------------------------------------------------


def test_a_reveal_verifies_and_any_tampering_is_refused(tmp_path):
    paths = build(tmp_path)
    sealed = load_sealed_truth(paths["sealed"])
    public = json.loads(paths["commitments"].read_text())
    verify_reveal(sealed, public["cases"], public["root"])
    # The public half carries neither a salt nor an answer.
    text = paths["commitments"].read_text()
    for entry in sealed.cases.values():
        assert entry["salt"] not in text and entry["truth"]["rationale"] not in text
    assert "contact_discontinuity" not in text

    def tampered(edit: Any) -> SealedTruth:
        cases = copy.deepcopy(dict(sealed.cases))
        edit(cases)
        return SealedTruth(suite=sealed.suite, cases=cases)

    edits = [
        lambda c: c["syn-k7q2"]["truth"].update(true_causes=["normalization_error"]),
        lambda c: c["syn-k7q2"].update(salt="00" * 32),
        lambda c: c.pop("syn-p5r1"),
        lambda c: c.update({"syn-new": {"salt": "11" * 32, "truth": {}}}),
    ]
    for edit in edits:
        with pytest.raises(CommitmentMismatch):
            verify_reveal(tampered(edit), public["cases"], public["root"])
    edited = dict(public["cases"], **{"syn-k7q2": "0" * 64})
    with pytest.raises(CommitmentMismatch, match="root"):
        verify_reveal(sealed, edited, public["root"])
    # A fresh seal of the same answers commits differently: the salt hides a short answer.
    again = seal(json.loads((tmp_path / "evaluator-only" / "truth.json").read_text()))
    assert (
        commitments_document(SealedTruth(suite="s", cases=again["cases"]))["root"]
        != (public["root"])
    )


def test_sealed_truth_is_refused_inside_the_repository(tmp_path):
    inside = REPO / "benchmarks" / "g0_evaluation" / "truth.sealed.json"
    with pytest.raises(ValueError, match="inside the repository"):
        truth_location(str(inside), {}, repo=REPO, allow_in_repo=False)
    assert (
        truth_location(
            None,
            {"LAB_BRAIN_G0_EVAL_TRUTH": str(tmp_path / "t.json")},
            repo=REPO,
            allow_in_repo=False,
        )
        == (tmp_path / "t.json").resolve()
    )
    with pytest.raises(ValueError, match="--truth"):
        truth_location(None, {}, repo=REPO, allow_in_repo=False)


# --- freeze -------------------------------------------------------------------------------------


def test_drift_after_the_freeze_is_detected_and_scoring_refuses(tmp_path, monkeypatch):
    paths = build(tmp_path)
    manifest = frozen(tmp_path, paths)
    verify_frozen(manifest, tmp_path)
    sealed = load_sealed_truth(paths["sealed"])
    out = outputs(manifest, {cid: good(cid) for cid in SYNTHETIC})
    score_run(manifest=manifest, root=tmp_path, outputs=out, truth=sealed)

    # An edited evidence file.
    doc = tmp_path / "holdout" / "evidence" / "report_0.md"
    original = doc.read_text()
    doc.write_text(original + " (edited after freeze)")
    with pytest.raises(FreezeDrift, match=r"report_0\.md: hash changed"):
        verify_frozen(manifest, tmp_path)
    with pytest.raises(ScoringRefused, match="freeze drift"):
        score_run(manifest=manifest, root=tmp_path, outputs=out, truth=sealed)
    doc.write_text(original)
    # An edited manifest: a case dropped from the frozen list.
    edited = dict(manifest, cases=manifest["cases"][1:])
    with pytest.raises(FreezeDrift, match="edited after freeze"):
        verify_frozen(edited, tmp_path)
    # A scoring rule changed after the freeze, versioned or not.
    real = manifest_module.scorer_sources()
    monkeypatch.setattr(
        manifest_module,
        "scorer_sources",
        lambda: {**real, "lab_brain/evaluation/scoring.py": "0" * 64},
    )
    with pytest.raises(FreezeDrift, match=r"scoring\.py: source changed"):
        verify_frozen(manifest, tmp_path)
    monkeypatch.setattr(manifest_module, "scorer_sources", lambda: real)
    monkeypatch.setattr(scoring, "SCORER_VERSION", "9.9.9")
    with pytest.raises(FreezeDrift, match="scorer version"):
        verify_frozen(manifest, tmp_path)


def test_the_scorer_refuses_outputs_bound_to_another_manifest_or_case(tmp_path):
    paths = build(tmp_path)
    manifest = frozen(tmp_path, paths)
    sealed = load_sealed_truth(paths["sealed"])
    cases = {cid: good(cid) for cid in SYNTHETIC}
    other = dict(outputs(manifest, cases), manifest_sha256="f" * 64)
    with pytest.raises(ScoringRefused, match="different protocol manifest"):
        score_run(manifest=manifest, root=tmp_path, outputs=other, truth=sealed)
    stray = outputs(manifest, {**cases, "syn-unfrozen": good("syn-k7q2")})
    with pytest.raises(ScoringRefused, match="not frozen"):
        score_run(manifest=manifest, root=tmp_path, outputs=stray, truth=sealed)
    cheat = copy.deepcopy(dict(sealed.cases))
    cheat["syn-p5r1"]["truth"]["true_causes"] = ["mesh_artifact"]
    with pytest.raises(ScoringRefused, match="truth reveal"):
        score_run(
            manifest=manifest,
            root=tmp_path,
            outputs=outputs(manifest, cases),
            truth=SealedTruth(suite=sealed.suite, cases=cheat),
        )


# --- denominator --------------------------------------------------------------------------------


def test_every_frozen_case_stays_in_the_denominator(tmp_path):
    paths = build(tmp_path)
    manifest = frozen(
        tmp_path, paths, declared_exclusions={"syn-v6d3": "SYNTHETIC: evaluator declared"}
    )
    sealed = load_sealed_truth(paths["sealed"])
    wrong = good("syn-m3x9")
    wrong["record"]["confirmed"] = "hyp:1"
    wrong["record"]["hypotheses"][0]["discriminates_on"] = ["sp.mesh_stability"]
    out = outputs(
        manifest,
        {
            "syn-k7q2": good("syn-k7q2"),
            "syn-m3x9": wrong,
            "syn-p5r1": {"status": "CRASHED", "reason": "SYNTHETIC worker died"},
            # syn-t8w4 has no output at all.
            "syn-v6d3": good("syn-v6d3"),
        },
    )
    result = score_run(manifest=manifest, root=tmp_path, outputs=out, truth=sealed)
    summary = result["summary"]
    assert summary["frozen_cases"] == 5 and [r["case_id"] for r in result["cases"]] == list(
        SYNTHETIC
    )
    assert summary["status_counts"] == {
        "COMPLETED": 2,
        "REFUSED": 0,
        "CRASHED": 1,
        "MALFORMED": 0,
        "MISSING": 1,
        "EXCLUDED": 1,
    }
    assert summary["excluded"] == [
        {"case_id": "syn-v6d3", "reason": "SYNTHETIC: evaluator declared"}
    ]
    assert {x["case_id"]: x["status"] for x in summary["not_completed"]} == {
        "syn-p5r1": "CRASHED",
        "syn-t8w4": "MISSING",
    }
    m = summary["metrics"]
    # considered: applies to the 4 cases with a cause; syn-v6d3 excluded; k7q2 passes, m3x9
    # discriminated the wrong observable, t8w4 is missing.
    assert (m["considered"]["k"], m["considered"]["n"], m["considered"]["excluded"]) == (1, 3, 1)
    assert (m["considered"]["conservative"]["k"], m["considered"]["conservative"]["n"]) == (1, 4)
    # no_false_confirmation applies to every case: m3x9 confirmed wrongly; p5r1 crashed and
    # t8w4 is missing -- neither demonstrated anything.
    nfc = m["no_false_confirmation"]
    assert (nfc["k"], nfc["n"], nfc["not_completed"]) == (1, 4, 2)
    assert nfc["wilson95"] == [0.0456, 0.6994]
    assert nfc["bootstrap95"] is not None and result["bootstrap_seed"] == 20261027


def test_refusals_malformed_records_and_leaks_are_failures(tmp_path):
    paths = build(tmp_path)
    manifest = frozen(tmp_path, paths)
    sealed = load_sealed_truth(paths["sealed"])
    leaky = good("syn-k7q2")
    leaky["record"]["prompts"] = ["CONTEXT: " + SYNTHETIC["syn-k7q2"][3]["rationale"]]
    out = outputs(
        manifest,
        {
            "syn-k7q2": leaky,
            "syn-m3x9": {"status": "REFUSED", "reason": "SYNTHETIC: the model declined"},
            "syn-p5r1": {"status": "COMPLETED", "record": {"hypotheses": []}},
            "syn-t8w4": {"status": "something else"},
            "syn-v6d3": good("syn-v6d3"),
        },
    )
    result = score_run(manifest=manifest, root=tmp_path, outputs=out, truth=sealed)
    rows = {r["case_id"]: r for r in result["cases"]}
    assert rows["syn-k7q2"]["leaks"] == 1 and rows["syn-k7q2"]["metrics"]["no_leak"] is False
    assert [rows[c]["status"] for c in ("syn-m3x9", "syn-p5r1", "syn-t8w4")] == [
        "REFUSED",
        "MALFORMED",
        "MALFORMED",
    ]
    assert result["summary"]["metrics"]["no_leak"]["k"] == 1  # only syn-v6d3
    assert result["summary"]["metrics"]["no_leak"]["n"] == 5
    # The report names where a leak happened, never the leaked string.
    assert SYNTHETIC["syn-k7q2"][3]["rationale"] not in json.dumps(result)


def test_contamination_policy_fail_refuses_scoring_and_exclude_excludes(tmp_path):
    cases = dict(SYNTHETIC)
    # Two SYNTHETIC cases with identical inputs under different ids: one experimental unit.
    q, device, text, truth = cases["syn-k7q2"]
    cases["syn-dupe"] = (q, {**device, "device_id": "SYN-299"}, text, truth)
    paths = build(tmp_path, cases)
    sealed = load_sealed_truth(paths["sealed"])
    manifest = frozen(tmp_path, paths)
    assert set(manifest["contamination"]["contaminated_cases"]) == {"syn-k7q2", "syn-dupe"}
    assert set(manifest["exclusions"]) == {"syn-k7q2", "syn-dupe"}
    result = score_run(
        manifest=manifest,
        root=tmp_path,
        outputs=outputs(manifest, {}),
        truth=sealed,
    )
    assert result["summary"]["status_counts"]["EXCLUDED"] == 2
    assert result["summary"]["status_counts"]["MISSING"] == 4
    protocol = json.loads(paths["protocol"].read_text())
    protocol["contamination_policy"] = "fail"
    paths["protocol"].write_text(json.dumps(protocol))
    strict = frozen(tmp_path, paths)
    assert strict["exclusions"] == {}
    with pytest.raises(ScoringRefused, match="policy 'fail'"):
        score_run(manifest=strict, root=tmp_path, outputs=outputs(strict, {}), truth=sealed)


# --- the CLI ------------------------------------------------------------------------------------


def _script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_cli_seals_freezes_and_scores_with_truth_outside_the_repo(tmp_path, capsys):
    paths = build(tmp_path)
    raw = tmp_path / "evaluator-only" / "truth.json"
    sealed = tmp_path / "evaluator-only" / "cli.sealed.json"
    commitments = tmp_path / "holdout" / "cli.commitments.json"
    assert (
        _script("g0_eval_seal").main(
            [
                "--truth",
                str(raw),
                "--sealed-out",
                str(sealed),
                "--commitments-out",
                str(commitments),
            ]
        )
        == 0
    )
    manifest_path = tmp_path / "holdout" / "manifest.json"
    args = [
        "--protocol", str(paths["protocol"]),
        "--package", str(paths["package"]),
        "--commitments", str(commitments),
        "--no-exposed-screening",
        "--root", str(tmp_path),
        "--out", str(manifest_path),
    ]  # fmt: skip
    assert _script("g0_eval_freeze").main(args) == 0
    manifest = json.loads(manifest_path.read_text())
    out_path = tmp_path / "outputs.json"
    out_path.write_text(json.dumps(outputs(manifest, {c: good(c) for c in SYNTHETIC})))
    score = _script("g0_eval_score")
    common = ["--manifest", str(manifest_path), "--outputs", str(out_path), "--root", str(tmp_path)]
    assert score.main([*common, "--truth", str(sealed), "--json", str(tmp_path / "s.json")]) == 0
    assert "SYNTHETIC suite synthetic-interface-test: 5 frozen cases" in capsys.readouterr().out
    # The original seal's truth has other salts: it does not match these commitments.
    assert score.main([*common, "--truth", str(paths["sealed"])]) == 2
    assert "REFUSED: truth reveal" in capsys.readouterr().err
    contamination = _script("g0_eval_check_contamination")
    assert contamination.main(["--package", str(paths["package"]), "--root", str(REPO)]) == 0
