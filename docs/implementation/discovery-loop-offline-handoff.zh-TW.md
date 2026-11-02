# Discovery Loop v0(離線)交接

日期:2026-11-01(第 1–9 節);2026-11-02 評估精煉(第 10 節)
分支:`discovery-loop-offline`,基底 `58c68be`(`g0-owner-boundary-closure`)。沒有 push。
評估精煉分支:`discovery-independent-evaluation`,基底 `118a4ac`(本分支的最後一個 commit)。沒有 push。
狀態:工程候選。`READY_FOR_REAL_RESEARCH` 仍為 false。G0 仍為 NOT PASSED。

## 1. 這是什麼

- 一個離線的「發現迴圈」。它補上現有驗證迴圈缺少的步驟:
  - 只提出能被可用實驗區分的機制;
  - 記錄沒有任何存活假說能解釋的觀測(異常),並先用事先登記的重測檢查;
  - 所有假說都失敗時,重新框架,但不刪除失敗紀錄;
  - 依「每單位成本的區分度」選實驗,預算固定;
  - 無法區分時明確停止。
- 它**永遠不產生 CONFIRMED**。最好的結果是「存活,等待 Causal Warrant Gate」。
- 設計細節:`docs/implementation/discovery-loop-offline.md`。
- 報告:`docs/audit/discovery-loop-offline-2026-11-01/REPORT.zh-TW.md`。

## 2. Commit

| commit | 內容 |
|---|---|
| `bc3bb9f` | 引擎 `src/lab_brain/discovery/`、微環目錄、單元測試 |
| `c92e7df` | `scripts/discovery_benchmark.py`(組合根)、`pyproject.toml` 只對這個腳本豁免 §24.2 匯入禁令 |
| `31cca35` | 凍結的證據(在 `c92e7df` 產生)、凍結檢查測試、設計文件、報告 |
| `b3bbb55` | 只修正微環目錄 docstring 裡的類別數量 |
| `ccd562f` | 在 `b3bbb55` 重新凍結證據:結果檔逐位元相同,只有來源雜湊與 commit 改變 |
| (最後一個) | 本交接文件、重新產生的 `IMPLEMENTATION_STATUS.md` |

目前證據的 `manifest.json` `code_commit` 是 `b3bbb55`。評估種子第一次執行是在 `c92e7df`。

## 3. 檔案

- 引擎:`src/lab_brain/discovery/{model,catalog,numerics,forward,distinguish,protocol,loop,baselines,handover,worlds,metrics,benchmark}.py`
- 情境:`src/lab_brain/domains/silicon_photonics/discovery_catalog.py`(摘要值鎖定;沒有裝進產品;沒有新增條件 schema 欄位)
- 腳本:`scripts/discovery_benchmark.py`(`--check` 會重跑並逐檔比對)
- 測試:`tests/unit/test_discovery_{numerics,distinguish,loop,metrics,governance,benchmark}.py`、
  `tests/e2e/test_discovery_benchmark_frozen.py`、`tests/discovery_fixtures.py`
- 證據:`docs/audit/discovery-loop-offline-2026-11-01/evidence/`

## 4. 測試指令與結果

全部用主 checkout 的 venv,`PYTHONPATH` 指向本 worktree 的 `src`。

| 指令 | 結果 |
|---|---|
| `ruff check src tests scripts` | All checks passed |
| `ruff format --check src tests scripts` | 599 files already formatted |
| `mypy src` | Success: no issues found in 296 source files |
| 新增的離線測試(6 個單元檔 + 凍結檢查) | 100 passed(97 單元、3 e2e) |
| 全部非 PostgreSQL 測試(最終 tree) | 2376 passed, 1203 skipped(PostgreSQL 等閘門) |
| 全部測試 + PostgreSQL(新建並 migrate 的 `lab_brain_disc_full`,81 個 migration,`--status` 冪等) | 3575 passed, 4 skipped(本地模型、Lumerical、網路、Windows 認證);19 分 33 秒。在 `31cca35` 執行;之後只改了 docstring 與證據的出處欄位 |
| `python scripts/discovery_benchmark.py --check` | evidence is current |
| `python scripts/check_commit_messages.py --tip HEAD` | no AI authorship found |
| `python scripts/rebuild_obligation_inventory.py --check` | 84 occurrences, in sync |
| `python scripts/update_status.py` 然後 `--check`(用 PostgreSQL 全套的報告) | 重新產生;`IMPLEMENTATION_STATUS.md is up to date`(含 `--requirements-only`)。測試清單 3479 → 3579 |
| `python scripts/verify_environment.py` | 執行完成(只報告環境) |

## 5. 結果摘要(預算 12,200 個合成世界)

| | B0 單一假說(不是 LLM) | B1 現有 LIB 風格 | B2 LIB + Discovery |
|---|---|---|---|
| 正確結果率 | 0.080 [0.050, 0.126] | 0.310 [0.250, 0.377] | 0.890 [0.839, 0.926] |
| 錯誤發現率 | 0.370 [0.306, 0.439] | 0.250 [0.195, 0.314] | 0.010 [0.003, 0.036] |
| 平均花費 | 1.13 | 1.94 | 7.83 |
| 每個正確結果的花費 | 14.06 | 6.24 | 8.79 |

B2 在效率上**沒有**贏過 B1。只有雜訊的世界 B2 只答對 11/25(其餘停止,沒有錯誤宣稱)。
B2 有 2 次錯誤發現:漏掉弱的第二效應一次;把小幅度的耦合間隙偏差當成「只有雜訊」一次。

## 6. 交給 Causal Warrant Gate 的方式

- Gate 離線無法呼叫。迴圈只交出 `GateHandover` 封包,狀態永遠 `PENDING_CAUSAL_WARRANT_GATE`。
- 封包對應 Gate 的輸入:候選類別、對手(狀態、反駁依據、最能區分的實驗)、
  每個成員登記後通過的觀測、從未考慮的已宣告機制、未解決的異常、可拆開類別但不可用的實驗。
- `draft_certificates` 產生未收錄的核心 `Hypothesis` 憑證;不產生 `Prediction`。
- 封包裡的任何東西都**不**滿足 Gate 的要求:§8 收錄、OutcomeSpace 綁定、新的前瞻證據(011s)、
  DOMAIN 或簽章 REVIEW 授權、`ConfirmationRule.standing`(012p)。

## 7. 沒有改的東西

- 沒有 migration。沒有寫資料庫(除了測試自己新建的 `lab_brain_disc_full`)。
- 沒有碰平行分支的檔案:`scripts/migrate.py`、`llm_runtime/spend.py`、`evaluation/{runner,environment}.py`、
  `migrations/011s*`、`security/reviewer_identity.py`、`docs/spec_issues/`。
- 沒有改 `lab_brain/evaluation/` 的任何檔案(那裡的來源雜湊被凍結的評估 manifest 使用)。只匯入 `stats.wilson`。
- 沒有放寬任何既有規則或測試。唯一的設定變更:`pyproject.toml` 讓 `scripts/discovery_benchmark.py`
  這一個檔案豁免 TID251,理由寫在旁邊;引擎仍在禁令下,且有結構測試。

## 8. 合併注意

- 與 `g0-reliability-authenticity-closure` 可能衝突的只有 `IMPLEMENTATION_STATUS.md`(兩邊都會重新產生)
  和 `pyproject.toml`(只新增一行 per-file-ignore)。合併後重跑 `python scripts/update_status.py` 即可。
- 凍結檢查測試會在引擎或情境來源改動時失敗。這是故意的:改了就要重跑
  `python scripts/discovery_benchmark.py` 並一起提交證據。

## 9. Owner 決策(詳見報告第 8 節)

1. 是否接進研究流程,以及封包如何轉成 Gate 輸入。
2. 微環目錄是否成為產品領域知識(需要校準與審查)。
3. 嚴格度與成本的取捨。
4. 只有雜訊時「停止不宣稱」是否可接受。
5. 是否安排不同作者的獨立盲測。
6. 擴充是否只限已宣告類別。

## 10. 評估精煉(2026-11-02,分支 `discovery-independent-evaluation`)

基底 `118a4ac`。沒有 push。引擎 `src/lab_brain/discovery/` 一個位元都沒有改。
2026-11-01 的凍結證據沒有動。新證據放在新目錄。
報告:`docs/audit/discovery-independent-evaluation-2026-11-02/REPORT.zh-TW.md`。

### 10.1 做了什麼

- **獨立評估協定**:`docs/evaluation/discovery-independent-evaluation-protocol.md`(英文)、
  `docs/evaluation/discovery-independent-evaluation-protocol.zh-TW.md`(摘要)。
  角色分離、先承諾後揭露、凍結的引擎 SHA 與環境 manifest、盲跑、評估者評分、
  沒見過的機制家族(正確 = 不宣稱)、實際成本曲線(AUC、第一次答對的預算)、
  arm A/B/C 的真正定義與目前替身、預先登記的統計、否證條件、仍未驗證的事。
- **評估工具** `src/lab_brain/discovery_eval/`(放在引擎旁邊,因為 2026-11-01 的 manifest 雜湊引擎目錄的每個檔案):
  `blind`、`curves`、`held_out`、`hidden_worlds`。和引擎一樣受 §24.2 匯入禁令約束,有自己的結構測試。
- **隱藏世界格式**:`benchmarks/discovery_independent/hidden-worlds.schema.json` 與
  `example.hidden-worlds.json`(EXAMPLE ONLY,不是隱藏集;載入器預設拒絕把它當隱藏集)。
- **腳本** `scripts/discovery_independent_eval.py`(組合根;`pyproject.toml` 只對它新增一行 TID251 豁免)。
- **證據** `docs/audit/discovery-independent-evaluation-2026-11-02/evidence/`(在 `54eb00e` 產生)。

### 10.2 Commit

| commit | 內容 |
|---|---|
| `d43ea14` | 評估工具套件、範例檔與 schema、單元/對抗/治理測試 |
| `54eb00e` | 評估腳本(組合根)、`pyproject.toml` 一行豁免 |
| `af1ee9e` | 一次完整執行的凍結證據(在 `54eb00e` 產生)、凍結檢查測試 |
| `c71a9d7` | 協定(英文+中文摘要)、設計文件第 10 節、報告 |
| `c7e0eab` | 本交接第 10 節 |
| `73a3caa` | 重新產生的 `IMPLEMENTATION_STATUS.md`(測試清單 3579 → 3701) |
| (最後一個) | 本交接的測試結果(10.4) |

### 10.3 結果摘要(合成世界,同一作者系譜)

| | B0 單一假說(不是 LLM) | B1 現有 LIB 風格(不是 PostgreSQL LIB) | B2 LIB + Discovery |
|---|---|---|---|
| 正確率,上限 4 | 0.080 | 0.295 [0.236, 0.362] | 0.345 [0.283, 0.413] |
| 正確率,上限 12 | 0.080 | 0.300 [0.241, 0.367] | 0.865 [0.811, 0.906] |
| 正確率,上限 24 | 0.080 | 0.300 | 0.970 [0.936, 0.986] |
| 實際成本,上限 12 | 1.21 | 1.92 | 7.70 [7.30, 8.10] |
| 每個正確結果的實際成本,上限 12 | 15.1 | **6.38** [5.31, 7.92] | 8.90 [8.14, 9.78] |
| 錯誤發現率,上限 12 | 0.340 | 0.245 | 0.020 [0.008, 0.050] |
| AUC(正確率對上限) | 0.080 | 0.299 [0.240, 0.359] | 0.823 [0.790, 0.852] |
| held-out 強行套用率,預算 12(n=195) | 0.395 | 0.533 | 0.400 [0.334, 0.470] |
| held-out 強行套用率,預算 24 | 0.395 | 0.554 | 0.472 [0.403, 0.542] |

- 上限 4:B2 − B1 正確率 +0.050 [−0.025, 0.130],Holm p = 0.25,不顯著。
- B2 在每個上限的效率都比 B1 差。
- 真機制家族不在目錄時,B2 和 B0 一樣常強行套用;預算越多越常。家族留在目錄時,B2 答對 0.908。
- 引擎確認:來源雜湊與 2026-11-01 manifest 相同;凍結的主評估逐位元重現。

### 10.4 測試指令與結果

全部用主 checkout 的 venv,`PYTHONPATH` 指向本 worktree 的 `src`
(`python -c "import lab_brain;print(lab_brain.__file__)"` 指向本 worktree)。

| 指令 | 結果 |
|---|---|
| `ruff check src tests scripts` | All checks passed |
| `ruff format --check src tests scripts` | 610 files already formatted |
| `mypy src` | Success: no issues found in 301 source files |
| 新增的離線測試(4 個單元檔 + 凍結檢查) | 全部通過;全部 discovery 測試 217 passed(重新產生證據前),凍結檢查 5 passed |
| 全部非 PostgreSQL 測試 | **2498 passed, 1203 skipped**(PostgreSQL 等後端閘門、本地模型、Lumerical、網路、Windows),99.7 秒 |
| `python scripts/discovery_independent_eval.py --check` | evidence is current(另一個行程,約 130 秒) |
| `python scripts/discovery_benchmark.py` 的凍結檢查 `tests/e2e/test_discovery_benchmark_frozen.py` | 通過(引擎沒變) |
| `python scripts/check_commit_messages.py --range 58c68be..HEAD` | no AI authorship found |
| `python scripts/rebuild_obligation_inventory.py --check` | 84 occurrences, in sync |
| `python scripts/update_status.py` 然後 `--check`、`--check --requirements-only` | 重新產生;`IMPLEMENTATION_STATUS.md is up to date`。測試清單 3579 → 3701 |
| 全部測試 + PostgreSQL(`lab_brain_p3_full`) | **未完成,見下** |

PostgreSQL 全套測試:
- 新建 `lab_brain_p3_full` 並 migrate:81 個 migration 全部套用,`--status` 顯示 pending 0,再跑一次 migrate 顯示 up to date。
- 之後 127.0.0.1:5433 的伺服器停止了(用量上限重置時容器重啟;資料目錄 `/home/user/pgdata` 最後寫入 12:58 UTC)。
  這個 sandbox 拒絕切換使用者的指令(`su`、`runuser`),所以無法以 `postgres` 身分重新啟動它。
- 伺服器停止時跑過一次:2527 passed、1170 skipped、1 failed、3 errors。
  失敗與錯誤**全部**是 `Connection refused`,不是程式結果,不能當作 PostgreSQL 全套的證據。
- 需要:有人以 `postgres` 身分重新啟動伺服器(`pg_ctl -D /home/user/pgdata -o "-p 5433 ..." start`),
  再重建 `lab_brain_p3_full` 並執行
  `LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_p3_full python -m pytest -q -p no:cacheprovider -rs`。
- 本分支沒有改任何 PostgreSQL 相關的程式碼、migration 或測試;新的程式只在離線套件裡。

### 10.5 沒有改的東西

- 沒有改 `src/lab_brain/discovery/`、`discovery_catalog.py`、`docs/audit/discovery-loop-offline-2026-11-01/evidence/`。
- 沒有改 `src/lab_brain/verification/prospective.py`、`src/lab_brain/evaluation/*`、migrations、`docs/spec/*`。
- 沒有 migration。沒有接研究流程。沒有寫資料庫(除了測試自己新建的 `lab_brain_p3_full`)。
- 沒有 LLM、網路、模擬器或付費呼叫。

### 10.6 合併注意

- `IMPLEMENTATION_STATUS.md` 會和其他分支衝突;合併後重跑 `python scripts/update_status.py`。
- `pyproject.toml` 只新增一行 per-file-ignore。
- `tests/e2e/test_discovery_independent_eval_frozen.py` 會在評估工具、腳本、範例或 schema 改動時失敗。
  改了就要重跑 `python scripts/discovery_independent_eval.py` 並一起提交證據。
  引擎改動則兩個凍結檢查(2026-11-01 與 2026-11-02)都會失敗。

### 10.7 新的 Owner 決策

1. 是否核准獨立評估協定並固定其值;指派世界作者(至少兩位)、評估者、審查者(不可是引擎作者系譜)。
2. arm A 的模型(本機或有支出上限的雲端)與固定方式。
3. arm B:是否建立驅動真正 PostgreSQL LIB 的 harness(需要 OutcomeSpace 決定)。
4. 實驗室是否做成獨立行程服務。
5. Discovery 在詞彙缺口時會強行套用:是否要求在接研究流程前先處理。本分支沒有改引擎。
6. B2 在低預算時對簡單世界比 B1 差:是否接受這個取捨。
