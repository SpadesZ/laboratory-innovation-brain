# Laboratory Innovation Brain

實驗室的科研信念狀態，作為可追溯、可反駁、可繼承的結構化記憶。

- **規格**：[SAI 3.3](docs/spec/SAI_3.3.md)（`SAI` 是規格文件名稱，不是產品名稱）
- **目標系統**：Laboratory Innovation Brain
- **第一個 DomainPack**：Silicon Photonics（**不是** core hard-code）

它不是論文問答機器人，不是 simulation 跑批工具，也不是 LLM agent swarm。它要做三件事：

1. **記得為什麼** — 不只存結論，存證據鏈與當時的條件
2. **知道自己不知道** — `UNKNOWN` 是合法狀態，不得由模型補值
3. **知道下一步最便宜的驗證是什麼** — 不預設一定要跑模擬

## 核心不變式

任何繞過這條路徑直接修改信念狀態的實作，都會被靜態測試拒絕（SYS-001）：

```
Artifact / SourceWork
  → Claim / Observation
  → Attestation
  → RelationJudgment
  → TransitionPolicy
  → BeliefRevisionEvent
  → EpistemicStateProjection
```

## 快速開始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"
.\.venv\Scripts\python.exe -m pytest
```

不需要 PostgreSQL、Lumerical license 或外網即可跑完核心測試（AGT-007）。需要真實後端的測試以
`postgres` / `lumerical` / `network` marker 標記並預設跳過。

```powershell
# 需要真實 PostgreSQL 的測試（開發／測試用資料庫，不是產品）
docker compose -f compose.dev.yaml up -d
.\.venv\Scripts\python.exe -m pytest -m postgres
```

## 以 Docker 執行本機產品

```powershell
docker compose up --build        # 啟動；開啟 http://127.0.0.1:8765/
docker compose down              # 停止；資料庫、artifact 與產生的密碼全部保留
docker compose down -v           # 重設：刪除資料庫、artifact 與產生的密碼（無法復原）
docker compose logs -f web       # 工作區日誌
docker compose logs local-models # 本機模型（Ollama）探測結果
```

- 導覽：首頁 `/` · 研究資料 `/data` · 新增研究 `/runs/new` · 研究紀錄 `/episodes` · AI 模型設定
  `/settings/llm` · 系統狀態 `/status`。頁面時間以 `LAB_BRAIN_TZ`（預設 `Asia/Taipei`）顯示；儲存的時間
  一律為 UTC。

- 包含：PostgreSQL 17 + pgvector、每次啟動自動 migration、管理者 bootstrap（研究者、其 project 與
  成員資格、LLM 管理權）、研究工作區、本機輕量模型路由設定；皆有 health check。
- **只綁定主機的 loopback**（`127.0.0.1:8765`）：工作區沒有登入機制，區網中任何人都不能連到它。
- **不在映像檔或 compose 檔中放任何密碼**：資料庫密碼在第一次啟動時產生，只存在 `secrets`
  volume。在「AI 模型設定」直接貼上的 API 金鑰保存在只掛載到 `web` 的 `credentials` volume（每把金鑰
  一個 0600 檔案、以不透明 ID 命名），資料庫只存參照與指紋；這是**檔案權限隔離，不是加密**——能讀取
  Docker volume 的人就能讀取金鑰。`docker compose down` 會保留金鑰，`docker compose down -v` 會一併
  刪除。也可在「進階設定」改用 git 忽略的 `deployment/docker/llm-keys.env`（範本為
  `llm-keys.env.example`）中的環境變數。
- 持久資料位於 Docker named volumes：`lab-brain-workspace_db`（資料庫）、
  `lab-brain-workspace_artifacts`（上傳檔案原始位元組）、`lab-brain-workspace_secrets`（產生的密碼）。
  以 `docker volume inspect <名稱>` 查看。
- 可在同目錄的 `.env`（git 忽略）覆寫：`LAB_BRAIN_PORT`、`LAB_BRAIN_ACTOR`、`LAB_BRAIN_PROJECT`、
  `LAB_BRAIN_CLEARANCE`、`LAB_BRAIN_LOCALE`、`LAB_BRAIN_OLLAMA_URL`、`LAB_BRAIN_INFERENCE_DEADLINE`
  （見 `compose.yaml` 開頭）。
- `LAB_BRAIN_INFERENCE_DEADLINE`（秒，預設 180）是這個部署每次模型呼叫可等待回應的上限：能力測試與
  研究中的模型呼叫都以它為準；若某個已確認模型的必要測試紀錄比它慢，配置不會顯示為可套用。只用 CPU
  的本機模型需要較大的值。逾時會記為「回應逾時」（TIMEOUT），不是「連不上」。
- 主機上的 Ollama 經由 `host.docker.internal` 以 LOCAL 路由連線（Linux 需讓 Ollama 監聽
  docker bridge，例如 `OLLAMA_HOST=0.0.0.0`）。本機模型只經既有能力探測、只自動綁定輕量 slot，
  主要推理與獨立批判永遠由研究者自行選擇。
- 管理指令（持有資料庫憑證者即為部署管理者），經由映像檔的 entrypoint 取得資料庫連線：
  `docker compose run --rm --no-deps init lab-brain admin show`；同樣方式執行
  `admin member <project> <actor> --clearance ... --scope LLM_EGRESS`、
  `admin project <project> --name ... --privacy-mode RESEARCH`、`admin llm-admin <actor>`。

設計與驗證記錄：[`docs/implementation/system-closure.md`](docs/implementation/system-closure.md)。

## 研究一個問題：`lab-brain research run`

給一個研究目標與本地檔案，開一個 ResearchEpisode，得到一份完整報告：輸入狀態、證據與來源、
互相競爭的假說、辯論與批判、目前信念狀態、驗證計畫、已執行的檢查、**等待中的模擬**、溯源與下一步。

```powershell
$env:LAB_BRAIN_DATABASE_URL = "postgresql://lab_brain:lab_brain@localhost:5433/lab_brain"
.\.venv\Scripts\python.exe scripts\migrate.py
.\.venv\Scripts\lab-brain.exe research run `
  --project prj:ps-rs --actor act:rkuo `
  --goal "Why is Rs extremely high and weakly bias dependent while Cj trends normally?" `
  --measurement fixtures\evidence\rs_anomaly_report.md `
  --verification-input PS-504.device.json `
  --literature-corpus fixtures\external\literature_corpus.json `
  --literature-query "series resistance contact normalization reverse bias" `
  --artifact-root .\artifacts --report report.md
```

- 執行者必須是該 project 的有效成員；否則沒有 episode、沒有資料列、沒有報告。
- 每個檔案的 trust class 由使用者宣告（`--measurement` / `--run-record` / `--note`），系統不推斷。
- 外部文獻只在同時給出 provider 與**使用者宣告為 public 的查詢**時才會被搜尋。
- **沒有模擬器時不會假裝有**：Lumerical 未安裝／無授權時，所有 SIMULATION capability 標為
  UNAVAILABLE；便宜的檢查照常執行，最佳下一步若需要模擬，則在報告中列為 **BLOCKED / pending**，
  episode 以 SUSPENDED 停放，等可用時以同一個 episode 續跑。
- 沒有設定語言模型時，假說／批判由 DomainPack 機制目錄的本地規則推理器產生，並在
  InferenceProvenance 與報告中如實標示（`rules:<catalog>`，非 LLM）。

### 續跑同一個 episode：`--episode`

```powershell
.\.venv\Scripts\lab-brain.exe research run `
  --project prj:ps-rs --actor act:rkuo --episode <episode id> --artifact-root .\artifacts
```

- `research run` 不帶 `--episode` 一律開**新** episode（id 由系統產生）；帶 `--episode` 只代表**續跑**。
- 只能續跑**自己開的**、**同一 project** 內、處於 SUSPENDED 的 episode；未知的 id、別的 project 的
  episode、同事開的 episode 一律得到同一句拒絕，且不寫入任何資料列。
- COMPLETED / ABANDONED 的 episode 不接受新的 research run；另一個 run 正在進行時也拒絕。
- 續跑經由 `episode_resume`（正式生命週期）恢復，沿用第一次 run 的假說集合、辯論、驗證輸入與框架，
  **不重新辯論**、不接受新輸入；已執行過的檢查不會再執行；每次 run 記錄於 `research_runs`。

設計與驗證記錄：[`docs/implementation/product-vertical.md`](docs/implementation/product-vertical.md)。

### 在瀏覽器中研究：`lab-brain web`

```powershell
.\.venv\Scripts\lab-brain.exe web --actor act:rkuo --artifact-root .\artifacts
# 開啟 http://127.0.0.1:8765/
```

導覽依研究者的工作順序排列：**首頁**（現在該做什麼）· **研究資料**（要把資料交給 Lab Brain，就是來這裡）·
**新增研究** · **研究紀錄** · **AI 模型設定**（僅 AI 模型管理者）· **系統狀態**。

- **研究資料**（`/data`）：「＋ 匯入研究資料」→ 選檔案 → 宣告資料類型（量測報告或實驗紀錄／模擬或運算
  紀錄／筆記、想法或文獻摘錄）→ 宣告資料分級（公開／實驗室內部／實驗室機密／保密協議）。兩者都必填、
  沒有預設值、系統不推斷；超出自己閱讀權限的分級不能選（會說明原因）。檔案走唯一的正式匯入路徑
  （secret scan → artifact 與 occurrence → 段落 → inbox item），狀態為 可用於研究／部分可用／處理中／
  需要人工確認／與既有檔案內容相同／已被安全規則擋下／處理失敗，每一種都說明發生了什麼、下一步怎麼做。
  相同內容再次上傳是同一個 artifact（DUPLICATE），不會產生第二份證據。
- **新增研究**（`/runs/new`）：研究問題與其分級 → 研究專案 → 勾選研究專案中已可用的資料（不必重新
  上傳；別的研究專案的資料永遠不會出現）→ 選填新檔案 → 選填外部資料來源（本機文獻檔＋確認可公開的
  查詢、驗證輸入）→ **確認研究輸入**（列出這次研究將使用的全部內容）→ 開始研究。選用既有資料時直接
  使用已處理好的段落，不會重新匯入、不會複製證據。
- **研究任務**頁面顯示目前狀態（例如「等待中，可以繼續」）、繼續研究、執行紀錄與原樣保存的研究報告；
  識別碼放在「技術細節」。沒有模擬器時，需要模擬的檢查列為等待中，之後可以繼續同一項研究。
- **系統狀態**：資料庫、檔案儲存、研究資料匯入、AI 模型配置、本機模型（Ollama）、外部 AI API、
  模擬（Lumerical 未安裝時顯示為已知限制，不是故障）與無法使用的功能及原因。
- 一個 workspace 代表一個 actor（與 CLI 的 `--actor` 相同的信任模型），只綁定本機 loopback；授權在
  伺服器端逐一請求檢查；所有 POST 需要 CSRF token；前端沒有任何 JavaScript。

設計與驗證記錄：[`docs/implementation/research-data-workspace.md`](docs/implementation/research-data-workspace.md)
（先前版本：[`web-workspace.md`](docs/implementation/web-workspace.md)）。

### 介面語言與 AI 模型設定

- 頁首 **English／繁體中文** 切換（`lab-brain web --locale zh-TW` 可設定預設）。只翻譯介面；報告內容、
  證據、識別碼與狀態值一律原樣保存與顯示。介面語言與研究輸出語言（英文）是分開的。
- **AI 模型設定**（僅部署授權的 AI 模型管理者）分四步：① 新增模型連線（模型服務／名稱／API 金鑰或本機
  模型／新增；自訂網址與環境變數在「進階設定」）② 取得可用模型 → 選模型 → 執行模型能力測試 → 確認此
  模型 ③ 指派模型給研究工作（研究角色 → 模型用途寫在程式中；只能選已確認、且通過該用途所需測試的模型）
  ④ 檢查並套用配置。每個階段都顯示「下一步」，缺什麼以「尚待處理／怎麼完成」清單呈現，完成後只有一個
  「套用配置」按鈕；服務網址、金鑰來源、內部識別碼與路由細節放在「進階設定與技術細節」。
- 外部 API：選模型服務、填名稱、貼上 API 金鑰、按「＋ 新增」。金鑰保存在此部署的憑證儲存空間
  （Docker：`credentials` volume，以檔案權限保護、未加密；Windows 原生執行：Windows 認證管理員），
  資料庫只存參照（`file:` / `wincred:` / `env:`）與指紋（`****abcd`），之後不會再顯示。更換金鑰後舊金鑰
  立即停用並刪除；移除連線時，除非另一個連線仍在使用，否則一併刪除。環境變數與既有憑證參照在「進階設定」。
- 本機模型（Ollama）：不需要也不顯示任何金鑰欄位；頁面直接顯示能否連上本機 Ollama，按「取得可用模型」
  即建立連線並取得模型清單。設計記錄：[`docs/implementation/model-credentials.md`](docs/implementation/model-credentials.md)。
- 傳輸：連到其他主機的模型服務一律必須是 `https://`；明文 `http://` 只能連到這台電腦（本機 Ollama、
  容器部署宣告的 Docker 主機）。模型呼叫一律不跟隨轉址（redirect），金鑰與研究內容不會被帶到別處。
  舊資料中違反此規則的連線無法啟用、測試或用於研究。設計記錄：
  [`docs/implementation/model-transport.md`](docs/implementation/model-transport.md)。
- 研究的辯論若在產生任何假說集之前就失敗（例如模型呼叫逾時），研究任務會「暫停」而不是結束；修正原因
  後按「繼續」，同一個研究任務會以第一次已採納的證據重新辯論，不會重新匯入或重新採納。設計記錄：
  [`docs/implementation/inference-deadline-and-debate-retry.md`](docs/implementation/inference-deadline-and-debate-retry.md)。
- 模型能力測試記錄「證明了多少」：假說引擎的測試以這個部署的研究所需的競爭假說數量進行（研究的垂直領域
  每個已編目的機制一個；矽光子為 5 個），並記錄該數量。只證明較少數量的模型不能用於「主要推理」：配置
  檢查會列出原因，研究會在呼叫模型前被拒絕。測試規則（測試內容、角色提示詞、回應格式）改變後，先前完成
  的模型確認即失效，必須重新測試並重新確認；舊的確認紀錄與推理來源紀錄保留不變。設計記錄：
  [`docs/implementation/role-qualification.md`](docs/implementation/role-qualification.md)。
- 假說引擎的能力測試是一組固定、有版本的一致性測試（hypothesis-conformance@1.0.0）：除了原本的單一結果
  空間案例，還有一個多結果空間案例，其證據會提到不屬於任何宣告結果空間的量。模型必須在每個案例中都提出
  足夠數量的假說，且每個預測只能使用 CONTEXT 中宣告的結果空間（含版本）與該空間允許的結果；自行從證據
  推論出結果空間的模型不會通過。測試規則改變後，舊的模型確認會失效，而且必須重新測試才能再確認（不能只
  解除確認再確認）。設計記錄：
  [`docs/implementation/hypothesis-conformance.md`](docs/implementation/hypothesis-conformance.md)。
- 每一筆模型能力測試結果都記錄它執行時的測試規則識別碼；確認模型時只採用在目前測試規則下完成的測試
  結果。舊的、未記錄規則的測試結果不能用來確認模型，以它們確認的既有模型也會被拒絕使用，直到重新測試
  並重新確認。設計記錄：[`docs/implementation/probe-semantics.md`](docs/implementation/probe-semantics.md)。
- 套用配置後，新研究經由同一個 `ScientificLLM`、預算／外部傳輸規則、型別化角色解析器與
  InferenceProvenance 使用真實模型；未套用時由本機規則式推理負責（明示的備援）。「反方審查」退回
  「主要推理」時會明確標示「不是獨立的模型」。
- 命令列（`lab-brain research run`）永遠不呼叫語言模型；有配置套用中時會拒絕執行，請改用工作台。
- **兩種權限分開**：AI 模型設定是部署層級的管理（研究專案成員資格不給予此權限）；某個研究專案的證據
  能否送往外部 AI API，由**該研究專案自己**的外部傳輸設定決定（`/projects/<id>/egress`），需要該專案的
  `LLM_EGRESS` 核准權限、只能核准自己有閱讀權限的分級、私有模式的專案不能外送。

設計與驗證記錄：[`docs/implementation/web-workspace-v2.md`](docs/implementation/web-workspace-v2.md)、
[`docs/implementation/research-data-workspace.md`](docs/implementation/research-data-workspace.md)。

## 專案結構

| 路徑 | 內容 |
|---|---|
| `src/lab_brain/core/` | domain-agnostic 核心：models / epistemic / provenance / repositories / policies |
| `src/lab_brain/domains/` | DomainPack；`silicon_photonics/` 擁有全部光子物理與 Lumerical specifics |
| `src/lab_brain/spec/` | 規格的機器可讀投影，供 T-SPEC-001 / T-SPEC-002 使用 |
| `migrations/` | 版本化 SQL migration，schema 語意的唯一落地處 |
| `docs/normative_statements.yaml` | Normative Statement Registry（§23.6） |
| `docs/milestones.yaml` | 里程碑閘門與 requirement 分配（§26.1） |
| `docs/spec_coverage_audit/` | 每個里程碑出口前的人工稽核記錄（§23.5 (2)） |
| `docs/adr/` | Architecture Decision Records |
| `IMPLEMENTATION_STATUS.md` | 當前實作狀態，Requirement / Test 逐條對照 |

`core/` 不得 import `domains/silicon_photonics`（§24.2，由 T-EXT-001 強制）。

## 規格治理

59 requirements ↔ 59 tests（`v3.3-a6` 新增 EVI-009 後由 58 改為 59；權威數字由
`scripts/update_status.py` 自規格推導寫入 `IMPLEMENTATION_STATUS.md`，此處僅為轉述）。
兩條 spec 測試守住這個不變式：

| Test | 檢查 |
|---|---|
| `T-SPEC-001` | Requirement ID 唯一；每條 requirement 至少一個 test；沒有 test 指向未知 ID |
| `T-SPEC-002` | Registry 內部一致；每筆 entry 對應既有 Test ID 或帶明確 DEFERRED rationale |

**Registry 的完整性不由 CI 保證。** §23.5 把覆蓋責任拆成兩段：T-SPEC-002 只驗證登錄項彼此一致，
「正文每一條 hard MUST 都已登錄」是人工稽核閘門，產出 `docs/spec_coverage_audit/<milestone>.md`。
T-SPEC-002 通過**不得**被推論為 registry 完整。

遇到規格內部衝突時，依 AGT-015：**block 當前 slice、建立 spec issue**，不得選「看起來比較新」的那段繼續施工。

## 貢獻規則：commit 不得標註 AI 作者

這是**儲存庫貢獻規則**，不是 SAI Requirement——它不新增 Requirement/Test ID，59 ↔ 59 不受影響。

commit message **不得**出現把此次 commit 的作者身分歸給 AI 的 trailer 或署名行
（AI 身分的 `Co-Authored-By:`、`Generated-by:`、`AI-generated:`、`Assisted-by:` 等，
以及 `Generated with <模型>` 這類 footer）。

規則刻意窄：

- **人類的 `Co-Authored-By:` 不受影響**，包含 GitHub 的 `@users.noreply.github.com` 私密信箱；
- **在內文討論 AI 完全可以**——提到 provider adapter、benchmark 用了哪個模型、甚至討論這條規則本身，
  都不會被擋。被擋的只有「署名」。

```powershell
.\scripts\dev.ps1 hooks            # 安裝 commit-msg hook（core.hooksPath -> .githooks）
.\scripts\dev.ps1 commit-hygiene   # 手動檢查目前 enforced 範圍
```

**hook 只是即時回饋,CI 才是閘門。** `core.hooksPath` 需手動開啟、`--no-verify` 可略過、
新 clone 預設沒有、網頁介面 commit 根本不會跑 hook——所以 `.github/workflows/ci.yml` 的
`commit-hygiene` job 才是權威,它重跑 `ENFORCED_FROM..HEAD` 全範圍。

**向前適用。** `ENFORCED_FROM` 是規則建立前的最後一個 commit;既有歷史已逐筆驗證乾淨,
**不為了套用事後規則而改寫已發佈的歷史**。
