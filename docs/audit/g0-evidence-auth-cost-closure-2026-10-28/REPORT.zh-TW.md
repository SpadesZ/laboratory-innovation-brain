# G0 證據時間、驗證邊界與費用上限收尾報告

日期:2026-10-28
分支:`g0-evidence-auth-cost-closure`
起點:`g0-reliability-bilingual-closure` @ `7988ed77f4366d49a1929ca9588a1e048aea9468`(與遠端相同、工作區乾淨,改動前已確認)
狀態:**工程候選,停在 Independent Chief Auditor 關卡。G0 未通過。**

| 類別 | 本次狀態 |
|---|---|
| 工程成功(離線測試、CI) | 見 §5 |
| 真實 LLM 研究表現 | **沒有執行** |
| 物理驗證 | **沒有** |

成本:零。沒有付費 API、沒有付費 runner、沒有 Lumerical、沒有呼叫任何真實模型服務。

## 1. 風險 1:舊證據被當成新的獨立驗證(已證明並修正)

012y (b) 用 observation 的 `created_at`(資料庫寫入時間)判斷「前瞻」。在 011o 上先寫測試
(證據:`evidence/evidence-timing-before-011p.txt`),4 條路全部被接受為篩檢後假說的支持:

| 繞過方式 | 011o | 011p |
|---|---|---|
| 執行在假說**之前**就開始,observation 現在才寫入 | 接受(缺陷) | 拒絕 |
| 新執行的輸出資料**擷取時間**(`captured_at`)在多年前 | 接受(缺陷) | 拒絕 |
| 另一個檢查讀取**被篩檢的輸出**當輸入 | 接受(缺陷) | 拒絕 |
| 「查詢既有證據」類的檢查(`EXISTING_EVIDENCE_LOOKUP`) | 接受(缺陷) | 拒絕 |
| 之後真正的新檢查(對照組) | 接受 | 接受 |

修正:`migrations/011p_screening_support_is_prospective_in_time.sql`。來源與每個被引用的 observation 都要:
執行在假說之後開始;輸入/輸出沒有在假說前擷取的資料;不讀取在假說前開始的執行的輸出;
capability 已登記、且種類會產生新證據。未登記的種類一律拒絕(fail closed)。

**合法的回溯證據保留,但不升級**:同樣的舊證據仍可用 `CITES` 記錄在篩檢後假說上(測試證明),
也仍可支持篩檢**之前**形成的假說;只有「當作篩檢後假說的前瞻支持」被拒絕。

收集器新增 `retrospective_basis` 事實;scorer 2.1.0 把它算作不可採用。

**新發現(工程缺口,不是科學錯誤)**:研究流程從不把 vertical 的 capability 寫進 `capabilities` 表,
所以在目前產品中,篩檢後假說**無法**得到任何前瞻支持(fail closed 的結果)。
要開放這條路,需要把 capability 登記納入流程 —— 列為 Owner/工程待辦。

## 2. 風險 2:session 參照不等於已驗證的互動(已證明並強化)

先證明:以 Ada 登入,從資料庫讀出她有效的 `session_audit_ref`,直接插入一筆 WEB_SESSION 研究執行;
011n 接受,匯出顯示「已登入的網頁工作階段」,沒有任何限定。

修正:`migrations/011q_research_interaction_attestation.sql`、`src/lab_brain/security/interaction_attestation.py`。
- 網頁層在已登入且通過 CSRF 的「開始/接續」請求上,用 Ed25519 簽一份標準化陳述(執行、episode、trace、
  執行者、專案、session 參照、路由、方法、簽署時間、一次性 nonce)。私鑰只在網頁層;公鑰釘選在資料庫**之外**,可用 `until=` 換鑰。
- 資料庫 CHECK 要求陳述欄位等於這一列;nonce 只能用一次;寫入後不能修改、補上或刪除。
- 驗證在 Python 端,每次顯示時重新計算。
- 四個宣稱等級:`INTERACTION_VERIFIED`(唯一可說「來自已驗證的互動」)、`SESSION_RECORDED_UNVERIFIED`、
  `OPERATOR_UNATTESTED`、`LEGACY_UNATTESTED`。頁面、摘要、`report.md` 兩種語言都寫出等級與「沒有證明什麼」;
  新的 `AUTH_CLAIM` 對等檢查擋下任何語言的過度宣稱。沒設金鑰時仍記錄,但等級是未驗證。

**仍然受信任的部分**:持有網頁層簽章金鑰或能改部署設定的人可以讓執行通過驗證;
**A12 沒有被解決,仍是 Owner 決定**;被偷的 session cookie 經真正的網頁層使用,會產生已驗證的互動(這是身分驗證風險,不是來源風險)。
細節:`auth-boundary.md`。

## 3. 風險 3:金額硬上限(已設計並實作,未用真實服務測試)

稽核:`cost-path-audit.md`,13 條可能計費的路徑(含 file:line)。已證明的缺口:
chat 請求**沒有 `max_tokens`**(輸出無上限);需要上限時遠端請求仍會送出;結構化輸出被拒會變成兩個計費請求;
資格探測不記錄用量;逾時沒有留下任何用量紀錄。

修正:`migrations/011r_llm_spend_ceiling.sql`、`src/lab_brain/llm_runtime/spend.py`、`provider.py`。
- 所有對遠端端點、有內容的請求,都在唯一的出口 `OpenAICompatibleClient._request` 先過金額檢查。
- 最壞金額 = (輸入上界 × 輸入單價 + `max_tokens` × 輸出單價)/ 1,000,000;
  輸入上界 = 請求內容位元組數 × 安全倍數(≥1)+ 圖片配額 + 固定額外量(假設一個 token 至少一個位元組)。
- 每個請求都送 `max_tokens`;沒有就拒絕。
- 在 PostgreSQL 鎖住預算列後原子預留;多行程/多執行緒不會超過上限。
- 沒有用量、用量格式錯、HTTP 錯誤、逾時、連線錯誤 → 保留最壞金額。
- 回報用量超過預留 → OVERRUN,依較大值收費並**斷路**,之後所有遠端請求被拒,直到 Owner 重設。
- 帳本只能附加,只有 `llm_spend_*` 函式能寫;不記錄金鑰或提示內容。
- 真實 LLM 評估:外部模型沒有上限、幣別、兩個單價、價格來源與日期 → 第一次呼叫前拒絕。
- 正式網頁環境:預設行為不變;`LAB_BRAIN_LLM_SPEND_REQUIRED=1` 才強制。是否在正式環境強制 —— **Owner Gate**。

**剩餘假設(需 Owner 對每個服務確認)**:服務商遵守 `max_tokens`(含推理/thinking token);
token ≥ 1 位元組;宣告的價格正確。違反時只能在那一次請求付費之後發現並斷路。
建議另外在服務商端設定預算警示,作為第二層防護。

## 4. 變異測試證據的對帳

上一份報告寫「778/778」,但它的證據檔是一次 777/778 的完整執行,加上另一次 1/1 的重跑 —— 兩個檔案,不是一次完整執行。
這次在最終程式碼上重新跑**一次完整的**變異測試,結果與證據檔一一對應,見 §5。

## 5. 驗證

全部在本機免費資源執行。證據在 `evidence/`。

| 項目 | 結果 |
|---|---|
| 靜態檢查:`ruff check`、`ruff format --check`(src tests scripts)、`mypy src` | 全部通過(277 檔) |
| 規格測試 `pytest tests/spec` | 245 passed |
| 不需資料庫的完整回歸 | 2233 passed, 1117 skipped |
| 新建資料庫(78 個 migration 到 011r)完整 PostgreSQL 回歸 | **3342 passed, 4 skipped**(另 2 個狀態檔過期,已重新產生)。`evidence/full-postgres-suite.log` |
| 風險 1 先重現的證據 | `evidence/evidence-timing-before-011p.txt`(5 失敗、2 通過) |
| **完整變異測試,最終程式碼 `50c2c15`,一次完整執行** | **795/795 killed**(09:56–11:08 UTC)。`evidence/mutation-full-795-final-50c2c15.log` |

變異測試對帳(全部保留在 `evidence/`,不合併計算):

| 執行 | SHA | 結果 | 處理 |
|---|---|---|---|
| 第一次完整 | `2b8b6ab` | 793/795 | `sql_spend_accepts_no_max_tokens`:測試缺口(沒有直接呼叫 SQL 函式),已補;`sql_spend_reservations_race`:見下 |
| 第二次完整 | `9065794` | 794/795 | race 存活:原本的多執行緒測試**取決於時序**,有時能殺、有時不能。沒有列鎖時,資料表 CHECK 仍會擋住超支(fail closed),只是拒絕訊息不同。改成**確定性**測試:A 開著交易持有預留,B 必須等待,A 提交後 B 必須得到上限本身的拒絕。單獨重跑 3/3 killed |
| **最終完整** | **`50c2c15`** | **795/795** | 一次完整執行,報告的數字就是這個證據檔 |

**CI**

| SHA | Run | 結果 |
|---|---|---|
| `2b8b6ab` | 40651691319 | 4 個 job 全部 success;負向控制「AI-authored history refused as expected」 |
| `9065794` | 40659390569 | 4 個 job 全部 success |
| `50c2c15` | 40668159570 | 4 個 job 全部 success |

記錄本表的 commit 本身也有 CI run,結果見最終回報。

Commit 祖先:`7988ed7` → `6c8447d` → `6a140f9` → `098a357` → `2b8b6ab` → `4ff10f3` → `9065794` → `50c2c15` → 記錄 commit。

**Git 歷史沒有 AI 署名**:每個 commit 的 author 與 committer 都是 `SpadesZ <rickiekuo1203@gmail.com>`,訊息沒有 trailer;CI commit 身分檢查通過。

## 6. 剩餘限制

1. 沒有真實 LLM 結果;沒有獨立盲測集;雙語語意品質 NOT VERIFIED;沒有物理驗證。
2. 篩檢後假說在目前產品中得不到前瞻支持(capability 沒有登記,fail closed)。
3. 金額上限依賴服務商遵守 `max_tokens` 與宣告價格正確;資料庫特權角色仍可繞過 trigger(A12)。
4. 互動簽章的信任根是網頁層金鑰與部署設定;A12 仍開放。
5. 本機 PostgreSQL 16,CI 用 pg17。

## 7. 剩餘 Owner Gates

1. 審查 011p(時間與種類規則)、011q(互動簽章)、011r(金額上限)的設計。
2. 決定是否把 capability 登記納入研究流程,讓篩檢後假說能得到前瞻支持。
3. 決定正式環境是否強制金額上限(`LAB_BRAIN_LLM_SPEND_REQUIRED`)。
4. 產生並保管互動簽章金鑰、釘選公鑰;A12(直接 SQL 改角色)的處置。
5. 真實 LLM 評估:先宣告每個模型的官方單價、來源、日期與金額上限,並確認服務商如何計算 thinking token。
6. 指派獨立評估者與審查者;在 `main` 設定 branch rule。
7. G0 是否通過:只能由獨立審查決定。本報告**不**宣稱 G0 PASS。
