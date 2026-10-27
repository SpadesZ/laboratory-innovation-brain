# SiPh Lab — G0 探索性篩檢（Exploratory Screening）：稽核報告

分支：`g0-exploratory-screening-v2`（自 `g0-research-reliability` `d14c1cd` 分出）
程式與證據的最後提交：`f18360e`；本報告在其後的提交中（只有文件）。
參考規格：SAI 3.4 分期基準 `a38ad63`（唯讀；未改、未合併）。
性質：審查用候選。未合併到 `integration-integrity-accounts` 或 `main`、未部署、未動正式資料、未呼叫付費模型、未執行 Lumerical、未啟用 SP 1.1.0、`READY_FOR_REAL_RESEARCH` 仍為 `false`。**本報告不認證 G0 PASS，也不是 HARD-LOCK。**

標記：【事實】＝本輪實際執行並留有證據；【推論】＝依程式推得；【未做】＝沒做並說明原因；【阻礙】＝做不到，列出缺什麼。

---

## 0. 直接回答

- 【事實】選項 A 已實作：一個**受治理、有上限、與結果無關**的篩檢階段（screening stage），在涵蓋審查之後、反方（Critic）之前，對「沒有任何假說預測」的低成本本機檢查做讀取。它是獨立的型別化、持久化作業（`ScreeningPlan`、`ScreeningObservation`、migration `012y`），**不是** VerificationPlan。
- 【事實】異常讀取（與領域宣告的健全參考結果不同）會觸發一次新的假說產生（`prm:hypothesis-screening-review@1.0.0`）。新假說被記錄為「篩檢後提出」（conditioned）；SQL 對**任何寫入者**拒絕它從（a）那次讀取、（b）比它早的觀察、（c）同一讀取的決定性重複，得到 SUPPORTS。驗證流程也不會對同一輸入重跑已篩檢的檢查。
- 【事實】選項 B 以原型實作：裝置結構摘要（device structure summary），只有設計宣告欄位、來源指標、單位與不確定性，不含任何判定；**預設關閉**，分開評估。
- 【事實】離線軟體矩陣（替身模型，**不是**真實 LLM）四種設定 × 開發 12 例 + 封存保留 10 例：所有治理不變量都是 0（錯誤確認、篩檢後假說被支持、重複讀取、不合格篩檢、錯誤異常、洩漏）。篩檢設定下，判別性低成本檢查執行率由基準的 0.0 升到 1.0。
- 【阻礙】**真實 Gemini 重測沒有做**：本任務未授權付費呼叫，這個雲端環境也沒有 Gemini 金鑰或本機 qwen。G0 的科學有用性在真實模型上**仍未驗證**，G0 **未通過**。第 13 節列出之後要跑的確切指令。

---

## 1. 提交

| 提交 | 內容 |
|---|---|
| 封存提交 | 獨立作者寫的 10 個保留案例與評估者真值，`SEAL.txt` 雜湊；任何評估前提交 |
| 篩檢核心 | 型別、selection、executor、`012y`、辯論整合、Critic 保留 token、引用相關性、重疊假說紀錄、結構摘要（旗標）|
| 呈現 | 研究頁（中英）、完整報告、Markdown 報告的篩檢段落；「篩檢後提出」標記 |
| 單元測試 | 31 項 |
| 凍結評估協定 | 四種設定、分組、指標、門檻與檔案雜湊；在任何矩陣執行前提交 |
| 矩陣、評分、續跑與專案隔離測試 | |
| 稽核義務 | 成員權限的第二層防護、18 條新突變、SPEC-ISSUE-016、舊報告勘誤 |
| 最終證據 | 離線矩陣結果 |

全部提交作者為 `SpadesZ`（倉庫既有慣例），無 AI 署名、未簽 AI 金鑰。見 §12 第 5 項。

---

## 2. 變更的檔案（相對 `d14c1cd`）

新增：
- `migrations/012y_exploratory_screening.sql`
- `src/lab_brain/core/models/screening.py`、`src/lab_brain/core/repositories/screening.py`
- `src/lab_brain/verification/screening.py`
- `src/lab_brain/cognition/overlap.py`
- `src/lab_brain/research/structure.py`、`src/lab_brain/domains/silicon_photonics/structure.py`
- `benchmarks/g0_screening/`：`protocol.json`、`score.py`、`dev/`（cases、truth、1 份證據變體）、`holdout/`（cases、truth、3 份證據變體、SEAL）
- `docs/spec_issues/SPEC-ISSUE-016-exploratory-screening.md`
- `tests/g0_standin.py`、`tests/unit/test_g0_exploratory_screening.py`、`tests/e2e/test_g0_exploratory_screening_postgres.py`、`tests/e2e/test_g0_screening_matrix_postgres.py`
- `docs/audit/g0-exploratory-screening-2026-10-27/`（本報告與證據）

修改：
- `src/lab_brain/cognition/debate.py`、`roles.py`、`catalog_reasoner.py`
- `src/lab_brain/research/service.py`、`report.py`、`render.py`、`vertical.py`
- `src/lab_brain/domains/silicon_photonics/product.py`
- `src/lab_brain/interfaces/web/app.py`、`pages.py`、`i18n.py`
- `src/lab_brain/core/models/identifiers.py`
- `scripts/migrate.py`、`scripts/mutation_battery.py`
- `IMPLEMENTATION_STATUS.md`（重產）、`docs/spec_issues/README.md`
- `docs/audit/g0-research-reliability-2026-10-21/REPORT.zh-TW.md`（只加勘誤）
- 測試：`test_g0_coverage_review_postgres.py`（政策版本 1.2.0）、`test_web_debate_retry_postgres.py`（功能旗標參數）、`test_research_live_model_postgres.py`（設定與矩陣案例）、`test_web_workspace_postgres.py`、`test_causal_warrant_counterexample_postgres.py`（突變修補）、`test_episode_cognition_path_postgres.py`（宣告 status 欄）、`postgres_fixtures.py`、`report_samples.py`

共 63 個檔案（其中 9 個是矩陣證據 JSON）。

---

## 3. 篩檢設計：十項要求逐條對照

| # | 要求 | 實作 |
|---|---|---|
| 1 | 依註冊的型別化能力、可用輸入、授權、預先宣告的成本／風險政策選擇；不讀基準真值 | `select_screening` 的參數只有：假說、預測詞彙、能力描述、工作流程、領域宣告的篩檢規範（`ScreeningNorm`）、輸入**種類**與 artifact id、已篩檢清單、政策。沒有任何參數能傳入裝置內容（單元測試檢查函式簽章）。部署以 `ResearchFeatures.exploratory_screening` 開關 |
| 2 | 明確資格：不可逆、外部呼叫、授權模擬、專案範圍、資源上限、目的 | 依固定順序判定，第一條不符即記錄原因：已被假說預測、未宣告規範、動作類型不是「讀取既有」、不可用（含 DEGRADED）、需授權席位、不可逆、需人力或金錢、隱私限制、缺輸入、無工作流程、超過單項上限、已篩檢。規範宣告 `LOCAL_NO_EGRESS`，執行後再核對 Run 的 `environment.execution == local`，不符即記為 FAILED、不採用。每項入選檢查都記錄目的 |
| 3 | 最便宜且足夠；不全部跑；確定性優先順序、預算、上限、去重、停止 | 只考慮**沒有假說判別**的觀測；`screening:research-run@1.0.0`：最多 2 項、合計估計 60 秒、單項 10 秒；依（估計時間、計算量、capability id）排序；同一輸入同一檢查每個研究任務只讀一次（DB 唯一索引）；失敗、無席位、預算拒絕即停止，其後記為 NOT_RUN。**異常不停止**：同一裝置兩個故障不能由 id 排序決定 |
| 4 | 一級型別化持久作業，不藏在規劃器裡 | 三張 append-only 表；`VerificationPlan` 與 `011k` 未改 |
| 5 | Job/Run、輸入輸出來源、授權、結果、成本、時間、重試識別、重播 | 每項檢查一個 Job（key `scr:<episode>:<inputs hash>`）、經 `BudgetedToolDispatcher`（COST-001）、Run 帶後端身分與輸入雜湊；結果從**已儲存**輸出讀取；Observation + Attestation 經 admission gate；記錄估計成本、時間、evidence line |
| 6 | 異常可觸發新一輪假說；正常結果也保留 | 有異常才問一次篩檢後審查；正常讀取同樣存成 Observation + Attestation，並顯示在頁面 |
| 7 | 篩檢觀察不得自動 SUPPORT、CONFIRM、升級事後假說 | 篩檢讀取**不產生任何 relation**；事後假說記入 `screening_conditioned_hypotheses`；SQL 守衛（a）（b）（c）|
| 8 | 事後機制須有事先宣告、獨立的後續驗證或授權審查 | 驗證不重跑同一讀取；事後假說只能從**不同**的檢查得到支持，且仍經 Causal Warrant Gate；結論文字與下一步明寫此限制。【未做】「只靠授權審查升級」的新路徑：需規格決定（§12）|
| 9 | 重複同一決定性檢查不是獨立佐證 | 驗證排除已篩檢的（能力、輸入）；SQL 規則（c）；既有獨立性計算本來就以 evidence line 計（重複只算一次）|
| 10 | 保留 Causal Warrant Gate、簽章審查、轉移政策、證據權威 | 這些檔案一行未改；篩檢讀取若是其他機制的宣告特徵，只會**阻擋**確認（`ConfirmationRule` 讀取整個任務的觀察）|

---

## 4. 裝置結構摘要（原型，預設關閉）

- 【事實】由 SP 套件從**已解析**的 `DeviceProject`（拒絕未知欄位）依白名單產生：裝置 id、繪製長度、萃取用長度、每個接點的 id／區域／via 是否接金屬／重疊量、網格、摻雜。每欄有 JSON 指標、單位、`DESIGN_DECLARED` 標記與不確定性說明。`solver_converges`（mock 求解器開關，不是設計欄位）被排除並說明原因。
- 【事實】不套用任何規則，不出現 CONTINUOUS／DISCONTINUOUS／AGREES／DISAGREES。名稱或路徑含 truth、label、expected、cause、verdict 等字的欄位會被拒絕（第二道防線）。
- 【事實】只從**本次執行存在本專案**的驗證輸入產生，只給本次執行的假說引擎呼叫；與證據同分類、同外送決定。它不是證據：不能被引用為 grounding，不產生 relation。
- 【推論】摘要包含 `via_to_metal: false` 這類設計欄位，對開路案例資訊量很大；這是合法的設計輸入，但也表示 B 的效果高度取決於模型怎麼讀它，且可能產生錯誤線索（見 §8 的 ho-03）。是否啟用需要 Owner 決定。

---

## 5. 與 SAI 契約的衝突與規格決定

- 【事實】§9.1／`VER-001` 規定「驗證動作」必須有預測的判別結果；§25.4 則要求規劃器先做 connectivity／extraction consistency 等低成本檢查。兩者對「沒有預測的低成本讀取」**既不允許也不禁止**。
- 處置：未悄悄放寬契約。篩檢被實作為**非驗證動作**（暫用 Reading B），`011k` 的 VER-001 觸發器未改，並開立 `SPEC-ISSUE-016`（GATE，Blocks gate: M4，OPEN），附提議條文 `VER-009`。若 Owner 判定 Reading A，關掉旗標即可移除此階段。

---

## 6. 驗證結果

| 項目 | 結果 |
|---|---|
| 不需資料庫的完整測試 | 2012 通過、1039 略過、0 失敗（狀態檔重產後） |
| 規格一致性 | 206 通過 |
| ruff、ruff format、mypy strict（264 個原始檔） | 通過 |
| 本機 PostgreSQL 16 完整測試（新建資料庫、71 個 migration） | 3048 通過、4 略過、2 失敗 → 兩項處理後重跑通過（見下） |
| 新的篩檢 e2e（6 項）與矩陣（5 項） | 全部通過 |
| 新的單元測試 | 31 通過 |
| 突變 | 20/20 被抓到（§7） |
| GitHub Actions | 見 §6.1 |

- 【事實】PG 兩項失敗：
  1. `test_episode_cognition_path_postgres`：既有守衛要求每個 `status` 欄都要宣告為非信念的生命週期。這是**真缺口**；已宣告 `screening_observations.status`（執行生命週期）。
  2. `test_service_roles_postgres`：本機伺服器原本用 `trust` 登入，任何密碼都能進；改成 `scram-sha-256`（與 CI 相同）後通過。屬於環境設定，不是程式問題。

### 6.1 CI

- 【事實】舊分支 `g0-exploratory-screening` 的第一次 CI（run 40475940923）：提交規範、規格一致性、lint／型別／完整測試通過；**PostgreSQL 工作失敗**。這個雲端環境的代理擋住了 CI 日誌主機，無法讀出失敗的測試名稱；【推論】是上述第 1 項（之後才修）。
- 【事實】新分支 `g0-exploratory-screening-v2` 的 CI：run 40491425160，結果寫在本報告提交之後的聊天回覆中（本報告撰寫時仍在執行）。

---

## 7. 突變測試

- 【事實】新增 18 條：篩檢的選擇規則（已被預測、不可用、數量、預算、去重、單項上限）、讀取結果的判定、事後假說的條件紀錄、引用相關性、異常讀取必須被解釋、Critic 保留、驗證不重跑、結構摘要洩漏防護，以及 `012y` 的 SQL 規則（a）（b）（c）、append-only、只能記錄計畫選中的檢查。
- 【事實】連同兩條舊的存活突變，共 20 條：**20/20 被抓到**（`evidence/mutation_battery_g0_screening.log`）。其中 `verification_repeats_the_screened_reading` 在電池中標為 ERROR，已手動重跑確認是斷言失敗（真擊殺），而且 SQL 規則（c）在這個突變下也擋住了支持關係。
- 【未做】完整 719 條電池沒有在本輪重跑（每條要重建或複製資料庫，時間長）；建議在 Owner 驗收前跑一次。

### 7.1 兩條舊的存活突變（獨立子代理調查，`evidence/surviving_mutants_findings.md`）

| 突變 | 為何存活 | 安全後果 | 處置 |
|---|---|---|---|
| `workspace_episode_ignores_membership` | 另外兩層（只回傳給開啟者的 SQL、分類標籤 clearance）在既有測試中都先擋下，所以這道守衛從未決定過任何測試 | 若守衛真的消失：**只有該研究任務的開啟者本人**在兩種情況下仍可讀頁面、`report.md`、`summary.html`——（1）帳號被全域停用但成員資格仍有效；（2）2026-10-21 前、無分類紀錄的任務且成員資格已失效。證據摘錄仍被擋。嚴重度：低到中（撤權缺口，不是跨使用者外洩）| 新測試 `test_the_opener_reads_their_episode_only_while_the_gate_admits_them`；並加第二層防護：分類標籤層在專案閘門拒絕時一律不給 clearance |
| `the_review_rivals_cross_projects` | 只有在 PostgreSQL 選擇評估子查詢時才會失敗；選擇與表格統計有關（查詢計畫不同），不是測試順序 | 無跨專案外洩：外層查詢本來就限定專案；突變只會讓 `review show` 在該情況下報錯。嚴重度：低 | 測試夾具讓對立假說在該觀測上有預測，子查詢必定被評估；電池說明文字改為準確描述 |

---

## 8. 科學驗收矩陣（離線、替身模型）

協定 `benchmarks/g0_screening/protocol.json` 在任何矩陣執行前提交（含門檻與檔案雜湊）；真值只在執行**之後**由 `score.py` 讀取。

| 設定／分組 | 機制被考慮 | 其中事前提出 | 判別檢查有執行 | 錯誤異常 | 錯誤確認 | 事後假說被支持 | 重複讀取 | 每例篩檢數 | 正常讀取 | 事後假說數 | 確認數 | 洩漏 | 協定判定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline / dev | 0.333 | 0.333 | 0.0 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | PASS |
| baseline / holdout | 0.25 | 0.25 | 0.0 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | PASS |
| screening / dev | 0.833 | 0.333 | 1.0 | 0 | 0 | 0 | 0 | 1.917 | 16 | 7 | 0 | 0 | PASS |
| screening / holdout | 0.875 | 0.25 | 1.0 | 0 | 0 | 0 | 0 | 1.9 | 13 | 6 | 0 | 0 | PASS |
| structure / dev | 0.917 | 0.917 | 1.0 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | PASS |
| structure / holdout | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 0 | 0.0 | 0 | 0 | 0 | 0 | PASS |
| combined / dev | 0.917 | 0.917 | 1.0 | 0 | 0 | 0 | 0 | 1.333 | 16 | 0 | 0 | 0 | PASS |
| combined / holdout | 1.0 | 1.0 | 1.0 | 0 | 0 | 0 | 0 | 1.2 | 12 | 0 | 0 | 0 | PASS |

解讀：
- 【事實】基準（等同真實 Gemini 的行為形狀）：開路案例的接點檢查**從未執行**（0.0），與 2026-10-21 實測一致。
- 【事實】只開篩檢：每個開路案例都讀到 DISCONTINUOUS，提出篩檢後假說；這些假說 **0 次被支持、0 次確認**，任務停在 PROVISIONAL／SUSPENDED，結論寫明「該讀取不能支持它」。代價：每例約 1.9 次讀取，其中約 2/3 是正常讀取（沒有改變任何事）。
- 【事實】只開結構摘要：替身模型在讀取前就提出接點或長度的假說，接著由驗證**事先宣告地**執行檢查；但 ho-03（重疊 101 nm，剛好合規）也被提出為錯誤線索，之後被檢查結果（CONTINUOUS）牴觸。模型自寫的機制沒有領域 warrant，所以仍需人員判斷，確認數為 0。
- 【事實】兩者合併：結構假說已涵蓋的觀測不再篩檢（篩檢只補剩下的盲點）。
- 【事實】兩種設定都考慮不到的：反向摻雜（dv-06）——低成本檢查看不到，替身也沒有線索。接點讀取器不可用時（dv-10、ho-09），篩檢不會碰它。
- 【事實】可重現性：篩檢設定在開發組重跑兩次，正規化紀錄完全相同（`test_the_screening_configuration_reproduces_on_the_dev_split`）。
- 【事實】評估過程中的一次修正：第一次矩陣執行時 `ineligible_screening` 不是 0，原因是**量測程式**從空的 `capabilities` 表讀動作類型。改為讀篩檢計畫內的型別化候選後為 0。門檻未改。
- 限制：這些數字是**平台**對某種形狀回覆的反應，不是模型的科學能力。替身規則已凍結並雜湊。

---

## 9. 篩檢計畫與觀察紀錄（樣本：dv-01，開路通孔）

- 計畫：`screening:research-run@1.0.0`；未涵蓋觀測含 `sp.contact_connectivity`、`sp.normalization_basis`（及模擬才能看的觀測，不合格）；入選依序為萃取一致性、接點連通性。網格、DC 掃描、四點量測、製程分批均記錄為「未宣告篩檢規範」。
- 讀取：萃取一致性 → AGREES（正常）；接點連通性 → DISCONTINUOUS（異常）。各有自己的 Job（`scr:` key）、Run、Observation、Attestation。
- 審查：替身提出「broken contact via in the access path」，回應 O 代號的異常讀取，引用與其內容有共同字詞的證據；記錄為 conditioned。
- 驗證：未重跑接點檢查（「not repeated by verification」），事後假說沒有任何 SUPPORTS。
- 全部 22 例 × 4 設定的紀錄：`evidence/offline_matrix/*.outputs.json`；評分：`scored.json`、`matrix.md`。

---

## 10. 基準答案不可取得的證據

- 【事實】研究系統只收到：裝置檔（合併到標稱裝置的欄位）、證據文件、目標。`DeviceProject` 拒絕未知欄位，所以 `truth`、`expected` 等鍵根本無法進入（單元測試）。
- 【事實】每個案例送給模型的**全部提示**都被掃描：案例 id、真值鍵、評估者理由、基準檔的 note 與 case id——四種設定、44 個任務，洩漏 0；替身模型讀到的所有內容也為 0。
- 【事實】篩檢的選擇函式沒有能接收裝置內容的參數；兩個不同裝置得到逐欄相同的計畫（e2e）。
- 【事實】`score.py` 不在產品套件中；產品程式不讀任何 truth 檔。
- 【揭露】保留案例的作者（獨立子代理）在交付訊息裡摘要了每個案例的真值，因此**實作者看過**保留案例的真值；替身規則與門檻是之後才凍結的。這組保留案例不能稱為「實作者未見」。開發案例 dv-01–dv-08 來自平台開發時用的 VS-SP-001 基準。

---

## 11. 其他稽核義務

- **重複或重疊假說**：【事實】新增 `cognition/overlap.py`：判別預測完全相同的兩個假說會被記錄並顯示，**不合併、不刪除**（「接點斷開」與「探針接觸電阻」可能共享預測但物理不同）。用 2026-10-21 的 Gemini「不足」案例回放：第 2 輪加入的 3 個替代假說，**正好是 3 組判別預測完全相同的重述**（例如一個假說文字是另一個的後半句）。
- **引用相關性**：【事實】涵蓋審查與篩檢審查的新假說，所引用的證據必須至少有一項與假說的陳述、機制、假設、干擾因子或否證有共同內容字（宣告的詞彙規則，不是語意判斷）；否則拒絕。每次的共同字詞都記錄。
- **Critic 預留**：【事實】辯論政策 1.2.0 預留 12,000 token（帳本的空白分詞計數）給反方。Stage B 之前，涵蓋審查、篩檢審查與任何重問，若會使剩餘預算低於預留，就不做並記錄。單元測試：預算偏緊時兩項審查被保留，反方照常執行。篩檢本身不耗 token。
- **舊報告勘誤**：【事實】舊報告 §2.2、§7 第 5 項「Gemini 是否接受 JSON schema 未實測」已過時：同一報告 §5.1 的實測中 Gemini 15/15 次（全部 26/26 次）都在 JSON schema 模式下被接受。已加註勘誤，原文其餘未改。
- **突變**：見 §7。
- **繁體中文呈現**：【事實】新增的系統文字全部中英對照、英文術語附在中文旁；研究頁的篩檢段落以名稱顯示檢查、觀測與結果，不顯示原始識別碼（L1 原始識別碼測試抓到一處後已修）。模型自寫的文字照舊標示「未翻譯」。canonical 紀錄未改。

---

## 12. 剩餘 G0 阻礙與需要 Owner 決定的事

阻礙：
1. 【阻礙】真實 LLM 驗證未做（無授權、無金鑰、無本機模型）。缺：Owner 授權的付費 Gemini 呼叫（或可用的合規本機模型）。
2. 【阻礙】新提示 `prm:hypothesis-screening-review@1.0.0` 尚未納入資格探測（probe）。真實研究使用前，需要加一個探測案例（會使現有資格鎖定失效、需重新測試）。
3. 篩檢後的機制要被確認，仍需不同的事先檢查或人員；在本領域，開路的唯一低成本判別檢查就是已讀過的那一項，所以這類機制目前只能由人員判斷或之後的量測解決。
4. 本機 7B 模型仍不能擔任主要推理；Lumerical 仍無；模型自寫文字仍不翻譯（同前次報告）。
5. 完整 719 條突變電池未重跑。

需要 Owner 決定：
1. **SPEC-ISSUE-016**：Reading B（篩檢是非驗證作業，新增 `VER-009`）或 Reading A（移除篩檢）。建議 B。
2. **結構摘要**是否啟用（預設關閉）。建議先在真實模型上與篩檢分開比較，再決定。
3. 是否要一條「授權審查即可提升篩檢後機制」的路徑（目前沒有；需規格條文）。
4. 授權真實 Gemini 重測（§13）。
5. **舊分支** `g0-exploratory-screening`：其中的提交作者為 AI 身分並帶簽章；我改寫作者後推送到 `-v2`。刪除舊分支需要強制操作，權限未允許，請 Owner 刪除或保留。所有 `-v2` 提交都以倉庫既有身分 `SpadesZ <rickiekuo1203@gmail.com>` 記錄；若要改用其他身分，請告知。

---

## 13. 之後的真實 Gemini 重測

前提：Owner 授權（會外送測試專案的範例證據並可能計費）、新建資料庫、`GEMINI_API_KEY` 由 Owner 設定、可連到的本機 qwen2.5:7b（或把 critic／utility 也指向外部模型）。建議先補 §12 阻礙 2 的探測。

```
# 每種設定各一個新資料庫
for F in baseline screening structure combined; do
  LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/<新建的資料庫_$F> \
  LAB_BRAIN_LIVE_PRIMARY=models/gemini-3.1-pro-preview LAB_BRAIN_LIVE_PRIMARY_PROVIDER=gemini \
  LAB_BRAIN_LIVE_PRIMARY_KEY_ENV=GEMINI_API_KEY LAB_BRAIN_LIVE_CRITIC=qwen2.5:7b LAB_BRAIN_LIVE_UTILITY=qwen2.5:7b \
  LAB_BRAIN_LIVE_FEATURES=$F LAB_BRAIN_LIVE_CASES=matrix \
  LAB_BRAIN_LIVE_EVIDENCE=docs/audit/g0-exploratory-screening-2026-10-27/evidence/live_gemini_$F \
  pytest tests/e2e/test_research_live_model_postgres.py
  python benchmarks/g0_screening/score.py docs/audit/g0-exploratory-screening-2026-10-27/evidence/live_gemini_$F/matrix.outputs.json
done
```

預估外部呼叫：每種設定約 10 次資格探測 +（3 個原始情境 + 22 個矩陣案例）× 約 5–7 次（篩檢審查只在有異常時多 1 次）≈ 每種設定 135–185 次；四種設定約 540–740 次。可先只跑 `screening` 與 `baseline` 以減半。

判讀：協定門檻在真實模型上同樣適用；治理不變量必須全為 0；有用性的數字才是 G0-S 的證據，仍需具資格的獨立審查者逐項判斷（G0-S 規定）。

---

## 14. 界線

未合併、未部署、未動正式資料（只用新建的測試資料庫）；沒有任何付費或外部模型呼叫；未執行 Lumerical；未啟用 SAI 3.4 runtime 或 SP 1.1.0；`READY_FOR_REAL_RESEARCH` 未改；SAI 3.4 基準與歷史證據未改（舊報告只加勘誤註記）。
