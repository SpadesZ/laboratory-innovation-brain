# SiPh Lab — Lumerical 前研究平台驗收：稽核報告

日期：2026-10-21
分支：`pre-lumerical-acceptance`（自整合候選 `integration-integrity-accounts` `f3fadf6` 分出）
性質：審查用候選。未合併、未部署、未改正式資料；`READY_FOR_REAL_RESEARCH` 仍為 `false`；SP 1.1.0 未啟用。本報告不認證產品就緒，也不是 HARD-LOCK。

標記說明：【事實】＝本輪實際執行並留有證據；【推論】＝依程式或紀錄推得、未另行執行；【未做】＝沒有做，並說明原因。

---

## 0. 驗收問題的直接回答

> 研究者能否在沒有 Lumerical 的情況下端到端使用 SiPh Lab、以自然的繁體中文理解結果，並得到科學上站得住腳的最終報告，同時每一項未執行的模擬都明確標示為未驗證？

**部分可以，關鍵一項仍被擋住。**

- 【事實】流程本身可以：以領域包的**規則式目錄推理器**（不是語言模型），從建立專案、匯入資料、開研究、執行可執行的檢查、經治理程序改變信念、到中文結果頁與可匯出的研究摘要，三種證據情境都跑通（§6）。
- 【事實】中文呈現可以：同一批紀錄，主畫面英文比例從約 60% 降到約 20%；剩下的英文只有括號內保留的英文術語與研究者自己輸入的問題；原始狀態代碼從 13–15 種降到 0（§3.4）。
- 【事實】未執行的模擬：每一頁都列出「以下檢查沒有執行，結果未知、未經驗證，也沒有以任何假設值代替」，三個情境的模擬工作（job）數皆為 0（§6）。
- 【事實】**真實語言模型端到端驗證沒有完成**：本機沒有任何模型通過主要推理所需的 ROLE_HYPOTHESIS 能力測試。這是精確的阻礙，不是成功（§2）。因此，目前的「最終報告」中的假說來自規則目錄，不是語言模型；在擁有者解除 §2.3 的阻礙並實跑之前，不能宣稱「LLM 研究流程已驗收」。

---

## 1. 交付內容與版本

| 提交 | 內容 |
|---|---|
| `3afee21` | 研究結果頁依研究者的問題順序重寫；領域包的策展中文；狀態值以文字呈現；未翻譯標示；本語言研究摘要匯出；驗收測試 |
| `4bc1505` | 驗收測試加上「證據可追溯到上傳的資料」；刪除已無呼叫者的 `EpisodeView.falsifiers`，並把守護它的突變改指向新程式；證據檔 |
| `db67209` | 真實模型測試可由擁有者自行指定外部主要推理模型（金鑰只放在擁有者設定的環境變數） |
| `3b472fe` | 格式修正 |
| REVIEW_SHA | 審查發現的修正（§5.3） |
| REPORT_SHA | 本報告與證據 |

CI：見 §5.5。

---

## 2. Priority A — 真實語言模型端到端驗證

### 2.1 阻礙（精確）

【事實】主要推理欄位（REASONING_PRIMARY）要求模型通過 CHAT、STRUCTURED_JSON、ROLE_HYPOTHESIS、ROLE_SPECIALIST（`src/lab_brain/llm_runtime/capabilities.py` 的 `SLOT_REQUIREMENTS`）。目前的探測版本是 `probe-6.0.0`（`src/lab_brain/llm_runtime/probes.py`）。

本機 Ollama 只有 `qwen2.5:7b`、`qwen2.5-coder:7b`、`qwen2.5-coder:1.5b-base`、`nomic-embed-text`；機器沒有 NVIDIA GPU，記憶體 31.6 GB。

部署資料庫的能力探測紀錄（唯讀查詢，`evidence/deployment_probe_records_probe-6.0.0.txt`）：

| 模型 | ROLE_HYPOTHESIS（probe-6.0.0） | 原因（探測紀錄原文摘要） | ROLE_CRITIQUE |
|---|---|---|---|
| qwen2.5:7b | FAILED（2026-10-13） | 假說 'h1' 沒有指定型別化的否證預測 | PASSED |
| qwen2.5-coder:7b | FAILED（2026-10-13） | 指定的否證預測 relation_effect 是 SUPPORTS，不是 CONTRADICTS | PASSED |
| gemini-3.1-pro-preview（外部） | PASSED（2026-10-13） | — | FAILED：'CONTRADICTS' 不是有效的 ObjectionKind |

【事實】本分支上重新實跑一次（`tests/e2e/test_research_live_model_postgres.py`，`LAB_BRAIN_LIVE_PRIMARY=qwen2.5:7b`，新建的測試資料庫，本機推論，8 項探測全跑，歷時 8 分 28 秒）：

- qwen2.5:7b 的 ROLE_HYPOTHESIS 仍 FAILED，原因：「hypothesis 'h1' carries no typed prediction」（假說沒有附帶型別化預測）；
- 主要推理欄位因此拒絕綁定，研究沒有執行；測試以「BLOCKED: REASONING_PRIMARY refuses qwen2.5:7b」結束；
- 證據：`evidence/live_model_qwen2.5-7b/probes.json`、`pytest_tail.log`。

這正是應有的行為：沒有通過資格的模型不會被拿來做研究，系統也沒有用規則推理器或假回應代替。

### 2.2 已備妥、可直接執行的真實模型驗收

【事實】`tests/e2e/test_research_live_model_postgres.py`（未設定時自動略過）：

- 經由網頁介面新增連線、8 項探測、鎖定、綁定欄位、啟用；任何欄位拒絕時，以探測原因報告阻礙並停止；
- 三個情境（充分／不足／競爭證據）實跑研究；
- 檢查：每一筆推論來源紀錄（InferenceProvenance）都是指定的模型；沒有任何模擬工作；若有「已確認」，被確認的假說必須自己事先宣告過該觀察結果；中文頁面由來源紀錄列出推理模型；
- 設定 `LAB_BRAIN_LIVE_EVIDENCE=<目錄>` 時，寫出探測、推論來源列（含模型原文輸出）、每個情境的中文頁面與摘要，供稽核。

### 2.3 需要擁有者決定（擇一）

| 選項 | 做法 | 代價與風險 |
|---|---|---|
| (a) 外部主要推理 | 主要推理用 Gemini（已在 probe-6.0.0 通過 ROLE_HYPOTHESIS），批判與快速處理用本機 qwen2.5:7b（已通過 ROLE_CRITIQUE、ROLE_QUERY）。擁有者自行設定金鑰環境變數後執行：`LAB_BRAIN_LIVE_PRIMARY=models/gemini-3.1-pro-preview LAB_BRAIN_LIVE_PRIMARY_PROVIDER=gemini LAB_BRAIN_LIVE_PRIMARY_KEY_ENV=<變數名> LAB_BRAIN_LIVE_CRITIC=qwen2.5:7b LAB_BRAIN_LIVE_UTILITY=qwen2.5:7b` | 測試專案的證據（儲存庫內的範例報告，不是實驗室資料）會送到 Google；可能產生 API 費用；測試先以專案自己的頁面宣告外送 |
| (b) 下載較大的本機模型 | 例如 14B 等級模型（約 9 GB），以 8 項探測完整測一次；通過才綁定 | 需要擁有者同意下載；CPU 推論慢（7B 的單項假說探測約 4 分鐘，14B 估計加倍）；不保證通過 |
| (c) 接受阻礙 | 以本報告為準，真實模型驗收延後 | 無法宣稱 LLM 研究流程已驗收 |

我沒有自行選擇：(a) 涉及外送與費用，(b) 涉及下載，都需要擁有者明確同意。

---

## 3. Priority B — 研究者的繁體中文

### 3.1 做法

- 【事實】領域包附上策展的對照表：`src/lab_brain/domains/silicon_photonics/presentation.py`。以**英文原文本身**為鍵；名稱保留英文術語，例如「網格收斂假象（mesh convergence artifact）」。版本名 `sp.presentation@1.0.0 (curated; awaiting the laboratory's review)`。
- 【事實】`ProductVertical` 多了 `presentation` 與 `presentation_ref`，只供呈現；推理、驗證、重播都不讀它。
- 【事實】網頁的 `Terms` 依原文查表：
  - 有策展翻譯：顯示中文；
  - 沒有（例如語言模型自己寫的文字、尚未翻譯的新句子）：**照原文顯示，並標示「（未翻譯，顯示英文原文）」**，頁首計數，稽核層列出原文對照；絕不猜測。
- 【事實】儲存的狀態值（假說狀態、結論、檢查狀態、轉移決定、步驟）一律以文字呈現；原值放在提示（tooltip）與稽核層。
- 【事實】紀錄不變：完整報告仍以原文放在稽核層；`report.md` 匯出不變。

### 3.2 匯出

- 【事實】新路徑 `/episodes/<id>/runs/<n>/summary.html`：依讀者語言輸出研究摘要，標明是「衍生文件」，列出：
  - 來源：製作當下 `report.md` 匯出的 SHA-256；
  - 使用的翻譯版本、以英文原文顯示的段落數、推理來源（依推論來源紀錄）、製作時間；
  - 翻譯與原文對照表。
- 【事實】存取規則與 `report.md` 相同（只有研究開啟者；其他人 404；ADMIN 只能經由 `/admin` 稽核頁閱讀）。已加入存取矩陣測試。

### 3.3 已知限制

- 【事實】策展翻譯尚未經實驗室的領域專家審閱；版本名明示這一點。
- 【未做】語言模型產生的文字沒有機器翻譯：一律照原文並標示。若要翻譯，需另做「衍生翻譯＋來源紀錄＋驗證」的設計（建議另開工作）。

### 3.4 量測（同一批紀錄，改版前後）

【事實】`evidence/language_coverage_before_after.txt`；資料庫 `lab_brain_acc_ui`，同樣三個研究任務，只換程式版本：

| 情境 | 改版前（`f3fadf6`）英文比例 | 改版後（`3afee21`） | 去掉括號術語後 | 再去掉研究者自己的問題與專案名 | 可見原始狀態代碼 |
|---|---:|---:|---:|---:|---|
| 充分證據 | 60.4% | 21.2% | 4.8% | 0.0% | 13 種 → 0 |
| 不足證據 | 58.5% | 18.7% | 4.7% | 0.9% | 13 種 → 0 |
| 競爭證據 | 60.3% | 20.6% | 4.7% | 0.9% | 15 種 → 0 |

計算方式：主畫面（不含收合層、程式碼）中，連續三個以上英文單字的字元比例。0.9% 是「Lumerical DEVICE/CHARGE」這個產品名稱。

---

## 4. Priority C — 研究結果的介面

### 4.1 主畫面順序（依任務要求）

1. 研究問題與目前結論（含「已獲支持／尚未判定／已排除」）；
2. 互相競爭的假說與各自的證據狀態（比較表）；
3. 實際做了哪些檢查、觀察到什麼；
4. 支持或挑戰各假說的證據（每個假說：主張、事先宣告的預測、支持與挑戰的觀察）；
5. 為什麼能（或不能）下結論；
6. 下一步該做什麼（最佳檢查、為何無法執行、需要什麼、它的結果可以判定什麼）。

每一行標示種類：假說、預測、觀察、解讀、已確認的發現（只有「已確認」的結論帶最後這個標記）。來源紀錄、識別碼與診斷資訊在可展開的「證據與推理」「稽核與來源紀錄」兩層。

### 4.2 瀏覽器實測

【事實】`evidence/browser_check.txt` 與 `evidence/screenshots/01..23`：

- 內建瀏覽器（Chromium），帳號模式、新建資料庫、經由應用程式寫入的三個案例；
- 中文與英文、桌面（1024 寬）與手機（375 寬）；
- 手機與桌面都沒有橫向溢出；摘要匯出沒有任何表單。
- 檢查中發現並修正：「尚未判定」原本與「獲得支持」同為綠色，容易誤讀；已改為中性灰。

【未做】其他瀏覽器、列印版面、螢幕閱讀器。

---

## 5. Priority D — 驗證

### 5.1 新增與更新的測試

- 【事實】`tests/unit/test_research_reading.py`（11 項）：中文主畫面、英文、模型文字未翻譯標示、紀錄不變與原文對照、行的種類、「為什麼不能下結論」（開放假說、從未執行的檢查、支持不等於確認、證據矛盾、確認的依據）、由來源紀錄列出語言模型、未執行檢查「可以判定什麼」來自事先宣告的預測、摘要文件。
- 【事實】`tests/unit/test_sp_presentation.py`（3 項）：目錄每個名稱、主張、否證、檢查、觀察量、結果都有中文；名稱保留英文術語；宣告連結的摘要值（digest）不變。
- 【事實】`tests/e2e/test_research_acceptance_without_lumerical_postgres.py`（4 項，PostgreSQL）：完整流程與三種證據情境、證據可追溯、摘要來源雜湊、續跑後第 1 次執行的畫面不變、非成員 404。
- 【事實】`tests/e2e/test_research_live_model_postgres.py`（1 項，需設定才執行，§2.2）。
- 【事實】更新的既有測試：`tests/unit/test_episode_view_page.py`、`tests/e2e/test_web_episode_view_postgres.py`、`tests/e2e/test_web_research_data_postgres.py` 改為比對新版文字；每一項原本守護的性質都保留（例如仍以資料庫的列逐筆比對頁面上的檢查、觀察與信念轉移）。`tests/security/test_web_access_matrix_postgres.py` 新增摘要路徑。

### 5.2 執行結果

- 【事實】不需資料庫的完整測試：1897 通過、1025 略過（需後端）、0 失敗。
- 【事實】ruff、ruff format、mypy strict 通過；狀態檔已更新。
- 完整 PostgreSQL 測試：FULL_PG
- 【事實】突變測試（`scripts/mutation_battery.py`）：本輪相關的 24 項全部被抓到（11 項新增、13 項既有的研究頁與語言項目，其中 4 項因改版而改指向新程式）；沒有因語法錯誤造成的假擊殺。`evidence/mutation_battery_reading.log`。
- 【事實】migration：本輪沒有新增 migration；完整 PostgreSQL 測試從空資料庫套用全部 69 個 migration。

### 5.3 獨立範圍審查

REVIEW

### 5.4 先前的保護是否保留

- 【事實】註冊安全、ADMIN 全實驗室稽核閱讀、成員隔離、研究證據不可變、簽章審查：相關測試都在完整套件內並通過（§5.2）。
- 【事實】SP 1.1.0 未啟用；`READY_FOR_REAL_RESEARCH` 未改。

### 5.5 CI

CI

---

## 6. 三個證據情境（不需 Lumerical，規則式目錄推理器）

| 情境 | 裝置專案 | 結果 | 頁面怎麼說 | 模擬工作數 |
|---|---|---|---|---:|
| 充分 | 陰極通孔未連到金屬（contact-open-via） | 已確認：存取區接點不連續 | 支持的觀察（接點連通性＝不連續）；依據 1 項可驗證的診斷依據；已被否證的對立假說；**限制：從未檢驗的對立假說**（摻雜補償、探針接觸、網格收斂） | 0 |
| 不足 | 設計正常（probe-artifact） | 尚未確認 | 兩個假說被設計檢查否證；三個仍待判定；兩項模擬無法執行、結果未知；四點探針需人員執行 | 0 |
| 競爭 | 通孔未連＋正規化長度 1000 µm | 尚未確認 | 兩個對立假說各自獲得自己的觀察支持，「證據無法指出單一原因」；支持不等於確認 | 0 |

【事實】三者都由 `tests/e2e/test_research_acceptance_without_lumerical_postgres.py` 自動檢查，也有截圖（§4.2）。

---

## 7. 剩餘阻礙與風險

1. **真實語言模型驗收未完成**（§2）。需要擁有者選 (a)、(b) 或 (c)。
2. Lumerical：沒有授權的提供模組與席位；所有模擬維持「未執行、未驗證」。
3. 策展中文尚未經實驗室領域專家審閱。
4. 語言模型產生的文字不翻譯，只標示。
5. 研究紀錄列表頁的「結果」欄對等待中的研究顯示「-」（本輪未改，候選）。
6. 截圖由瀏覽器窗格自動縮放；未測其他瀏覽器、列印與螢幕閱讀器。

---

## 8. 本輪沒有做的事（依界線）

未合併、未部署、未改正式資料（部署資料庫只做唯讀查詢）、未產生付費 API 費用、未下載模型、未執行 Lumi Agent、未捏造模擬結果、未改 `READY_FOR_REAL_RESEARCH`、未自我認證就緒。
