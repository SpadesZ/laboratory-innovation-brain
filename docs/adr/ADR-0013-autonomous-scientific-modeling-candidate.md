# ADR-0013：以受治理的 typed 建構建立自主科學建模能力

Status: Proposed — Candidate only; not accepted
Date: 2026-10-20
Affected Requirements: ASM-001–018 (candidate); SIM-001/002/003, TST-001, EXT-001, EPI-003/004/005, SEC-001/002, COST-001, OPS-001/004, UX-001–007 (existing)
Human Approval Required: Yes — 新長期產品目標與 P0 科學/安全契約，尚未核准
Spec revision: SAI 3.4.0-candidate.1；active SAI 3.3 不變

## Context

現有 simulation/Job/Run/資源/預算及 mock contract 不足以讓產品從問題第一次建立物理模型。
依賴外部 coding agent 手工補模型會使完成品無法自行運作。直接讓 LLM 執行任意 script 則
破壞 P19/typed tools、權限與可重現性，也無法證明數值或科學可靠。

## Constraints

繼承 P1–P28、DomainPack 邊界、既有 immutable/evidence/event/CWG、project isolation、
budget/egress、四類工具與 HARD-LOCK。沒有 license 不能簽實機驗收；既有 mock 仍只作契約證據。

## Options Considered

1. **提議採用**：內部科學 reasoner 產生 typed spec/patch，確定性 compiler 及受限 licensed worker 建構與執行，獨立 validators/evaluator 驗證後經現有科學准入。
2. 維持人工專案＋sweep，或由外部 coding agent 補齊首次模型；較少開發，但不滿足自主完成品目標。

任意 generated code 不是接受的第三選項，因與現行 P19/SIM-003 直接衝突。

## Proposed Decision

採候選的 model/build/refinement/validation envelope；領域物理 payload 留在 DomainPack，
vendor lowering/session 留在 provider。重用 simulation/job/resource/budget seams，
以 G1–G9 分開驗收。先 CHARGE，再按研究需要 MODE/FDTD/INTERCONNECT/多物理。
沒有外部 coding agent 的乾淨部署也能在已核准範圍內完成新問題；必要 review 仍由人處理。

## Consequences

增加 compiler/schema、材料來源、readback、worker/evaluator 隔離、數值與物理 benchmark 的
實作與授權依賴。不能靠 prompt 或現有 deterministic benchmark 宣稱完成。
Owner 要先核准能力範圍、精度/成本門檻、資料權利與人工介入 policy；詳細 D-01–D-08
見 [決策與審查](../spec/sai34/decisions-and-review.md)。

## Migration / Rollback

本次只有候選文件及文件 CI，無 runtime/schema migration。active spec/registry/milestones
不變；移除候選導覽/檢查與候選檔案即可回復文件層。未來 schema/worker 變更分 slice 另審；
不重寫歷史 snapshot、不重開鎖定、不能以回退刪掉新科研紀錄。

## Tests / Evidence

[SAI 3.4 Candidate](../spec/SAI_3.4_Candidate.md)、[候選驗收](../spec/sai34/acceptance.md)、
[source gap](../spec/sai34/implementation-gap.md) 及 `python docs/spec/sai34/check_candidate.py`。
所有 T-ASM-* 是 planned test obligations，不代表實作或 licensed replay 完成。
