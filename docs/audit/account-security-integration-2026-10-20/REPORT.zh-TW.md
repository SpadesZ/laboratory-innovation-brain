# 帳號安全最終修正與整合準備稽核報告

日期：2026-10-20。
本報告是**待審查的整合候選**，不是自行核准的發行版。沒有合併到 `main`、沒有部署、沒有讀寫正式環境資料、沒有建立正式憑證、沒有付費 API 呼叫、沒有執行 Lumi Agent。`READY_FOR_REAL_RESEARCH` 仍為 false。

【事實】可由本資料夾的證據、測試或 commit 重現。【解讀】是分析判斷。【未驗證】是沒有執行過的部分。

---

## 1. 結論

| 要求 | 結果 |
|---|---|
| 1. 消除 F12b | 完成。註冊只收電子郵件；開啟郵件連結的人才設定姓名與密碼；資料庫拒絕未確認帳號有密碼（`012v`） |
| 2. 兩種系統角色；ADMIN 完整可稽核讀取 | 完成。ADMIN 經監督頁讀取所有研究專案、完整報告（含機密摘錄）、報告匯出與所有 artifact；每次讀取先記錄再回傳，並顯示給成員 |
| 3. ADMIN 不得捏造、外送、改寫歷史 | 完成並測試。非成員 ADMIN 無法加資料、開始或繼續研究、宣告外送；研究歷史的不可改規則在資料庫層 |
| 4. 成員管理集中由 ADMIN 核准 | 完成。只有有效 ADMIN 能開啟專案、加入、變更、移除成員；任何人都不能授予或改動自己的成員資格；OWNER 只是專案成員角色，只持有外送宣告權 |
| 5. 稽核所有存取路徑 | 完成。新增逐條路由測試（5 種身分 × 每條路由），並從原始碼讀出路由清單，新路由沒有列入就失敗 |
| 6. 註冊、核准、停用、復原、session 撤銷 | 全部重測通過 |
| 7. 保留研究完整性修正與歷史重播 | 整合分支的完整 PostgreSQL 測試（含 F-01–F-03 與決策逐位元重現的測試）在 CI 通過：2898 通過、0 失敗（§6） |
| 整合候選 | `integration-integrity-accounts`，見 §5；`sp-declarations-candidate` 未納入 |
| 獨立對抗自我稽核 | 已執行。13 項發現：10 項完全修正、2 項部分修正（A9、A12）、1 項（A3）交擁有者決定；修正都有回歸測試（§7） |

## 2. 分支與 SHA

| 分支 | 用途 | 最終程式碼 SHA | CI |
|---|---|---|---|
| `research-integrity-closure` | 研究完整性 F-01–F-03（本輪未變） | `ad799e9` | 成功：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39340933634> |
| `lab-accounts-v1` | 帳號 V1（本輪修正在此） | `a293e00` | 成功（四個工作全過；PostgreSQL 2898 通過、5 略過）：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39420345220> |
| `integration-integrity-accounts` | **整合候選**：`main` ＋ 研究完整性 ＋ 帳號 | `f82998e` | 成功（四個工作全過；PostgreSQL 2898 通過、5 略過）：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39420354157> |
| `sp-declarations-candidate` | SP 1.1.0 候選（隔離、未啟用、本輪未變） | `7d2cd09` | 成功：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39341112584> |

本輪在 `lab-accounts-v1` 上的 commit：`523d7f8`（先驗證、ADMIN 才能管成員、ADMIN 完整讀取）、`bfde08b`（存取矩陣與突變項目）、`e2b0d31`（瀏覽器檢查發現的修正）、`55afcfd`（對抗稽核的修正）、`9639241`（對應的突變項目）、`27d4817`（狀態檔）、`a293e00`（CI 找到的測試衝突，見 §6.2）。本報告之後另以只改文件的 commit 加入兩個分支。

## 3. 修正前後

### 3.1 F12b：先驗證，再設定密碼

| | 修正前（`012u`） | 修正後（`523d7f8` 起） |
|---|---|---|
| 註冊表單 | 姓名、電子郵件、密碼 | 只有電子郵件 |
| 誰設定密碼 | 註冊的人（可能不是地址主人） | 開啟郵件連結的人，在確認地址的同一步 |
| 陌生人先註冊別人的地址 | 地址主人確認後，帳號用陌生人的密碼登入 | 陌生人從未有密碼；地址主人在連結中設定自己的 |
| 名稱或密碼被拒 | — | 整個交易回滾，連結仍可用；連結只能用一次 |
| 資料庫 | 無此規則 | `012v`：未確認的帳號不能有密碼（每個寫入者都適用） |
| 既有資料 | — | `012v` 移除確認前就存在的密碼（演練見 §6.4） |

【事實】未確認帳號仍可被同一地址「再註冊」以重寄連結；已確認的地址只會收到通知信。每帳號每小時最多 3 封、每小時新註冊數有上限；註冊與重設的回應至少 1 秒（不論地址是否存在）。

### 3.2 ADMIN 完整讀取

| | 修正前 | 修正後 |
|---|---|---|
| 非成員 ADMIN 閱讀報告 | 證據摘錄依 ADMIN 自己的分級遮蔽 | 完整，含機密分級摘錄 |
| 報告匯出 | 無 | `/admin/episodes/<id>/runs/<n>/report.md` |
| 研究檔案 | 只列出宣告為研究資料的檔案，看不到內容 | 列出專案持有的每個 artifact（上傳、研究執行的輸入與產出），可開啟內容 |
| 稽核 | 專案摘要、報告、成員研究清單 | 另加每個 artifact；每次讀取在回傳任何內容前寫入 `admin_access_log`，成員在專案頁看得到 |

【事實】ADMIN 的完整讀取只在 `/admin` 監督頁。一般研究頁面仍只看成員資格與分級：非成員 ADMIN 開 `/episodes/<id>` 仍是 404。這是刻意的：研究頁面也包含寫入路徑，若讓 ADMIN 通過一般閘門，ADMIN 就能寫入。

### 3.3 成員管理

| | 修正前 | 修正後 |
|---|---|---|
| 誰能加入、變更、移除成員 | 有效 ADMIN，或該專案的 OWNER（以自己的分級為上限） | 只有有效 ADMIN |
| OWNER | 管理成員 ＋ 外送宣告權 | 只有外送宣告權（專案層級角色，不是系統角色） |
| 自己的成員資格 | 任何人都不能改 | 不變：任何人（含 ADMIN）都不能改 |
| 建立研究專案 | MEMBER 可建立並成為 OWNER | 只有 ADMIN 開啟，並指定另一人為擁有者（稽核 A6） |
| 移除自己 | 可以 | 不可以（稽核 A7） |

### 3.4 存取路徑

【事實】`tests/security/test_web_access_matrix_postgres.py` 以五種身分（未登入、非成員、PUBLIC 成員、OWNER、非成員 ADMIN）走過每條路由：
- 23 條讀取路由、115 次請求：讀取只到該到的人；列表頁不對外人顯示專案名稱或研究 id；
- ADMIN 的每次監督讀取都已記錄；
- 20 條寫入路由、76 次請求（其中 54 次應被拒，含 MEMBER 建立專案）：每次之後比對研究、資料、artifact、專案、外送宣告、成員、帳號、模型連線，全部不變；
- 未登入一律導向登入（表單則導向「重新登入」）；不支援的 HTTP 方法回 405；
- 路由清單由 `app.py` 原始碼讀出，新路由沒有列入或註明在他處測試就失敗。

## 4. 測試與突變證據

- 帳號相關測試項目：帳號整合 24、專案 6、web 端到端 24、收件匣 2、存取矩陣 4、稽核回歸 9，全部通過。
- 突變電池（帳號，70 項）：70/70 被殺，沒有任何一項是因匯入錯誤而「被殺」。
  - 本輪新增 23 項：
    - 先驗證 9 項：姓名與密碼規則、`012v`、ADMIN 才能管成員、成員表單只給 ADMIN、ADMIN 讀取不遮蔽、artifact／匯出／報告讀取都有記錄；
    - 稽核修正 14 項：A1、A2（兩處）、A4、A5（`012w`）、A6（兩處）、A7、A8、A9、A10、A11、A12（`012w`）、A13。
  - 移除 2 項（它們守的「OWNER 管成員」程式碼已刪除）。
  - `v2_locale_switch_leaves_the_workspace` 在上一輪 F1 修正後已失效（錨點不存在），本輪改為指向現在守門的呼叫。
- **更正上一輪的數字**：上一輪報告的 48/48 中，`a_members_research_is_viewed_unseen` 刪掉迴圈的唯一敘述，突變本身是語法錯誤，因匯入失敗而「被殺」，不是被測試抓到。實際是 47 項有效 ＋ 1 項無效。本輪改為 `pass` 後由測試失敗殺掉。
- 證據：`evidence/battery_accounts_56_entries.log`（第一輪 56 項）、`evidence/battery_accounts_70_entries.log`（最終 70 項）。

## 5. 整合候選與祖先關係

【事實】實際祖先關係是一條線性堆疊，全部未合併、沒有 PR：

```
main (d0ab848)
 └ m1-p1-research-memory-foundation  41b3cec
    └ causal-warrant-gate-v1          db94748
       └ ux-research-workspace-clarity f89da04
          └ research-integrity-closure ad799e9   （b5e36a8 之後只多兩個狀態檔 commit）
             └ lab-accounts-v1        a293e00   （自 b5e36a8 分出）
```

- `research-integrity-closure` 比 `main` 多 106 個 commit、616 個檔案。所以「研究完整性 ＋ 帳號」的整合必然包含 M1-P1、CWG V1/V1.1 與 UX 三個分支。
- `main` 在 `72391aa` 之後有 4 個文件 commit；唯一衝突在 `README.md`（開發資料庫改用 `compose.dev.yaml`，保留 `main` 新增的環境變數行）。
- `IMPLEMENTATION_STATUS.md` 是產生的檔案，整合後以完整測試重新產生。
- `sp-declarations-candidate` 不在整合分支的祖先中，也沒有 `012t`。

整合分支：`integration-integrity-accounts` ＝ `main` ＋ `research-integrity-closure` ＋ `lab-accounts-v1`（`--no-ff` 合併）。與 `lab-accounts-v1` 的差異只有 `main` 的 README 修改與 `docs/assets`。

## 6. 驗證

### 6.1 完整測試

【事實】整合分支：
- 不需資料庫的完整測試（`ff81f14`）：1883 通過、0 失敗；ruff、ruff format、mypy strict 通過；狀態檔為最新。`f82998e` 只多改一個 PostgreSQL 測試。
- 本機新建資料庫上的完整 PostgreSQL 測試（`f82998e`）：2901 通過、2 略過、0 失敗（37 分鐘）。
- 早先在 `101ecd1`（對抗稽核修正之前）的同一測試：2890 通過，失敗 2 個都是當時尚未重新產生的狀態檔。

### 6.2 CI

【事實】CI 的「Backend profile (postgres)」工作會在新建資料庫上套用全部 migration，再跑完整測試。

第一次推送（稽核修正之後）：
- `lab-accounts-v1` `27d4817`：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39418147703>
- `integration-integrity-accounts` `ff81f14`：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39418574835>
- 兩者的 PostgreSQL 工作各 **1 個失敗**、2897 通過：`tests/e2e/test_web_workspace_postgres.py::test_an_excerpt_is_withheld_once_the_actor_may_no_longer_read_it`。這個既有測試把開啟者降到 PUBLIC，但問題是 INTERNAL，並期待頁面仍顯示、只遮蔽摘錄；A2 修正後頁面改為 404。我修正前只跑了帳號相關的 PostgreSQL 測試，沒有跑完整套件，所以沒在本機先抓到。
- 處置（`a293e00`）：依政策，問題本身已不屬於此人，頁面與匯出為 404，測試改為斷言這點；「摘錄依目前分級重新授權」仍適用於開啟者保有的 episode（012q 之前、未記錄分級者），測試以繞過觸發器的方式建立這種歷史資料並照原樣檢查。這不是放寬測試：前半更嚴格，後半保留原本的性質。

修正後：
- `lab-accounts-v1` `a293e00`：成功（四個工作全過；PostgreSQL 2898 通過、5 略過）：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39420345220>
- `integration-integrity-accounts` `f82998e`：成功（四個工作全過；PostgreSQL 2898 通過、5 略過）：<https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39420354157>

### 6.3 升級

【事實】整合分支 `ff81f14` 的 69 個 migration（含本輪的 `012v`、`012w`）：
- 以 `main` 自己的 migrator 建立的資料庫（24 個）→ 69：成功；
- `lab_brain_rd`（55）、`lab_brain_cwg_verify`（61）、`lab_brain_cwg4`（62）的複本 → 69：成功，只有 `schema_migrations` 改變；
- 開發用 `lab_brain`（16）已知無法通過 checksum 檢查（先前紀錄），不作為升級來源。
- 證據：`evidence/upgrade_integration_*.txt`。

### 6.4 `012v` 對既有資料的演練

【事實】以 `665b899`（有 `012u`、沒有 `012v`）建立資料庫，放入一個「確認前就設定密碼」的帳號，再用整合分支 `ff81f14` 升級：`012v` 與 `012w` 套用成功、該密碼被移除、約束已驗證。證據：`evidence/drill_012v_on_a_012u_database.txt`。

### 6.5 瀏覽器

【事實】內建瀏覽器、本機 `lab-brain web --accounts`、一次性資料庫，英文與繁中、桌面與 375×812：
- 先驗證註冊（弱密碼被拒後同一連結仍可用；用過的連結失效）；
- ADMIN 讀取完整報告（0 筆遮蔽）、匯出、上傳檔與研究執行的輸入與產出；
- OWNER 專案頁沒有成員表單，並列出 ADMIN 的每次檢視；
- 檢查中發現三個問題並修正（`e2b0d31`）：研究儲存的檔案以內容位址顯示、該位址讓手機版頁面寬到 708 px、過期確認連結導向重設密碼。
- 稽核修正之後再檢查：PUBLIC 成員看到的 ADMIN 檢視紀錄不含超出分級的問題與檔名；MEMBER 沒有建立專案的表單；ADMIN 指定自己為擁有者被拒，指定 Bob 則建立成功。
- 證據：`evidence/browser_check.txt`。

## 7. 獨立對抗自我稽核

【事實】
- 由獨立範圍的子代理執行：在獨立 worktree（`bfde08b`）與一次性資料庫上，寫出 20 個可執行的探測（缺陷存在時測試通過），全部執行，回報 13 項發現（1 HIGH、5 MEDIUM、7 LOW）。它沒有修改 repo。
- 我在另一個一次性資料庫上重跑這 20 個探測：20/20 通過，也就是每一項缺陷都重現。
- 修正後（`55afcfd`）再跑同一批探測（只把建立專案改成新介面，並排除兩個單執行緒的同時降級探測，原因見下）：
  - 其餘 15 個缺陷探測中，12 個失敗（缺陷消失）；
  - 3 個仍通過，與處置一致：A3（交決定）、A12 的直接 SQL 部分（交決定）、A9 的「每小時合併」部分（交決定；總覽的紀錄已修正，但探測只計算專案層級的紀錄）；
  - 兩個「防線成立」的檢查通過（其中一個第一次因我改寫探測時用錯變數名而失敗，更正後通過）；量測項不做斷言。
- 證據：`evidence/adversarial_auditor_run_bfde08b.log`、`evidence/adversarial_rerun_before_fixes_bfde08b.log`、`evidence/adversarial_after_fixes_55afcfd.log`、`evidence/adversarial_probes/`。

| ID | 嚴重度 | 發現 | 處置 |
|---|---|---|---|
| A1 | HIGH | ADMIN 讀過報告後，專案頁的檢視紀錄把 INTERNAL 研究問題的全文顯示給只有 PUBLIC 的成員 | 紀錄依讀者分級隱藏問題與檔名（未記錄分級視為最嚴格） |
| A2 | 中 | episode 開啟者被降級後，仍能讀 INTERNAL 問題的頁面與匯出 | 頁面、匯出、清單都要求目前分級涵蓋問題的分級（012q 之前未分級的 episode 仍歸開啟者，因為只有他能宣告） |
| A3 | 中 | 一位 ADMIN 可註冊自己的第二個地址、自己核准、加入任何專案並給 OWNER，然後寫資料、宣告外送 | **未修改程式，交擁有者決定**（§8）。外送那一段仍需維運者先把專案設成 RESEARCH；這個帳號在成員名單與帳號事件中可見 |
| A4 | 中 | 註冊上限填滿後，已註冊與未註冊地址回應不同；郵件故障時亦然 | 上限對所有地址都先檢查；註冊時寄信失敗不告知 |
| A5 | 中 | 兩位 ADMIN 同時互相降級或停用，可讓有效 ADMIN 變成 0 | `012w`：讓 ADMIN 離開有效狀態的變更逐一進行；第二筆等第一筆提交後被拒 |
| A6 | 中 | 建立專案等於授予自己 OWNER、任意分級與外送權（MEMBER 與 ADMIN 皆然） | 只有 ADMIN 開啟專案，並指定另一人為擁有者 |
| A7 | 低 | ADMIN 可把自己從專案移除 | 任何人都不能移除自己的成員資格 |
| A8 | 低 | 婉拒未確認的註冊後，該地址永遠無法再註冊 | 未確認的註冊不能被婉拒；它會過期，地址仍可再用 |
| A9 | 低 | 實驗室總覽列出私人專案卻不留紀錄；一小時內重複讀取只記一筆 | 總覽改為留下實驗室層級的紀錄；每小時合併交擁有者決定 |
| A10 | 低 | 成員只看得到最新 50 筆檢視紀錄 | 顯示全部 |
| A11 | 低 | 變更密碼前寄出的重設連結仍可用 30 分鐘 | 變更密碼時一併作廢 |
| A12 | 低 | 有資料庫權限的寫入者可直接把帳號升為 ADMIN；也可寫入 10 年期的 session | session 由 `012w` 限制在 12 小時內；直接 SQL 改角色屬於維運者信任根，交擁有者決定 |
| A13 | 低 | 登入沒有回應時間下限（已註冊地址約慢 12–15 ms） | 登入也套用同一個下限 |

另外兩點（【事實】）：
- 修正 A5 之後，稽核者的兩個「同一執行緒內開兩個交易互相降級」的探測會永遠等待：第二個交易在等第一個的鎖，而第一個在同一執行緒中無法提交。這是修正生效的表現，不是缺陷；改以兩個執行緒的測試驗證（`test_a5`：第二筆等待、第一筆提交後被拒、仍有 1 位有效 ADMIN）。
- 稽核者另指出「婉拒後原確認連結仍可確認」；A8 之後未確認的註冊不能被婉拒，此情況不再發生。

回歸測試：`tests/security/test_adversarial_findings_postgres.py`（9 項）、`tests/integration/test_lab_projects_postgres.py`（A6、A7）、`tests/e2e/test_web_accounts_postgres.py`（A13）、存取矩陣新增「建立專案」被拒的路由。

## 8. 未解決風險與需要決定的事項

風險（【解讀】）：

| 風險 | 說明 |
|---|---|
| A3 一人兩帳號 | 一位 ADMIN 可核准自己控制的第二個帳號並授予成員資格，之後以該帳號寫入研究資料；若專案已被維運者設為 RESEARCH，還能宣告外送。成員名單與帳號事件看得到此帳號 |
| A12 直接 SQL | 有資料庫遷移權限的維運者可直接改角色或狀態，不留帳號事件；最小權限角色只限制服務本身 |
| 監督紀錄以小時合併 | 同一位 ADMIN 在一小時內對同一對象的多次讀取只記一筆 |
| F7 | ADMIN 加人時，可得知某地址是否有有效帳號；只有 ADMIN 能加人，接受為設計 |
| 回應時間下限 | 若外部 SMTP 比 1 秒慢，重設密碼的時間仍可能透露帳號存在；下限以阻塞等待實作，佔住一個伺服器執行緒 |
| 依 IP 的速率限制 | 沒有；面對網際網路時需在反向代理設定 |
| 重寄確認連結 | 有人反覆以某地址註冊，會讓地址主人較早的連結失效（每小時最多 3 封） |
| `012v` 舊資料清除 | 只由一次演練驗證，CI 不跑這條路徑 |
| 單一 ADMIN 的實驗室 | 新專案與新成員都要 ADMIN；ADMIN 不能成為自己開的專案的成員，若需要須由另一位 ADMIN 加入 |

需要擁有者決定：
1. 合併方式（見 §9）。
2. A3：是否加入「兩人規則」——例如核准帳號的 ADMIN 不能是第一次授予它成員資格（或 OWNER）的 ADMIN。代價是只有一位 ADMIN 的實驗室，新成員需要第二位 ADMIN 才能加入專案。
3. A12：是否讓資料庫觸發器也拒絕「沒有 ADMIN 的角色或狀態變更」，並記錄事件。代價是維運者的命令列也必須經由帳號系統。
4. 監督紀錄要「每次讀取一筆」還是維持「每小時一筆」。
5. 正式郵件服務（SMTP）、對外網址與反向代理的速率限制。
6. SP 1.1.0 是否繼續（仍隔離、未啟用）。

## 9. 建議合併順序

【解讀】兩種方式，皆需人工審查後再做：

- **A. 逐一合併（建議）**：依堆疊順序各開一個 PR 合到 `main`：
  1. `m1-p1-research-memory-foundation`（第一個 PR 處理 README 衝突）
  2. `causal-warrant-gate-v1`
  3. `ux-research-workspace-clarity`
  4. `research-integrity-closure`
  5. `lab-accounts-v1`
  每一步都是前一步的直接延伸，審查範圍小、可逐步回退。
- **B. 一次合併**：審查完 `integration-integrity-accounts` 後，把它合到 `main`。結果與 A 相同，但一次審查 616 個以上的檔案。

`sp-declarations-candidate` 不在任何一步中；若日後要啟用，在步驟 4 之後另開 PR，並先完成 SP 1.1.0 的科學審查決策。

## 10. 證據檔案

`evidence/` 內：
- `battery_accounts_56_entries.log`、`battery_accounts_70_entries.log`
- `browser_check.txt`
- `upgrade_integration_from_main.txt`、`upgrade_integration_lab_brain_rd.txt`、`upgrade_integration_lab_brain_cwg_verify.txt`、`upgrade_integration_lab_brain_cwg4.txt`
- `drill_012v_on_a_012u_database.txt`
- `adversarial_auditor_run_bfde08b.log`、`adversarial_rerun_before_fixes_bfde08b.log`、`adversarial_after_fixes_55afcfd.log`、`adversarial_probes/`（稽核者的探測原檔，附說明）

所有日誌都已移除測試密碼、權杖、cookie 與本機使用者路徑。
