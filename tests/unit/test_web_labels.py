"""Human-readable routing names on the workspace's pages -- and nothing renamed underneath.

The Runtime and LLM settings pages show researchers "Primary reasoning" / 「主要推理」, "Adversarial
review" / 「反方審查」, "Proposes competing hypotheses" / 「能以規定格式提出競爭假說」. The canonical IDs
-- `LogicalSlot`, `CognitiveRole`, `Capability` -- the routing table and what each slot requires are
exactly what they were; each raw ID is still one step away, in the name's tooltip and in the
page's technical details.
"""

from __future__ import annotations

import datetime as dt
import html
import re

from lab_brain.cognition.routing import CognitiveRole
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.web import labels
from lab_brain.interfaces.web.pages import Chrome
from lab_brain.interfaces.web.settings_pages import readiness_block
from lab_brain.llm_runtime.capabilities import (
    BINDABLE_SLOTS,
    SLOT_REQUIREMENTS,
    Capability,
    role_routes,
    roles_on,
)
from lab_brain.llm_runtime.readiness import Readiness, SlotReadiness
from lab_brain.llm_runtime.registry import RuntimeRow

T0 = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)

ZH_SLOTS = {
    "REASONING_PRIMARY": "主要推理",
    "FAST_UTILITY": "快速輔助",
    "REASONING_ADVERSARIAL": "獨立批判",
    "PRIVATE_LOCAL": "本機私有模型",
    "CODE": "程式與運算",
    "VISION": "圖像理解",
    "EMBEDDING": "語意向量",
}
ZH_ROLES = {
    "SUPERVISOR": "研究流程統籌",
    "HYPOTHESIS_ENGINE": "假說產生與比較",
    "VERIFICATION_PLANNER": "驗證規劃",
    "NOVELTY_AUDITOR": "創新性／先前研究檢查",
    "DOMAIN_SPECIALIST": "領域專家",
    "EVIDENCE_RESEARCHER": "證據與資料搜尋",
    "ADVERSARIAL_CRITIC": "反方審查",
}
EN_SLOTS = {
    "REASONING_PRIMARY": "Primary reasoning",
    "FAST_UTILITY": "Fast assistance",
    "REASONING_ADVERSARIAL": "Independent critique",
    "PRIVATE_LOCAL": "Private local model",
    "CODE": "Code and computation",
    "VISION": "Image understanding",
    "EMBEDDING": "Semantic embedding",
}
EN_ROLES = {
    "SUPERVISOR": "Research orchestration",
    "HYPOTHESIS_ENGINE": "Hypothesis generation and comparison",
    "VERIFICATION_PLANNER": "Verification planning",
    "NOVELTY_AUDITOR": "Novelty and prior-work check",
    "DOMAIN_SPECIALIST": "Domain specialists",
    "EVIDENCE_RESEARCHER": "Evidence and data search",
    "ADVERSARIAL_CRITIC": "Adversarial review",
}
RAW_IDS = (
    *ZH_SLOTS,
    *ZH_ROLES,
    "CHAT",
    "STRUCTURED_JSON",
    "ROLE_QUERY",
    "ROLE_HYPOTHESIS",
    "ROLE_SPECIALIST",
    "ROLE_CRITIQUE",
)


def _readiness() -> Readiness:
    """A runtime with the Critic falling back to PRIMARY, built from the real routing tables."""
    runtime = RuntimeRow("lrt:1", "demo", "ACTIVE", ("PUBLIC",), "act:1", T0, "act:1", T0, None)
    slots = []
    for slot in (*BINDABLE_SLOTS, LogicalSlot.EMBEDDING):
        bound = slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY)
        slots.append(
            SlotReadiness(
                slot=slot,
                state=(
                    "READY"
                    if bound
                    else "FALLBACK"
                    if slot is LogicalSlot.REASONING_ADVERSARIAL
                    else "BUILTIN"
                    if slot is LogicalSlot.EMBEDDING
                    else "UNBOUND"
                ),
                roles=tuple(r.value for r in roles_on(slot)),
                requires=tuple(sorted(c.value for c in SLOT_REQUIREMENTS.get(slot, ()))),
                model="fake-reasoner" if bound else None,
                connection="demo" if bound else None,
                reach="EXTERNAL" if bound else None,
                route="lk:0123456789abcdef" if bound else None,
            )
        )
    return Readiness(
        runtime=runtime,
        slots=tuple(slots),
        critic="FALLBACK: REASONING_ADVERSARIAL is not bound, so the Adversarial Critic runs on "
        "REASONING_PRIMARY (fake-reasoner). That is NOT model-route independence: the critique's "
        "independence rests on the inverted evidence path alone.",
        critic_independent=False,
        egress="External model routes (demo) may carry evidence classified PUBLIC.",
        blockers=(),
        warnings=(),
    )


def _render(locale: str) -> str:
    return str(readiness_block(Chrome("act:1", locale, "tok", "/runtime", "runtime"), _readiness()))


def _visible(markup: str) -> str:
    """What a reader sees without opening technical details or hovering: no tooltips."""
    without_details = re.sub(r"<details.*?</details>", " ", markup, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", without_details)).split())


def _details(markup: str) -> str:
    return " ".join(
        html.unescape(
            re.sub(
                r"<[^>]+>", " ", " ".join(re.findall(r"<details.*?</details>", markup, flags=re.S))
            )
        ).split()
    )


def test_the_internal_ids_and_the_routing_are_exactly_what_they_were():
    assert {s.value for s in BINDABLE_SLOTS} | {"EMBEDDING"} == set(ZH_SLOTS)
    assert {r.value for r in CognitiveRole} == set(ZH_ROLES)
    assert {c.value for c in Capability} == {
        "CHAT",
        "STRUCTURED_JSON",
        "ROLE_QUERY",
        "ROLE_HYPOTHESIS",
        "ROLE_SPECIALIST",
        "ROLE_CRITIQUE",
        "CODE",
        "VISION",
    }
    assert {r.value: s.value for r, s in role_routes().items()} == {
        "SUPERVISOR": "REASONING_PRIMARY",
        "EVIDENCE_RESEARCHER": "FAST_UTILITY",
        "HYPOTHESIS_ENGINE": "REASONING_PRIMARY",
        "ADVERSARIAL_CRITIC": "REASONING_ADVERSARIAL",
        "VERIFICATION_PLANNER": "REASONING_PRIMARY",
        "NOVELTY_AUDITOR": "REASONING_PRIMARY",
        "DOMAIN_SPECIALIST": "REASONING_PRIMARY",
    }
    assert {s.value: sorted(c.value for c in r) for s, r in SLOT_REQUIREMENTS.items()} == {
        "REASONING_PRIMARY": ["CHAT", "ROLE_HYPOTHESIS", "ROLE_SPECIALIST", "STRUCTURED_JSON"],
        "REASONING_ADVERSARIAL": ["CHAT", "ROLE_CRITIQUE", "STRUCTURED_JSON"],
        "FAST_UTILITY": ["CHAT", "ROLE_QUERY", "STRUCTURED_JSON"],
        "CODE": ["CHAT", "CODE"],
        "VISION": ["CHAT", "VISION"],
        "PRIVATE_LOCAL": ["CHAT", "STRUCTURED_JSON"],
    }
    # One name per ID, in every locale -- nothing left to a literal on some page.
    assert set(labels.SLOT_NAMES) == {*BINDABLE_SLOTS, LogicalSlot.EMBEDDING}
    assert set(labels.ROLE_NAMES) == set(CognitiveRole)
    assert set(labels.CAPABILITY_NAMES) == set(Capability)


def test_traditional_chinese_shows_the_researchers_names():
    shown = _visible(_render("zh-TW"))
    for name in (*ZH_SLOTS.values(), *ZH_ROLES.values()):
        if name == "反方審查":
            continue  # the Critic has no slot of its own here; it is named in the fallback line
        assert name in shown, name
    assert "「反方審查」改由「主要推理」（fake-reasoner）執行" in shown
    assert "能以規定格式提出競爭假說" in shown and "能輸出結構化資料（JSON）" in shown
    assert "改由主要推理執行" in shown and "未設定（選用）" in shown


def test_english_shows_the_researchers_names():
    shown = _visible(_render("en"))
    for name in (*EN_SLOTS.values(), *EN_ROLES.values()):
        if name == "Adversarial review":
            continue
        assert name in shown, name
    assert "Adversarial review runs on Primary reasoning (fake-reasoner)" in shown
    assert "Proposes competing hypotheses in the required form" in shown


def test_raw_ids_leave_the_main_view_and_stay_in_tooltips_and_details():
    for locale in ("zh-TW", "en"):
        markup = _render(locale)
        shown = _visible(markup)
        for raw in RAW_IDS:
            assert not re.search(rf"(?<![A-Za-z0-9_]){raw}(?![A-Za-z0-9_])", shown), (locale, raw)
        details = _details(markup)
        for raw in RAW_IDS:
            assert raw in details, (locale, raw)
        assert "lk:0123456789abcdef" in details
        assert 'title="REASONING_PRIMARY"' in markup and 'title="ROLE_HYPOTHESIS"' in markup
        assert "NOT model-route independence" in details, "the server's own sentence is kept"


def test_switching_language_changes_every_label_and_no_id():
    zh, en = _render("zh-TW"), _render("en")
    assert _visible(zh) != _visible(en)
    ids = lambda m: sorted(re.findall(r'title="([A-Z_]+)"', m))  # noqa: E731
    assert ids(zh) == ids(en)
    strip = lambda m: re.sub(r"<summary>.*?</summary>|<th>[^<]*</th>|<h4>.*?</h4>", "", m)  # noqa: E731
    assert [strip(d) for d in re.findall(r"<details.*?</details>", zh, flags=re.S)] == [
        strip(d)
        .replace("Primary reasoning", "主要推理")
        .replace("Fast assistance", "快速輔助")
        .replace("Independent critique", "獨立批判")
        .replace("Private local model", "本機私有模型")
        .replace("Code and computation", "程式與運算")
        .replace("Image understanding", "圖像理解")
        .replace("Semantic embedding", "語意向量")
        for d in re.findall(r"<details.*?</details>", en, flags=re.S)
    ]


def test_rule_text_names_known_ids_and_leaves_everything_else_as_it_is():
    text = "llm model <b>fake-reasoner</b> has not proven {ROLE_HYPOTHESIS} for REASONING_PRIMARY; CODE"
    out = str(labels.humanize(text, "zh-TW"))
    assert '<span class="term" title="ROLE_HYPOTHESIS">能以規定格式提出競爭假說</span>' in out
    assert '<span class="term" title="REASONING_PRIMARY">主要推理</span>' in out
    assert "&lt;b&gt;fake-reasoner&lt;/b&gt;" in out, "escaped, never markup"
    assert out.endswith("; CODE"), "an ID that names both a slot and a capability is left as is"
