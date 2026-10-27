# WP4 — G0 科學雙語就緒度稽核（G0-A、G0-B、G0-P）

日期：2026-10-27　分支：`g0-offline-integrity-closure`　範圍：離線（無網路模型、無付費 API、
無 Lumerical、無機器翻譯）。

## 結論先講

- **結構上的雙語一致性（structural parity）可以離線驗證**，本次已建成檢查器並在真實 research
  episode 上通過（頁面、摘要匯出，英文與繁中，含 Chromium 實際渲染）。
- **LLM 撰寫之科學文句的雙語語意品質：NOT VERIFIED。** 離線只能確認數字、單位、正負號、ID、
  狀態、否定、確認主張與覆蓋率一致；無法確認一句流暢的中文是否真的等於英文原意。這需要獨立的
  雙語審查者（含領域資格）。pack 的策展翻譯本身也註明「尚待實驗室領域專家審閱」
  （`sp.presentation@1.0.1` 的 `@note`）。
- G0 整體不因本 WP 變成 PASS：G0-B 需要「獨立雙語審查＋結構化 parity」，本 WP 只交付後者；
  另有下列兩項已證實的缺口需要產品決策。

## 檢查器

`src/lab_brain/interfaces/web/bilingual_parity.py`（純函式；只有 `canonical_snapshot` 讀資料庫）。
放在 `interfaces.web` 而不是 `research`，因為它讀 `i18n` 的產品詞彙表，研究層不應依賴介面層。

| 檢查 | 內容 | 依據 |
|---|---|---|
| STRUCTURE / COVERAGE / NON_EMPTY | 每個 `v-*` 區段拆成 block（p、li、td、h2/h3、blockquote、狀態/標籤/ID span），依文件順序對齊；形狀不同即報；九類內容（假說、預測、觀察、解讀、結論、不確定性、限制、引用、下一步）逐類計數；英文非空的欄位繁中也必須非空 | `pages._tag`、`pages.status`、`Terms.name` 的 markup |
| NUMBERS | 每個對齊 block 的數值＋正負號＋單位為相同 multiset（ID 與 digest 先移除） | |
| IDENTIFIERS | tooltip（`title`）、`<code>`、文中 ID/sha256 相同 | |
| STATUS | 狀態 span 的儲存值相同，且顯示文字等於產品 `i18n` 表該值的詞（不猜翻譯） | `i18n.Messages(f"{family}.{value}")` |
| NEGATION / CLAIM | 去掉產品介面句（`i18n` 模板）後，報告內容的否定數與「確認」主張數相同；策展翻譯表（`v.l3.originals`）逐對比較 | `i18n.templates`、頁面上的原文對照表 |
| NOT_PERFORMED | 每個無法執行的模擬：有 `ws-BLOCKED` 狀態的 li，且有一個元素同時寫出它、原因、所需條件（繁中可用策展翻譯或原文） | `EpisodeReport.pending` |
| LANGUAGE / SINGLE_LANGUAGE | 繁中閱讀區段不得出現未標示的英文；繁中匯出不得整份沒有中文（回到單語） | `tr.untranslated` 標示 |
| CANONICAL | 渲染前後，資料庫每個表每一列的 SHA-256 相同 | `canonical_snapshot` |

刻意排除、且在程式碼中說明的地區差異：未翻譯標記本身、各語言的原文對照表、「以英文原文顯示的
段落數」（英文版依定義為 0）、「製作時間」列。

已知限制（檢查器本身）：否定詞是詞彙表比對（英文 not/no/never/un-… 與中文 不/沒/未/無/非/否，
並排除「否證」等詞）；不檢查 may/likely/可能 這類語氣強弱；`interpretations` 在本次兩個 e2e
案例中為 0，對該類別的覆蓋檢查只有單元測試證據。

## 稽核表

狀態：IMPLEMENTED+TESTED／IMPLEMENTED-UNTESTED／MISSING／NOT VERIFIABLE OFFLINE。

### G0-A authenticated workflow

| 條件 | 狀態 | 證據 |
|---|---|---|
| 帳號登入後才能使用；未登入一律導向登入 | IMPLEMENTED+TESTED | `app.py:176`（`SESSION_COOKIE`）、`app.py:2319-2384`；`tests/e2e/test_web_accounts_postgres.py:84`、`tests/security/test_web_access_matrix_postgres.py:387` |
| 依 project membership/clearance 開啟 episode、讀報告與匯出 | IMPLEMENTED+TESTED | `app.py:2228-2260`（`_opened`：opener＋`authorize_project`＋012q clearance）；access matrix `_OPENER_ONLY`（`report.md`、`summary.html`，`tests/security/test_web_access_matrix_postgres.py:62-63,346`） |
| 拒絕跨專案／非成員（兩種語言） | IMPLEMENTED+TESTED | 本 WP：`tests/e2e/test_g0_bilingual_parity_postgres.py`（非成員在 en、zh-TW 讀頁面/摘要/report.md 皆 404 且不洩漏問題文字） |
| ADMIN 不自動取得科學寫入/審查權 | IMPLEMENTED+TESTED | `tests/e2e/test_web_accounts_postgres.py:524-630`（ADMIN 只讀、每次讀取有紀錄、不能開始/續跑研究） |
| 保存 actor/project/run/trace | IMPLEMENTED+TESTED | `migrations/012c_research_runs.sql:28-50`（actor_id、project_id）；`research_episodes.trace_id` |
| 保存 session 的非秘密稽核 ref（與 run 綁定） | **MISSING** | `research_runs` 沒有 session 欄位（`migrations/012c_research_runs.sql:28-50`）；`account_sessions.session_hash`（`migrations/012u_accounts.sql:150`）沒有連到任何 run。本 WP 不可改 migrations。 |
| 續跑/匯出在帳號模式下 | IMPLEMENTED+TESTED | `tests/e2e/test_research_acceptance_without_lumerical_postgres.py:277` |

### G0-B bilingual science/export

產品提供的匯出：`report.md`（`app.py:1322`，`render.render_markdown`，`render.py:27`）與
`summary.html`（`app.py:1358`，`pages.summary_document`，`pages.py:2443`，依請求語言）。頁面：
`pages.episode_page`（`pages.py:2311`）。

| 條件 | 狀態 | 證據 |
|---|---|---|
| 頁面：八類內容 en／zh-TW 結構對應、適用非空欄位 100% | IMPLEMENTED+TESTED | 本 WP e2e：頁面約 860 個 block 對齊、0 finding；單元測試涵蓋 `pages.episode_page` |
| 摘要匯出（summary.html）同上 | IMPLEMENTED+TESTED（修正後） | 同上；修正見「已證實缺陷 1」 |
| 數值/單位/正負號/ID/狀態/否定/確認主張一致 | IMPLEMENTED+TESTED（結構層） | `tests/unit/test_g0_bilingual_parity.py`（翻轉正負號、換單位、刪否定、提高狀態、加確認句皆被抓到）；e2e 真實資料 0 finding |
| 不確定度、條件的「語意」一致 | NOT VERIFIABLE OFFLINE | 只能檢查數字與否定詞；條件句的意義需雙語審查 |
| 翻譯不新增觀察、不提高 authority | IMPLEMENTED+TESTED（結構層） | 單元測試：只在繁中多一個觀察 → STRUCTURE＋COVERAGE；狀態值或狀態詞被提高 → STATUS |
| 只翻譯標籤／科研正文只有一語 | IMPLEMENTED+TESTED（偵測） | 繁中區段若有未標示英文 → LANGUAGE；整份無中文 → SINGLE_LANGUAGE。模型文字無策展翻譯時，產品以原文顯示並標「未翻譯」（`pages.py:534` `Terms`，`i18n.py:932`），e2e 驗證有標示 |
| **所有匯出格式皆雙語** | **MISSING（已證實，缺陷 2）** | `report.md` 在任何語言都是同一份英文（逐位元相同）。`tests/e2e/test_g0_bilingual_parity_postgres.py::test_the_markdown_export_reads_in_the_readers_language` 為 strict xfail |
| **引用（citations）在繁中匯出中** | **MISSING（已證實，缺陷 3）** | `summary.html` 只含 L1，沒有任何來源摘錄（檢查器 coverage `citations` = (0, 0)）；唯一帶引用的匯出是英文 `report.md`。頁面上 L2（`pages.py:1709`）有引用 |
| canonical hashes/簽章/事件不變 | IMPLEMENTED+TESTED | 本 WP e2e：渲染兩種語言、兩條路徑（WSGI、Chromium）、非成員被拒後，所有表的每一列 SHA-256 不變；`research_run_reports` 原文不變；摘要所載 `report.md` digest 不變 |
| 獨立雙語審查 | NOT VERIFIABLE OFFLINE | 需要合格的雙語審查者；本 WP 不能也沒有代替 |

### G0-P provenance and honest scope

| 條件 | 狀態 | 證據 |
|---|---|---|
| 每項無法執行的模擬標示為未執行（NOT_PERFORMED），附原因與所需條件，兩種語言 | IMPLEMENTED+TESTED（修正後） | 產品用語是狀態 `BLOCKED`（`i18n` `ws.BLOCKED`「cannot run here／無法在此執行」）＋「not run; result unknown」（`i18n.py:771`），`report.md` 的 `## Pending simulation actions`（`render.py:226`）與 `Not performed:`（`render.py:266`）。缺陷 1 修正後，頁面與摘要對每一項都寫出原因與所需條件 |
| 無偽造 solver Run/result | IMPLEMENTED+TESTED | `tests/e2e/test_research_acceptance_without_lumerical_postgres.py:154`（模擬 capability 無任何 job） |
| 原始 canonical records 前後 hash 不變；原文不被翻譯覆寫 | IMPLEMENTED+TESTED | `Terms` 只查表、不寫入（`pages.py:534`）；本 WP e2e 全表快照比對 |
| observation/citation 回查 ArtifactOccurrence/SourceWork/EvidenceUnit、locator/hash；InferenceProvenance | IMPLEMENTED+TESTED（既有測試；本 WP 未深入重審） | `tests/e2e/test_research_acceptance_without_lumerical_postgres.py:125-131`（attestation 指向來源 artifact）、`:154-171`（inference_provenance）；頁面引用列出 attestation ID 與 locator，檢查器確認兩語相同 |

## 已證實的缺陷（demonstrated）

1. **摘要匯出與頁面 L1 只對「最佳下一步」模擬寫原因與所需條件（G0-P）——已修正。**
   其他同樣無法執行的模擬只有「同樣無法在這裡執行：X」，沒有原因與條件；這份摘要是唯一的
   繁中匯出。先寫失敗測試
   `tests/unit/test_g0_bilingual_parity.py::test_the_exported_summary_names_why_every_unavailable_simulation_did_not_run_in_both`
   （真實 e2e 資料中 `cap:sp.charge_dc_sweep` 也一樣），再最小修正
   `src/lab_brain/interfaces/web/pages.py:1646-1667`（`_next_html`：每一項都加上
   `v.blocked_because`，沿用既有 i18n 句子，不新增翻譯）。
2. **`report.md` 回到單語（G0-B 失敗條件「匯出回到單語」）——未修正，需要產品決策。**
   它是正式紀錄的匯出，摘要以它的 SHA-256 為來源（`i18n.py:158-166`、`pages.py:2443`）。
   改成繁中版需要整份 Markdown 的繁中渲染（`render.py` 全是英文模板），不是最小修正；
   也要決定 digest 指向哪一份。以 strict xfail 記錄。
3. **繁中匯出沒有引用（citations）——未修正，需要產品決策。** `summary.html` 依設計只含 L1；
   引用只在頁面 L2 與英文 `report.md`。
4. **G0-A：沒有把 session 的非秘密稽核 ref 綁到 research run。** 需要 migration，不在本 WP 範圍。

## 次要觀察（demonstrated，但不屬科研正文，未修正）

- 繁中頁面 L3「完整報告」（`report_html`）有寫死的英文詞：`licence`、`kept`、`status`、
  `not admitted`（`pages.py:2656`）、`job`、`run`（`pages.py:2807`），沒有標示未翻譯。L3 已聲明
  報告內容依原文保存（`i18n.py:158`），但這些是介面詞，不是報告內容。
- 摘要的「以英文原文顯示的段落數」不計入使用者自己輸入的研究問題（英文、未標示）。研究問題
  是使用者原文，不是科學內容。

## 假設性風險（hypothetical，未證實）

- 策展翻譯若語意錯但數字/否定/ID 都對，檢查器不會發現（見 NOT VERIFIED）。
- 語氣強弱（may／likely／可能／確定）沒有被比對；只比對「確認」與狀態值。
- 真實 LLM 輸出的英文文句若含大量 un-/dis- 字首詞，在繁中「以原文顯示」時兩邊計數相同，
  不會誤報；但若未來對 LLM 文字做機器翻譯，否定詞表可能需要擴充。

## 測試與指令

```
.venv/bin/python -m pytest -q tests/unit/test_g0_bilingual_parity.py
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_wp4 \
  .venv/bin/python -m pytest -q tests/e2e/test_g0_bilingual_parity_postgres.py
```

e2e 內含 Chromium（node `playwright`，`javaScriptEnabled: false`）經 socket 讀取兩種語言的頁面與
摘要並通過同一檢查；若 node 或 playwright 不存在則 skip。

## NOT VERIFIED

- LLM 撰寫之科學文句的雙語語意品質（需獨立雙語審查者）。
- 策展翻譯（`sp.presentation@1.0.1`）的領域正確性（pack 自註尚待領域專家審閱）。
- 真實 LLM（G0-L）下的雙語輸出：本 WP 只用規則式目錄推理器與 `tests.g0_standin` 替身。
