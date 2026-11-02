"""The hidden-world scaffold: a different author's sealed worlds, validated, sealed, run blind, scored.

format          the example loads; the JSON schema's key sets are the validator's
location        a real hidden set is refused inside the repository; an example is refused as a
                hidden set unless the caller runs the scaffold demonstration
malformed       every structural defect is refused, with its reason
leaks           a removal reason or suite that names the truth is refused; a renamed copy of an
                engine class labelled held_out is refused (it is aliased)
sealing         fresh random salts by default; the engine package carries no truth key, no world
                id, no category; the reveal refuses any change after the commitment
laboratory      declared worlds read exactly what the benchmark's synthetic world reads
blind run       the engine is handed its catalog, the case's experiments and a blind laboratory;
                outputs carry case ids only; scoring refuses foreign outputs
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.loop import investigate
from lab_brain.discovery.model import to_jsonable
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery.worlds import SyntheticWorld, WorldSpec
from lab_brain.discovery_eval import hidden_worlds as hw
from lab_brain.discovery_eval.blind import find_truth_leaks
from lab_brain.domains.silicon_photonics.discovery_catalog import ring_catalog
from lab_brain.spec import repo_root

EXAMPLE = repo_root() / "benchmarks" / "discovery_independent" / "example.hidden-worlds.json"
SCHEMA = repo_root() / "benchmarks" / "discovery_independent" / "hidden-worlds.schema.json"


@pytest.fixture(scope="module")
def catalog():
    return ring_catalog()


@pytest.fixture
def data():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _demo_salt(world_id: str) -> str:
    return hashlib.sha256(f"test:{world_id}".encode()).hexdigest()


def _parse(data, catalog):
    return hw.parse_hidden_worlds(data, catalog, DISCOVERY)


def _refused(data, catalog, fragment: str) -> None:
    with pytest.raises(hw.HiddenWorldRefused) as caught:
        _parse(data, catalog)
    assert any(fragment in p for p in caught.value.problems), caught.value.problems


@pytest.fixture(scope="module")
def sealed_example(catalog):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    worlds = hw.parse_hidden_worlds(data, catalog, DISCOVERY)
    sealed, package = hw.seal(worlds, salts=_demo_salt)
    return worlds, sealed, package


# -- format and location --------------------------------------------------------------------------


def test_the_example_loads_and_is_marked_as_an_example(catalog, data):
    worlds = _parse(data, catalog)
    assert worlds.example_only is True
    assert "EXAMPLE ONLY" in worlds.notice
    categories = {w.world_id: w.category for w in worlds.worlds}
    assert set(categories.values()) == set(hw.CATEGORIES)
    by_id = {w.world_id: w for w in worlds.worlds}
    assert by_id["example-05"].aliases == ()
    assert "hyp:geometry.width_wide" in by_id["example-06"].aliases


def test_the_json_schema_names_exactly_the_validators_keys():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["properties"]
    world = props["worlds"]["items"]["properties"]
    hidden = world["hidden"]["properties"]
    declared, tabulated = hidden["effects"]["items"]["oneOf"]
    assert set(props) == set(schema["required"]) == hw.TOP_KEYS
    assert set(props["author"]["properties"]) == hw.AUTHOR_KEYS
    assert set(props["interface"]["properties"]) == hw.INTERFACE_KEYS
    assert set(world) == hw.WORLD_KEYS
    assert set(world["public"]["properties"]) == hw.PUBLIC_KEYS
    assert set(hidden) == hw.HIDDEN_KEYS
    assert set(declared["properties"]) == hw.DECLARED_EFFECT_KEYS
    assert set(tabulated["properties"]) == hw.TABULATED_EFFECT_KEYS
    assert set(hidden["noise"]["properties"]) == hw.NOISE_KEYS
    assert tuple(hidden["category"]["enum"]) == hw.CATEGORIES
    assert props["kind"]["const"] == hw.HIDDEN_WORLDS_KIND


def test_a_real_hidden_set_is_refused_inside_the_repository(tmp_path, data):
    real = copy.deepcopy(data)
    real["example_only"] = False
    inside = tmp_path / "repo" / "hidden.json"
    inside.parent.mkdir()
    inside.write_text(json.dumps(real), encoding="utf-8")
    with pytest.raises(hw.HiddenWorldRefused, match="inside the repository"):
        hw.load_document(inside, repo=tmp_path / "repo", allow_example=False)
    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps(real), encoding="utf-8")
    assert hw.load_document(outside, repo=tmp_path / "repo", allow_example=False) == real


def test_the_example_is_refused_as_a_hidden_set():
    with pytest.raises(hw.HiddenWorldRefused, match="not a hidden set"):
        hw.load_document(EXAMPLE, repo=repo_root(), allow_example=False)
    assert hw.load_document(EXAMPLE, repo=repo_root(), allow_example=True)["example_only"]


# -- malformed ------------------------------------------------------------------------------------


def _world(data, world_id):
    return next(w for w in data["worlds"] if w["world_id"] == world_id)


MALFORMED = {
    "wrong kind": (lambda d: d.update(kind="lab-brain/other@1"), "kind"),
    "extra top key": (lambda d: d.update(hint="width"), "keys outside the schema"),
    "missing notice": (lambda d: d.pop("notice"), "missing"),
    "author role": (lambda d: d["author"].update(role="engine_author"), "world_author"),
    "foreign interface": (
        lambda d: d["interface"].update(catalog_digest="sha256:" + "0" * 64),
        "catalog_digest",
    ),
    "unavailable motivating": (
        lambda d: d["interface"].update(motivating_experiment="ellipsometry"),
        "motivating_experiment",
    ),
    "no worlds": (lambda d: d.update(worlds=[]), "non-empty list"),
    "duplicate world id": (
        lambda d: d["worlds"].append(copy.deepcopy(d["worlds"][0])),
        "appears twice",
    ),
    "bad world id": (lambda d: d["worlds"][0].update(world_id="has space"), "world_id"),
    "float amplitude": (
        lambda d: _world(d, "example-01")["hidden"]["effects"][0].update(amplitude=1.2),
        "a float",
    ),
    "bool seed": (lambda d: _world(d, "example-01")["hidden"].update(seed=True), "seed"),
    "negative seed": (lambda d: _world(d, "example-01")["hidden"].update(seed=-1), "seed"),
    "unknown class": (
        lambda d: _world(d, "example-01")["hidden"]["effects"][0].update(
            declared_class="thermo.unknown"
        ),
        "not in the engine catalog",
    ),
    "amplitude outside range": (
        lambda d: _world(d, "example-01")["hidden"]["effects"][0].update(amplitude="9.5"),
        "outside",
    ),
    "not a decimal": (
        lambda d: _world(d, "example-01")["hidden"]["effects"][0].update(amplitude="1,2"),
        "decimal string",
    ),
    "unknown category": (
        lambda d: _world(d, "example-01")["hidden"].update(category="easy"),
        "category",
    ),
    "declared with two effects": (
        lambda d: _world(d, "example-02")["hidden"].update(category="declared"),
        "exactly one declared class",
    ),
    "null with an effect": (
        lambda d: _world(d, "example-01")["hidden"].update(category="null"),
        "category null has no effects",
    ),
    "composition of one family": (
        lambda d: _world(d, "example-02")["hidden"]["effects"][0].update(
            declared_class="thermo.self_heating", amplitude="1.0"
        ),
        "share a mechanism family",
    ),
    "non-stationary without slope": (
        lambda d: _world(d, "example-07")["hidden"]["effects"][0].update(session_slope="0"),
        "non-zero session slope",
    ),
    "held-out with slope": (
        lambda d: _world(d, "example-05")["hidden"]["effects"][0].update(session_slope="0.1"),
        "no session slope",
    ),
    "unknown entry": (
        lambda d: _world(d, "example-05")["hidden"]["effects"][0]["sensitivity"].append(
            ["baseline", "temperature", "1.0"]
        ),
        "not a declared entry",
    ),
    "duplicate row": (
        lambda d: _world(d, "example-05")["hidden"]["effects"][0]["sensitivity"].append(
            ["baseline", "shift", "1.0"]
        ),
        "appears twice",
    ),
    "all-zero table": (
        lambda d: _world(d, "example-07")["hidden"]["effects"][0].update(
            sensitivity=[["baseline", "shift", "0"]]
        ),
        "every value is zero",
    ),
    "effect named like a class": (
        lambda d: _world(d, "example-05")["hidden"]["effects"][0].update(
            effect_id="scatter.sidewall"
        ),
        "names an engine class or family",
    ),
    "extra noise key": (
        lambda d: _world(d, "example-01")["hidden"]["noise"].update(drift="1"),
        "keys outside the schema",
    ),
    "truth smuggled into public": (
        lambda d: _world(d, "example-01")["public"].update(category="declared"),
        "keys outside the schema",
    ),
    "unknown removed experiment": (
        lambda d: _world(d, "example-01")["public"].update(removed=[["xrd", "no machine"]]),
        "not an available experiment",
    ),
    "motivating removed": (
        lambda d: _world(d, "example-01")["public"].update(removed=[["baseline", "broken"]]),
        "motivating experiment cannot be removed",
    ),
    "everything removed": (
        lambda d: _world(d, "example-01")["public"].update(
            removed=[
                [e, "broken"]
                for e in (
                    "power_sweep",
                    "tec_stabilized",
                    "gas_cell_reference",
                    "fiber_recouple",
                    "polarization_controlled",
                    "width_array",
                    "gap_array",
                    "radius_array",
                    "wavelength_span",
                    "cutback",
                )
            ]
        ),
        None,
    ),
}


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_malformed_worlds_are_refused(name, catalog, data):
    mutate, fragment = MALFORMED[name]
    mutate(data)
    if fragment is None:
        # Removing all but the motivating experiment is allowed; removing it too is not.
        _parse(data, catalog)
        _world(data, "example-01")["public"]["removed"].append(["baseline", "broken"])
        fragment = "motivating experiment cannot be removed"
    _refused(data, catalog, fragment)


# -- leaks ----------------------------------------------------------------------------------------

LEAKS = {
    "class id": ("example-01", "thermo.ambient was ruled out"),
    "family": ("example-04", "the geometry.thickness team keeps the tool"),
    "mechanism": ("example-01", "no thermo-optic drift check today"),
    "regime": ("example-01", "ambient temperature offset suspected"),
    "last id segment": ("example-01", "ambient lab"),
    "effect id": ("example-05", "reserved for example.unseen_mechanism"),
    "category": ("example-05", "this one is held out"),
    "world id": ("example-02", "see example-02 notes"),
}


@pytest.mark.parametrize("name", sorted(LEAKS))
def test_a_removal_reason_that_names_the_truth_is_refused(name, catalog, data):
    world_id, reason = LEAKS[name]
    _world(data, world_id)["public"]["removed"] = [["cutback", reason]]
    _refused(data, catalog, "names the truth")


def test_a_neutral_removal_reason_is_accepted(catalog, data):
    _world(data, "example-01")["public"]["removed"] = [["cutback", "the dicing saw is booked"]]
    assert _parse(data, catalog)


def test_a_suite_that_names_a_truth_is_refused(catalog, data):
    data["suite"] = "held-out stress"
    _refused(data, catalog, "suite names the truth")


def test_a_renamed_copy_labelled_held_out_is_refused_as_aliased(catalog, data):
    _world(data, "example-06")["hidden"]["category"] = "held_out"
    _refused(data, catalog, "label it aliased_held_out")
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    _world(data, "example-05")["hidden"]["category"] = "aliased_held_out"
    _refused(data, catalog, "label it held_out")


# -- sealing --------------------------------------------------------------------------------------


def test_default_salts_are_fresh_and_random(catalog, data):
    worlds = _parse(data, catalog)
    _, first = hw.seal(worlds)
    _, second = hw.seal(worlds)
    assert first["root"] != second["root"]
    assert set(first["commitments"]).isdisjoint(second["commitments"])


def test_the_engine_package_carries_no_truth(catalog, sealed_example):
    worlds, sealed, package = sealed_example
    assert [c["case_id"] for c in package["cases"]] == sorted(
        c["case_id"] for c in package["cases"]
    )
    needles = {w.world_id for w in worlds.worlds} | {"held_out", "non_stationary", "aliased"}
    for w in worlds.worlds:
        needles |= {str(e.declared_class or e.effect_id) for e in w.effects}
    assert find_truth_leaks(package, needles) == []
    text = json.dumps(package)
    assert not any(f'"{key}"' in text for key in hw.TRUTH_KEYS)
    parsed = hw.parse_engine_package(package, catalog)
    assert len(parsed.cases) == len(worlds.worlds)
    assert all(w["salt"] for w in sealed["worlds"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["cases"][0]["public"].update(hidden={"seed": 1}),
        lambda p: p["cases"][0].update(world_id="example-01"),
        lambda p: p.update(seed=3),
        lambda p: p["cases"][0]["public"].update(removed=[["cutback", 1.5]]),
        lambda p: p.update(root="sha256:" + "0" * 64),
        lambda p: p["commitments"].popitem(),
        lambda p: p["cases"][0].update(case_id="example-01"),
        lambda p: p.update(kind="lab-brain/discovery-hidden-worlds@1"),
    ],
)
def test_the_engine_side_loader_refuses_truth_keys_and_malformed_packages(
    mutate, catalog, sealed_example
):
    _, _, package = sealed_example
    bad = copy.deepcopy(package)
    mutate(bad)
    with pytest.raises(hw.HiddenWorldRefused):
        hw.parse_engine_package(bad, catalog)


def test_the_reveal_refuses_any_change_after_the_commitment(catalog, sealed_example):
    _, sealed, package = sealed_example
    parsed = hw.parse_engine_package(package, catalog)
    assert hw.reveal(sealed, parsed, catalog, DISCOVERY).suite == "format-example"

    changed_truth = copy.deepcopy(sealed)
    first = next(w for w in changed_truth["worlds"] if w["world_id"] == "example-01")
    first["hidden"]["effects"][0]["amplitude"] = "1.3"
    with pytest.raises(hw.CommitmentMismatch, match="commitments"):
        hw.reveal(changed_truth, parsed, catalog, DISCOVERY)

    changed_public = copy.deepcopy(package)
    changed_public["cases"][0]["public"]["removed"] = [["cutback", "the saw is booked"]]
    with pytest.raises(hw.CommitmentMismatch, match="altered"):
        hw.reveal(sealed, hw.parse_engine_package(changed_public, catalog), catalog, DISCOVERY)

    dropped = copy.deepcopy(sealed)
    dropped["worlds"].pop()
    with pytest.raises(hw.CommitmentMismatch, match="case set"):
        hw.reveal(dropped, parsed, catalog, DISCOVERY)

    resalted = copy.deepcopy(sealed)
    resalted["worlds"][0]["salt"] = "ab" * 32
    with pytest.raises(hw.HiddenWorldRefused, match="does not derive from its salt"):
        hw.reveal(resalted, parsed, catalog, DISCOVERY)


# -- laboratory, blind run, scoring ---------------------------------------------------------------


def test_a_declared_hidden_world_reads_exactly_what_the_synthetic_world_reads(catalog, data):
    worlds = _parse(data, catalog)
    for world in worlds.worlds:
        if world.category not in ("declared", "composition", "null"):
            continue
        spec = WorldSpec(
            world.world_id,
            world.category,
            world.seed,
            tuple((str(e.declared_class), e.amplitude) for e in world.effects),
            removed=world.removed,
            glitch_motivating=world.noise.glitch_motivating,
            glitch_first=world.noise.glitch_first,
            glitch_sigma=world.noise.glitch_sigma,
        )
        ours = hw.HiddenWorldLab(world, catalog, "baseline")
        theirs = SyntheticWorld(spec, catalog, "baseline")
        assert ours.motivating() == theirs.motivating()
        for session, experiment in enumerate(("power_sweep", "baseline", "gap_array"), start=1):
            assert ours.measure(experiment, replicate=0, session=session) == theirs.measure(
                experiment, replicate=0, session=session
            )


def test_a_non_stationary_world_drifts_with_the_session(catalog, data):
    world = next(w for w in _parse(data, catalog).worlds if w.category == "non_stationary")
    flat = hw.HiddenWorld(**{**world.__dict__, "noise": hw.Noise(scale=1e-3)})
    lab = hw.HiddenWorldLab(flat, catalog, "baseline")
    early = dict(lab.measure("baseline", replicate=0, session=1))["shift"]
    late = dict(lab.measure("baseline", replicate=0, session=9))["shift"]
    assert late - early == pytest.approx(10.0 * 0.5 * 8, abs=0.1)


def test_the_blind_run_hands_the_engine_nothing_hidden(catalog, sealed_example):
    worlds, sealed, package = sealed_example
    seen = []

    def spy(**kwargs):
        seen.append(kwargs)
        return investigate(**kwargs)

    parsed = hw.parse_engine_package(package, catalog)
    lab_side = hw.parse_hidden_worlds(sealed, catalog, DISCOVERY, sealed=True)
    outputs = hw.run_blind(
        parsed,
        catalog,
        arms=(benchmark.Arm("spy", "spy", DISCOVERY, spy),),
        budget=12,
        laboratories=hw.sealed_laboratories(lab_side, catalog),
    )
    assert set(outputs["cases"]) == {c.case_id for c in parsed.cases}
    needles = {w.world_id for w in worlds.worlds} | {"held_out", "non_stationary"}
    needles |= {str(e.effect_id) for w in worlds.worlds for e in w.effects if e.effect_id}
    assert find_truth_leaks(outputs, needles) == []
    for call in seen:
        assert call["catalog"] is catalog
        assert type(call["lab"]).__name__ == "BlindLaboratory"
        assert find_truth_leaks(to_jsonable(call["catalog"]), needles) == []
        assert call["budget"].total == 12


def test_scoring_the_example_end_to_end(catalog, sealed_example):
    _, sealed, package = sealed_example
    parsed = hw.parse_engine_package(package, catalog)
    lab_side = hw.parse_hidden_worlds(sealed, catalog, DISCOVERY, sealed=True)
    outputs = hw.run_blind(
        parsed,
        catalog,
        arms=benchmark.ARMS,
        budget=12,
        laboratories=hw.sealed_laboratories(lab_side, catalog),
    )
    revealed = hw.reveal(sealed, parsed, catalog, DISCOVERY)
    score = hw.score_outputs(outputs, revealed, parsed, catalog, DISCOVERY, seed=1, resamples=100)
    assert score["cases"] == 8
    for arm in ("B0", "B1", "B2"):
        cell = score["arms"][arm]
        assert cell["correct"]["n"] == 7  # the aliased world is scored apart
        assert cell["missing"] == 0
        assert cell["all_within_cap_and_metered"]
    for row in score["rows"]:
        assert not (row["correct"] and row["false_discovery"])
        if row["category"] == "aliased_held_out":
            assert not row["correct"]

    missing = copy.deepcopy(outputs)
    missing["cases"].pop(sorted(missing["cases"])[0])
    partial = hw.score_outputs(missing, revealed, parsed, catalog, DISCOVERY, seed=1, resamples=50)
    assert all(partial["arms"][a]["missing"] == 1 for a in ("B0", "B1", "B2"))

    foreign = {**outputs, "package_root": "sha256:" + "1" * 64}
    with pytest.raises(hw.ScoringRefused):
        hw.score_outputs(foreign, revealed, parsed, catalog, DISCOVERY, seed=1, resamples=50)
    invented = copy.deepcopy(outputs)
    invented["cases"]["case-000000000000"] = invented["cases"][sorted(invented["cases"])[0]]
    with pytest.raises(hw.ScoringRefused):
        hw.score_outputs(invented, revealed, parsed, catalog, DISCOVERY, seed=1, resamples=50)
    outside = copy.deepcopy(outputs)
    first = sorted(outside["cases"])[0]
    outside["cases"][first]["B2"].update(
        outcome="SURVIVING_PENDING_WARRANT_GATE", claim=["hyp:not.in.catalog"]
    )
    with pytest.raises(hw.ScoringRefused):
        hw.score_outputs(outside, revealed, parsed, catalog, DISCOVERY, seed=1, resamples=50)


def test_a_package_for_another_catalog_is_not_run(catalog, sealed_example):
    from dataclasses import replace

    _, _, package = sealed_example
    parsed = hw.parse_engine_package(package, catalog)
    other = replace(catalog, version="9.9.9")
    with pytest.raises(hw.HiddenWorldRefused):
        hw.run_blind(parsed, other, arms=benchmark.ARMS, budget=12, laboratories=lambda c: None)
