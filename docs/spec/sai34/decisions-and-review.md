# SAI 3.4 Candidate — Owner 決策、風險與批判性自我審查

版本：`3.4.0-candidate.1`。候選文件完成不等於規格獲准或研究平台驗收。
`READY_FOR_REAL_RESEARCH = false`

## 1. 尚待 Owner 決策

以下全部 **OPEN**；列出可審建議，不代表代替 Owner 裁決。review checkpoint：2026-11-20，
或 C34-A0/受影響 gate 前，以先到者為準。日期到期不自動同意，也沒有建立排程。

| ID | 需要決定的內容 | 建議與替代方案 | 阻擋 |
|---|---|---|---|
| D-01 | 接受 ASM 長期必達目標、3.4 啟用程序、候選 namespace/ADR 與能力邊界 | 建議：以核准模型族逐步自主；替代：只保留人工建模/掃描能力，則不滿足本次目標 | C34-A0；不能啟用規格或重開 HARD-LOCK |
| D-02 | CHARGE 模型族/權威參數/適用域、獨立 benchmark 與 observable 精度、n、成本與成功率門檻 | 建議：先選條件完整且有獨立量測的 PN 模型族；替代：先做解析/範例回歸，但只能接受軟體建構 | G3–G5/G9 正式驗收 |
| D-03 | 因果辨識與人工授權範圍；CWG 的 DISCRIMINATION、多原因、擴大 declarations 與 SP 1.1.0 未決項 | 建議：沿用既有已准範圍，超出即 review；替代：另開獨立科學審查擴大，不能在此靜默決定 | 新模型族的 G6；不阻礙原邊界內離線設計 |
| D-04 | 站點 Lumerical design/solve/HPC entitlement、OS/版本/worker、最大並行與費用 | 建議：先單一 CHARGE 合格 worker 與有限配額；替代：隔離遠端 license worker，先證網路/權限邊界 | C34-A3/A4；REQUIRES_LICENSE |
| D-05 | 範例/材料庫/文獻/量測的取得、使用、修改、封存與散布權 | 建議：只採權利明確且可封存依賴；替代：權利未知者僅留書目，不納入建構或 benchmark | 相關來源准入、重播與 G4 |
| D-06 | 容許自動改動範圍、不可逆動作、service/evaluator/reviewer 職責與強制簽核 | 建議：先核准狹窄數值/校準空間；替代：逐次核可較大物理變更，人工成本更高 | capability 啟用、G8/G9 |
| D-07 | 既有帳號稽核 A3（第二地址/兩人規則）、A12（DB 寫入角色事件）、監督紀錄粒度 | 建議：維持未決與可見，服務無 reviewer 金鑰；替代：另以安全 ADR 強化兩人規則/DB gate | 若宣稱跨人職責可信或擴大自動授權，先裁決；不自行修 runtime |
| D-08 | 研究就緒宣告的範圍、獨立 evaluator 與最終簽核人 | 建議：逐模型族/solver/條件接受且保留全部失敗；替代：只承認開發資格，持續 false | 任何 readiness 宣告；本次保持 false |

Reviewer 的 signed warrant 與 Owner 的規格核准為不同證據，不能互代。
提交/推送候選文件不構成這些決策的批准。

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
| 「完全自主」可能取消 P12/P16、CWG signed review | ASM-001 限定已核准 envelope；ASM-013/014 保留必要簽核與人工歧義 gate | D-01/D-03/D-06 OPEN，不修改現行規範 |
| builder `build_*` 會違反 3.3 四類工具動詞 | 將 construct 設為 provider 私有 typed protocol；公開工具沿用四動詞與舊 ID | 未分配新公開工具 ID |
| 歷史 VS-SP-001 以既有專案為輸入，不能證明首次建模 | 舊 replay 原封保留；新增 G1/G9 空白 workspace/未見案例 | licensed replay 與新能力各別未驗證 |
| 任意 generated script 即使加 sandbox 仍違反 P19 | 固定 compiler/operations、無自由 code 欄位、外來 active content 隔離 | provider 尚未實作；不能宣稱已防住 |
| 同範例/同建構器產生 reference 是循環驗證 | family split、獨立 evaluator、只把範例當 development，專家模型不是物理真值 | G4/G5 缺資料與 Owner 凍結門檻 |
| 用單一 convergence flag 或假定 measurement 永遠真 | 六層狀態、獨立數值研究、authority 偏序、reference 不可比/UNKNOWN 合法 | 精度數字未校準，不虛填 |
| 調 mesh 同時改 mobility/geometry 造成科學假設漂移 | 規則分類的 patch、分支 lineage、物理變更重新驗證與 review | 未實作 bounded loop |
| 以 license blocker 掩蓋 provider 還未寫 | gap 分開進度與環境軸，provider 為 SPECIFIED＋REQUIRES_LICENSE | 尚缺 compiler/provider/worker 與全真重播 |
| 修改 active registry 會默默重開既有 conformance/鎖定 | 凍結三個 active 檔案的 hash、候選 registry 零已實作 tests、ADR Proposed | 啟用前另作完整三件套/散文覆蓋審核 |
| 可重現性誤要求 binary 專案完全相同 | 固定 canonical inputs/operations；raw artifacts 各自 hash，數值依容差比較 | 真實跨 worker 尚未執行 |
| 「移除 coding agents」被誤解為禁用正常模型推理 | 發展工具與 ScientificLLM runtime 明確分離；模型只可輸出 typed proposals | G9 需 deployment-equivalent 證據 |
| 階段序列強迫先建模，破壞 cheap-first | 責任鏈可選擇不建模，凍結目的/比較後才執行 | 既有 planner 不變 |

## 4. 驗證證據的讀法

文件 checker 的成功只表示結構映射、基準保存與本地連結有效；不是 hard-MUST 散文完備證明。
既有 spec CI 證明 active 3.3 的 conformance/ratchet 沒被破壞；full suite/Backend profile
針對同一 final SHA 的軟體測試，沒有 Ansys license 與物理 holdout。
本次沒有新做正式研究、沒有 merge/deploy、沒有改 DB 或呼叫付費模型 API。

最終 commit 與 CI run 由交付回覆提供；對應 run 的 `head_sha` 才是結果適用版本。
