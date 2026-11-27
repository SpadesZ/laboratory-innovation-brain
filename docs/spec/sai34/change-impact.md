# SAI 3.4 Candidate — 版本變更與遷移影響

版本：`3.4.0-candidate.2`；相對 `SAI_3.3.md`（a1–a18）；本次修正基準 `61f6beba0fb6898a9d18cca9bb7e8b4005a9f51c`。
Candidate-only。`READY_FOR_REAL_RESEARCH = false`。

## 0. candidate.2 精確修正範圍

| 審查項目 | 受影響契約 | 結果與測試義務 |
|---|---|---|
| 授權前真實研究接受 | ASM-002/012/014/016/018、G0、C34-A2 | 新增 G0-A/L/S/B/P：認證、真實受治理 LLM、科學可用性、雙語正文/匯出、provenance 與未執行模擬；catalog/mock 不通過 |
| 科學內容雙語 | ASM-016、T-ASM-016、G0/G9 | 假說/預測/觀察/解釋/不確定度/結論/限制/匯出，完整語意與結構 parity；canonical records/hash/狀態保留 |
| 分期 Owner gate | ASM-014/018、C34-A0–A4、ADR-0013 | 明列核准的架構/slice 才能離線開發；license/物理 benchmark/部署在適用 gate 前核准，本次只改文件 |
| 重現範圍 | ASM-017、G7、T-ASM-017、C34-A3–A5 | G7-SITE 單站與 G7-WORKER 跨 worker 各別接受；不以缺第二 worker 阻擋單站，不從單一安裝宣稱跨站 |
| 帳號與治理 | ASM-014、G0、ADR、D-07 | 人類角色只有 ADMIN/MEMBER，其他 project/reviewer/service 是分開的授權概念；A3/A9/A12 保持 OPEN |
| 審查處置紀錄 | D-01–D-08、candidate registry、ADR | 原樣保留審查的同意/部分/條件/暫緩性質與 Human Owner 同意方向；正式狀態仍 OPEN，無啟用/部署/readiness 變更 |

保留原架構、18 個 requirement/statement keys 與 T-ASM-* planned IDs，沒有新增 runtime 或第 19 條需求。

## 1. 變更摘要

| 原規格落點 | 候選增補 | 影響/保留 |
|---|---|---|
| §1–4、§21 產品目標 | ASM-001/002：完成品自行首次建模、執行、驗證與細化 | 擴大長期目標；不把 3.3 的「不是跑批工具」解讀成禁止有治理的建模能力；不強迫每次研究跑模擬 |
| §6、§17.20/21 外部來源 | ASM-003/010：來源 family、權利分項、參數來源與 sealed holdout | 重用 ExternalSourceAdapter/SourceWork/occurrence；公開不等於可執行/散布 |
| §10、§17.4、§24 DomainPack | ASM-004–007/015/017：typed model、建構器、readback、專用 provider/worker | 不修改核心物理欄位，不放任意 script，不增第五類公開工具，不重用/改名歷史工具 ID |
| §9、§15、§17.19.2 | ASM-008–011：六層認知驗收、獨立 baseline、收斂/uncertainty/refinement | 門檻由校準/Owner 凍結；保留 cost vector、多目標與 least-cost sufficient selection |
| §8、§12、§14、CWG V1.1 | ASM-012–014：准入、warrant、必要人工介入 | event-sourced belief、signed review、ACL/外送/budget/ReviewQueue 均保留；不以自主性取消簽核 |
| UX-001–007、§22、§26 | ASM-016/018：科研內容/匯出雙語、G0 與六層狀態、licensed 外部驗收、roadmap | 不新增第六類 error、不用 mock 證明 G0 或物理成功、不改 M0a–M8 簽核 |

## 2. 本次變動的範圍

candidate.1 新增候選規格、架構/路線圖、驗收、差距、風險/Owner 清單、提議 ADR、候選 registry
與離線文件 checker/CI。candidate.2 修正上述契約與 checker，保留原 CI 配線，更新狀態導覽。
沒有新增 Runtime API、DB migration、solver adapter、模型建構程式、依賴或 paid service。

`docs/spec/SAI_3.3.md`、`docs/normative_statements.yaml`、`docs/milestones.yaml` 保持原始 bytes。
active requirement/test 數量與 §26 mapping 不變。候選的 ASM 命名空間、planned tests 及
candidate milestones 不進 active parser；不能由綠燈宣稱未實作需求已覆蓋。

## 3. 規格啟用後的實作順序（本次未執行）

1. C34-A0 可先以具名限範圍架構核准進行符合 active 3.3 的離線 slice；全面啟用另需接受 ADR、凍結 3.4 全量版本/inventory、同步 active 三件套及人工覆蓋審核。後期決策分期收取，不默認授權。
2. 新 typed model/envelope 與 DomainPack payload 以獨立版本引入；schema/單位/權利/假設拒絕案例先行。
3. immutable build/patch/validation refs 掛接現有 artifact/Job/Run；新 extension table 另有 migration、重入/升級演練與 rollback 設計。
4. fake provider 完成軟體/安全 gate 後實作 licensed adapter；任何 vendor SDK import 只在選配 provider，保留 AGT-007 的免 license 核心測試。
5. 擴大精度/物理與自主驗收，再各別加入 MODE/FDTD/INTERCONNECT/coupling。

既有 Run 沒有 model-spec refs 時如實標為 legacy/imported；不回填不存在的建構史。
新 provenance 不能改變既有 canonical decision snapshot bytes；歷史可重播，新的 science
policy 僅以具版本的事件/決定作用。append-only correction/撤回不刪原記錄。

未來 rollback 先停新 capability/worker，再保留新資料為唯讀、切回舊 reader；不能靠 DROP
extension tables 或回滾 migration 刪掉新科研紀錄。若舊版不能理解新狀態，明示 unsupported，
不把它映射為已驗證。正式 migration 方案仍須對具體 schema 單獨審查。

## 4. 必要回歸與驗收依賴

| 變更面 | 必要證據 |
|---|---|
| core/domain extension | EXT-001/ToyDomain、移除 solver/plugin 啟動、無 core/vendor import |
| job/cost/ACL | 既有 resource-demand/job-scope/预算/route 矩陣，加新 worker、撤權、late callback/fencing 反例 |
| evidence/warrant | SIM-001/002、同 extractor 模擬/量測、project occurrence、Causal Warrant Gate、signed review/replay/歷史快照 |
| source/benchmark | 家族去重、active-content、版權分項、sealed oracle 與污染反例 |
| UI/report | UX-001–007、八類科研正文/匯出兩語完整性、canonical hashes/狀態一致、分級/續跑、UNKNOWN/未執行模擬 |
| 真實授權前研究 | G0：authenticated genuine governed LLM、獨立科學/雙語審查與 provenance；fake/catalog 不能替代 |
| 新建構能力 | G1–G9，G7-SITE/G7-WORKER 分開；其中 fake/mock 與 licensed 證據分列 |

文件 checker 只查：基準 hash、候選義務/registry/test plan/gate 的映射、roadmap 分配、
deferral/Owner 狀態與本地連結。它不進行散文完備審核，也不做 solver 或物理驗收。
