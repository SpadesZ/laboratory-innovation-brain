# 外部 LLM 費用路徑稽核與金額上限(2026-10-28)

狀態:已實作,只用本機假服務測試。本工作沒有呼叫任何真實模型服務,沒有付費呼叫。

## 1. 稽核前的結論

- 評估只有「呼叫次數」與「token 數」上限(`src/lab_brain/evaluation/live_budget.py`),沒有金額上限。
- 上限在每個情境開始前檢查,不是在每個 HTTP 請求前檢查。
- 所有模型請求都經過同一個地方:`OpenAICompatibleClient._request`(`src/lab_brain/llm_runtime/provider.py:306`)。
  所以金額上限放在這裡,就能涵蓋所有呼叫端,包括以後新增的呼叫端。

## 2. 每一條可能計費的路徑

「稽核前」欄是修改前的狀態。「現在」欄是修改後的狀態。
行號是修改後的檔案。

| # | 路徑 | 位置 | 稽核前有計量嗎 | 稽核前的上限 | 現在 |
|---|---|---|---|---|---|
| 1 | 研究角色 primary / critic / utility(假說、批判、專家、別名等) | `runtime.py:622` `RouteCompletion.__call__` → `provider.py:290/292` | 有 span 才算(`live_budget.py:84`) | 每次執行的 Budget Gate(token),情境前累計檢查 | 每個請求都先預留最壞金額 |
| 2 | 角色回覆被解析器拒絕後的重試(`max_attempts=2`) | `cognition/debate.py:1280`,`research/service.py:1363` | 有 span | Budget Gate | 每次重試是新請求,各自預留 |
| 3 | coverage review、screening review | `research/service.py:1364-1365`,`cognition/debate.py`(`COVERAGE_REVIEW`、`SCREENING_REVIEW`) | 有 span | Budget Gate + critic 保留量 | 各自預留 |
| 4 | 資格探測(8 種 probe,`ROLE_HYPOTHESIS` 是多個案例) | `probes.py:785`、`probes.py:824`;由 `runtime.py:366` `LLMSettings.test_model` 呼叫 | **沒有**:不寫 span,也不記 token | 只有評估提案的人工數字 | 每個請求都預留;拒絕時 probe 記為 ERROR,不送出 |
| 5 | 結構化輸出被拒後的第二個請求 | `provider.py:290` | **沒有**:一次邏輯呼叫 = 兩個計費請求,span 只算一次 | 無 | 兩個請求分開預留;第一個(400,沒有用量)保留最壞金額 |
| 6 | 逾時:服務端可能已計費,但用戶端拿不到用量 | `provider.py:325` | **沒有**:沒有回覆就沒有 span | 無 | 保留最壞金額(RETAINED) |
| 7 | 連線錯誤、HTTP 錯誤、非 JSON 回覆 | `provider.py:325`、`provider.py:334` | 沒有 | 無 | 保留最壞金額 |
| 8 | 回覆沒有 usage,或 usage 格式錯 | `provider.py:340-344` | 用每次呼叫上限估算 | 情境前檢查 | 保留最壞金額 |
| 9 | 輸出長度 | `provider.py:266` | **沒有上限**:`chat()` 不送 `max_tokens` | 無 | 每個 chat 請求都送 `max_tokens`(預設 16384,`LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS`) |
| 10 | 多個行程 / 執行緒同時呼叫 | web 伺服器是多執行緒(`interfaces/web/__init__.py:49`);評估可能多個行程共用資料庫 | 不是原子操作 | 兩個行程可以同時通過「已用 + 保留 ≤ 上限」 | PostgreSQL 鎖住預算列再預留(`llm_spend_reserve`),不會超過上限 |
| 11 | 連線健康檢查、取得模型清單 | `runtime.py:298`、`runtime.py:314`、`runtime.py:565`;`app.py:1913`、`app.py:2004`(兩處都是 `list_models`,不是 chat) | 不需要 | — | 不計量(見 §4) |
| 12 | 續寫(continuation)、串流 | 程式沒有這兩種請求 | — | — | 不存在;若以後加入,一樣經過 `_request`,一樣要預留 |
| 13 | 指向本機但實際轉送到付費服務的代理(例如本機 LiteLLM) | 任何 LOCAL 連線 | 沒有 | 無 | 有預算時一律計量,只有 Owner 宣告免費的端點例外(`011t`);完全沒有預算時仍不計量,除非 `LAB_BRAIN_LLM_SPEND_METER_LOCAL=1`(見 `docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md` §3.6) |

## 3. 已證明的缺口與假設性的缺口

### 已證明(先寫會失敗的測試,再修)

修改前先執行 `tests/unit/test_g0_spend_gaps.py`,結果是 2 個失敗、1 個通過(第三個是記錄事實的測試)。

| 缺口 | 證明它的測試 | 修改前 | 修改後 |
|---|---|---|---|
| 輸出沒有上限(沒有 `max_tokens`) | `test_gap_unbounded_output_every_chat_request_carries_max_tokens` | 失敗 | 通過 |
| 沒有金額檢查:要求上限時,遠端請求仍然送出 | `test_gap_no_money_check_a_required_ceiling_refuses_a_remote_request_unsent` | 失敗(連線被打開) | 通過(沒有打開連線) |
| 結構化輸出 fallback:一次呼叫 = 兩個計費請求 | `test_gap_two_per_call_a_schema_refusal_is_two_billed_requests` | 通過(事實) | 通過;兩次預留由 `test_the_schema_fallback_reserves_twice` 證明 |
| 資格探測不在 span 計量裡 | `tests/e2e/test_g0_spend_ledger_postgres.py::test_probes_are_reserved_though_the_span_meter_never_saw_them` | span 計量 = (0, 0) | span 計量仍是 (0, 0),但金額帳本記到每一個 probe 請求 |
| 逾時沒有用量 | `test_a_timeout_keeps_the_worst_case`(unit 與 e2e) | 沒有任何紀錄 | RETAINED,保留最壞金額 |

### 假設性(沒有實際觀察到,但設計上已處理)

- 兩個行程同時通過情境前檢查而超額:沒有實際發生過;現在用資料庫鎖防止(`test_concurrent_reservations_never_pass_the_ceiling`,24 個執行緒、各自的連線)。
- 服務商不遵守 `max_tokens`,或把隱藏的推理 token 算在外面:無法在本機證明;現在結算時偵測(OVERRUN),並停止所有後續呼叫。
- 服務商在 4xx 錯誤也收費:不知道;現在一律保留最壞金額。
- 服務商加在請求外的 token(對話模板、schema 說明文字):用 `request_overhead_tokens` 與安全倍數處理。

## 4. 設計

### 4.1 位置

`OpenAICompatibleClient._request`(`provider.py:306`)在建立 HTTP 請求之前呼叫 `_reserve`(`provider.py:318`)。
預留失敗就拋出 `ProviderError(SPEND_REFUSED)`,**一個 byte 都不送出**。

要計量的請求:有 body,而且目的地不是本機。
不計量:
- 沒有 body 的 `GET`(`/models`)。它沒有提示詞,不產生 token。`_request` 只允許 GET 沒有 body;沒有 body 的 POST 會被拒絕。
  OpenAI、Gemini 等服務的模型清單 API 不收費。這是根據公開文件的判斷,Owner 可以再確認。
- 本機(loopback 或部署宣告的主機),除非 guard 設定 `meter_this_machine`。

### 4.2 最壞金額公式

```
input_bound = ceil(body_bytes × safety_multiplier) + 圖片數 × image_allowance_tokens + request_overhead_tokens
worst_case  = (input_bound × 輸入單價 + max_tokens × 輸出單價) / 1,000,000
```

- `body_bytes`:整個序列化後請求 body 的 UTF-8 byte 數。
- 假設:一個 token 至少代表一個 byte(byte-level BPE;有 byte fallback 的 SentencePiece)。所以提示詞的 token 數不會超過 byte 數。JSON 跳脫只會讓 body 變長。
- `safety_multiplier` ≥ 1(預設 1);`image_allowance_tokens` 預設 4096;`request_overhead_tokens` 預設 1024。都存在預算列,建立後不能改。
- 沒有 `max_tokens` 的計量請求會被拒絕。

### 4.3 原子預留(migration `011r_llm_spend_ceiling.sql`)

- `llm_spend_reserve`:`SELECT ... FOR UPDATE` 鎖住預算列 → 找單價 → 算最壞金額 → `charged + worst_case > ceiling` 就拒絕 → 同一個交易內加上金額並寫 RESERVATION。
- 資料表 CHECK `llm_spend_budgets_within_ceiling`:電路沒有打開時,`charged ≤ ceiling`。
- 每次操作是自己的 autocommit 連線。研究執行回滾也不會刪掉預留。

### 4.4 結算

| 情況 | 紀錄 | 收費 |
|---|---|---|
| 有 prompt_tokens 與 completion_tokens,且沒有超過預留 | SETTLEMENT | 回報用量 × 單價;`total_tokens − prompt_tokens` 比 completion 大時,差額算輸出 |
| 沒有用量、格式錯、HTTP 錯誤、逾時、連線錯誤、非 JSON | RETAINED | 最壞金額 |
| 回報金額、prompt token 或輸出 token 超過預留 | OVERRUN | 回報金額與最壞金額取大;**電路打開**,之後所有預留都被拒絕 |

- 只有 Owner 呼叫 `llm_spend_set_ceiling(..., close_circuit => TRUE)` 才能關閉電路,而且新上限要 ≥ 已收費金額。
- 行程在預留後當掉:最壞金額永遠保留(安全方向)。

### 4.5 帳本

- `llm_spend_ledger`:RESERVATION、SETTLEMENT、RETAINED、OVERRUN、CEILING。只記 call id、模型、endpoint host、大小與金額;不記金鑰,不記提示詞。
- 觸發器:不能 UPDATE / DELETE;不能直接 INSERT(只有 `llm_spend_*` 函式能寫)。
- `llm_spend_prices`:只能新增。單價由 Owner 宣告,含幣別(必須是預算的幣別)、來源、日期。repo 不估價。
- `llm_spend_budgets`:參數不能改;金額、上限、電路只能經由函式改;不能刪除。
- ~~限制:這是防止誤寫,不是權限控制。能自己設定交易旗標的資料庫角色可以繞過。~~
  已由 `011t` 關閉:觸發器還要求 `current_user` 是資料表擁有者;管理函式只給 `lab_brain_spend_admin`;
  服務角色只能預留、結算、保留。見 `docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md`。
- 測試 fixture 用 TRUNCATE 清表時不會觸發列級觸發器;目前 fixture 沒有列出這三個表(測試用各自的預算 id)。

### 4.6 用哪個 guard

每次請求時決定(`spend.resolve`),順序:
1. client 建立時給的 `spend=`。
2. 行程安裝的 guard(`spend.install`)——即時評估用這個。
3. 環境變數 `LAB_BRAIN_LLM_SPEND_BUDGET`(資料庫用 `LAB_BRAIN_LLM_SPEND_DSN` 或 `LAB_BRAIN_DATABASE_URL`)。有設定但無法連線 → 拒絕所有計量請求。

沒有 guard 時(`011t` 之後):
- 遠端請求一律拒絕,不送出。`LAB_BRAIN_LLM_SPEND_REQUIRED` 已沒有作用。
- 唯一例外:Owner(`lab_brain_spend_admin`)在資料庫宣告這個端點免費。
- 有資料庫但沒有預算時,guard 只放行宣告免費的端點。

## 5. 即時評估:必須有金額上限

- `tests/e2e/test_research_live_model_postgres.py`:外部主模型時,呼叫 `spend_from_env`。缺少下列任何一個就在第一次呼叫前拒絕:
  `LAB_BRAIN_LIVE_SPEND_CEILING`、`LAB_BRAIN_LIVE_SPEND_CURRENCY`、`LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK`、`LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK`、`LAB_BRAIN_LIVE_PRICE_SOURCE`、`LAB_BRAIN_LIVE_PRICE_DATE`(可選:`LAB_BRAIN_LIVE_SPEND_MULTIPLIER`、`LAB_BRAIN_LIVE_SPEND_BUDGET`)。
- 有設定時:在新資料庫宣告預算與主模型單價(以提供者的 host + 模型名稱為鍵),並為整個行程安裝 **required** guard。
  workspace 建立的所有 client(probe、研究、重試)都會被計量。沒有單價的模型或主機會被拒絕。
- 每個情境開始前,電路已打開就停止(`check_spend_before_episode`)。

## 6. 產品 web runtime(`011t` 更新)

- 預設改成拒絕:沒有預算時,遠端請求一律不送出。只有 Owner 宣告免費的端點例外。
- 有預算(`LAB_BRAIN_LLM_SPEND_BUDGET=<預算 id>`)時,本機端點也計量,只有宣告免費的端點例外。
- 預算、單價、上限、免費端點只能由 `lab_brain_spend_admin` 的成員宣告(`spend.declare_budget`、
  `spend.declare_price`、`spend.set_ceiling`、`spend.declare_free_endpoint`)。服務角色不能。
- `LAB_BRAIN_LLM_SPEND_METER_LOCAL=1`:沒有預算時,未宣告免費的本機端點也拒絕。
- Owner 的步驟:`docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md` §7。

## 7. 剩下的風險(要 Owner 確認)

1. 服務商必須遵守 `max_tokens`,包括推理 / thinking token。每個服務商都要 Owner 確認。不遵守時只能事後偵測(OVERRUN),那一個請求已經付費。
2. token ≤ byte 的假設。非 byte-level 的 tokenizer 或特殊 token 可能例外;用安全倍數與 overhead 處理,結算時偵測。
3. 有些服務商(例如 OpenAI 推理模型)不接受 `max_tokens`,要用 `max_completion_tokens`。這時請求會以 400 失敗(保留最壞金額),不會在沒有上限的情況下產生內容。
4. 單價由 Owner 宣告。單價錯了,上限也會錯。快取折扣、分級價格不計入(只會高估)。
5. 建議在服務商端另外設定預算警示或硬上限,作為第二層防護。
6. 預設 `max_tokens` = 16384 可能截斷很長的推理輸出;截斷的回覆會被解析器拒絕,重試會再次預留。
