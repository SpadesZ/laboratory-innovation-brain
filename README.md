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

52 requirements ↔ 52 tests。兩條 spec 測試守住這個不變式：

| Test | 檢查 |
|---|---|
| `T-SPEC-001` | Requirement ID 唯一；每條 requirement 至少一個 test；沒有 test 指向未知 ID |
| `T-SPEC-002` | Registry 內部一致；每筆 entry 對應既有 Test ID 或帶明確 DEFERRED rationale |

**Registry 的完整性不由 CI 保證。** §23.5 把覆蓋責任拆成兩段：T-SPEC-002 只驗證登錄項彼此一致，
「正文每一條 hard MUST 都已登錄」是人工稽核閘門，產出 `docs/spec_coverage_audit/<milestone>.md`。
T-SPEC-002 通過**不得**被推論為 registry 完整。

遇到規格內部衝突時，依 AGT-015：**block 當前 slice、建立 spec issue**，不得選「看起來比較新」的那段繼續施工。
