# SAI 3.4 — 分期啟用的架構基準

版本：`3.4.0-phased.1`｜日期：2026-10-21。
狀態：**限範圍架構基準；指定 SHA 通過完整 CI 並進入整合線後生效**。
`READY_FOR_REAL_RESEARCH = false`

## 1. 授權、效力與規格組成

Human Owner 本次明確授權：整合 `3.4.0-candidate.2`、開始分期啟用程序，讓 G0 可靠度工作與
授權前自主建模準備各自前進。這是後續開發的限範圍架構授權，不是科學產品接受、全面 runtime
conformance、license 使用、付費模型呼叫或部署授權。[授權與變更影響紀錄](sai34/integration-activation.md)
保存原話、範圍、祖先關係與條件；[ADR-0014](../adr/ADR-0014-phased-sai34-activation.md) 記錄其決定。

本版本由以下三份固定契約組成，不靠「新版優先」裁決衝突：

1. [SAI 3.3](SAI_3.3.md)（a1–a18）完整繼承：60 個既有 requirements、原測試/registry/milestones、P1–P28、歷史事件與 HARD-LOCK 保持原義及 bytes。
2. [已批准候選的 §1–§10](SAI_3.4_Candidate.md)：ASM-001–018 的架構、G0 與 G1–G9 契約完整採用；內容固定於 `eaea2c03e24b968c62ef9d60e7032f279f5e136c`，由本次授權開啟下述開發階段。
3. 本文件與 [分期 normative registry／activation mapping](sai34/activation.yaml)：明定目前適用 scope、舊需求相依、新 planned tests、milestones、Owner gates 與具名 deferrals。

候選本身的「待批准／尚未開始」狀態、candidate registry 及 ADR-0013 保留為該 SHA 的歷史。
它們不是新的啟用紀錄；新的授權記在 ADR-0014 與本 profile。候選的物理與治理契約未被改寫。
本次沒有修改既有 MUST、科學 authority、帳號權限、solver 介面或資料 schema。
若後續 slice 發現直接矛盾，依 AGT-015 開 spec issue，停止受影響的 slice，不能任選一段。

## 2. 已開放的兩條工作線

| 工作線 | 可獨立進行的工作 | 不代表什麼／仍須先取得什麼 |
|---|---|---|
| P-G0 | 依 G0-A/L/S/B/P 改善真實 LLM 研究可靠度、認證、provenance、科學雙語內容與匯出、未做模擬的誠實呈現；離線回歸與無付費的合規本機驗證 | 不等到模型建構器或 license 才開始；真實外送、模型費用、資料權利、actor/egress/budget 仍逐次受現行 gate；catalog/mock 不能接受 G0 |
| P-MODEL | 型別化 spec、單位/權威參數驗證、封閉建構 operations、確定性 lowering、fake SDK/readback、worker/queue/fencing/recovery 的離線設計與測試規劃 | 不等到 G0 已驗收才準備；不能執行真實 solver、假造 license/readback 或把 mock 當物理證據；所有實作仍是後續獨立 slice，本次只整合文件 |

兩線共享型別、證據與治理契約；任何跨線 API/schema/受保護行為變更要獨立說明相依與回歸。
共同結案可有依賴，但不能把一條線的完整成功變成另一條開始工作的前置條件。
`pre-lumerical-acceptance` 是 Agent A 的獨立開發分支，未在本次合併；其測試、報告與未接受
結果保留在原分支，不能移作這條整合線的 G0 PASS。細節見變更影響紀錄 §3。

## 3. 分期啟用與驗收

| Profile milestone | 接受／開放條件 | 目前範圍與後續 gate |
|---|---|---|
| P0-BASIS | Owner 授權收錄、候選固定、legacy 相容、18 條映射與 deferral 完整、文件限定 diff、同 SHA 完整 CI 通過，再進整合線 | 滿足後只啟用本架構基準；不關閉 D-01–D-08，不把任何 ASM 或科學 gate 標 DONE |
| P-G0 | 可自 P0 開始；真實、受治理且經認證的研究流程符合 [G0](sai34/acceptance.md#21-g0--pre-lumerical-research-acceptance-gate) 全部條件才可另提接受 | 本次未接受。mock/catalog 只作軟體回歸；Agent A 尚未合併的證據獨立審查 |
| P-MODEL | 可自 P0 開始；按 C34-A1/A2 的離線建構、隔離與故障矩陣分 slice 實作 | 本次未實作。fake/mock 不授予 G1 真實 readback 或 G2 求解成功 |
| P-LICENSED | D-04 站點/OS/entitlements/worker 與執行預算、D-05 權利、D-06 執行 policy、D-02 適用數值協定先核准 | 對應 C34-A3；G1–G3、G7-SITE、G8 licensed 部分與原 TST-001；未授權／未執行 |
| P-PHYSICAL | D-02 獨立資料/精度/n/成功率、D-03 適用 warrant、D-08 用途接受先核准 | 對應 C34-A4；G4–G6/G9 與單站重現；未授權／未接受 |
| P-PORTABILITY | 只有聲稱跨 worker/站點時，另資格化第二 worker/目標站與相同重播 | G7-WORKER 與跨站分開；不回頭阻擋合法單站驗收；後續 solver/coupling 仍按 C34-A5 |
| P-FULL-RUNTIME | 全部適用 ASM 實作、標記測試、outcome ratchet、規格工具與 source inventory 的遷移經獨立 slice 驗證及明確核准 | DEFERRED；本次不改 parser/namespace/active 3.3 registry，不宣稱完整 3.4 執行覆蓋 |

G0 是真實 LLM 的授權前研究接受；G1–G9 是自主建模／數值／物理與相關治理接受。
這兩種接受不可互相代替。G7-SITE 與 G7-WORKER 分別出結果，同安裝重啟不能證明跨 worker，
同站多 worker 不能證明跨站。所有未執行的模擬仍明列，readiness 持續 false。

## 4. Requirements／tests／registry 相容

60 條既有需求及其 §26 Test IDs 完整繼承；18 條 ASM 義務以原 statement key／T-ASM-* planned ID
逐條對應 legacy 依賴、工作線、後期 gate、Owner 決策與 deferral。合計為 **60 條繼承＋18 條新義務**，
不是 78 個已實作／已測試項目。

舊 [registry](../normative_statements.yaml)、[milestones](../milestones.yaml) 與 3.3 parser 保留為
既有實作的 executable conformance profile。新 [activation.yaml](sai34/activation.yaml) 是分期 3.4
架構的正式 registry/對照，不把尚未存在的 T-ASM-* 註冊成已執行 tests。
每條 ASM 的 `tests: []`、`implementation_status: SPECIFIED` 與 `deferral_status: DEFERRED`
如實表示新增義務未完成；離線可開始不表示可略過其驗收。

兩個 profile 的檢查在 CI 並列：原 T-SPEC-001/002＋執行覆蓋 ratchet 保護歷史，candidate checker
保護批准來源，activation checker 核對映射、scope、deferral、分支隔離與 protected tree。
文件結構機器檢查不替代散文逐條審核；本次審查矩陣見變更影響紀錄。
之後把 ASM 納入 runtime namespace/traceability/outcome ratchet 的動作，是 P-FULL-RUNTIME 的
具名遷移義務，不能在實作時默默加入或假稱本次已完成。

## 5. 保留的 Owner Gates

D-01–D-08 全部仍 OPEN。本次額外授權僅覆蓋文件整合、分期啟用準備及上述兩條開發工作的
開始範圍；不自動核准特定資料、物理參數、精度、license、付費外送、擴大因果 authority 或部署。
A3 第二帳號、A9 稽核合併、A12 直接 SQL 權限仍須安全封口。同一自然人的第二帳號不具獨立
科研審查資格；人類帳號仍只有 ADMIN/MEMBER，project/reviewer/service identities 不增帳號角色。
SP 1.1.0 不啟用；M0a–M3 HARD-LOCK、M4 licensed TST-001 blocker 及歷史 canonical records 保留。

沒有 merge main、部署、正式資料操作、付費 API 或 licensed simulation。完整 science/product
接受需各自的證據與 Owner 授權，不能由架構啟用、文件 CI 或任何開發代理的報告推定。
