"""The candidate SP declaration version 1.1.0: prepared for the owner, never registered by the pack.

Causal Warrant Gate V1.1, review 04 (science validation) found three links whose check cannot
observe what the link claims. The candidate leaves exactly those three to a person (`012t`) and is
otherwise 1.0.0. Pinned here: 1.0.0 is unchanged, the candidate differs from it in those three
links only, and the product still registers and reasons under 1.0.0 alone -- so nothing the product
concludes changes until the owner activates it. Its behaviour on the benchmark is
`tests/e2e/test_sp_candidate_declarations_postgres.py`.
"""

from __future__ import annotations

from lab_brain.core.models.enums import RelationType
from lab_brain.domains.silicon_photonics import product

WITHDRAWN = {
    "contact_discontinuity": (RelationType.CONTRADICTS,),
    "dopant_compensation": (RelationType.CONTRADICTS,),
    "mesh_artifact": (RelationType.SUPPORTS,),
}


def test_the_registered_version_is_unchanged():
    current = product.diagnostic_declaration_set()
    assert current.ref == "sp.rs_anomaly_mechanisms@1.0.0"
    assert current.digest == product.DECLARATION_DIGESTS[current.ref]
    assert all(not d.review_only for d in current.declarations)


def test_the_candidate_leaves_exactly_three_links_to_a_person_and_is_otherwise_1_0_0():
    current = product.diagnostic_declaration_set()
    candidate = product.candidate_declaration_set()
    assert candidate.ref == "sp.rs_anomaly_mechanisms@1.1.0"
    assert candidate.digest == product.CANDIDATE_DIGESTS[candidate.ref] != current.digest
    assert {d.class_id: d.review_only for d in candidate.declarations if d.review_only} == WITHDRAWN
    for old, new in zip(current.declarations, candidate.declarations, strict=True):
        assert old.model_dump(exclude={"review_only"}) == new.model_dump(exclude={"review_only"})
    assert set(product.CANDIDATE_REVIEW_ONLY) == set(WITHDRAWN)
    for key, (effect, reason) in product.CANDIDATE_REVIEW_ONLY.items():
        assert (effect,) == WITHDRAWN[key] and len(reason) > 40, "each withdrawal says why"


def test_the_product_neither_registers_nor_reasons_under_the_candidate():
    vertical = product.product_vertical(outputs=None, jobs=None, broker=None, now=lambda: None)  # type: ignore[arg-type,return-value]
    assert [s.ref for s in vertical.declaration_sets] == ["sp.rs_anomaly_mechanisms@1.0.0"]
    assert vertical.active_declarations == "sp.rs_anomaly_mechanisms@1.0.0"
    assert product.mechanism_catalog().version == product.CATALOG_VERSION == "1.0.0"


def test_a_reviewer_is_told_which_links_the_domain_leaves_to_them(monkeypatch):
    """Once the candidate is installed, the review packet says a withdrawn link is theirs."""
    from lab_brain.interfaces import review_cli

    candidate = product.candidate_declaration_set()
    monkeypatch.setattr(review_cli, "_installed_declarations", lambda: (candidate,))
    mesh = candidate.by_class("mesh_artifact")
    assert mesh is not None
    lines = review_cli._attribution(mesh.signature, mesh.mechanism)
    assert any("leaves this class's SUPPORTS link to a person" in line for line in lines), lines
    normalization = candidate.by_class("normalization_error")
    assert normalization is not None
    plain = review_cli._attribution(normalization.signature, normalization.mechanism)
    assert not any("to a person" in line for line in plain)
