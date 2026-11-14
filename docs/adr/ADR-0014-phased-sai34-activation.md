# ADR-0014：SAI 3.4 架構分期啟用，保留 3.3 執行契約

Status: Accepted for scoped architecture integration; effectiveness requires same-SHA CI and integration-line publication
Date: 2026-10-21
Affected Requirements: inherited SAI 3.3 requirements unchanged; ASM-001–018 architectural obligations, runtime tests deferred
Human Approval Required: Yes — 本次使用者明確授權文件整合、分期啟用準備及 G0／授權前建模準備範圍；未授權科學接受或部署
Spec profile: `3.4.0-phased.1`

## Context

已批准的 Candidate.2 在 `eaea2c03e24b968c62ef9d60e7032f279f5e136c`。
整合線目前為 `f3fadf6eaa7676d27b0129beeb40239cba2e1723`；Agent A 在另外的
`pre-lumerical-acceptance` 開發。需要一個可核查的後續架構依據，又不能把文件啟用冒充 G0
或物理接受，也不能把待實作 ASM 填入已執行覆蓋。

## Constraints

保留 SAI 3.3 原文、60 條需求/測試、registry/milestones、P1–P28、HARD-LOCK、歷史 canonical
records 與全部 runtime/test/source bytes。Candidate.2 的九份契約/檢查文件固定不改。
只可把文件／治理 diff 整入 integration，不合併 Agent A 或 main，不啟用 SP 1.1.0，readiness false。

## Options Considered

1. **採用**：3.4 正式分期架構 profile＋逐條 mapping/deferrals；保留 3.3 executable conformance。G0 與離線建模兩條線各自前進，實際 acceptance 另驗。
2. 現在就修改 runtime spec parser、namespace、active registry 與歷史 ratchet 以宣稱全面 3.4；超出本次文件限定範圍，也會改受保護行為，因此不採用。

## Decision

[SAI_3.4.md](../spec/SAI_3.4.md) 與 [activation.yaml](../spec/sai34/activation.yaml) 是後續開發的
架構入口；`ACTIVE_SPEC.yaml` 指向架構 profile 及繼承的 3.3 executable profile。
18 條 ASM 原義與 planned IDs 不變，每條明列工作線、相依、Owner gate、延期理由與 review date。
這是版本組合與效力範圍的具體紀錄，不是 normative override；直接契約矛盾仍依 AGT-015 停 slice。

G0 reliability 可先做，不等待建構器或 license；授權前建模準備不等待 G0 簽核。
Actor、來源權利、敏感度、egress、budget 仍在每次副作用前驗證；本次不准付費 API。
後續 runtime 接線/marker/ratchet 的完整遷移另列 P-FULL-RUNTIME，現在不改 source 或 tests。
ADR-0013 保留為 Candidate.2 歷史；本 ADR 只接受其限範圍架構使用，未關閉 D-01–D-08。

## Consequences

後續開發有明確架構基準與兩條獨立工作線；CI 同時驗歷史、候選及啟用對照。
代價是暫時有 architecture/executable 兩個清楚命名的 profile，不能稱為完整 3.4 runtime conformance。
所有 planned runtime tests 仍欠交付。真實模型穩定性、G0 科學可用性、licensed replay、物理精度、
獨立 benchmark、A3/A9/A12、部署與 readiness 各自保留原核准／接受要求。

## Migration / Rollback

無 DB/schema/runtime migration。整合前先在隔離分支通過完整 CI，再以無 force 的 fast-forward
發布同一已驗 SHA 至整合線；target 漂移需重新檢視相依與 diff。
若撤回分期架構 profile，以新文件 commit 停用新入口並保留原紀錄；不倒寫歷史或刪 Agent A 分支。
從 main 到此整合線既有的 runtime 堆疊不屬本次差異，不能誤報為本次 runtime 修改。

## Tests / Evidence

原 spec conformance、candidate checker、[activation checker](../spec/sai34/check_activation.py)
及同 SHA 的完整 CI／PostgreSQL ratchet。來源、保留範圍、授權與自我審查見
[integration-activation.md](../spec/sai34/integration-activation.md)。沒有新增已完成的 runtime test ID。
