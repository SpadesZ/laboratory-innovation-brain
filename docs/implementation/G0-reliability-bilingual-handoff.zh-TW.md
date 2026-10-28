# G0 科學可靠性與雙語收尾 — 交接

分支:`g0-reliability-bilingual-closure`(從 `g0-offline-integrity-closure` @ `2e6962e`)。
報告:`docs/audit/g0-reliability-bilingual-closure-2026-10-28/REPORT.zh-TW.md`。
狀態:工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。沒有真實 LLM 結果、沒有物理驗證、沒有盲測。

## 現在有什麼

| 項目 | 位置 |
|---|---|
| Scorer 2.0.0(可採用支持、發現拆分、輸入/輸出洩漏分開、MALFORMED、競爭假說、可反駁性) | `src/lab_brain/evaluation/scoring.py` |
| 支持來源事實的收集器 | `src/lab_brain/evaluation/collect.py` |
| 舊矩陣協定修訂 2 | `benchmarks/g0_screening/protocol-amendment-2.json`、`score.py` |
| 引用的證據也受篩檢 guard 檢查 | `migrations/011o_screening_guard_reads_the_cited_basis.sql` |
| 研究執行的 session 來源 | `migrations/011n_research_session_provenance.sql`、`src/lab_brain/research/run_provenance.py` |
| 繁中科學匯出、引用、原文保留、session 區塊 | `src/lab_brain/research/render.py`、`src/lab_brain/interfaces/web/{pages,i18n,bilingual_parity,app}.py` |
| 真實 LLM 評估提案 + 累計上限 | `docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md`、`src/lab_brain/evaluation/live_budget.py` |

## 怎麼驗證

```
.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts && .venv/bin/mypy src
.venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<新建並 migrate 的 DB> .venv/bin/python -m pytest -q
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<DB> .venv/bin/python scripts/mutation_battery.py
```

注意:跑完變異測試後,`scripts/update_status.py` 需要先有一次完整測試執行(變異測試會覆寫測試報告)。

## 下一步(Owner)

見報告 §8。最重要:審查 scorer 2.0.0、011o、011n;決定是否授權真實 LLM 評估;指派獨立評估者與審查者。
