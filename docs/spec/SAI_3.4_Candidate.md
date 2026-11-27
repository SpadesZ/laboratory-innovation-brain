# SAI 3.4 Candidate — 自主科學建模與驗證

版本：`3.4.0-candidate.2`｜日期：2026-10-21｜狀態：**候選，待 Human Owner 核准**。

本版修正 `61f6beba0fb6898a9d18cca9bb7e8b4005a9f51c` 的 CONDITIONAL PASS 項目；保留架構與 ASM-001–018，未新增第 19 條需求。

`READY_FOR_REAL_RESEARCH = false`

## 0. 效力、基準與閱讀方式

本候選以 [SAI 3.3](SAI_3.3.md) 全文及其 a1–a18 修訂為繼承基準，增加完整的自主建模契約。
它是一份「凍結基準＋本文件增補＋附屬驗收契約」的版本化候選，並非用摘錄取代 3.3。
3.3 的規範、P1–P28、既有 Requirement/Test、事件與資料契約全部繼承；未提及部分原義保留。
3.3 仍是現行權威規格；本候選沒有啟用權限，也不授權改動 HARD-LOCK 行為。
§11 的全面啟用與 C34-A0 的限範圍離線開發核准分開；後者可先行，但不啟用 SAI 3.4。
未來離線 slice 須有具名、可追溯且明列範圍的架構核准，並遵守 active 3.3；不能由審查建議推定批准。

| 基準 | 固定識別 |
|---|---|
| 儲存庫 | `SpadesZ/laboratory-innovation-brain` |
| 檢視的整合分支 | `integration-integrity-accounts`，`f3fadf6eaa7676d27b0129beeb40239cba2e1723` |
| GitHub main | `d0ab848646dd7250fc4eadb1a37600860685e6ca`；整合分支尚未合併 |
| 3.3 文件 SHA-256（原始 bytes） | `d7576691ef846ef05d8a0036434402a6fb0317f3c28af97597d4fc5dc375c1aa` |

配套文件：[架構與路線圖](../architecture/sai34-autonomous-modeling.md)、
[驗收](sai34/acceptance.md)、[實作差距](sai34/implementation-gap.md)、
[遷移與變更](sai34/change-impact.md)、[Owner 決策與自我審查](sai34/decisions-and-review.md)、
[候選規範登錄](sai34/normative-statements.yaml)、[ADR-0013](../adr/ADR-0013-autonomous-scientific-modeling-candidate.md)。

§1–§10 每一條粗體 MUST 由獨立的 statement key 標示；同節其餘文字細化該契約。
這些義務的 Requirement/Test IDs 僅為候選命名空間 `ASM-* / T-ASM-*`。
候選登錄中的 `tests: []` 表示實作測試尚未交付，`planned_tests` 是待實現義務，不能算測試通過。
文件檢查也不能證明物理正確、散文覆蓋完整或 milestone 完成。

## 1. 必達產品目標與自主性邊界

<!-- statement: autonomy.production -->
**ASM-001 MUST：完成的 SiPh Lab 能由部署內的產品服務完成首次物理建模、執行、驗證與受控細化；生產研究流程不依賴 Codex、Claude Code 或其他外部 coding agent。**

開發工具可建立產品；它們不屬於產品控制平面。正式環境沒有開發 agent 的 CLI、工作階段、
個人登入、任務接手或編修 repo 步驟。內部科學推理可透過現有 ScientificLLM/ModelRouter，
但只輸出型別化提案，不取得 shell、原始 SDK、任意 Python/LSF 或部署寫入權限。
這不等同於禁止已授權的模型 API；敏感度、外送與成本仍走現有閘門。

首次建模是從研究條件與核准的模型族描述，在空白工作目錄建立新專案；不能以修改既有
`.ldev/.lms/.fsp/.icp` 或隱藏的預建專案冒充。既有專案匯入與參數掃描另列能力。
可重用經審查的建構元件；不宣稱能自主解決任何尚未定義的物理問題。
自主能力的範圍由版本化 capability envelope 明訂模型族、工作條件、物理假設與驗證範圍。
範圍外的請求安全停止，不要求外部 coding agent 來續跑。

<!-- statement: workflow.governed -->
**ASM-002 MUST：每次自主研究保留以下全鏈的版本化輸入、輸出、治理決定與可重啟檢查點，並沿用最便宜且足夠的驗證選擇。**

```text
Research Question → Literature & Example Discovery → Competing Hypotheses
 → Physical Model Specification → Autonomous Model Construction
 → Verification Planning → Licensed Lumerical Execution
 → Numerical & Physical Validation → Model Refinement
 → Evidence Admission → Causal Belief Revision → Research Report
```

這是科學責任鏈，不是「每個問題都強制跑 solver」的腳本。若既有證據或便宜檢查已足夠，
保留不建模的選擇理由。建構前先凍結問題、競爭假說、必要參數與驗證目的；建構後可依實際
資源細化 execution plan，但不能在看過評估答案後改評分規則。流程狀態與失敗分支見架構文件。

另設 **G0 — Pre-Lumerical Research Acceptance Gate**：在沒有 Lumerical 的情況下，
由通過身分驗證且有專案權限的研究者，經產品服務與真實、受治理的 LLM 完成問題→證據→
競爭假說/預測→可用的英文及繁中科學報告，保存完整 provenance 並逐項明列未執行模擬。
CatalogReasoner、mock/fake/canned responses 或只翻譯 UI 標籤都不能滿足 G0。
G0 與免模型的離線契約測試、G1–G9 的建模/物理驗收各自出具證據，不互相代替。
具體真實呼叫、科學可用性及負例條件見 [驗收契約](sai34/acceptance.md#21-g0--pre-lumerical-research-acceptance-gate)。

## 2. 文獻、範例與知識來源

<!-- statement: sources.provenance -->
**ASM-003 MUST：文獻、公開 Ansys 範例及其他外部材料經現有 ExternalSourceAdapter、專案授權與來源准入後才可參與模型提案；可讀、可執行、可修改、可散布分別判定，來源依賴不能算獨立佐證。**

`ReferenceRecord@1` 在既有 SourceWork/ArtifactOccurrence 上加 domain extension reference：
來源 URL/DOI、作者/發布者、標題、版本/commit、擷取 UTC 時間、原始內容 hash、頁碼/段落/檔案、
所用參數或操作、來源 family、引用角色、授權文字定位及其 hash、存取範圍與資料分級。
欄位無權威值時記 UNKNOWN；不能由模型填補。引用頁面有更新時建立新版本，不覆蓋舊的。

角色分為 `CONSTRUCTION_GUIDE / CALIBRATION / DEVELOPMENT_CHECK / HOLDOUT_REFERENCE`。
範例及其修改版、相同論文衍生資料、同一模型的數值匯出與螢幕圖歸入同一依賴 family。
建構、校準或開發已使用的 family 不進獨立 holdout。權利未知時可保存授權範圍內的定位與
書目，不下載或重散布不明附件，不執行其腳本。公開可見不等於開放授權。

範例中的程式碼只作不可信資料。由建構器重表達為允許的 typed operations；外來 instruction、
安裝指令、檔案讀寫、網路呼叫、隱藏的 script object 或其他可執行 payload 不隨專案載入。
人工核准來源授權與核准科學內容是兩個不同決定。

官方工程參考（原候選查閱 2026-10-20；本次未重新擷取，未下載或執行範例，未判定附件散布權）：

- [CHARGE simulation object](https://optics.ansys.com/hc/en-us/articles/360034918633-CHARGE-solver-Simulation-object)：設定與 normalization 欄位參考；不能充當器件真實性的證據。
- [Python API overview](https://optics.ansys.com/hc/en-us/articles/360037824513-Python-API-overview)：提供官方自動化與範例導覽；SDK 選用、版本與環境仍待相容性測試。
- [Licensing overview](https://optics.ansys.com/hc/en-us/articles/360033862333-Lumerical-product-components-and-licensing-overview)：設計環境、solver 與運算資源授權須各自盤點，不能假設一個 seat 涵蓋所有產品。

## 3. 型別化物理模型契約

<!-- statement: modelspec.typed -->
**ASM-004 MUST：建構與執行只接受版本化、單位可驗證且必要參數有來源的 PhysicalModelSpec；未知、矛盾或超出核准範圍的輸入不得用 solver 預設值悄悄補足。**

`PhysicalModelSpec@1` 由三層組成；本候選只定契約，沒有新增 runtime schema：

| 層 | 契約與責任 |
|---|---|
| 通用 immutable envelope | `spec_id/version/project_id/episode_id/domain_pack_ref/model_family_ref/schema_ref/content_hash/parent_ref`、研究問題與假說 refs、source refs、field-status、policy refs、分級與建立者 |
| DomainPack payload | geometry、materials、doping、contacts/boundaries、solver、mesh、conditions、observables、physical assumptions、validity envelope、輸入不確定度 |
| provider lowering | solver 版本相容表、允許 operation 版本、建構器版本與 readback；不把 vendor 欄位帶進 core |

每個物理量帶值、單位、維度、來源、有效範圍及不確定度/UNKNOWN 原因；正規單位採 SI，
vendor 邊界顯式換算並做 round-trip。拒絕 NaN/Inf、維度不合、未宣告欄位、循環參照與過大物件。
不能把 `0`、空值與 UNKNOWN 混為一談。時間、長度、頻率、電荷、濃度與總量/每長度正規化
各自有 schema；同量綱不同物理意義的量仍用不同型別。

CHARGE 第一個 payload `sp.charge.model@1` 最少包含：

| 類別 | 欄位與拒絕條件 |
|---|---|
| geometry | 座標系、2D/3D、尺寸/區域/拓樸、布林運算、接觸面與重疊優先序；無意義或未宣告的重疊/斷路拒絕 |
| materials | 材料庫版本與每區域 assignment、溫度/摻雜依賴、介電/能帶/遷移率/復合模型及係數來源；不可混用不同模型的參數 |
| doping | donor/acceptor、濃度維度、位置與分布、活化假設；製程劑量不直接冒充體濃度 |
| boundary | 電極/接觸型別、偏壓/參考端、絕緣/對稱/週期等邊界、熱邊界與電流符號；不存在接觸面的邊界拒絕 |
| solver | electrostatics/drift-diffusion、DC/SSAC/transient、統計/溫度/復合假設、求解器設定與明示預設、初始化/continuation 規則 |
| mesh | 全域/局部約束、接面/介面細化、品質條件、最大 cells/memory、收斂研究序列；不是單一 mesh label |
| observation | bias/frequency/temperature/time sweep、正負號、器件長度、總量與 per-length 正規化、Cj/Rs 抽取有效域及原始陣列保存 |
| assumptions | 每個假設的理由、來源、適用範圍、可改動分類、檢查與違反時的停止條件 |

模型族的權威必填參數清單由 DomainPack 版本決定；規格允許的值不代表物理假設已驗證。

## 4. 自主建構與安全修改

<!-- statement: construction.constrained -->
**ASM-005 MUST：模型建構由經審查的確定性建構器將 PhysicalModelSpec 降階為封閉的 typed operation 集合，在受限 worker 內執行；不執行模型生成的任意程式碼。**

內部 reasoner 只可提議 spec 或 `ModelPatch@1`。建構器擁有固定的 region/material/contact/
doping/solver/mesh/monitor 操作與型別，沒有 `eval_script`、任意函式名稱、shell、套件安裝、
外送或自訂 analysis script 的欄位。需要 vendor script 的底層細節只能來自受審查的固定模板；
參數以 SDK data call 或安全序列化傳入，不拼接未信任文字。新 operation 走正常軟體審查。

`BuildManifest@1` 保存 spec hash、operation DAG/hash、建構器與模板版本、material dependency
hash、環境、操作結果、新專案 hash、失敗診斷及 `ModelReadback@1`。readback 從 vendor 專案
重新讀回 geometry/material/boundary/solver/mesh 與 normalization，與原 spec 獨立比較。
儲存成功或生成漂亮畫面都不等於 readback 通過。空白建構測試同時保留專案前後清單。

worker 使用非管理員身分、專案專用暫存根、路徑正規化/符號連結逃逸拒絕、輸入唯讀、
限制輸出與記憶體、程序 allowlist、預設禁止網路；僅明列的 license endpoint 可通。
套件與模板以 hash 鎖定。共享 worker 每份工作使用乾淨 session，禁止沿用隱藏材料或變數。
接收的 artifact 不因副檔名而可信，匯入前檢查 active content；不能確認安全的舊專案隔離。

<!-- statement: execution.licensed -->
**ASM-006 MUST：真正 Lumerical 執行只由已資格化的專用 provider 與 licensed worker 提供；solver 身分、授權、產品能力或版本不符時拒絕執行，不以 mock 假冒。**

provider 實現既有 `SimulationBackend` 邊界並由 capability registry 對外揭露。
healthcheck 分清安裝、SDK 相容、design-environment license、solve/HPC entitlement 與即時可用資源。
預先探測不保證執行時仍有 seat；實際 checkout/釋放也進紀錄。license server secrets 不進
manifest、來源材料、模型 context 或一般研究報告。合規與站點安裝驗證由 license 管理者負責。

<!-- statement: resources.recovery -->
**ASM-007 MUST：建構、執行與細化依既有 Job/Run、ResourceDemand、BudgetGate 與 CostLedger 管理資源、重試、取消及恢復，所有外部副作用先授權與保留預算。**

沿用 `WAITING_RESOURCE`、受限重試、lease 與 idempotency；新增需求以 extension 宣告 GUI/solver/
HPC entitlement、CPU/GPU、記憶體、磁碟、wall time、seat time 與 project quota，不重造佇列。
worker 有 heartbeat、fencing token、逾時與優雅終止/強制終止規則；過期 worker 不能回寫。
無法判定 vendor 是否仍執行時標記 execution outcome UNKNOWN，先對帳程序與輸出，再決定重試。
不能以「exactly once」掩蓋外部 process 重複；每 attempt 有自己的紀錄，只有一個被接納的結果。
程式重啟從已提交檢查點續跑；取消後保留部分輸出作診斷，不當正式物理證據。
預算包含已完成、失敗、重試與待對帳成本；停止不等於免除費用。

## 5. 數值、參考與物理驗證

<!-- statement: validation.numerical -->
**ASM-008 MUST：數值驗證獨立記錄求解器退出、殘差/守恆、離散化與步階收斂、敏感度及數值不確定度；solver 宣告 converged 不能代替這些檢查。**

VerificationPlan 在求解前凍結 observable、適用域、測量運算、比較方法、容許誤差、
至少三層可比較的網格/步階、邊界距離研究、資源上限及失敗處理。非漸近、振盪、符號翻轉或
多解時不套用漂亮的 Richardson 數字；記 UNKNOWN/FAIL，提出可區分原因的下一步。
空間、bias/frequency/time 步階與外域尺寸分開研究，保留耦合效應。

<!-- statement: validation.physical -->
**ASM-009 MUST：物理驗證由版本化 DomainPack validators 與獨立 reference contract 完成，界定物理假設、適用範圍及不確定度；趨勢合理或與另一個 solver 相同均不足以單獨宣告物理有效。**

驗證器不重用建構器產生的「預期答案」作唯一 oracle；validator 的測量運算與抽取器以
獨立 fixtures 檢查。解析極限、守恆與對稱性可驗證實作；對真實器件的預測能力另需獨立、
條件可比且有測量不確定度的資料。reference 條件缺失時不可比，不自動降門檻。
驗收的六個層次及 observable 專屬指標見 [驗收契約](sai34/acceptance.md)。

<!-- statement: benchmark.independence -->
**ASM-010 MUST：建構/校準/開發資料與獨立 holdout 依來源 family、器件/製程批次與參數推導依賴隔離；評估答案及逐案例分數不回饋給建模或細化迴圈。**

`BenchmarkSplitManifest@1` 保存 family DAG、分割規則、資料與評分器 hash、封存時間、
存取主體與不相交證明。只移除檔名或隨機切陣列列數不足以隔離。獨立 evaluator 可讀答案、
模型輸出與 sealed protocol；builder 看不到 hidden ground truth、專家專案或 scoring credentials。
分數由不受 builder 控制的程序產出並簽存。揭露結果後若改模型，該 holdout 退出獨立驗收，
重新預註冊新集合；保留原失敗。沒有獨立 reference 時，G4/G5 明列 BLOCKED。

## 6. 自動細化與停止

<!-- statement: refinement.bounded -->
**ASM-011 MUST：自動細化只在預先核准的物理假設、參數範圍、開發目標與資源預算內進行，產生 immutable 子版本，不改評估答案、既有證據、驗證器或結論標準。**

`RefinementPlan@1` 區分三類變更：

1. 數值：網格、步階、容許誤差、初始化；凍結物理假設，並防止 continuation 隱藏另一分支。
2. 校準：只用 CALIBRATION/DEVELOPMENT 資料，具權威範圍的參數與識別性/相關性分析。
3. 科學：材料/遷移率/復合模型、接觸性質、geometry、doping、邊界或物理機制改動。
   若已屬核准競爭假說的候選空間，可建立另支 spec 並重新驗證；超出空間即 ReviewItem。

`ModelPatch@1` 指定 parent hash、允許欄位、新舊值、理由、分類、policy/budget refs 與
預期可反駁效果。分類由規則驗證，不由 LLM 自稱。任何參數改動都使相關驗證失效；
不能把前一模型的 PASS 搬到新模型。每次保留敏感度、成功/失敗、停止理由與 lineage。

停止條件：全部目標驗收通過；預算/attempt/wall-time 用盡；連續無實質改善達預定上限；
不識別/多解/模型失配；缺權威參數；無資源；無足夠行動；授權被撤銷。後六者停止時，
結果分別是 PARTIAL/UNKNOWN/BLOCKED 或需要 ReviewItem，不能包成研究成功。
具體上限在執行前由版本化 policy 設定；必填，不能留無限迴圈。

## 7. 證據准入與因果信念

<!-- statement: evidence.admission -->
**ASM-012 MUST：模型輸出僅能經既有 Artifact/Observation/Attestation 准入路徑進入科研紀錄，保留 Run、BackendValidity、ValidationReport、條件、不確定度、來源依賴與模型族身分；未驗證結果不能取得較高 authority。**

solver 執行成功可保存 raw artifact；不代表可用於任何結論。模擬 Observation 描述的是
模型在指定條件下的輸出，不能冒充實體量測。獨立性按來源與建模依賴追蹤；同一模型的
多次 mesh、不同 solver 的共享假設、同一範例的翻版都不自動增加獨立證據數。
失敗、UNKNOWN 與 SIM_TO_REAL_CONFLICT 保留，不以刪除或平均處理消失。

<!-- statement: causal.warrant -->
**ASM-013 MUST：自主建模結果沿用 Causal Warrant Gate、AuthorityPolicy、TransitionPolicy、durable authorization Decision、BeliefRevisionEvent 與 replay；數值吻合不能自行升級為因果機制已確認。**

模型預測、reference agreement、機制辨識與可用於介入的因果主張分開。共同可觀測預測
不足以辨識 rival 機制。既有 domain declaration 的版本/範圍、signed reviewer grant、
職責分離與確認可重推導檢查仍適用。ASM 不新增自動產生 warrant 的捷徑。
SP 1.1.0 候選沒有整入基準，也沒有因這份文件獲准啟用。
DISCRIMINATION、多原因與擴大 declaration 等未決事項仍交 Owner（D-03）。

## 8. 人工介入、隔離與研究記憶

<!-- statement: human.intervention -->
**ASM-014 MUST：人工介入由明列的科學歧義、缺少權威參數、安全/授權、不可逆動作及既有強制簽核觸發，透過單一 ReviewQueue 留痕；自動化不能代簽或把逾時視為同意。**

先把可核准的模型族、參數範圍與風險 policy 一次核清，範圍內日常建構/重試不逐步詢問。
必要簽核不得以「降低人工摩擦」取消。ReviewItem 包含確切缺口、最多兩個可選方案、
證據、影響、需要誰決定及有效期；續跑重新驗證授權、分級、簽章、版本與剩餘預算。
人類帳號角色只有 **ADMIN、MEMBER**。Human Owner 是本規格的決策責任人，並非第三種帳號角色。
project membership/OWNER 是專案授權；independent scientific reviewer authorization 是另行驗證的
科學審查授權；worker service identity 是非人類服務身分。三者都不是新增人類帳號角色，
不從 ADMIN/MEMBER 或彼此自動推導。ADMIN 能監督讀取不代表能作科學簽核；worker 沒有 reviewer 私鑰。
既有 A3、A9、A12 安全決策保持未決，不因這項分類或自主性而放行。

每一 spec/build/attempt/patch/validation/report reference 受現有 project scope 與當前 clearance
限制；含共享 artifact 時仍需 project occurrence。條件/問題敏感度在首次與續跑一致。
研究記憶只重用當前仍可授權、未撤回且 warrant 可驗證的紀錄；失敗可作 case memory，
不自動變成 hard validator 或 approved heuristic。

## 9. 可擴充 solver 與雙語介面

<!-- statement: extension.domain_boundary -->
**ASM-015 MUST：core 只持有 model/build/validation 的通用 envelope 與 provider/capability 介面；CHARGE、MODE、FDTD、INTERCONNECT 及多物理細節由 DomainPack/provider 擁有，移除它們不破壞 core。**

保留 §10.2 四種工具動詞與 `DOM-SP-TOOL-xxx` 歷史 ID；不重新命名舊工具。
建模不是第五類公開 `build_*` 工具。建構是 provider 私有 typed protocol，可由註冊的
`run_*` workflow 組合，inspection 用 `inspect_*`，驗證用 `validate_*`；新公開 ID 另經審查。
建構 Job 不冒充 solver Run，build artifact 與求解的 Observation 分開。
多物理交接檢查座標、單位、網格內插、守恆、材料模型相容性、normalization 與迭代收斂；
單一 solver PASS 不傳遞為整個 coupling PASS。

<!-- statement: interface.bilingual -->
**ASM-016 MUST：研究者所見的英文/繁中科學內容涵蓋假說、預測、觀察、解釋、不確定度、結論、限制及匯出；兩語保留相同的證據、可機器驗證狀態、數值、版本、成本與停止原因，原始 canonical records 不被翻譯覆寫，未知、未執行模擬或欠因果授權不得表達為成功。**

沿用版本化 MessageCatalog 與既有五類 error taxonomy，不加第六類。
新增 reason codes 是獨立分類，遵守 UX-001–007；一般介面不洩漏 secrets/stack trace。
識別碼、數值、單位、原始引文與儲存資料不由語系切換改寫。
科研敘述本身提供兩語，不僅翻譯導覽、按鈕或欄位標籤；適用於研究頁、報告、歷史檢視及
所有提供的匯出格式。沒有對應 canonical 內容時保留缺漏/UNKNOWN，不為湊雙語捏造觀察。
翻譯/解釋是衍生呈現，綁定 canonical record/hash、目標語系、翻譯產生者/版本與 provenance；
可追溯至原文，不改其語言、內容 hash、證據身分、簽章、數值或事件狀態，也不新增科學 authority。
兩語皆區分 observation 與 interpretation，保留否定、條件、機率/不確定度、claim strength、
rivals 與未執行模擬。逐項 semantic coverage、雙語審查與 export parity 納入 G0/G9 及 T-ASM-016。
標準輸出包含可讀摘要＋可機器驗證的證據清單、假說/rival、limitations、失敗與 blocked 項目；
每個主張連到具分級授權的精確來源與 run，沒有通過的階段不顯示綠色「已驗證」。

## 10. 重現與正式驗收邊界

<!-- statement: replay.reproducible -->
**ASM-017 MUST：從封存的 typed spec 與依賴可在乾淨、已資格化的環境重建、重跑、重抽取與重評分；數值相等性依預註冊容差判斷，原始 bytes/hash 不變性與浮點可重現性分開記錄。**

G7 分開記錄 `G7-SITE`（單站同一已資格化安裝的乾淨 session 重現）及 `G7-WORKER`
（第二個獨立合格 worker 的移植/重現）。單站可先接受其明列範圍，不以缺第二 worker
阻擋合法單站驗證。只有第二 worker 的證據才能接受 G7-WORKER；同一安裝換 session/程序
不算第二 worker，同站多 worker 也不能宣稱跨站資格。跨站主張另需目標站點資格與重播證據。

Run extension 保存 spec/build/operation hashes、provider/SDK/solver/OS/硬體版本、材料庫、
種子與執行緒、resource/lease/attempt refs、實際 checkout、輸入輸出陣列與單位、
抽取器/驗證器/BenchmarkPolicy 版本、stdout/stderr/exit、UTC times、cost reconciliation。
不能以一個 project hash 取代外部材料或 license 環境依賴。不可封存的相依寫明取得方式、
權利與到期風險；缺少時結果不可宣稱可重播。

<!-- statement: readiness.external_gate -->
**ASM-018 MUST：授權前分開接受離線軟體/安全契約與真實受治理 LLM 的 G0 科研工作流程；兩者均不驗證未執行的 solver 或物理精度，真實 solver/獨立物理驗證仍需外部驗收，在 Owner 接受適用範圍的全部關卡之前 READY_FOR_REAL_RESEARCH 保持 false。**

六層狀態採 `PASS / WARN / FAIL / UNKNOWN / BLOCKED`，每層各有證據與適用範圍。
單一總分不能取代逐層結果；建立成功不推出求解成功，求解成功不推出數值收斂，收斂不推出
reference agreement，agreement 不推出物理有效，物理有效不推出因果結論。
這份文件完成與 CI 成功只表示候選文件可審，不代表任何新增 runtime 功能完成。

## 11. 規格啟用與歷史相容

本候選沒有 normative override。下列動作均未在本次執行：

C34-A0 只收取離線 slice 所需的架構核准，至少包含 D-01 的設計範圍、D-03 的既有 CWG
邊界、D-05 的 fixture/來源權利與 D-06 的無外部副作用限制。核准紀錄明列 actor、時間、
決策/ADR 版本、允許動作、排除項目與適用 slice；缺它即不開始該 slice。
D-02 的真實物理 benchmarks、D-04 的 license/worker 與 D-08 的部署/就緒不必在 A0 全數
結案，而在各自 milestone 前核准。任何新的安全權限或未決 A3/A9/A12 行為不能被離線核准繞過。
本次 Human Owner 已同意審查建議的方向、條件與文件修正；詳見決策紀錄。
這次只修候選文件，正式決策仍 OPEN；具體離線 runtime slice 尚未獲准開始。

1. Owner 審核 [決策清單](sai34/decisions-and-review.md) 與 ADR-0013；明確接受/修改新長期目標、能力範圍及 P0 科學/安全契約。
2. 維護者凍結獲准的 3.4 全量版本，逐條對照 3.3 的章節、Appendix、Requirement/Test；消除直接衝突，不能用「3.4 優先」帶過。
3. 依 §0.3/§23.5 將核准 ASM 義務及真正的 test mapping 納入 active spec/registry/milestones，補散文覆蓋人工審核；未實作義務保留具名 deferral 與 review date。
4. 分 slice 實作，版本化新 domain extension/storage schema；既有 scientific record 不回填假造新 spec refs。必要 migration 另提驗證、回退及資料保存方案。
5. 經適用 CI、license 環境、holdout 與 Owner 簽核後逐項改里程碑；M0a–M3 的既有簽核、M4 的 TST-001 blocker 及 M6–M8 原狀保留。

驗收門檻不得由實作人員為通過測試調低。與既有簽核衝突時開 spec issue；停止受影響的
實作 slice，仍可整理候選文件及不受影響的證據。此版不更動部署、金鑰、現有資料庫或 paid API。
