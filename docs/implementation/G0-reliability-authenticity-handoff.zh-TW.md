# G0 可靠性與真實性收尾:交接

分支:`g0-reliability-authenticity-closure`(起點 `g0-owner-boundary-closure` @ `58c68be`)
狀態:工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。沒有真實 LLM 結果、沒有盲測、沒有物理驗證。

同一階段的另外兩條分支(不在這條分支上,也沒有整合):
- `discovery-loop-offline`(起點 `58c68be`):離線 Discovery Loop v0。
- `sai-3.5-discovery-candidate`(起點 `a38ad63`):SAI 3.5 候選規格。只是候選,沒有啟用。

## 現在有什麼

| 項目 | 位置 |
|---|---|
| 報告 | `docs/audit/g0-reliability-authenticity-2026-11-01/REPORT.zh-TW.md` |
| 設計(英文) | `docs/audit/g0-reliability-authenticity-2026-11-01/design.md` |
| 修正前的失敗證據 | `docs/audit/g0-reliability-authenticity-2026-11-01/evidence/*_before*.log` |
| 本機代理一律計量(011v) | `migrations/011v_llm_spend_local_is_not_free.sql`、`src/lab_brain/llm_runtime/{spend,provider}.py` |
| 簽章的驗證授權(011w) | `migrations/011w_signed_verification_authorizations.sql`、`src/lab_brain/verification/prospective.py`、`src/lab_brain/security/reviewer_identity.py` |
| 盲測輸入凍結、環境漂移 | `src/lab_brain/evaluation/{runner,environment,packages,manifest}.py`、`scripts/g0_eval_environment.py` |
| SPEC ISSUES | `docs/spec_issues/SPEC-ISSUE-017/018/019-*.md`(都是 OPEN,要 Owner 決定) |
| Owner 決定 | `docs/implementation/G0-owner-decisions.zh-TW.md`(A6、B6–B8、E4–E5、F4–F5 是新的) |

Migration 順序:`... 011t → 011u → 011s → 011v → 011w`(`scripts/migrate.py` 的 APPLY_ORDER)。

## 行為改變(部署前一定要知道)

- 本機模型(Ollama 等)的請求**一律計量**。沒有預算、也沒有 Owner 的免費宣告 → 送出前拒絕。
  要用本機模型:Owner 用 `spend.declare_free_endpoint(..., model, ...)` 宣告那一個模型(不能用 `*`)。
- `LAB_BRAIN_LLM_SPEND_METER_LOCAL` 已經不讀了。
- 篩檢後的驗證授權**一定要簽章**。先由 review authority 為那個人登記授權金鑰
  (`sign_enrolment(..., scope="VERIFICATION_AUTHORIZATION")` + `enrol_authorizer`),
  再用 `SqlVerificationAuthorizations.authorize(..., signer=AuthorizationSigner(...))`。
  沒有設定 `LAB_BRAIN_REVIEW_AUTHORITIES` 時,任何授權都不算數(fail closed)。
- 盲測:`run_blind` 不再接受 `environment_sha256` 字串;要傳 `environment=` 與 `observe_environment=`。
  `g0_eval_environment.py` 多了 `--database-url`。scorer 版本 2.3.0。

## 測試要知道的事

- PostgreSQL 測試的假模型伺服器(127.0.0.1)會被當成「已宣告免費」(`tests/conftest.py`)。
  測試計費規則本身的模組要標記 `real_spend_guard`,才會看到部署時的真實行為。
- 傳輸層的單元測試用 `tests/free_test_endpoints.py` 明確選擇這個替身。
- 需要授權的測試用 `tests/authorizer_keys.py`(一個測試用 authority、登記金鑰、簽章)。

## 怎麼驗證

```
.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts && .venv/bin/mypy src
.venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<新建並 migrate 的 DB> .venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<DB> .venv/bin/python scripts/mutation_battery.py
.venv/bin/python scripts/update_status.py   # 要在完整測試之後執行
```

注意:這個容器重啟後 PostgreSQL 會停,要重新啟動(指令見 `G0-owner-boundary-handoff.zh-TW.md`)。

## 下一步

Owner:見 `G0-owner-decisions.zh-TW.md` 與 SPEC-ISSUE-017/018/019。實作:等 Independent Chief Auditor 審查結果。
