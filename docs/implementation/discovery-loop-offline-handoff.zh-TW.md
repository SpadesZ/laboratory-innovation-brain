# Discovery Loop v0(離線)交接

日期:2026-11-01
分支:`discovery-loop-offline`,基底 `58c68be`(`g0-owner-boundary-closure`)。沒有 push。
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
