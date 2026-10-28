# G0 探索性篩檢 V2 收尾報告

> **勘誤(2026-10-28,證據對帳)**:本報告的變異測試「全部抓到」是第一輪結果加上修正後的重跑合併計算;重跑沒有另存證據檔,證據檔本身記錄的是第一輪。詳見 `docs/audit/g0-owner-boundary-closure-2026-10-28/evidence-reconciliation.md`。


日期:2026-10-27
分支:`g0-exploratory-screening-v2`
狀態:**候選,待 Owner 審查。G0 未通過。沒有物理確認。**
範圍:只做離線開發與驗證。沒有付費模型呼叫、沒有付費 runner、沒有 Lumerical、沒有合併、沒有部署、
沒有正式資料變更、沒有刪除分支。

## 1. 交付項目

| # | 要求 | 結果 | 位置 |
|---|---|---|---|
| 1 | 用 Reading B 解決 SPEC-ISSUE-016,留可稽核決策紀錄 | 完成。Owner 核准原文寫入 ADR。SAI 3.3 鎖定要求與登錄表不變 | `docs/adr/ADR-0015-exploratory-screening-is-not-a-verification-action.md`、`docs/spec_issues/SPEC-ISSUE-016-exploratory-screening.md`(RESOLVED) |
| 2 | 正式環境預設關閉 | 完成。`ResearchFeatures.exploratory_screening=False`;web `Workspace` 預設不開 | `src/lab_brain/research/service.py` |
| 3 | 補 Screening Review 資格探針 | 完成。probe-8.0.0 加 `screening-review`;新增 `ROLE_SCREENING_REVIEW` 合約與 schema(rc-6.0.0)。之前正式呼叫沒有合約,這是真缺口,已補 | `src/lab_brain/llm_runtime/probes.py`、`contracts.py` |
| 4 | 執行前 fail-closed | 完成。`preflight` 在建立 Job 前檢查:計畫選取、登錄、可用性、動作層級、授權/隱私、不可逆、金錢、人力、授權座位、上限、LOCAL_NO_EGRESS 宣告、工作流程工具、專案輸入。執行中再檢查未宣告工具。拒絕寫成 `REFUSED` 紀錄 | `src/lab_brain/verification/screening.py`、`migrations/012z_screening_fail_closed.sql` |
| 5 | 中斷與證據持久化失敗的故障注入 | 完成。6 個 PostgreSQL 測試 | `tests/e2e/test_g0_screening_faults_postgres.py` |
| 6 | 已曝光的 holdout 改列為開發/回歸證據 | 完成。protocol amendment 1;評分輸出改標 `exposed-regression (former holdout)`。目前**沒有**獨立盲測 | `benchmarks/g0_screening/protocol-amendment-1.json`、`score.py` |
| 7 | 目標測試、PostgreSQL 回歸、變異測試 | 完成,見 §3 | — |
| 8 | 限制、CI SHA、驗證證據 | 本報告 §3–§5 | — |

## 2. Commits

| SHA | 內容 |
|---|---|
| `6224bcc` | Reading B 決策、預設關閉、資格探針、fail-closed、故障注入、holdout 重新分類 |
| `6e27244` | 補強未宣告工具測試、V2 報告、handoff |
| `0463be3` | 記錄 CI 結果 |
| 本 commit | 記錄 trailer 修正後的 CI |

## 3. 驗證證據

全部在本機免費資源執行(Python 3.13、PostgreSQL 16 + pgvector,127.0.0.1:5433)。CI 用公開 repo 的
免費 runner(計費 0 ms)。

### 3.1 靜態檢查

```
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src
```
結果:全部通過。

### 3.2 不需資料庫的測試

```
.venv/bin/python -m pytest -q
```
結果:2033 passed(`6224bcc`,改寫前為 `67f6cd0`,內容相同)。規格測試:206 passed。
V2 新單元測試 `tests/unit/test_g0_screening_closure.py`:20 passed。

### 3.3 PostgreSQL

```
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_main \
  .venv/bin/python -m pytest -q tests/e2e/test_g0_screening_faults_postgres.py
```
結果:6 passed。

完整回歸(新建資料庫 `lab_brain_full`,72 個 migration 到 012z):

```
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_full \
  .venv/bin/python -m pytest -q
```
結果:**3076 passed, 4 skipped**(11 分 38 秒)。4 個 skip:本機 live 模型、Lumerical、網路、Windows Credential Manager——都依設計不在本次範圍。紀錄:`evidence/full-postgres-suite.log`。

### 3.4 變異測試

```
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_mut \
  .venv/bin/python scripts/mutation_battery.py --only <52 個篩檢相關項目>
```
- 第一輪:51/52 killed。存活:`screening_dispatches_an_undeclared_tool`。
  原因:測試用未登錄的工具 `DOM-SP-TOOL-999`,所以「未登錄」檢查先擋下,「未宣告」檢查沒被測到。
- 修正:測試改用已登錄、本機、無座位、但工作流程沒宣告的 `DOM-SP-TOOL-006`,並檢查拒絕原因文字。
- 重跑:1/1 killed。合計 **52/52 killed**。
- 紀錄:`evidence/mutation-targeted-52.log`(第一輪原始輸出)。
- 全部 732 項的完整變異測試**沒有**在本次執行。

### 3.5 CI

CI run `40506215320`,SHA `fcf7a7497c602f73d50e908005be672615510c7f`:

| Job | 結果 |
|---|---|
| Lint, types and full suite | success |
| Backend profile (postgres) | success |
| Spec conformance (T-SPEC-001 / T-SPEC-002) | success |
| Commit hygiene (no AI authorship attribution) | **failure** |

失敗原因:`fcf7a74` 的 commit 訊息帶了 AI 署名 trailer。這是本次執行的錯誤,違反 repo 規則。
程式與測試本身全部通過。

修正(Owner 授權 force push):用 `git rebase -x` 從 `fecf642` 之後的每個 commit 訊息移除 trailer,
再 `git push --force-with-lease` 到本分支。檔案內容不變,只有 commit 訊息與 SHA 改變:
`67f6cd0`→`6224bcc`、`fcf7a74`→`6e27244`、`3b5d4d1`→`0463be3`。修正後的 CI 見下方。

修正後 CI run `40516645153`,SHA `3928fc8e306797ed5ab5e2e05c78e881d691c2f9`:**四個 job 全部 success**
(Lint, types and full suite;Backend profile (postgres);Spec conformance;Commit hygiene)。

前一個 SHA `fecf642` 的 CI run `40492814298` 四個 job 都 success。

## 4. 風險與限制

1. **沒有真實 LLM 重測。** 新探針只用 fake provider 驗證。因為 probe-8.0.0 是新版本,所有既有資格鎖都過期,
   正式使用前要重新取得資格(需要付費呼叫,要 Owner 授權)。
2. **沒有獨立盲測。** 原 holdout 已曝光,只當回歸證據。科學表現沒有獨立證據。
3. 篩檢後產生的機制假說仍需要人審查;篩檢不是驗證動作,不能支持(SUPPORTS)它自己的條件化假說。
4. 完整 732 項變異測試沒有跑,只跑 52 項目標項目。
5. 本機 PostgreSQL 16;CI 用 pg17。
6. 舊分支 `g0-exploratory-screening` 有 AI 署名 commit,還在遠端。刪除要 Owner 操作。
7. 這個環境的代理擋住 CI log 主機;CI 失敗時要在 GitHub UI 看測試名稱。

## 5. 剩餘 Owner Gates

1. 是否在正式環境開啟篩檢(目前預設關閉)。
2. 裝置結構摘要開或關。
3. 篩檢後假說的「只審查」升級路徑。
4. 授權真實 Gemini 資格重測(要先提供預估最高費用)。
5. 刪除舊分支 `g0-exploratory-screening`。
6. commit 身分設定確認。
7. 建立新的獨立盲測 holdout。
8. G0 是否通過:只能由 Owner 決定。本報告**不**宣稱 G0 PASS。
