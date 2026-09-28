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
# 需要真實 PostgreSQL 的測試
docker compose up -d
.\.venv\Scripts\python.exe -m pytest -m postgres
```

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

- 同一個研究流程的網頁介面：選 project、輸入目標、上傳 measurement / run record / note、
  （選填）verification input 與 literature corpus，送出後即得到 episode；之後可再回來查看並
  **Continue** 一個 SUSPENDED 的 episode；COMPLETED 的 episode 為唯讀。
- 頁面顯示的是該次 run 由研究服務回傳、原樣記錄的報告（與 CLI 同一份資料、同一個 Markdown
  renderer），加上 episode 與 research run 的即時狀態；前端沒有任何 JavaScript，也不做任何推導。
- 一個 workspace 代表一個 actor（與 CLI 的 `--actor` 相同的信任模型），只綁定本機
  loopback；授權每個請求都在伺服器端檢查；所有 POST 需要 CSRF token。

設計與驗證記錄：[`docs/implementation/web-workspace.md`](docs/implementation/web-workspace.md)。

### Web Workspace V2：語言切換與 LLM 設定

- 頁首固定導覽（研究 Episode／新研究／LLM 設定／執行環境）與 **English／繁體中文** 切換
  （`lab-brain web --locale zh-TW` 可設定預設）。只翻譯介面；報告內容、證據、識別碼與狀態值
  一律原樣顯示。介面語言與研究輸出語言（英文）是分開的。
- **LLM 設定**：連線 → 取得／宣告模型 → 能力測試 → 鎖定 → Slot 綁定 → 執行環境就緒 → 啟用。
  角色永遠不直接綁定模型（CognitiveRole → LogicalSlot 唯讀顯示）；每個 slot 只能綁定已鎖定、且
  實際通過該 slot 所需能力探測的模型。
- 憑證只以參照保存：`env:變數名稱`，或 Windows Credential Manager（`wincred:`）；資料庫只存參照
  與指紋（`****abcd`）。沒有安全儲存區時，直接輸入的金鑰會被拒絕（fail closed）。
- 啟用執行環境後，新研究經由同一個 `ScientificLLM`、預算／外送閘門、型別化角色解析器與
  InferenceProvenance 使用真實模型；未啟用時由本機機制目錄推理器負責（明示的備援）。
  「反方審查」退回「主要推理」時會明確標示「沒有模型路由獨立性」。
- 執行環境頁面以研究者看得懂的名稱顯示（主要推理、快速輔助、獨立批判、假說產生與比較、反方審查…），
  內部識別碼保留在提示與「技術細節」中。
- 命令列（`lab-brain research run`）永遠不呼叫語言模型；有 LLM 執行環境啟用時會拒絕執行，請改用工作區。

設計與驗證記錄：[`docs/implementation/web-workspace-v2.md`](docs/implementation/web-workspace-v2.md)。

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
