# SAI 3.4 Candidate — Owner 決策、風險與批判性自我審查

版本：`3.4.0-candidate.2`。候選文件完成不等於規格獲准或研究平台驗收。
`READY_FOR_REAL_RESEARCH = false`

## 1. 尚待 Owner 決策

以下全部 **OPEN**。來源為 2026-10-21 使用者提供的
「SAI 3.4 — Independent Chief Auditor D-01～D-08 Review」，審查基準
`61f6beba0fb6898a9d18cca9bb7e8b4005a9f51c`，verdict 為 CONDITIONAL PASS。
同一訊息末尾 Human Owner 明示「我human同意上述」，已記錄對八項方向、條件及文件修正要求的同意。
該訊息同時明定只繼續文件修正、需要明確授權的決策仍 OPEN，不改為 APPROVED/ACCEPTED/CLOSED。
因此本紀錄沒有授予 runtime 開發、規格啟用、權限修改、license 使用、部署或研究就緒簽核。
review checkpoint：2026-11-20 或各項適用 milestone 前；不再一律要求所有後期決策在 A0 結案。
日期到期不自動同意，也沒有建立排程。以下是審查建議的結構化轉錄，不擴張其界線。

| ID | 審查者提議處置 | 條件與未決事項 | 正式狀態/適用 gate |
|---|---|---|---|
| D-01 | 同意方向：自主首次建模、不依賴外部 Coding Agent | 正式啟用待規格修訂；離線開發另需明列範圍的架構/slice 核准 | OPEN；C34-A0 的限範圍核准與 §11 全面啟用分開 |
| D-02 | 部分同意：首個模型族採 CHARGE／PN 接面 | 精度、樣本數、成功率等依獨立資料與用途再核准，不虛設門檻；權威參數與適用條件仍需確認 | OPEN；C34-A3 的數值協定、C34-A4 的 G4/G5/G9；不擋無關離線 slice |
| D-03 | 暫緩擴大：保留 CWG V1.1 | 不啟用 SP 1.1.0，不自動擴張 DISCRIMINATION 或多原因確認 | OPEN；A0 明定保留邊界，擴張另審，新模型族 G6 依已准範圍 |
| D-04 | 同意規劃：先支援單一合格 CHARGE worker | license、OS、HPC 額度到實驗室實查；第二 worker/站點另驗，不阻擋單站驗收 | OPEN；C34-A3 的站點資格與執行預算 |
| D-05 | 原則同意：合法使用權的公開範例可作開發參考 | 每個來源分別核對修改/執行/散布權；獨立測試資料不得污染；材料/量測依賴仍逐項確認 | OPEN；A0/A1 用到的 fixture 權利、實際來源准入及 G4/G7 |
| D-06 | 有條件同意：受控數值細化與核准範圍內參數變更 | 材料模型、物理假設及超出範圍修改另行審查；具體欄位/上限/權限 policy 尚待核准 | OPEN；A0 離線邊界，實際 capability/執行前另核准 |
| D-07 | 部分保留：可由唯一 ADMIN 管理，另有獨立科研審查資格與完整不可竄改稽核 | A3 第二帳號、A9 稽核合併、A12 直接 SQL 權限仍須安全封口；不硬性要求所有成員核准都由兩位 ADMIN；同一自然人的第二帳號不算獨立科研 reviewer | OPEN；正式部署或任何聲稱身分隔離已成立前驗證；不改 runtime |
| D-08 | 同意原則：依模型族、solver、有效條件分別驗收 | license 與物理驗證未完成前維持 false；獨立 evaluator、用途範圍與最終接受另需記錄 | OPEN；C34-A4 及任何部署/readiness 宣告 |

Reviewer 的 signed warrant 與 Owner 的規格核准為不同證據，不能互代。
提交/推送候選文件不構成這些決策的批准。

### 1.1 分期授權與帳號界線

C34-A0 的核准對象是具體離線 slice 的架構與無副作用範圍，不是把 D-01–D-08 全部結案。
本次 Human Owner 的同意連同「只改文件」限制保留；不把它當成開始 runtime 開發的授權。
後續核准需留下決策/ADR/policy 版本、actor、時間、範圍、允許動作、排除項與證據。
物理 benchmark、站點 entitlement 及部署/readiness 各在 D-02/D-04/D-08 對應 gate 裁決。

人類帳號角色只有 ADMIN、MEMBER。project membership/OWNER、獨立科學 reviewer 授權、
非人類 worker service identity 是另外的治理概念，不增加帳號角色，也不相互授權。
ADMIN 的最高管理權不能推出 DB 服務角色可無限制直接 SQL 改使用者角色；本修訂不替
A12 選定實作。不能把同一自然人控制的兩帳號視為兩個獨立科學審查者；此身分隔離要在
正式部署前驗證。A3/A9/A12 的 OPEN、具體限制與尚未完成證據不因方向同意而消失。

## 2. 候選風險登錄

此表增補 3.3 §20；不取消既有風險，尤其 R-1（license）與獨立 ground-truth 依賴。

| ID/嚴重度 | 風險、訊號與影響 | 防線與驗收 | 責任/殘餘 |
|---|---|---|---|
| R34-01 P0 | 流程暗中需要開發 agent，不能獨立運作 | G9 封鎖 agent 可執行檔/網路與工作階段，記錄 process/人工操作，空白建模 | 產品維護者；目前 SPECIFIED |
| R34-02 P0 | script injection、專案 active content、path escape 越權 | fixed typed compiler、禁任意 code、sandbox、拒絕 fixtures；G1/G8 | provider 安全負責人；vendor process 自身攻擊面仍需資格化 |
| R34-03 P0 | 範例/專家模型/holdout 互相污染形成循環驗證 | family DAG、權限隔離、seal/scorer hashes、揭露後退役；G4/G9 | 獨立 evaluator；隱性共享資料仍需人工審查 |
| R34-04 P0 | 假設/validator 被細化器改動以做出想要答案 | immutable patches、policy-classified changes、只看 development evidence；G3/G6/G8 | DomainPack 科學 reviewer；模型失配允許棄答 |
| R34-05 P0 | 擬合與趨勢符合被升格為因果確認 | CWG/AuthorityPolicy/Decision/event、rival 辨識、不得自鑄 grant；G6 | 科學 Owner；D-03 未決 |
| R34-06 P1 | 單位、接觸/邊界/材料預設或 per-length 錯誤造成看似合理數值 | typed fields、權威來源、readback、獨立 units/normalization fixtures；G1/G3/G5 | DomainPack/provider；文獻缺參數仍 BLOCKED |
| R34-07 P1 | solver converged 但 mesh/外域/步階未收斂、多解未識別 | 三層獨立研究、守恆、分支/初值敏感度與 uncertainty；G3/G5 | 數值驗證負責人；站點 license 依賴 |
| R34-08 P1 | license 不足、GUI/engine entitlement 誤判、版本不可重播 | qualification matrix、實際 checkout、有限等待/對帳；G2/G7/G8 | license 管理者；不保證 seat 即時可用 |
| R34-09 P1 | crash/retry/晚回覆重跑或超支，孤兒程序仍計費 | reserve/settle、lease fencing、attempt ledger、取消/對帳；G8 | worker 維護者；外部執行不能保證 exactly once |
| R34-10 P0 | 跨 project refs/session/credentials/答案流出 | 現有 ACL/occurrence＋worker/evaluator scope、撤權測試；G8 | 安全 Owner；不宣稱 OS 管理員不可繞過 |
| R34-11 P1 | 模型形式與資料不足，專家相符被當作 ground truth | 獨立實測/不確定度、可比條件、專家只當 baseline；G4/G5 | D-02；資料不足不得承諾精度 |
| R34-12 P1 | CHARGE 通過後外推其他 solver 或 multiphysics | 個別 qualification、field-transfer/守恆/coupling gate；G1–G9 重做適用部分 | solver 維護者；C34-A5 DEFERRED |
| R34-13 P1 | Candidate 被誤當 active contract，mock/CI 被誤當物理認證 | 雙 registry、基準 hash、status 導覽、各 gate evidence class；文件 checker | 規格維護者；仍需人工散文覆蓋審核 |

## 3. 批判性自我審查

本節為本次文件的自我審查，**沒有聲稱獨立審查或 Owner acceptance**。

| 發現 | 本候選的處置 | 剩餘狀態 |
|---|---|---|
| 「完全自主」可能取消 P12/P16、CWG signed review | ASM-001 限定已核准 envelope；ASM-013/014 保留必要簽核與人工歧義 gate | D-01/D-03/D-06 方向/條件已收到 Human Owner 同意，但正式決策仍 OPEN，不修改現行規範 |
| builder `build_*` 會違反 3.3 四類工具動詞 | 將 construct 設為 provider 私有 typed protocol；公開工具沿用四動詞與舊 ID | 未分配新公開工具 ID |
| 歷史 VS-SP-001 以既有專案為輸入，不能證明首次建模 | 舊 replay 原封保留；新增 G1/G9 空白 workspace/未見案例 | licensed replay 與新能力各別未驗證 |
| 任意 generated script 即使加 sandbox 仍違反 P19 | 固定 compiler/operations、無自由 code 欄位、外來 active content 隔離 | provider 尚未實作；不能宣稱已防住 |
| 同範例/同建構器產生 reference 是循環驗證 | family split、獨立 evaluator、只把範例當 development，專家模型不是物理真值 | G4/G5 缺資料與 Owner 凍結門檻 |
| 用單一 convergence flag 或假定 measurement 永遠真 | 六層狀態、獨立數值研究、authority 偏序、reference 不可比/UNKNOWN 合法 | 精度數字未校準，不虛填 |
| 調 mesh 同時改 mobility/geometry 造成科學假設漂移 | 規則分類的 patch、分支 lineage、物理變更重新驗證與 review | 未實作 bounded loop |
| 以 license blocker 掩蓋 provider 還未寫 | gap 分開進度與環境軸，provider 為 SPECIFIED＋REQUIRES_LICENSE | 尚缺 compiler/provider/worker 與全真重播 |
| 修改 active registry 會默默重開既有 conformance/鎖定 | 凍結三個 active 檔案的 hash、候選 registry 零已實作 tests、ADR Proposed | 啟用前另作完整三件套/散文覆蓋審核 |
| 可重現性混合單站與跨 worker，過早阻擋單站驗收 | G7-SITE 與 G7-WORKER 各別記錄；跨站主張另需目標站點資格 | 單站、跨 worker、跨站都未在本次執行；缺第二 worker 不否定單站結果 |
| 「移除 coding agents」被誤解為禁用正常模型推理 | 發展工具與 ScientificLLM runtime 明確分離；模型只可輸出 typed proposals | G9 需 deployment-equivalent 證據 |
| 階段序列強迫先建模，破壞 cheap-first | 責任鏈可選擇不建模，凍結目的/比較後才執行 | 既有 planner 不變 |
| 授權前只驗 mock，缺少有用的真實 LLM 研究接受 | 增加獨立 G0-A/L/S/B/P；真實模型、認證、科學 rubric、provenance 與未做模擬皆為必要條件 | G0 未執行，不由本次文件 CI 代替 |
| ASM-016 只要求 UI/狀態語系，未保證科研正文 | 擴至八類科學內容及所有提供的匯出，要求 semantic coverage/雙語審查、canonical hash 不變 | 翻譯不是新 evidence，也不改 machine-verifiable state |
| A0 以未定 license/精度/部署決策阻擋所有離線工作 | 改為範圍明確的架構核准，後期決策在適用 gate 前收取 | 沒有明確離線 slice 核准時仍不能開發；本次只改文件 |
| 把 reviewer、project OWNER 或 worker 誤寫成帳號角色 | 明列 ADMIN/MEMBER；其他皆為分開的治理概念，不互推權限 | A3/A9/A12 保持 OPEN，獨立性不能靠第二帳號湊數 |
| 把審查者建議或 Human Owner 同意方向擴大成所有決策已批准 | 逐項轉錄來源、方向同意與限制；八個正式狀態均 OPEN | 無規格啟用、runtime、部署或 readiness 授權 |

## 4. 驗證證據的讀法

文件 checker 的成功只表示結構映射、基準保存與本地連結有效；不是 hard-MUST 散文完備證明。
本修訂另用結構規則及破壞反例檢查 G0 不接受 mock、完整科學雙語範圍、分期 gate、
單站/跨 worker 分離、僅兩種人類帳號角色與 OPEN 決策；仍由本節人工逐項檢查規範矛盾。
既有 spec CI 證明 active 3.3 的 conformance/ratchet 沒被破壞；full suite/Backend profile
針對同一 final SHA 的軟體測試，沒有 Ansys license 與物理 holdout。
本次沒有新做正式研究、沒有 merge/deploy、沒有改 DB 或呼叫付費模型 API。

最終 commit 與 CI run 由交付回覆提供；對應 run 的 `head_sha` 才是結果適用版本。
