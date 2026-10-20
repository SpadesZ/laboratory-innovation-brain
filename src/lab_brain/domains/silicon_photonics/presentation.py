"""How this pack's declared words read to a researcher, in each interface language.

PRESENTATION ONLY. The catalog, the capabilities, the outcome spaces and every stored record keep
their canonical English text and identifiers exactly; nothing here is read by reasoning,
verification or replay. A page looks a canonical string up here and shows the rendering beside
the original, which stays one step away (the page's original-text table, the full report).

CURATED, NOT GENERATED. Each Traditional Chinese rendering was written for the declared English it
is keyed by, keeping the English scientific term beside the Chinese. A key is the canonical text
itself, so a changed catalog sentence has no rendering until one is written for it -- the page then
shows the English, marked as untranslated, and `tests/unit/test_sp_presentation.py` fails.
Text a language model wrote is never in here: it has no curated rendering and is shown as written.

The renderings have not yet been reviewed by the laboratory's domain experts; `PRESENTATION_REF`
names this version so a page and an export can say which renderings they used.
"""

from __future__ import annotations

from typing import Final

from lab_brain.domains.silicon_photonics import diagnosis, reasoning, tools
from lab_brain.domains.silicon_photonics import vertical as sp

PRESENTATION_REF: Final = "sp.presentation@1.0.0 (curated; awaiting the laboratory's review)"

#: Identifiers (capabilities, observables, outcomes) -> (English name, Traditional Chinese name).
NAMES: Final[dict[str, tuple[str, str]]] = {
    sp.CAP_INSPECT_CONNECTIVITY: (
        "contact connectivity inspection",
        "接點連通性檢查（connectivity inspection）",
    ),
    sp.CAP_EXTRACTION_CONSISTENCY: (
        "extraction consistency check",
        "萃取一致性檢查（extraction consistency）",
    ),
    sp.CAP_MESH_SENSITIVITY: (
        "mesh sensitivity simulation",
        "網格敏感度模擬（mesh sensitivity）",
    ),
    sp.CAP_CHARGE_DC: ("CHARGE DC sweep simulation", "CHARGE 直流掃描模擬（DC sweep）"),
    sp.CAP_FOURPOINT_PROBE: (
        "four-point probe measurement",
        "四點探針量測（four-point probe）",
    ),
    sp.CAP_FABRICATE_SPLIT: ("split-lot fabrication", "分批試製（split-lot fabrication）"),
    tools.CHARGE_AC_CAPABILITY: ("CHARGE AC sweep simulation", "CHARGE 交流掃描模擬（AC sweep）"),
    sp.OBS_CONNECTIVITY: ("contact connectivity", "接點連通性（contact connectivity）"),
    sp.OBS_NORMALIZATION: ("normalization basis", "長度正規化基準（normalization basis）"),
    sp.OBS_MESH: ("mesh stability", "網格收斂穩定性（mesh stability）"),
    sp.OBS_CARRIER: ("carrier profile", "載子濃度分布（carrier profile）"),
    sp.OBS_PROBE: ("probe contact resistance", "探針接觸電阻（probe contact resistance）"),
    tools.OBSERVABLE_IMPEDANCE: ("small-signal impedance", "小訊號阻抗（small-signal impedance）"),
    diagnosis.CONTINUOUS: ("continuous", "連續（continuous）"),
    diagnosis.DISCONTINUOUS: ("discontinuous", "不連續（discontinuous）"),
    diagnosis.AGREES: ("agrees", "一致（agrees）"),
    diagnosis.DISAGREES: ("disagrees", "不一致（disagrees）"),
    diagnosis.STABLE: ("stable", "穩定（stable）"),
    diagnosis.UNSTABLE: ("unstable", "不穩定（unstable）"),
    diagnosis.NOMINAL: ("nominal", "符合設計值（nominal）"),
    diagnosis.COMPENSATED: ("compensated", "出現摻雜補償（compensated）"),
    diagnosis.ELEVATED: ("elevated", "偏高（elevated）"),
    reasoning.RS_FALLS: (
        "Rs falls with reverse bias",
        "Rs 隨逆向偏壓下降（falls with reverse bias）",
    ),
    reasoning.RS_INSENSITIVE: (
        "Rs insensitive to bias",
        "Rs 對偏壓不敏感（bias-insensitive）",
    ),
    reasoning.RS_RISES: (
        "Rs rises with reverse bias",
        "Rs 隨逆向偏壓上升（rises with reverse bias）",
    ),
}

COUNTER_DOPING = (
    "Counter-doping compensates the rib and raises the resistance of the undepleted access path."
)
TWO_POINT = (
    "Probe contact resistance in the two-point measurement inflates the reported series resistance."
)

#: Declared English sentences and names -> their Traditional Chinese rendering.
ZH_TW: Final[dict[str, str]] = {
    # The mechanism catalog (`product.mechanism_catalog`): names, statements, falsifiers.
    "access contact discontinuity": "存取區接點不連續（access contact discontinuity）",
    "An access or contact discontinuity dominates the series resistance.": (
        "存取區或接點的不連續主導了串聯電阻（series resistance, Rs）。"
    ),
    "the connectivity inspection finds every contact tied to metal with full overlap": (
        "連通性檢查發現每個接點都與金屬層完全重疊相連"
    ),
    "length normalization error": "長度正規化錯誤（length normalization error）",
    "A length normalization error in extraction inflates the per-length resistance.": (
        "參數萃取時的長度正規化錯誤，使單位長度電阻（per-length resistance）被高估。"
    ),
    "the extraction's normalization length matches the drawn length": (
        "萃取所用的正規化長度與佈局繪製長度（drawn length）相符"
    ),
    "mesh convergence artifact": "網格收斂假象（mesh convergence artifact）",
    "A mesh convergence artifact in the access region inflates the extracted series resistance.": (
        "存取區的網格收斂假象使萃取出的串聯電阻（series resistance）被高估。"
    ),
    "refining the access mesh leaves the extracted Rs unchanged": (
        "加密存取區網格（mesh refinement）後，萃取出的 Rs 沒有改變"
    ),
    "dopant compensation in the rib": "脊部摻雜補償（dopant compensation in the rib）",
    COUNTER_DOPING: (
        "反向摻雜（counter-doping）補償了脊部（rib）的摻雜，使未空乏的存取路徑電阻升高。"
    ),
    "the DC sweep shows the design free-carrier density in the access region": (
        "直流掃描（DC sweep）顯示存取區的自由載子濃度（free-carrier density）符合設計值"
    ),
    "measurement probe contact artifact": "量測探針接觸假象（probe contact artifact）",
    TWO_POINT: "二點量測（two-point measurement）中的探針接觸電阻，使報告的串聯電阻被高估。",
    "a four point measurement reports the same series resistance": (
        "四點量測（four-point measurement）得到相同的串聯電阻"
    ),
    # Why a simulation cannot run here, and what it needs (`product.SIMULATOR_*`).
    "no simulation backend is wired in this deployment: this repository has no licensed "
    "Lumerical provider, and no Lumerical installation or licence seat is configured "
    "(TST-001, risk R-1)": (
        "這個部署沒有接上任何模擬後端：本儲存庫沒有授權的 Lumerical 提供模組，"
        "也沒有設定 Lumerical 安裝或授權席位（licence seat）（TST-001，風險 R-1）"
    ),
    "a Lumerical DEVICE/CHARGE installation with a licence seat, and the licensed provider "
    "module wired in place of the missing backend": (
        "已安裝並具授權席位的 Lumerical DEVICE/CHARGE，以及接上目前缺少之後端的授權提供模組"
    ),
}


def presentation() -> dict[str, dict[str, str]]:
    """Locale -> canonical text or identifier -> rendering, for `ProductVertical.presentation`."""
    return {
        "en": {key: en for key, (en, _) in NAMES.items()},
        "zh-TW": {**{key: zh for key, (_, zh) in NAMES.items()}, **ZH_TW},
    }


__all__ = ["NAMES", "PRESENTATION_REF", "ZH_TW", "presentation"]
