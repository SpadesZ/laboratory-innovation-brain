"""The Silicon Photonics pack's curated renderings cover every word of it a researcher reads.

coverage    every mechanism name, statement and falsifier in the catalog, every capability,
            observable and outcome the pack declares, and why a simulation cannot run here,
            has a Traditional Chinese rendering; every identifier has an English name
terms       a name keeps its English scientific term beside the Chinese
canonical   the renderings change nothing the pack reasons with: the catalog, its declared
            links and their registered digest are what they were
"""

from __future__ import annotations

import re

from lab_brain.domains.silicon_photonics import presentation, product
from lab_brain.domains.silicon_photonics import vertical as sp

CJK = re.compile(r"[一-鿿]")


def _vertical():
    return product.product_vertical(outputs=None, jobs=None, broker=None, now=lambda: None)


def test_every_declared_word_a_researcher_reads_has_a_rendering():
    vertical = _vertical()
    zh = vertical.presentation["zh-TW"]
    en = vertical.presentation["en"]
    sentences = [
        text
        for m in vertical.catalog.mechanisms
        for text in (m.mechanism, m.statement, m.falsifier)
    ]
    sentences += [product.SIMULATOR_UNAVAILABLE, product.SIMULATOR_REQUIRES]
    identifiers = [c.capability_id for c in vertical.planning_capabilities]
    identifiers += [o for c in vertical.planning_capabilities for o in c.produces]
    identifiers += [o for space in sp.outcome_spaces() for o in space.outcomes]
    for text in (*sentences, *identifiers):
        assert CJK.search(zh.get(text, "")), f"no Traditional Chinese rendering: {text!r}"
    for identifier in identifiers:
        assert en.get(identifier), f"no English name: {identifier!r}"
    assert vertical.presentation_ref == presentation.PRESENTATION_REF


def test_a_name_keeps_its_english_term_beside_the_chinese():
    names = [m.mechanism for m in _vertical().catalog.mechanisms]
    for name in names:
        rendering = presentation.ZH_TW[name]
        assert re.search(r"（[^）]*[A-Za-z][^）]*）", rendering), rendering
    for _, zh in presentation.NAMES.values():
        assert re.search(r"[A-Za-z]", zh), zh


def test_the_renderings_change_nothing_the_pack_reasons_with():
    declarations = product.diagnostic_declaration_set()
    assert declarations.digest == product.DECLARATION_DIGESTS[declarations.ref]
    catalog = _vertical().catalog
    assert catalog.mechanisms[0].statement == (
        "An access or contact discontinuity dominates the series resistance."
    )
