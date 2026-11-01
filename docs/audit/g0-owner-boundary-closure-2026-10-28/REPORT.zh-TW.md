# G0 Owner 邊界與離線可靠性收尾報告

日期:2026-11-01
分支:`g0-owner-boundary-closure`
起點:`g0-evidence-auth-cost-closure` @ `4497242`
狀態:**工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。**

| 類別 | 本次狀態 |
|---|---|
| 工程成功(離線測試、CI) | 見 §6 |
| 真實 LLM 研究表現 | **沒有執行** |
| 盲測 | **沒有執行**(只準備了協定與工具) |
| 物理驗證 | **沒有** |

成本:零。沒有付費 API、沒有付費 runner、沒有 Lumerical、沒有呼叫任何真實模型服務。
沒有改正式資料、沒有合併 `main`、沒有部署、沒有啟用 G0、沒有代替 Owner 做決定。

## 1. 提交(都由 SpadesZ 署名,沒有 AI 署名)

```
4497242  (起點)
055434b  盲測 runner、環境紀錄、變異測試證據對帳
471dc2d  011t:預算/單價/斷路只歸 Owner;沒有預算的遠端請求預設拒絕
f43907a  互動簽章金鑰生命週期;011u 帳號變更的雜湊鏈紀錄(A12 仍開放)
45a9454  011s:篩檢後支持需要宣告的種類、預先授權、新的血緣;operator 指令
f40a979  只用本機模型的即時評估,先要 Owner 的免費宣告
9cbeb9f..eefcad5  補 011s/011t/011u 的對抗測試與變異項目;Owner 決定、交接
aff855e  最後一次完整變異測試的證據檔
3062dca  狀態檔、完整測試證據、本報告
12d86d8  CI 以非 root 執行時,金鑰測試用一個 operator 擁有的信任檔替身;用目前的直譯器
<最後>   12d86d8 的完整變異測試證據、狀態檔、本報告
```

## 2. 優先 1:金額上限真的能執行

文件:`spend-administration.md`。

先證明漏洞(修改前 12/14 個對抗測試失敗,`tests/integration/test_g0_spend_admin_postgres.py`):
服務角色可以調高自己的上限、關閉斷路、宣告單價、偽造寫入旗標;
沒有預算的遠端請求會送出;有預算時本機代理不計量。

修正(`migrations/011t_llm_spend_administration.sql`):
- 新角色 `lab_brain_spend_admin`(NOLOGIN)。只有它的成員能建立預算、宣告單價與免費端點、改上限、關斷路。
- 服務角色只能預留、結算、保留。寫入旗標只在擁有者的函式裡有效,不能偽造。
- 遠端請求沒有 guard → 送出前拒絕。沒有開關可以關掉。
- 有預算時本機也計量;真正免費的本機模型要 Owner 宣告。
- 即時評估只用本機模型時,也要 Owner 的免費宣告(`install_local_free_guard`)。

剩下的例外(Owner 決定 A3):完全沒有預算時,本機請求不計量。

## 3. 優先 2:011p 的前瞻證據漏洞

文件:`prospective-evidence.md`。

先證明漏洞:在 011p 生效時,11 種不該被接受的依據都被接受為支持
(`tests/e2e/test_g0_prospective_evidence_postgres.py`)。包括:
擷取時間未知的量測檔、從 2020 年資料衍生的輸出、血緣循環、服務角色可以改 capability 種類、
規則檢查重讀被篩檢讀過的同一份設計檔、沒有人預先授權的檢查。

修正(`migrations/011s_prospective_evidence_authorization.sql`):
- **種類**:`capability_declarations` 只有資料表擁有者(migrator)能寫,內容要和 domain pack 的程式完全一致(資料庫重算雜湊)。已宣告的 capability 不能再改種類。
- **擷取時間**:經驗資料的擷取時間是 NULL → 拒絕(未知不是新的)。
- **血緣**:`derived_from` 與前一版本,遞迴最多 16 層;碰到篩檢輸出、假說之前的資料、未知時間、未登記的 artifact、循環或太深 → 拒絕。
- **預先授權**:篩檢後的驗證必須有一個專案中的 HUMAN 成員,在假說之後、檢查執行之前,為「這個假說、這個 capability、這個預測」登記授權;Job 在 QUEUED 時綁定。時間用資料庫時鐘。
- **合法的路**:有授權、新資料、新血緣的量測,可以支持篩檢後假說(端到端測試)。
- **保留**:回溯自我支持仍然不可能。舊證據仍可記錄為 CITES,也仍可支持篩檢前的假說。
- 評估收集器多了 4 個事實(`unknown_capture_time`、`lineage_before_hypothesis`、`unclassified_capability`、`unauthorized_verification`),用同一組 SQL 函式讀,所以 guard 被關掉也會被報告。
- scorer:執行沒有存提示詞時(`prompts_captured: false`),輸入洩漏記為「未驗證」,不是「沒有洩漏」。
- operator 指令:`lab-brain admin declare-capabilities`(只有資料表擁有者可以;服務角色被拒絕)。

## 4. 優先 3:簽章金鑰生命週期與 A12 邊界

文件:`key-lifecycle.md`、`a12-boundary.md`。

- 先證明缺口(`evidence/key_lifecycle_gaps_before.log`):金鑰權限太寬、沒釘選、已退役、在 repo 裡、沒有撤銷 → 都能啟動。
- 修正:`lab-brain interaction-key generate|pin|retire|revoke|check`;啟動檢查拒絕上面每一種情況。
- A12(用 migrator 或超級使用者直接改 SQL):**沒有解決**。`011u` 讓帳號、成員、帳號事件的每一個變更都留下雜湊鏈紀錄;`lab-brain admin account-audit` 找出「沒有帳號事件解釋」的變更,並印出鏈頭。
  這是**偵測**,不是**阻止**:擁有者或超級使用者仍可關掉 trigger 或改寫紀錄;鏈頭要存到資料庫外才有用。

## 5. 優先 4:證據對帳與零成本盲測協定

- 對帳:`evidence-reconciliation.md`。兩份舊報告的「全部抓到」是第一輪加重跑合併計算,重跑沒有證據檔;已在兩份報告加上勘誤。規則:之後只用一次完整執行加證據檔。
- 盲測協定:`docs/evaluation/G0-blind-evaluation-protocol.zh-TW.md`(本機模型、零成本、評估者與實作者分開)。
- 工具:`scripts/g0_eval_environment.py`(記錄並比對 commit、schema、套件、模型;拒絕遠端模型與未提交的工作區)、`lab_brain.evaluation.runner.run_blind`(只跑凍結的套件與案例;崩潰也留在分母)。

## 6. 驗證

| 檢查 | 結果 | 證據 |
|---|---|---|
| ruff、ruff format、mypy | 全部通過(mypy:282 個檔案) | 本機 |
| 完整 PostgreSQL 測試(新建資料庫,81 個 migration,`12d86d8` 程式) | **3475 passed, 4 skipped, 0 failed**(之後執行 `update_status.py`) | `evidence/full-postgres-suite.log` |
| 變異測試,第一次完整執行(`cfb7e19`) | 857/861 | `evidence/mutation-full-861-first-run-cfb7e19.log` |
| 變異測試,完整執行(`eefcad5`) | 861/861 | `evidence/mutation-full-861-final-eefcad5.log` |
| 變異測試,最後一次完整執行(`12d86d8`,程式最後一次改動之後) | **861/861** | `evidence/mutation-full-861-final-12d86d8.log` |
| CI | 見最後的推送;`3062dca` 的發現見下面 | GitHub Actions |

CI 的發現(`3062dca`):CI 用一般使用者執行測試。金鑰檢查規定「信任檔不能由執行網頁層的使用者擁有」(只有 root 例外),
所以以一般使用者建立的測試信任檔都被拒絕。這是規則正確,不是程式錯誤。
修正只改測試:`key_lifecycle._owner()` 是讀檔案擁有者的唯一函式;`tests/trust_owner.py` 讓測試把信任檔當作另一個 operator 擁有。
真正讀擁有者的測試標記 `real_owners`,另外新增「執行者自己擁有的信任檔被拒絕(root 除外)」的測試。
以一般使用者 `tester` 在本機重跑:通過。`12d86d8` 的 CI:全部測試通過,只有狀態檔過期(本次提交修正)。

變異測試的發現與修正(都在第一次完整執行之前或之後,都有紀錄):
- 舊的變異資料庫沒有 `schema_migrations`,所以角色測試在 setup 就出錯,被誤算為「抓到」(14 項)。
  修正電池後,這些規則裡有 21 項其實沒有測試;都補了測試(`tests/e2e/test_g0_prospective_authorization_postgres.py`、
  spend 與 A12 的「權限誤授時 trigger 仍然擋住」測試)。
- 第一次完整執行有 4 項存活:011s 取代了 011o 的 guard 函式(3 項,改指向 011s 的同一檢查),
  以及收集器的開始時間規則被 011s 的種類規則重複涵蓋(1 項,把測試改成只有開始時間是舊的)。
- 011p 規則 (h) 的兩項移到 011s(011s 自己判斷 (h))。

以前的 795 項,加上新的 68 項,減去移走的 2 項 = 861 項。

## 7. 工程有效 vs 科學有效

- 工程:上面每一條規則都有先失敗、後通過的測試,以及能抓到規則被關掉的變異測試。
- 科學:**沒有任何新的科學結果**。一個被接受的支持只代表「紀錄上看起來是預先登記、新的、獨立的檢查」;
  紀錄的真實性取決於寫入者(擷取時間、媒體類型、血緣都由寫入者提供)。不是物理確認。
- 篩檢後假說在目前產品中,要等 Owner 登記宣告並由真人授權後,才可能得到前瞻支持。

## 8. 剩餘風險

1. A12 仍開放(偵測不阻止)。migrator 的權限就是宣告種類與金額管理的信任根。
2. 授權的「人」只由資料庫斷言,沒有簽章;有服務角色權限的人可以替真實成員寫授權。
3. 寫入者提供的擷取時間、血緣、媒體類型無法獨立驗證;沒宣告血緣的複本偵測不到。
4. 沒有預算時本機請求不計量(Owner 決定 A3)。服務商是否遵守 `max_tokens` 未確認。
5. 沒有真實 LLM 結果、沒有盲測、雙語語意品質 NOT VERIFIED、沒有物理驗證。
6. 本機 PostgreSQL 16;CI 用 pg17。

## 9. Owner 決定

完整清單:`docs/implementation/G0-owner-decisions.zh-TW.md`(A 金額、B 前瞻驗證、C 金鑰、D A12、E 評估、F repo)。
G0 是否通過只能由獨立審查決定。本報告**不**宣稱 G0 PASS。
