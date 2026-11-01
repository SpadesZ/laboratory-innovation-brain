"""The offline benchmark is matched, frozen and honest about what it measures.

Runs on the DEVELOPMENT seeds only; the frozen evaluation seeds are exercised by the evidence check
in `tests/e2e/test_discovery_benchmark_frozen.py`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.handover import PENDING, draft_certificates
from lab_brain.discovery.model import Outcome, stable_digest
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    DEVELOPMENT_BASE_SEED,
    EVALUATION_BASE_SEED,
    WORLD_KINDS,
    ring_catalog,
    ring_scenario,
    ring_worlds,
)
from lab_brain.spec import repo_root


@pytest.fixture(scope="module")
def dev():
    scenario = ring_scenario(2, base_seed=DEVELOPMENT_BASE_SEED)
    return scenario, benchmark.run(scenario, 12, benchmark.ARMS)


def test_every_arm_gets_exactly_the_same_worlds_seeds_and_budget(dev):
    scenario, bench = dev
    assert [w.world for w in bench.worlds] == list(scenario.worlds)
    for run in bench.worlds:
        assert [r.arm for r in run.results] == ["B0", "B1", "B2"]
        assert {r.budget for r in run.results} == {12}
        assert {r.catalog_ref for r in run.results} == {scenario.catalog.ref}
        # Common random numbers: the same experiment's first run reads the same numbers in
        # every arm that ran it.
        first_runs: dict[str, set[tuple[tuple[str, float], ...]]] = {}
        for result in run.results:
            for observation in result.observations:
                if observation.replicate == 0:
                    first_runs.setdefault(observation.experiment_id, set()).add(observation.values)
        glitched = run.world.glitch_first
        if not glitched:
            assert all(len(v) == 1 for v in first_runs.values()), run.world.world_id


def test_the_worlds_cover_every_adversarial_kind_and_hide_what_they_should():
    worlds = ring_worlds(3, base_seed=DEVELOPMENT_BASE_SEED)
    catalog = ring_catalog()
    assert {w.kind for w in worlds} == set(WORLD_KINDS)
    by_kind = {k: [w for w in worlds if w.kind == k] for k in WORLD_KINDS}
    initial = {m.class_id for m in catalog.initial}
    for w in by_kind["outside_initial_prior"]:
        assert {c for c, _ in w.truth}.isdisjoint(initial)
    for w in by_kind["inseparable_pair"]:
        assert ("width_array", "this die carries a single ring width") in w.removed
    for w in by_kind["noise_only_null"]:
        assert w.truth == () and w.glitch_motivating and w.glitch_first
    for w in by_kind["composition"]:
        assert len(w.truth) == 2
    for w in by_kind["outside_all_declared"]:
        assert w.truth_hypothesis(catalog) is None
    for w in worlds:
        for class_id, amplitude in w.truth:
            m = catalog.mechanism(class_id)
            assert m.lower < amplitude < m.upper


def test_development_and_evaluation_worlds_do_not_overlap():
    dev = {(w.seed, w.world_id) for w in ring_worlds(25, base_seed=DEVELOPMENT_BASE_SEED)}
    evaluation = {(w.seed, w.world_id) for w in ring_worlds(25, base_seed=EVALUATION_BASE_SEED)}
    assert not {s for s, _ in dev} & {s for s, _ in evaluation}


def test_the_manifest_freezes_specs_protocols_and_sources(dev):
    scenario, _ = dev
    root = repo_root()
    manifest = benchmark.manifest(
        scenario,
        budget=12,
        arms=benchmark.ARMS,
        ablations=benchmark.ABLATIONS,
        sensitivity_budgets=(8, 16),
        seed=1,
        resamples=10,
        root=root,
        code_commit="test",
    )
    assert manifest["worlds"]["specs_digest"] == stable_digest(scenario.worlds)
    assert manifest["catalog"]["digest"] == scenario.catalog.digest
    sources = manifest["sources_sha256"]
    assert "src/lab_brain/discovery/loop.py" in sources
    assert "src/lab_brain/domains/silicon_photonics/discovery_catalog.py" in sources
    assert {a["arm"] for a in manifest["arms"]} >= {"B0", "B1", "B2"}
    changed = replace(scenario, worlds=(replace(scenario.worlds[0], seed=0), *scenario.worlds[1:]))
    other = benchmark.manifest(
        changed,
        budget=12,
        arms=benchmark.ARMS,
        ablations=benchmark.ABLATIONS,
        sensitivity_budgets=(8, 16),
        seed=1,
        resamples=10,
        root=root,
        code_commit="test",
    )
    assert other["worlds"]["specs_digest"] != manifest["worlds"]["specs_digest"]
    assert other["manifest_sha256"] != manifest["manifest_sha256"]


def test_a_summary_reports_rates_with_intervals_and_never_a_bare_count(dev):
    _, bench = dev
    summary = benchmark.summarize(bench, seed=1, resamples=50)
    for arm in ("B0", "B1", "B2"):
        s = summary["arms"][arm]
        assert s["correct_outcome"]["n"] == len(bench.worlds)
        assert s["correct_outcome"]["wilson95"] is not None
        assert "bootstrap95" in s["distinguishable_diversity"]
        assert set(s["per_kind"]) == set(WORLD_KINDS)
    assert "B2_minus_B1_correct" in summary["paired"]


def test_the_handover_maps_onto_the_gates_inputs_and_stays_pending(dev):
    _, bench = dev
    handed = [
        r for w in bench.worlds for r in w.results if r.arm == "B2" and r.handover is not None
    ]
    assert handed
    for result in handed:
        handover = result.handover
        assert handover is not None
        assert handover.status == PENDING
        assert handover.candidate_class == result.claim
        assert any("ConfirmationRule.standing" in r.where for r in handover.requirements)
        assert any("WarrantResolver" in r.where for r in handover.requirements)
        rival_ids = {r.hypothesis_id for r in handover.rivals}
        assert rival_ids.isdisjoint(result.claim)
        certificates = draft_certificates(
            handover, result.hypotheses, project_id="prj:offline", episode_id="epi:offline"
        )
        assert len(certificates) == len(result.claim) + len(handover.rivals)
        for certificate in certificates:
            assert certificate.falsifier.strip() and certificate.mechanism.strip()
            assert certificate.project_id == "prj:offline"


def test_the_single_hypothesis_baseline_is_labelled_as_what_it_is(dev):
    _, bench = dev
    b0 = [w.results[0] for w in bench.worlds]
    assert all("not a language model" in r.notes[0] for r in b0)
    assert all(r.anomalies == () and r.reframings == () for r in b0)
    assert all(len(r.claim) <= 1 for r in b0)
    assert all(r.outcome is not Outcome.INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE for r in b0)


def test_the_defect_demonstrations_show_the_naive_versions_failing(dev):
    _, bench = dev
    defects = benchmark.defect_demonstrations(bench)
    gaming = defects["hypothesis_count_gaming"]
    assert gaming["naive_count_after"] == gaming["naive_count_before"] + gaming["copies_added"]
    assert gaming["distinguishable_diversity_after"] == gaming["distinguishable_diversity_before"]
    assert "retrospective_support" in defects
