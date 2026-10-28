# G0 證據時間、驗證邊界與費用上限 — 交接

分支:`g0-evidence-auth-cost-closure`(從 `g0-reliability-bilingual-closure` @ `7988ed7`)。
報告:`docs/audit/g0-evidence-auth-cost-closure-2026-10-28/REPORT.zh-TW.md`。
狀態:工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。沒有真實 LLM 結果、沒有物理驗證、沒有盲測。

## 現在有什麼

| 項目 | 位置 |
|---|---|
| 篩檢後支持要在時間與種類上都是前瞻的 | `migrations/011p_screening_support_is_prospective_in_time.sql`、`src/lab_brain/evaluation/collect.py`(`retrospective_basis`)、scorer 2.1.0 |
| 研究執行的互動簽章與宣稱等級 | `migrations/011q_research_interaction_attestation.sql`、`src/lab_brain/security/interaction_attestation.py`、`auth-boundary.md` |
| 金額上限(預留/結算/斷路) | `migrations/011r_llm_spend_ceiling.sql`、`src/lab_brain/llm_runtime/spend.py`、`provider.py`、`cost-path-audit.md` |
| 真實 LLM 評估提案(已更新金額段落) | `docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md` |

## 設定(全部由 Owner 決定,不進 repo)

- 互動簽章:`LAB_BRAIN_INTERACTION_SIGNING_KEY`(私鑰檔)、`LAB_BRAIN_INTERACTION_AUTHORITIES`(釘選公鑰檔,`web:<label> ed25519:<key> [until=]`)。
- 金額上限:`LAB_BRAIN_LLM_SPEND_BUDGET`、`LAB_BRAIN_LLM_SPEND_REQUIRED`、`LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS`;真實評估另需 `LAB_BRAIN_LIVE_SPEND_CEILING` 與宣告的單價、來源、日期。

## 怎麼驗證

```
.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts && .venv/bin/mypy src
.venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<新建並 migrate 的 DB> .venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<DB> .venv/bin/python scripts/mutation_battery.py
```

注意:變異測試會覆寫測試報告;之後要先跑一次完整測試,`scripts/update_status.py` 才能更新清單。

## 下一步(Owner)

見報告 §7。
