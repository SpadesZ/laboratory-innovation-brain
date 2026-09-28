"""Human-readable names for the workspace's routing vocabulary -- presentation only, in one place.

Researchers read "Primary reasoning" / 「主要推理」, not `REASONING_PRIMARY`. This module is the ONE
mapping from the canonical machine IDs -- `LogicalSlot`, `CognitiveRole`, `Capability`, readiness
states, reach -- to localized names and one-line descriptions. It renames nothing: the enums, the
routing table, the capability IDs, the database and every provenance record keep their IDs exactly.
A page shows the name; the ID stays one step away, in the element's tooltip and in a collapsible
"technical details" block, for whoever needs to match it against a log, a row or a report.

Every page asks this module, so switching the interface language changes every label at once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from lab_brain.cognition.routing import CognitiveRole
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.web.i18n import LOCALES, Messages
from lab_brain.interfaces.web.pages import Html, cat, e, h
from lab_brain.llm_runtime.capabilities import Capability

# (English, Traditional Chinese) -- in `LOCALES` order.
_Pair = tuple[str, str]

SLOT_NAMES: Mapping[LogicalSlot, _Pair] = {
    LogicalSlot.REASONING_PRIMARY: ("Primary reasoning", "主要推理"),
    LogicalSlot.FAST_UTILITY: ("Fast processing", "快速處理"),
    LogicalSlot.REASONING_ADVERSARIAL: ("Independent critique", "獨立批判"),
    LogicalSlot.PRIVATE_LOCAL: ("Private local model", "本機私有模型"),
    LogicalSlot.CODE: ("Code and computation", "程式與運算"),
    LogicalSlot.VISION: ("Image understanding", "圖像理解"),
    LogicalSlot.EMBEDDING: ("Semantic embedding", "語意向量"),
}

SLOT_PURPOSES: Mapping[LogicalSlot, _Pair] = {
    LogicalSlot.REASONING_PRIMARY: (
        "the main scientific reasoning: hypotheses, specialist positions, planning",
        "主要的科學推理：假說、領域專家立場、驗證規劃",
    ),
    LogicalSlot.FAST_UTILITY: (
        "quick structured work such as rewriting evidence searches",
        "快速的結構化工作，例如改寫證據搜尋查詢",
    ),
    LogicalSlot.REASONING_ADVERSARIAL: (
        "a separate model for the adversarial critique",
        "由另一個模型負責反方批判",
    ),
    LogicalSlot.PRIVATE_LOCAL: (
        "sensitive work on a model running on this machine",
        "在本機執行的模型處理敏感工作",
    ),
    LogicalSlot.CODE: ("code and tool integration", "程式與工具整合"),
    LogicalSlot.VISION: ("figures and images in documents", "文件中的圖表與影像"),
    LogicalSlot.EMBEDDING: ("similarity search over evidence", "證據的相似度搜尋"),
}

ROLE_NAMES: Mapping[CognitiveRole, _Pair] = {
    CognitiveRole.SUPERVISOR: ("Research orchestration", "研究流程統籌"),
    CognitiveRole.HYPOTHESIS_ENGINE: ("Hypothesis generation and comparison", "假說產生與比較"),
    CognitiveRole.VERIFICATION_PLANNER: ("Verification planning", "驗證規劃"),
    CognitiveRole.NOVELTY_AUDITOR: ("Novelty and prior-work check", "創新性／先前研究檢查"),
    CognitiveRole.DOMAIN_SPECIALIST: ("Domain specialists", "領域專家"),
    CognitiveRole.EVIDENCE_RESEARCHER: ("Evidence and data search", "證據與資料搜尋"),
    CognitiveRole.ADVERSARIAL_CRITIC: ("Adversarial review", "反方審查"),
}

CAPABILITY_NAMES: Mapping[Capability, _Pair] = {
    Capability.CHAT: ("Answers a prompt", "能回應提問"),
    Capability.STRUCTURED_JSON: ("Returns structured data (JSON)", "能輸出結構化資料（JSON）"),
    Capability.ROLE_QUERY: ("Writes evidence search queries", "能撰寫證據搜尋查詢"),
    Capability.ROLE_HYPOTHESIS: (
        "Proposes competing hypotheses in the required form",
        "能以規定格式提出競爭假說",
    ),
    Capability.ROLE_SPECIALIST: (
        "States a specialist position in the required form",
        "能以規定格式提出領域專家立場",
    ),
    Capability.ROLE_CRITIQUE: (
        "Writes an adversarial critique in the required form",
        "能以規定格式撰寫反方批判",
    ),
    Capability.CODE: ("Writes valid code", "能撰寫有效的程式碼"),
    Capability.VISION: ("Reads images", "能讀取圖像"),
}

STATE_NAMES: Mapping[str, _Pair] = {
    "READY": ("Ready", "已就緒"),
    "MISSING": ("No model yet (required)", "還沒有模型（必要）"),
    "FALLBACK": ("Uses primary reasoning", "改由主要推理處理"),
    "BUILTIN": ("Built in", "內建"),
    "UNBOUND": ("Not set (optional)", "未設定（選用）"),
    "BLOCKED": ("Cannot be used", "目前無法使用"),
}

REACH_NAMES: Mapping[str, _Pair] = {
    "LOCAL": ("local model", "本機模型"),
    "EXTERNAL": ("external API", "外部 API"),
}

Messages.extend(
    {
        "lbl.technical": ("Technical details (internal IDs)", "技術細節（內部識別碼）"),
        "lbl.col.use": ("Used for", "用途"),
        "lbl.col.status": ("Status", "狀態"),
        "lbl.col.who": ("Who relies on it", "由哪些研究角色使用"),
        "lbl.col.needs": ("What the model must pass", "模型必須通過的測試"),
        "lbl.col.model": ("Model", "模型"),
        "lbl.col.notes": ("Notes", "說明"),
        "lbl.col.internal": ("Internal ID", "內部識別碼"),
        "lbl.col.shown_as": ("Shown as", "顯示名稱"),
        "lbl.via": ("via {connection}, {reach}", "經由 {connection}（{reach}）"),
        "lbl.nobody": ("no research step in this version", "這個版本沒有研究步驟使用"),
        "lbl.builtin_model": ("the built-in local embedder", "內建的本機向量模型"),
        "lbl.builtin_note": (
            "Always available on this machine; provider embeddings are not used in this version.",
            "一律在本機提供；這個版本不使用外部服務的向量模型。",
        ),
        "lbl.critic.fallback": (
            "Independent critique has no model, so Adversarial review runs on Primary reasoning "
            "({model}). This is NOT an independent model: the critique's independence rests "
            "only on its separate evidence search.",
            "「獨立批判」沒有指派模型，因此「反方審查」改由「主要推理」（{model}）處理。這不是獨立的模型："
            "反方審查的獨立性只來自它另外進行的證據搜尋。",
        ),
        "lbl.critic.same": (
            "Independent critique uses the same model as Primary reasoning ({model}): a separate "
            "use, but NOT an independent model.",
            "「獨立批判」與「主要推理」使用同一個模型（{model}）：用途分開，但不是獨立的模型。",
        ),
        "lbl.critic.own": (
            "Adversarial review has its own model: {model}.",
            "「反方審查」有自己的模型：{model}。",
        ),
        "lbl.egress.local": (
            "Every model runs on this machine: no model call leaves it.",
            "所有模型都在這台電腦上執行：沒有任何模型呼叫會離開這台電腦。",
        ),
        "lbl.egress.external": (
            "External APIs ({names}) may receive at most evidence classified {labels} -- and a "
            "project's evidence only if that project's own external transfer setting approves "
            "them: this configuration supplies models, not permission. Anything else is refused "
            "and the refusal is recorded; NDA material never leaves. The researcher's own access "
            "also applies.",
            "外部 API（{names}）最多只能收到分級為 {labels} 的證據，而且只有在該研究專案自己的外部"
            "傳輸設定"
            "核准時才會送出：模型配置只提供模型，不提供授權。其他內容一律拒絕並留下紀錄；保密協議（NDA）的"
            "資料永遠不會送出。研究者本身的閱讀權限同樣適用。",
        ),
        "lbl.rule_text": ("The server's rule text", "系統規則原文"),
    }
)


_ALL_IDS: dict[str, tuple[str, _Pair]] = {
    **{s.value: ("slot", n) for s, n in SLOT_NAMES.items()},
    **{r.value: ("role", n) for r, n in ROLE_NAMES.items()},
    **{c.value: ("capability", n) for c, n in CAPABILITY_NAMES.items()},
}
#: Tokens that name BOTH a slot and a capability: left as they are inside free text.
_AMBIGUOUS = frozenset({"CODE", "VISION"})
_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])("
    + "|".join(
        sorted((re.escape(t) for t in _ALL_IDS if t not in _AMBIGUOUS), key=len, reverse=True)
    )
    + r")(?![A-Za-z0-9_])"
)


def _pick(pair: _Pair, locale: str) -> str:
    return pair[LOCALES.index(locale) if locale in LOCALES else 0]


def _term(name: str, raw: str) -> Html:
    return h('<span class="term" title="{}">{}</span>', raw, name)


def slot(value: LogicalSlot, locale: str) -> Html:
    return _term(_pick(SLOT_NAMES[value], locale), value.value)


def slot_purpose(value: LogicalSlot, locale: str) -> str:
    return _pick(SLOT_PURPOSES[value], locale)


def role(value: str, locale: str) -> Html:
    try:
        return _term(_pick(ROLE_NAMES[CognitiveRole(value)], locale), value)
    except ValueError:
        return e(value)


def capability(value: str, locale: str) -> Html:
    try:
        return _term(_pick(CAPABILITY_NAMES[Capability(value)], locale), value)
    except ValueError:
        return e(value)


def state(value: str, locale: str) -> Html:
    css = re.sub(r"[^A-Z_]", "", value)
    name = _pick(STATE_NAMES[value], locale) if value in STATE_NAMES else value
    return h('<span class="state state-{}" title="{}">{}</span>', css, value, name)


def reach(value: str | None, locale: str) -> str:
    if value is None or value not in REACH_NAMES:
        return value or "-"
    return _pick(REACH_NAMES[value], locale)


def humanize(text: str, locale: str) -> Html:
    """Rule text with every unambiguous slot, role and capability ID shown by its name (the ID in
    the tooltip). Everything else -- model names, numbers, quoted values -- is escaped as is."""
    out: list[Html] = []
    last = 0
    for match in _TOKEN.finditer(text):
        out.append(e(text[last : match.start()]))
        raw = match.group(1)
        out.append(_term(_pick(_ALL_IDS[raw][1], locale), raw))
        last = match.end()
    out.append(e(text[last:]))
    return cat(out)


def listing(values: Iterable[Html], locale: str) -> Html:
    items = list(values)
    return cat(items, "、" if locale == "zh-TW" else ", ") if items else Html("-")


def technical(locale: str, rows: Sequence[tuple[str, str]], texts: Sequence[str] = ()) -> Html:
    """The raw IDs and the server's own sentences, one click away."""
    m = Messages(locale)
    table = cat(h("<tr><th>{}</th><td><code>{}</code></td></tr>", k, v) for k, v in rows)
    sentences = (
        h("<h4>{}</h4><ul>{}</ul>", m("lbl.rule_text"), cat(h("<li>{}</li>", t) for t in texts))
        if texts
        else Html("")
    )
    return h(
        '<details class="tech"><summary>{}</summary><table>{}</table>{}</details>',
        m("lbl.technical"),
        table,
        sentences,
    )


__all__ = [
    "CAPABILITY_NAMES",
    "REACH_NAMES",
    "ROLE_NAMES",
    "SLOT_NAMES",
    "SLOT_PURPOSES",
    "STATE_NAMES",
    "capability",
    "humanize",
    "listing",
    "reach",
    "role",
    "slot",
    "slot_purpose",
    "state",
    "technical",
]
