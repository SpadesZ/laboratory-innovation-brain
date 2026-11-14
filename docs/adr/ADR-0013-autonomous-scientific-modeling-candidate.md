# ADR-0013：以受治理的 typed 建構建立自主科學建模能力

Status: Proposed — Candidate only; not accepted
Date: 2026-10-20
Updated: 2026-10-21 — CONDITIONAL PASS corrections against `61f6beba0fb6898a9d18cca9bb7e8b4005a9f51c`
Affected Requirements: ASM-001–018 (candidate); SIM-001/002/003, TST-001, EXT-001, EPI-003/004/005, SEC-001/002, COST-001, OPS-001/004, UX-001–007 (existing)
Human Approval Required: Yes — Human Owner 已同意八項審查方向、條件與文件修正；正式決策保持 OPEN，尚未核准啟用或 runtime slice
Spec revision: SAI 3.4.0-candidate.2；active SAI 3.3 不變

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
以獨立 G0 與 G1–G9 分開驗收。G0 要真實受治理 LLM、經認證的產品研究流程、有用的英文/繁中
科研正文與匯出、完整 provenance 及未執行模擬清單，CatalogReasoner/mock 不能替代。
先 CHARGE/PN，再按研究需要 MODE/FDTD/INTERCONNECT/多物理。
沒有外部 coding agent 的乾淨部署也能在已核准範圍內完成新問題；必要 review 仍由人處理。
ASM-016 的八類科學內容是衍生雙語呈現，canonical records/hash/簽章/機器狀態保留。
G7-SITE 先接受同一合格安裝的單站重現；G7-WORKER 另驗第二合格 worker，不阻擋單站。
同站多 worker 不等於跨站資格。人類帳號角色僅 ADMIN/MEMBER；project membership、
independent scientific reviewer authorization 及 worker service identity 是分開的治理概念。

## Consequences

增加 compiler/schema、材料來源、readback、worker/evaluator 隔離、數值與物理 benchmark 的
實作與授權依賴。不能靠 prompt 或現有 deterministic benchmark 宣稱完成。
離線工作依 C34-A0 的明確架構/slice 核准先行，不要求 license、物理 benchmark 與部署決策
全部先結案；這些在對應 milestones 前各別核准。實際來源權利、egress、預算與執行權限
仍先於副作用，不能以離線核准放寬。詳細 D-01–D-08 見 [決策與審查](../spec/sai34/decisions-and-review.md)：
審查者建議及 Human Owner 同意方向已記錄，八個正式狀態均 OPEN；A3/A9/A12 安全決策未封口。
單一 ADMIN 不免除科學審查獨立性，也不授予 DB 服務角色無限制的角色修改 SQL 權限。

## Migration / Rollback

本次只有候選文件及文件 CI，無 runtime/schema migration。active spec/registry/milestones
不變；移除候選導覽/檢查與候選檔案即可回復文件層。未來 schema/worker 變更分 slice 另審；
不重寫歷史 snapshot、不重開鎖定、不能以回退刪掉新科研紀錄。

## Tests / Evidence

[SAI 3.4 Candidate](../spec/SAI_3.4_Candidate.md)、[候選驗收](../spec/sai34/acceptance.md)、
[source gap](../spec/sai34/implementation-gap.md) 及 `python docs/spec/sai34/check_candidate.py`。
所有 T-ASM-* 是 planned test obligations，不代表實作或 licensed replay 完成。
文件 checker 增加六項修正的矛盾檢查與破壞反例；G0、G7-SITE/G7-WORKER 均未在本次執行。
