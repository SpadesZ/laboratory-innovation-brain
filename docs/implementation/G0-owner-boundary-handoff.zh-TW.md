# G0 Owner 邊界收尾:交接

分支:`g0-owner-boundary-closure`(起點 `g0-evidence-auth-cost-closure` @ `4497242`)
狀態:工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。沒有真實 LLM 結果、沒有盲測、沒有物理驗證。

## 現在有什麼

| 項目 | 位置 |
|---|---|
| 報告 | `docs/audit/g0-owner-boundary-closure-2026-10-28/REPORT.zh-TW.md` |
| Owner 決定(彙整) | `docs/implementation/G0-owner-decisions.zh-TW.md` |
| 金額管理只歸 Owner(011t) | `migrations/011t_llm_spend_administration.sql`、`spend-administration.md` |
| 前瞻證據與預先授權(011s) | `migrations/011s_prospective_evidence_authorization.sql`、`src/lab_brain/verification/prospective.py`、`prospective-evidence.md` |
| 簽章金鑰生命週期 | `src/lab_brain/security/key_lifecycle.py`、`key-lifecycle.md` |
| A12 雜湊鏈紀錄(011u,只偵測) | `migrations/011u_account_change_audit.sql`、`src/lab_brain/accounts/change_audit.py`、`a12-boundary.md` |
| 盲測協定與工具 | `docs/evaluation/G0-blind-evaluation-protocol.zh-TW.md`、`scripts/g0_eval_environment.py`、`src/lab_brain/evaluation/runner.py` |
| 證據對帳 | `docs/audit/g0-owner-boundary-closure-2026-10-28/evidence-reconciliation.md` |

Migration 順序:`... 011r → 011t → 011u → 011s`(`scripts/migrate.py` 的 APPLY_ORDER)。

## 新指令

```
lab-brain admin declare-capabilities        # migrator 執行:登記 capability 種類(011s)
lab-brain admin account-audit [--expect-head SEQ:DIGEST]   # A12:找出沒有帳號事件的變更
lab-brain interaction-key generate|pin|retire|revoke|check
```

## 怎麼驗證

```
.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts && .venv/bin/mypy src
.venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<新建並 migrate 的 DB> .venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<DB> .venv/bin/python scripts/mutation_battery.py
.venv/bin/python scripts/update_status.py   # 要在完整測試之後執行
```

注意:
- 變異測試會覆寫測試報告;之後要先跑一次完整測試,`update_status.py` 才能更新清單。
- 變異測試的資料庫現在也建立 `schema_migrations`;以前缺這張表,角色測試會在 setup 出錯,被誤算為「抓到」。
- 這個容器重啟後 PostgreSQL 會停;要重新啟動。
- CI 用一般使用者執行。金鑰測試用 `tests/trust_owner.py` 把信任檔當作 operator 擁有;要讀真正擁有者的測試要標記 `real_owners`。
- 最後一次完整變異測試:`12d86d8`,861/861(`evidence/mutation-full-861-final-12d86d8.log`)。

## 下一步

Owner:見 `G0-owner-decisions.zh-TW.md`。實作:等 Independent Chief Auditor 審查結果。
