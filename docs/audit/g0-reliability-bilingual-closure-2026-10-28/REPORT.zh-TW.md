# G0 科學可靠性與雙語研究收尾報告

日期:2026-10-28
分支:`g0-reliability-bilingual-closure`
起點:`g0-offline-integrity-closure` @ `2e6962ee41cbfd70b22f8867b672bd042832814a`(與遠端相同、工作區乾淨,改動前已確認)
狀態:**工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。**

三件事分開寫,不可混用:

| 類別 | 本次狀態 |
|---|---|
| 工程成功(離線測試、CI) | 見 §6 |
| 真實 LLM 研究表現 | **沒有執行**。只有提案(§5) |
| 物理驗證 | **沒有**。沒有 Lumerical、沒有量測 |

## 0. 成本

零額外付費:沒有付費 API、沒有付費 runner、沒有 Lumerical、沒有外部模型呼叫。
CI 用公開 repo 的免費 runner。

## 1. 審查員指出的評估缺陷(全部先重現,再修正)

證據:`evidence/scorer-1.0.0-defects.txt`(合成紀錄在 scorer 1.0.0 上的結果)。

| # | 缺陷 | 1.0.0 的結果 | 2.0.0 的修正 |
|---|---|---|---|
| 1 | 篩檢後假說得到**合法的**前瞻支持也被扣分 | 前瞻支持 → `no_post_screening_support` 失敗;以它確認 → 假確認 | 每個支持都附上 4+1 個來源事實(由評估端從 canonical 資料列讀出,不信任受測系統的判定)。只有**不可採用**的支持才失敗;有可採用支持的確認不算假確認 |
| 2 | 篩檢前的發現與篩檢後的發現混在一起 | `considered` 算進篩檢後才提出的假說 | 分成 `considered_pre_screening` 與 `considered_with_screening`,並計 `screening_discoveries` |
| 3 | 正確的科學結論被當成洩漏 | 輸出寫出真因 → `no_leak` 失敗 | 分成 `no_input_leak`(真值出現在送給模型的輸入,任何長度都算)與 `no_secret_in_output`(輸出中出現案例 id 或 ≥8 字的評估者原文)。輸出說出答案是成功,不是洩漏 |
| 4 | 格式錯誤的輸出 | 少一個欄位 → **評分程式崩潰**(KeyError),整批沒有分數 | `record_problems` 先驗證每個欄位的型別與詞彙;任何錯誤 → 該案例 MALFORMED 並寫原因,仍留在分母,所有適用指標算失敗;評分程式不會因輸出而拋例外 |

另外新增兩個 G0-S 相關的推理指標:`competing_pre_screening`(篩檢前至少 2 個鑑別不同觀測量的競爭假說)、
`refutable`(每個假說至少有一個可反駁它的 CONTRADICTS 預測)。

**舊矩陣協定(已曝光的回歸案例)**:`benchmarks/g0_screening/protocol-amendment-2.json`。
門檻值不變;修正指標定義、新增「malformed 必須為 0」。這個協定的 `leak` 原本就只看提示,所以缺陷 3 不在它身上。
Stand-in 模型的矩陣結果:`evidence/matrix-standin-amendment-2.md`,8 列全部 PASS。拆開後看到以前看不到的事:
`screening` 設定下 dev 的 `considered` 是 0.833,但**篩檢前**只有 0.333,有 0.5 是篩檢的發現。
這是離線 stand-in 的數字,不是真實 LLM 表現。

## 2. 調查中發現的篩檢完整性缺陷(已證明並修正)

011m 的 guard 只檢查關係的來源實體,而且只在它是 observation 時才檢查;關係**引用的 attestation**(它真正的證據)從沒被讀。
在 011m 上先寫測試(證據:`evidence/cited-basis-before-011o.txt`),4 條繞過全部成功:

| 繞過方式 | 011m | 011o |
|---|---|---|
| 以被篩檢讀數的 attestation 當來源 | 通過(缺陷) | 拒絕 |
| 新 observation 引用被篩檢的 attestation | 通過(缺陷) | 拒絕 |
| 新 observation 引用重複檢查的 attestation | 通過(缺陷) | 拒絕 |
| 以另一個假說當來源 | 通過(缺陷) | 拒絕 |
| 之後內容真的不同、引用自己 attestation 的讀數(對照組) | 允許 | 允許 |

修正:`migrations/011o_screening_guard_reads_the_cited_basis.sql`。來源必須是 observation;每個引用的 attestation
必須屬於 observation;來源與每個被引用的 observation 都要通過 (a)(b)(c)(d)。只會更嚴格。
兩個舊測試 fixture 的「前瞻支持」原本引用被篩檢的 attestation,已改為引用新讀數自己的 attestation;斷言不變。

評估端的收集器(`lab_brain.evaluation.collect`)用同一套規則從資料列重新算出事實,所以分數不依賴 guard 一定成立:
在 guard 被關掉(在會回滾的交易內)寫入的不可採用支持,收集器仍然逐一標出。

## 3. 雙語報告與可稽核性

上一階段已證明、這次修正的缺陷(每個都先寫會失敗的測試):

| 缺陷 | 修正 |
|---|---|
| `report.md` 每種語言都是同一份英文(G0-B「匯出回到單語」) | 新增完整繁中科學匯出。內容來自產品自己的 i18n 詞彙與 pack 目錄;**沒有機器翻譯**。沒有審定譯文的 LLM 文字原樣顯示並標 〔英文原文，未翻譯〕;引用的證據標 〔原文引述，未翻譯〕;儲存值保留原值並在旁加中文(例 `BLOCKED〔無法在此執行〕`)。原本的 strict xfail 現在是通過的測試 |
| 繁中 `summary.html` 沒有引用 | 兩種語言的摘要與頁面都列出每個引用:attestation id、儲存的 locator、來源 artifact、內容 hash、專案 occurrence、source work、evidence unit 與其 digest,引文保持原文 |
| 繁中 L3 有寫死的英文詞(licence、kept、job、run 等) | 改用 i18n |

**網址與語言規則**:`report.md` 與 `summary.html` 跟隨讀者語言(cookie,預設英文);`?lang=en|zh-TW` 可指定,其他值回 404;
管理端匯出相同。英文 `report.md` 與之前**逐位元組相同**(測試釘住 golden SHA-256);繁中檔名為 `…run-N.zh-TW.md`。

**Digest**:canonical 資料不變。canonical digest 是英文紀錄匯出的 SHA-256;兩種語言的摘要都寫它,繁中 `report.md`
的開頭也寫它;每個摘要另寫自己語言 `report.md` 的 digest;每個匯出另有 RFC 9530 `Repr-Digest` header。

**結構對等檢查**擴充到 Markdown 匯出對、引用對等(CITATIONS)、原文保留(ORIGINAL,引文兩種語言逐位元組相同)、
session 來源詞。**Canonical 不變**:測試證明渲染、匯出兩種語言後每個資料表逐列相同,儲存的報告沒被修改。

**NOT VERIFIED**:LLM 寫的科學正文與審定譯文在兩種語言中是否同義。結構對等可以離線驗證;語意品質需要獨立雙語審查者。

## 4. 研究 session 來源(G0-A)

上一階段的缺口:session 的非秘密稽核 ref 沒有綁到研究執行。修正:`migrations/011n_research_session_provenance.sql`。

- 每個 session 有獨立的隨機 `session_audit_ref`(`sar:` + 32 hex),**由資料庫**在建立 session 時用 `gen_random_uuid()` 產生,
  寫入端給的值一律丟棄,之後不能改。登入仍只靠 `session_hash`;知道 ref 不能登入。原始 token 與 `session_hash` 從不複製到研究紀錄、報告或匯出。
- `research_runs.run_origin` 必填、沒有預設:`WEB_SESSION`(要 ref)、`OPERATOR_WORKSPACE`、`OPERATOR_CLI`、`LEGACY_UNATTESTED`(只給舊資料)。
- `WEB_SESSION` 的執行若 session 不屬於同一人、帳號不是 ACTIVE、session 已撤銷/過期/閒置、執行早於 session、或此人不是專案有效成員
  (含 clearance),**資料庫拒絕**。ADMIN 角色不給任何科學權限。
- 來源欄位不能改、不能刪;之後撤銷 session 不會改動已記錄的執行。報告必須帶自己執行的來源,且全文不可含任何 `session_hash`。
- 稽核 view `research_run_session_audit`:actor、project、run、episode、trace、origin、ref,沒有 hash。
- 兩種語言的頁面、`summary.html`、`report.md` 都顯示這個非秘密來源區塊,並說明 OPERATOR/LEGACY 來源**沒有**登入證明。

限制:`OPERATOR_*` 可由任何有資料庫權限的人宣告,所以標示為「未證明」而不是被阻止;只有 `WEB_SESSION` 能當 G0-A 證據。
資料庫超級使用者仍可關掉 trigger。有效性用資料庫時鐘判斷。

## 5. 真實 LLM 評估提案(未執行)

`docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md`:分階段、每階段有呼叫數與 token 上限、停止規則、金額上限公式
(建議階段 0+1 上限 USD 25;路由沒有宣告單價,所以不自行估價)。
累計上限現在由程式執行(`lab_brain.evaluation.live_budget`):外部模型沒設上限就在第一次呼叫前拒絕;
每個情境前從資料庫算已用量,未回報用量的呼叫按上限計。

## 6. 驗證

全部在本機免費資源執行(Python 3.13、PostgreSQL 16 + pgvector、本機 Chromium)。證據在 `evidence/`。

| 項目 | 結果 |
|---|---|
| 靜態檢查:`ruff check`、`ruff format --check`(src tests scripts)、`mypy src` | 全部通過(275 檔) |
| 規格測試 `pytest tests/spec` | 245 passed |
| 不需資料庫的完整回歸 `pytest -q` | 2205 passed, 1089 skipped(skip 的是要 PostgreSQL 的測試) |
| 新建資料庫(75 個 migration 到 011o)完整 PostgreSQL 回歸 | **3287 passed, 4 skipped**;另有 2 個 `test_status_freshness` 失敗,原因是狀態檔過期,已重新產生(之後 7 passed)。`evidence/full-postgres-suite.log` |
| 本階段新的單元測試(scorer 2.0.0、live cap、session、雙語匯出、對等) | 131 passed |
| 本階段新的 PostgreSQL 測試(獨立性、收集器、live cap、session、雙語匯出含 Chromium、對等、盲跑) | 29 passed |
| 篩檢矩陣(stand-in,修訂 2) | 8/8 PASS。`evidence/matrix-standin-amendment-2.md` |
| 缺陷先重現的證據 | `evidence/scorer-1.0.0-defects.txt`、`evidence/cited-basis-before-011o.txt` |
| **完整變異測試**(778 項) | 第一輪 777/778(55 分鐘);存活的 `sql_a_post_screening_support_cites_no_observation` 是**測試缺口**:沒有測試引用「不屬於 observation 的 attestation」。新增測試(引用報告 claim 的 attestation)後重跑 1/1 killed → **778/778**。`evidence/mutation-full-778.log` |
| GitHub CI | 見下 |

變異測試清單的整理:011m 的 (a)–(d) 項目被 011o 取代(guard 函式被替換),所以移除 4 個重複項、把 backend 項目改指 011o,
並新增 011o、011n、scorer 2.0.0、收集器、live cap、雙語匯出的項目;一個舊項目(`r11_the_summary_names_another_digest`)
因匯出程式碼改變而重新定位。

**CI**

CI_LINES

**Git 歷史沒有 AI 署名**:本分支每個 commit 的 author 與 committer 都是 `SpadesZ <rickiekuo1203@gmail.com>`,訊息沒有 trailer;
CI 的 commit 身分檢查通過,負向控制 annotation:「AI-authored history refused as expected」。

## 7. 剩餘限制

1. **沒有真實 LLM 結果。** 所有研究流程測試都用離線 stand-in 或 catalog reasoner。真實模型的表現未知。
2. **沒有獨立盲測集。** 22 個矩陣案例已曝光,只能當回歸證據。
3. **雙語語意品質 NOT VERIFIED。** 結構對等可離線驗證;LLM 正文與審定譯文是否同義,需要獨立雙語審查者。
4. **G0-S 有用性**需要具資格、獨立於產生者的審查者逐項判斷;新指標(競爭假說、可反駁性)只是必要條件。
5. `OPERATOR_*` 來源可被有資料庫權限的人宣告,所以只標示「未證明」;資料庫超級使用者仍可關閉 trigger。
6. 謊報「本機執行」的 backend:證據不採用,但已送出的資料收不回來(需要程序隔離或網路沙箱)。
7. 本機 PostgreSQL 16,CI 用 pg17。
8. 沒有物理驗證。

## 8. 剩餘 Owner Gates

1. 審查 scorer 2.0.0 的定義與協定修訂 2(門檻不變,指標定義修正)。
2. 審查 011o 的較嚴格規則(只有 observation 能支持篩檢後假說,引用的證據也要通過 (a)–(d))。
3. 審查 011n 的 session 來源設計;決定 OPERATOR 來源是否應該在正式環境被禁止。
4. 雙語匯出的網址/語言規則與 digest 決定(英文紀錄匯出為 canonical)。
5. 是否授權真實 LLM 評估(提案 §5:建議階段 0+1 上限 USD 25,需先在路由寫入官方單價)。
6. 指派獨立評估者建立封存盲測集、指派獨立的雙語與領域審查者。
7. 在 `main` 設定 branch rule,讓 commit 身分檢查成為必要關卡(上一階段已列出)。
8. 正式環境的篩檢與結構摘要仍關閉;`READY_FOR_REAL_RESEARCH` 未改。
9. G0 是否通過:只能由獨立審查決定。本報告**不**宣稱 G0 PASS。
