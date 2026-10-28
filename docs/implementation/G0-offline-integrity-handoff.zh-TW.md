# G0 離線完整性與評估收尾 — 交接

分支:`g0-offline-integrity-closure`(從 `g0-exploratory-screening-v2` @ `21cef3e`)。
報告:`docs/audit/g0-offline-integrity-closure-2026-10-27/REPORT.zh-TW.md`。
狀態:工程候選,停在 Independent Chief Auditor 審查關卡。G0 未通過。沒有合併、部署、付費呼叫、Lumerical。

## 現在有什麼

| 項目 | 位置 |
|---|---|
| Commit 身分檢查(作者、提交者、訊息、cherry-pick 來源) | `scripts/check_commit_messages.py`、`.github/commit-identity-policy.toml` |
| CI 關卡 + 舊分支負向控制 | `.github/workflows/ci.yml`(`commit-hygiene` job) |
| 合併關卡需要的 GitHub 設定(未改) | `docs/implementation/commit-integrity-gate.md` |
| 篩檢讀數換身分不能 SUPPORTS | `migrations/011m_screening_repeat_by_content.sql` |
| 篩檢對抗與獨立性測試 | `tests/e2e/test_g0_screening_{adversarial,independence}_postgres.py` |
| 封存評估流程(合成資料測試) | `src/lab_brain/evaluation/`、`scripts/g0_eval_*.py`、`docs/evaluation/` |
| 雙語結構對等檢查與稽核 | `src/lab_brain/interfaces/web/bilingual_parity.py`、`docs/audit/g0-offline-integrity-closure-2026-10-27/bilingual-audit.md` |

## 怎麼驗證

```
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src
.venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<新建並 migrate 的 DB> .venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<DB> .venv/bin/python scripts/mutation_battery.py --only <名稱>
python scripts/check_commit_messages.py --tip HEAD
```

本機 PostgreSQL 的 host 連線要用密碼驗證(`test_service_roles_postgres` 需要)。

## 下一步(Owner)

1. `main` 的 branch rule:必要 check「Commit hygiene (no AI authorship attribution)」、禁止 force push 與刪除、Code Owner 審查。
2. 審查 011m 的較嚴格重複定義。
3. 雙語匯出的產品決定:`report.md` 繁中版、繁中摘要的引用、session 稽核 ref migration。
4. 指派獨立評估者並封存盲測集;授權真實 LLM 重測(付費,先估費用)。
5. 刪除舊分支 `g0-exploratory-screening`(可選)。

## 給下一個工作階段

- 完整 mutation battery:756/756 killed(47 分鐘)。完整 PostgreSQL:3187 passed, 4 skipped, 1 xfailed。
- CI:`a682e9d` run 40540676295 四個 job 全部 success。
- 這個環境的代理擋住 CI log;CI 負向控制的結果用 annotation 讀:
  `gh api repos/SpadesZ/laboratory-innovation-brain/check-runs/<job id>/annotations`。

## 後續

接續在 `g0-reliability-bilingual-closure`:見 `docs/implementation/G0-reliability-bilingual-handoff.zh-TW.md`。
