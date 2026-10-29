# G0 真實 LLM 評估提案(有費用上限,**未執行**)

狀態:提案。需要 Owner 明確授權才可執行。本分支沒有做任何付費或外部模型呼叫。
執行後的結果仍然只是 **真實 LLM 研究表現** 的證據:不是物理驗證,也不是 G0 通過。
G0 是否通過要由獨立審查決定。

## 1. 要回答的問題

| 問題 | 需要的證據 | 本提案能給嗎 |
|---|---|---|
| 真實模型能否通過 probe-8.0.0 資格(含 `screening-review`) | 資格探測紀錄 | 能 |
| 真實模型在篩檢關閉/開啟時,能否在篩檢**之前**想到真因(`considered_pre_screening`) | scorer 2.0.0 指標 | 能(只限已曝光的回歸案例) |
| 治理不變量在真實模型下是否仍為 0(假確認、不可採用的支持、輸入洩漏、假異常、重複讀數) | scorer 2.0.0 + 協定修訂 2 | 能 |
| G0-S 科學有用性 | 獨立盲測集 + 具資格且獨立的審查者 | **不能**:要另外授權評估者與審查者 |
| G0-B 雙語語意品質 | 獨立雙語審查者 | **不能** |

## 2. 分階段,每階段都有停止規則

| 階段 | 內容 | 外部呼叫上限 | Token 上限 |
|---|---|---|---|
| 0 | probe-8.0.0 資格探測(主模型) | 30 | 200,000 |
| 1 | `baseline` 與 `screening` 兩種設定 × 25 個案例(22 個矩陣回歸案例 + 3 個原始情境) | 350 | 1,800,000 |
| 2(選擇性) | `structure`、`combined` | 350 | 1,800,000 |

- 依據:先前 Owner 授權的 Gemini 重測,每個研究情境約 5 次呼叫、約 28k token(`docs/audit/g0-research-reliability-2026-10-21/REPORT.zh-TW.md` §184)。
  估算用每案 6 次呼叫、30k token,再加 20% 緩衝。
- 停止規則:
  - 階段 0 沒有完整通過資格 → **停止**,不進階段 1。
  - 任一治理不變量 > 0 → 該設定停止,保留紀錄,回報。
  - 累計上限由程式執行,不是靠人工盯:`lab_brain.evaluation.live_budget`。
    - 外部主模型沒有設 `LAB_BRAIN_LIVE_MAX_CALLS` 與 `LAB_BRAIN_LIVE_MAX_TOKENS` → 第一次呼叫前就拒絕。
    - 每個情境開始前,從資料庫的 LLM_CALL 紀錄算已用量;沒有回報用量的呼叫按上限計。
      已用量 + 一個情境的保留量會超過上限 → 拒絕下一個情境。
    - 最多超出一個情境本身的 Budget Gate 上限(每個研究執行本來就有自己的 Budget Gate)。
  - 任何 MALFORMED 比例 > 20% → 停止並回報(代表合約或解析問題,不是科學結果)。

## 3. 金額上限(由程式執行)

金額上限現在由程式強制執行,不是人工估算
(`lab_brain.llm_runtime.spend`、migration `011r_llm_spend_ceiling.sql`;
稽核:`docs/audit/g0-evidence-auth-cost-closure-2026-10-28/cost-path-audit.md`)。

1. repo 不估價。Owner 提供當時官方單價(輸入/輸出,每百萬 token)、幣別、來源與日期,以及金額上限。
   外部主模型缺少任何一項 → 第一次呼叫(含資格探測)前就拒絕。
2. 每一個送到非本機的請求,送出**之前**先在 PostgreSQL 原子預留最壞金額:
   `input_bound = ceil(請求 body 的 UTF-8 byte 數 × 安全倍數) + 圖片數 × 4096 + 1024`
   `最壞金額 = (input_bound × 輸入單價 + max_tokens × 輸出單價) / 1,000,000`
   已收費 + 最壞金額 > 上限 → 拒絕,不送出。多個行程或執行緒同時呼叫也不會超過上限。
   每個 chat 請求都帶 `max_tokens`(預設 16384)。結構化輸出 fallback 的第二個請求另外預留。
3. 回覆後:有用量就按用量結算;沒有用量、錯誤、逾時 → 保留最壞金額;
   用量超過預留 → 記為 OVERRUN,停止所有後續呼叫,直到 Owner 檢查後重設。
4. 帳本只能新增,不記金鑰與提示詞。
5. 誰能改金額(`011t`):只有 `lab_brain_spend_admin` 的成員能建立預算、宣告單價、改上限、關電路、
   宣告免費端點。研究服務的資料庫角色只能預留、結算、保留,不能調高自己的上限,也不能偽造旗標。
   即時評估用 Owner 的連線(新資料庫的 migrator)宣告。
   步驟:`docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md` §7。
6. 本機也計量:本機端點可能是轉送到付費服務的代理。評估的 guard 對本機也預留;沒有單價就拒絕。
   真的免費的本機模型(例如 Ollama 的 critic / utility)要由 Owner 宣告:
   `LAB_BRAIN_LIVE_FREE_ENDPOINTS="127.0.0.1:11434 qwen2.5:7b"`、`LAB_BRAIN_LIVE_FREE_REASON=<原因>`。
   只用本機模型的評估也要宣告(`install_local_free_guard`),否則拒絕。
7. 建議的金額上限:階段 0+1 **USD 25**;階段 2 另外授權。
   因為每次請求都按最壞情況預留,實際可跑的量會比上限少;不夠時,縮小階段 1(例如先只跑 `screening`)。

剩下的假設(Owner 要確認):
- 服務商遵守 `max_tokens`,包括推理 / thinking token。每個服務商都要確認。不遵守時只能事後偵測,那一個請求已付費。
- 一個 token 至少是一個 byte(byte-level BPE)。安全倍數可調高(`LAB_BRAIN_LIVE_SPEND_MULTIPLIER`)。
- 建議在服務商端另外設定預算警示或硬上限,作為第二層防護。

## 4. 資料外送

測試專案的範例證據會送到外部模型服務。只用已在 repo 的合成或範例資料;不送正式資料;
不送評估端真值(產生端套件載入器會拒絕真值,`assert_no_truth` 會掃描提示)。

## 5. 執行方式(授權後)

每種設定一個新資料庫。主模型用 Owner 指定的外部模型;critic/utility 可用本機模型或同一外部模型(會增加呼叫數,需在上限內)。

```
LAB_BRAIN_LIVE_MAX_CALLS=<階段上限> LAB_BRAIN_LIVE_MAX_TOKENS=<階段上限> \
LAB_BRAIN_LIVE_SPEND_CEILING=<金額上限> LAB_BRAIN_LIVE_SPEND_CURRENCY=USD \
LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK=<輸入單價> LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK=<輸出單價> \
LAB_BRAIN_LIVE_PRICE_SOURCE=<單價來源> LAB_BRAIN_LIVE_PRICE_DATE=<YYYY-MM-DD> \
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<新資料庫> \
LAB_BRAIN_LIVE_PRIMARY=<模型> LAB_BRAIN_LIVE_PRIMARY_PROVIDER=<提供者> \
LAB_BRAIN_LIVE_PRIMARY_KEY_ENV=<金鑰環境變數> LAB_BRAIN_LIVE_FEATURES=<設定> \
LAB_BRAIN_LIVE_CASES=matrix LAB_BRAIN_LIVE_EVIDENCE=<證據目錄> \
.venv/bin/python -m pytest tests/e2e/test_research_live_model_postgres.py
.venv/bin/python benchmarks/g0_screening/score.py <證據目錄>/matrix.outputs.json
```

評分用 scorer 2.0.0(`lab_brain.evaluation.scoring`)與協定修訂 2(`benchmarks/g0_screening/protocol-amendment-2.json`)。
每個案例都留在分母;拒絕、崩潰、格式錯都算失敗。

## 6. 結果怎麼讀

- 22 個矩陣案例已曝光給實作者,所以結果是**開發/回歸**證據,不是盲測。
- `considered_pre_screening` 與 `considered_with_screening` 分開報告;篩檢後才發現的真因算篩檢的發現。
- 正確結論說出真因不算洩漏;真值出現在輸入才算。
- 報告必須同時寫出:工程測試結果、真實 LLM 表現、物理驗證(沒有做)三件事,不可混用。

## 7. 需要 Owner 決定

1. 是否授權階段 0 與 1,以及金額上限(建議 USD 25)與當時官方單價(含來源與日期)。
2. 模型與提供者;金鑰由 Owner 設定,不進 repo。
3. 是否同時授權獨立評估者建立封存盲測集(`docs/evaluation/G0-independent-holdout-workflow.md`),讓真實 LLM 評估能有盲測證據。
4. 產品 web runtime 是否在正式環境強制要求金額上限(`LAB_BRAIN_LLM_SPEND_REQUIRED=1`)。這是 Owner Gate;目前預設不強制。
