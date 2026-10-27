# G0 離線完整性與評估收尾報告

日期:2026-10-27
分支:`g0-offline-integrity-closure`
起點:`g0-exploratory-screening-v2` @ `21cef3ea14f14da7ee0c254bf92c46cebd686936`(遠端 HEAD 相同、為祖先、工作區乾淨,改動前已確認)
狀態:**工程候選,待 Independent Chief Auditor 審查。Engineering PASS 不等於 G0 Scientific Acceptance。G0 未通過,沒有物理確認。**

## 0. 範圍與成本

- 只用離線、免費資源:本機 Python 3.13、PostgreSQL 16 + pgvector、本機 Chromium。
- 沒有 Gemini 或其他計費模型呼叫、沒有付費 runner、沒有 Lumerical、沒有正式資料變更、沒有部署、
  沒有合併、沒有 force push、沒有刪除分支、沒有改 `READY_FOR_REAL_RESEARCH`、沒有改科學權限或驗收門檻。
- GitHub Actions:公開 repo 的標準 runner,計費 0 ms。
- 產品研究流程內沒有使用外部 coding agent。

## 1. WP1 — main 分支 commit 完整性

**問題(已證明)**:舊的 `scripts/check_commit_messages.py` 只看 commit 訊息。舊分支
`g0-exploratory-screening` 的 12 個 commit 作者與提交者都是 `Claude <noreply@anthropic.com>`,
但訊息沒有 trailer,所以舊檢查會讓它通過。

**改動**
- `.github/commit-identity-policy.toml`(新):Owner 控制的人類身分清單(email 與名字都要符合),
  加上只能提交、不能當作者的平台提交者 `GitHub <noreply@github.com>`。
- `scripts/check_commit_messages.py`:
  - 檢查每個可達 commit 的 Git author 與 committer,沒有下限(全部歷史 144 個 commit 已驗證是人類)。
  - 名字或地址指向 AI → 拒絕;清單列入 AI 身分 → 整份 policy 被拒絕。
  - 未列入的身分 → 拒絕(fail closed)。平台身分當作者 → 拒絕。
  - `(cherry picked from commit X)`:X 在本機時連原 commit 一起檢查,重設作者洗不掉;X 不在時印警告。
  - merge 走完兩邊祖先;squash 的平台 `Co-authored-by:` 走訊息規則;force push 後從 tip 重新計算。
  - 訊息規則不變,仍從 `ENFORCED_FROM` 開始。
- `.github/workflows/ci.yml`:用 `--tip`(PR 時是 PR head,不是合成 merge)。
  新增負向控制步驟:對舊分支執行,必須被拒絕。
- `.github/CODEOWNERS`(新)、`docs/implementation/commit-integrity-gate.md`(新)。
- 測試:`tests/spec/test_commit_identity_policy.py`(新)與更新的 `test_commit_message_hygiene.py`。
  真實暫存 repo 驗證 merge、squash、cherry-pick(保留/重設作者)、force push 改寫歷史、只有 AI committer、
  policy 遺失或列 AI;舊分支以凍結 metadata 與實際 ref 兩種方式驗證。

**沒有改 GitHub 設定。** 要讓它成為必要的合併關卡,Owner 要在 `main` 的 branch rule 設定:
需要 PR、必要 status check「Commit hygiene (no AI authorship attribution)」、禁止 force push 與刪除、
需要 Code Owner 審查、不允許 bypass。細節見 `docs/implementation/commit-integrity-gate.md`。

## 2. WP2 — 篩檢完整性與故障

### 2.1 已證明的缺陷:相同內容換身分即可 SUPPORTS(已修正)

012y 的 (c) 只在 capability、backend、inputs、parameters **全部相同** 時視為重複。先寫負向測試,
在 012y 上執行(證據:`evidence/independence-before-011m.txt`):

| 繞過方式 | 012y 結果 |
|---|---|
| 換 backend id(同 reader、同輸入、同參數) | 通過(缺陷) |
| 加無作用參數(reader 不把參數寫進輸出,位元組相同) | 通過(缺陷) |
| 另一個 capability 輸出同一個 artifact | 通過(缺陷) |
| 所有身分都換,只有輸出內容相同 | 通過(缺陷) |
| 換 backend 且輸出新內容 | 通過(缺陷) |
| 相同內容但不同 artifact id | 被 CHECK 拒絕(**不是缺陷**:`artifact_id = 'art:' || content_hash`) |
| 之後的、內容真的不同的讀數 | 允許(對照組) |

**修正**:`migrations/011m_screening_repeat_by_content.sql`(012 的字母已用完,`012t` 在其他分支已使用,
所以用 011m,在 012z 之後套用)。
- (c) 不再要求相同 backend:同 capability + 同輸入 + 同參數就是同一個檢查。
- (d) 新增:支持的 run 若與條件化讀數的 run 共用輸出 artifact(即位元組相同)→ 拒絕。
- 只會更嚴格;(a)(b) 不變;append-only、簽章審查、Budget Gate、TransitionPolicy 不變。

舊測試 `test_g0_exploratory_screening_postgres.py` 的「不同讀數」fixture 其實重用了被篩檢的輸出位元組。
它的斷言(之後真的不同的讀數可以 SUPPORTS)保留,只把 fixture 改成真的新輸出內容。

### 2.2 新的對抗測試

`tests/e2e/test_g0_screening_independence_postgres.py`(7)與
`tests/e2e/test_g0_screening_adversarial_postgres.py`(15):

| 情境 | 結果 |
|---|---|
| 選取後到執行前:capability 被移除、變成需授權、隱私限制、不可逆、需要座位、需要人、宣告不再是本機、工具綁座位、工具改執行別的 capability、輸入屬於別的專案 | 執行前 REFUSED,沒有 Job、沒有證據 |
| 宣告本機但 Run 記錄遠端執行 | FAILED,證據不採用 |
| 預檢通過後,宣告的工具被重新綁定 | 執行中 REFUSED,沒有派送 |
| 完成回呼送兩次 | 只有一個 Run;第二筆同檢查的篩檢紀錄被 SQL 拒絕 |
| 條件化紀錄寫不進去 | 假說與紀錄一起回滾,不留沒被條件化的篩檢後假說 |
| 成員資格撤銷 | 頁面、`report.md`、`summary.html` 都被拒絕,不顯示紀錄內容 |

既有故障注入(中斷的 Job/Run、證據寫入失敗、續跑關閉遺留 Job、SQL 拒絕缺證據紀錄)仍通過。

### 2.3 殘餘風險(假設性,未證明)

- 謊報「本機」的 backend:Run 記錄遠端時證據不採用,但已經送出去的資料收不回來。要真正防止,
  需要程序隔離或網路沙箱,不在本次範圍。
- 參數若真的改變物理意義、但輸出位元組相同,會被 (d) 拒絕。這是偏保守的方向。
- SQL 層無法判斷參數是否「有意義」;(c) 只比對完全相同的參數。

篩檢在正式環境仍預設關閉;結構摘要仍預設關閉。

## 3. WP3 — 獨立評估準備

`src/lab_brain/evaluation/`、`scripts/g0_eval_{seal,check_contamination,freeze,score}.py`、
`benchmarks/g0_evaluation/protocol.example.json`、`docs/evaluation/G0-independent-holdout-workflow.md`。

- 產生端與評估端檔案分開;產生端載入器用 kind、檔名、任何深度的真值欄位與 schema 拒絕評估材料。
- 真值以每案加鹽 SHA-256 承諾 + root 封存;真值放在 repo 外,腳本拒絕 repo 內的真值路徑。
- 凍結 manifest 釘住協定、評分程式碼的 hash、輸入檔 hash、案例清單、承諾;之後任何變動 → 拒絕評分。
  輸出綁定 manifest hash。
- 污染檢查:完全/8-gram 文字重疊、來源/裝置家族重疊、重複實驗單位(id 或正規化內容);
  包含已曝光的 `benchmarks/g0_screening` 案例。
- 分母:失敗、拒絕、崩潰、格式錯、缺輸出都留在分母;排除的案例另外列出,並有保守數字。
- 不確定度:Wilson 95% 區間 + 固定 seed 的 bootstrap。
- 只用合成資料測試。

**沒有建立真正獨立的盲測集,也不宣稱有。** 最終封存資料必須來自另外授權的評估者。

## 4. WP4 — G0 科學雙語準備

稽核表:`bilingual-audit.md`(G0-A、G0-B、G0-P,含 file:line)。
`src/lab_brain/interfaces/web/bilingual_parity.py`:離線結構對等檢查(覆蓋、數值/單位/正負號、ID/hash、
否定、狀態詞、claim strength、NOT_PERFORMED),並確認渲染兩種語言前後資料列逐位元組不變。

| 項目 | 狀態 |
|---|---|
| 摘要匯出只說明「最佳下一個」模擬為何不能跑(G0-P) | **已證明並修正**:每個不能跑的檢查都寫原因與需求 |
| `report.md` 各語言都是同一份英文(G0-B「匯出回到單語」) | **已證明,未修正**:需產品決定;以 strict xfail 記錄 |
| 繁中 `summary.html` 沒有引用(G0-B) | **已證明,未修正**:需產品決定 |
| session 非秘密稽核 ref 沒連到 `research_runs`(G0-A) | **缺少**:需要 migration |
| 繁中 L3 有未標記的英文字 | 輕微 |
| LLM 寫的科學正文雙語語意品質 | **NOT VERIFIED**(需要獨立雙語審查者) |
| 領域翻譯 `sp.presentation@1.0.1` 正確性 | **NOT VERIFIED**(pack 自己標記待專家審查) |
| 真實 LLM 下的雙語輸出(G0-L) | **NOT VERIFIED** |

## 5. 驗證

全部在本機免費資源執行。證據檔在 `evidence/`。

| # | 項目 | 指令 | 結果 |
|---|---|---|---|
| 1 | 靜態檢查(CI 範圍) | `ruff check src tests scripts`、`ruff format --check src tests scripts`、`mypy src` | 全部通過(272 檔) |
| 1 | 規格一致性 | `pytest -q tests/spec` | 245 passed |
| 2 | 不需資料庫的完整回歸 | `pytest -q` | 2122 passed, 1071 skipped(skip 的是需要 PostgreSQL 的測試) |
| 3 | 新建 DB(73 個 migration 到 011m)完整回歸 | `LAB_BRAIN_TEST_POSTGRES=1 ... pytest -q` | **3187 passed, 4 skipped, 1 xfailed**(13 分 22 秒);skip:本機 live 模型、Lumerical、網路、Windows;xfail:§4 的單語 `report.md`。`evidence/full-postgres-suite.log` |
| 4 | WP1 目標測試 | `tests/spec/test_commit_identity_policy.py`、`test_commit_message_hygiene.py` | 95 passed(含實際舊分支 ref) |
| 4 | WP2/WP3/WP4 PostgreSQL 目標測試 | 獨立性、對抗、故障、篩檢、盲跑、雙語 e2e | 37 passed, 1 xfailed |
| 4 | WP3/WP4 單元測試 | `test_g0_evaluation_*`、`test_g0_bilingual_parity.py` | 19 passed、29 passed |
| 4 | 011m 之前的負向測試 | 獨立性測試在 012y 上 | 5 failed(證明缺陷)、2 passed(對照)。`evidence/independence-before-011m.txt` |
| 5 | 篩檢與新項目變異測試 | `mutation_battery.py --only <76 項>` | 第一輪 72/76。4 個存活全部處理(見下),重跑 6/6 killed。`evidence/mutation-targeted-76-first-run.log` |
| 6 | **完整變異測試** | `mutation_battery.py`(全部 756 項,本機上限 2 小時) | **756/756 killed**,47 分鐘(15:33–16:20 UTC)。`evidence/mutation-full-756.log` |
| 7 | 瀏覽器與雙語匯出 | `test_g0_bilingual_parity_postgres.py`(本機 Chromium + Playwright) | 通過(在 3 與 4 內) |
| 8 | GitHub CI | 最終 SHA | 見 §5.2 |

第一輪 4 個存活的處理:
- 2 個 011m 項目「MUTANT DID NOT APPLY」:**battery 本身的缺陷**。所有 SQL 模板共用一個資料庫名稱,
  換 migration 時被重建,但快取仍指向它;排在 012y 項目之後的 011m 項目因此跑在缺表的模板上。
  已改為每個 migration 一個模板。
- `screening_preflight_ignores_privacy`:錨點先命中計畫階段的同一行(該檢查被 preflight 重複覆蓋,
  不是漏洞)。錨點改指 preflight。
- `parity_ignores_status`:**測試缺口**。沒有測試只改繁中的儲存狀態而保留文字。已新增此案例。

沒有弱化任何斷言;沒有修改凍結的 benchmark 答案;沒有靜默跳過失敗。唯一改動的既有測試 fixture
(§2.1)保留原斷言。

### 5.1 Git 歷史沒有 AI 署名

`python scripts/check_commit_messages.py --tip HEAD`:113 個訊息、147 個 commit 身分,沒有 AI 作者。
本分支新 commit 的 author 與 committer 都是 `SpadesZ <rickiekuo1203@gmail.com>`,訊息沒有 trailer。
CI 負向控制 annotation:「negative control: AI-authored history refused as expected」。

### 5.2 CI

CI_SECTION


## 6. 剩餘 Owner Gates

1. 在 `main` 設定 branch rule,讓 commit 完整性檢查成為必要關卡(§1)。
2. 新增人類貢獻者到 identity policy(目前只有 Owner)。
3. 刪除舊分支 `g0-exploratory-screening`(CI 負向控制會自動跳過,凍結 fixture 仍保留)。
4. 審查 011m 的較嚴格 (c)(d) 定義是否符合科學意圖。
5. 雙語匯出:`report.md` 是否要繁中版本、繁中摘要是否要加引用、session 稽核 ref 的 migration。
6. 指派獨立評估者,建立封存的盲測集。
7. 真實 LLM 資格重測(付費,需先估最高費用)與 G0-L/G0-S 真實研究驗收。
8. 正式環境是否開啟篩檢與結構摘要(目前都關閉)。
9. G0 是否通過:只能由 Owner 與獨立審查決定。本報告**不**宣稱 G0 PASS。
