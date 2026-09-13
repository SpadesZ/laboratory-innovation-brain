# SAI 3.3 — System Analysis with AI
## Laboratory Innovation Brain System Architecture

**版本**：3.3
**日期**：2026-09-11
**基準**：SAI 3.2 (2026-09-10) + FIX-1~8
**狀態**：Implementation-Ready Specification

> **SAI** = System Analysis with AI，是**規格文件名稱**。
> **Laboratory Innovation Brain** 是**目標系統名稱**。
> Silicon Photonics 是第一個 DomainPack，不是 core hard-code。

---

## 本版變更摘要（相對 v3.2）

| Fix | 內容 |
|---|---|
| FIX-1 | 統一 `TransitionPolicy.evaluate` 單一簽章；回傳改為結構化 `TransitionDecision` |
| FIX-2 | 新增 typed `Prediction` 與 side-effect-free `evaluate_hypothetical`，使 sufficiency 可確定性計算（VER-006） |
| FIX-3 | 新增 `Conflict` 型別，使 `blocking_conflict_policy` 可實作（EPI-006） |
| FIX-4 | 統一 DomainPack tool 命名類別（`run_*`/`extract_*`/`inspect_*`/`validate_*`）與單一 ID scheme `DOM-SP-TOOL-xxx` |
| FIX-5 | Normative Registry 完整性拆為「CI 可檢查」與「人工稽核」兩段 |
| FIX-6 | `independence_basis` 值域、`estimate_cost_contract`、`EvidenceField.review_id`、版本相對敘述 |
| FIX-7 | Lumerical seat 與 ground-truth benchmark 兩項外部依賴進 Risk Register |
| FIX-8 | 新增 Frontend Error & Recovery Contract：§17.22–17.24、§27、`UX-xxx` namespace、UX-001~007 |

**Requirement ↔ Test 不變式：59 ↔ 59。**

---

# 0. 規格治理 — 這份文件如何被使用

## 0.1 雙讀者原則

本規格同時服務兩類讀者：

- **人類**（PI、研究生、reviewer）：需要理解為什麼這樣設計、科學意義是什麼
- **Coding Agent**：需要可執行、可驗收、無歧義的契約

兩者衝突時，以**可驗收性**優先。凡是 Agent 無法據以寫出測試的描述，都不算完成規格。

Schema Version 必須可 migration。任何 schema 變更都要有版本、向前/向後策略與 migration 檔。

## 0.2 規範性語言

| 詞 | 意義 |
|---|---|
| **MUST / 必須** | 不可協商。違反即為 spec defect，Coding Agent 必須 block slice |
| **SHOULD / 應** | 預設遵守；偏離必須建立 ADR 說明理由 |
| **MAY / 可** | 實作者自由選擇 |
| **NOTE / 說明** | 敘述性，不具規範力 |

§6–§16 為 **normative architecture**。為維持人類可讀性，不要求每一句 MUST 都在正文尾端塞 ID；改用 **Normative Statement Registry**（§23.6）讓每條硬性規範可唯一映射到 Requirement ID、Test ID 或明確 DEFERRED rationale。

## 0.3 Requirement / Test / ADR 三件套

任何硬性規範必須同時存在三樣東西，缺一不可：

```
Requirement ID  ->  Normative statement (§25.3, §24.5)
Test ID         ->  Pass condition      (§26)
Registry entry  ->  §23.6 normative_statements.yaml
```

只有 Requirement 沒有 Test = 不會被實作。
只有 Test 沒有 Requirement = 測試指向未知規範。
兩者皆有但不在 Registry = 無法被 coverage lint 發現漏登。

## 0.4 變更控制

- 變更 **MUST** → 必須建立 ADR，並同步更新 Requirement 與 Test
- 跨越 core / domain 邊界的變更 → 必須建立 ADR
- 涉及科學語意或安全語意的 P0 契約 → 必須等待 Human approval，Agent 不得自行決定

## 0.5 本規格不負責的事

- 不指定具體 LLM 供應商或模型名稱（只定義 logical slots）
- 不指定 UI 框架
- 不承諾任何 benchmark 數字（數字由校準產生，見 LLM-002）
- 不替代實驗室既有的 ELN / LIMS，只定義整合邊界

## 0.6 Specification Closure Contract — 規格本身必須先通過自己的 CI

本規格**不設 Normative Override 條款**。

早期版本曾以「若後文與本節衝突，以本節為準」來處理殘留文字。該作法等於要求 Coding Agent 在讀取時自行解衝突——而 Agent 會傾向採信最像程式碼的區塊，那往往正是舊的。

因此本版採取的規則是：

```
消除衝突,不是要求 Coding Agent 自己判斷哪段比較新。

任何 normative schema、operator、Requirement ID、Test ID 與 Appendix 必須彼此一致。
若 T-SPEC-001 / T-SPEC-002 失敗,Agent MUST block 當前 slice,建立 spec issue,
不得選擇其中一個版本繼續施工(AGT-015)。
```

---

# 1. 為什麼需要 Laboratory Innovation Brain

實驗室真正的資產不是檔案，而是**知道什麼、為什麼知道、在什麼條件下知道、哪裡還不確定**。

目前這些資產分散在：學長姐的硬碟、口頭經驗、Slack 對話、沒人再打開的 simulation 專案、畢業後失聯的記憶。學生畢業 = 知識歸零。

Laboratory Innovation Brain 的目標不是「幫你寫論文」或「自動跑模擬」，而是：

> **把實驗室的科研信念狀態，變成可追溯、可反駁、可繼承的結構化記憶。**

## 1.1 三個它必須做到的事

1. **記得為什麼** — 不只存結論，存證據鏈與當時的條件
2. **知道自己不知道** — UNKNOWN 是合法狀態，不得由模型補值
3. **知道下一步最便宜的驗證是什麼** — 不預設一定要跑模擬

---

# 2. 定位 — 它不是什麼

| 它不是 | 因為 |
|---|---|
| 論文問答機器人 | RAG 只會回答「文件裡寫什麼」，不會維護實驗室相信什麼 |
| 自動 simulation 跑批工具 | 跑得多不等於知道得多；重點是選對下一個驗證 |
| LLM agent swarm | 多 agent 互相附和只會製造假共識 |
| 取代研究者判斷的系統 | 人類保留科學語意與 scope 的決策權（§23.4） |

---

# 3. 核心科學原則 P1–P28

| ID | 原則 |
|---|---|
| P1 | Evidence before belief — 沒有證據就沒有信念變更 |
| P2 | Append-only scientific record — 科研紀錄預設不覆寫 |
| P3 | **Inference is not Evidence** — LLM 推論永遠是 inference，不得升級為 observation |
| P4 | Condition-aware comparability — 條件不同的數據不得直接合併 |
| P5 | Falsifiability required — 假說必須帶 falsifier |
| P6 | Competing hypotheses — 任何時刻維持 ≥2 個競爭機制 |
| P7 | Provenance is mandatory — 每個 claim 可回溯到 artifact |
| P8 | Reproducible runs — run manifest 必須足以重跑 |
| P9 | Privacy by default — 敏感資料預設不外流 |
| P10 | No single scalar FoM — 不可只看單一指標判斷設計好壞 |
| P11 | Cheapest sufficient verification — 先做最便宜的足夠驗證 |
| P12 | Human owns scientific semantics — 科學語意由人決定 |
| P13 | Progressive evidence enrichment — 證據可分階段補強 |
| P14 | Extraction abstention — 抽不到就標 UNKNOWN，不猜 |
| P15 | Fidelity-aware authority — 低精度證據不得單獨推翻高精度結論 |
| P16 | Human approval for tacit knowledge — 經驗規則需人類核准才生效 |
| P17 | Domain-agnostic core — core 不得寫死任何領域 |
| P18 | Decision-relevant verification — 驗證必須能改變決策 |
| P19 | Typed tools only — 不使用 arbitrary script execution |
| P20 | Scale by evidence — 由實測負載決定架構升級，不預先過度工程化 |
| P21 | **Event-sourced belief** — 信念狀態由 append-only event 重建 |
| P22 | **Claim identity before corroboration** — 先解命題身分，再算佐證 |
| P23 | **Inference provenance everywhere** — 每個 LLM 產物都帶模型與 bundle 來源 |
| P24 | **Intent-aware retrieval** — 檢索策略隨研究意圖切換 |
| P25 | **Cost and waiting are first-class** — 等待與不可逆性是成本的一部分 |
| P26 | **Backend-agnostic metrics** — metric extractor 不綁特定後端 |
| P27 | **Evidence authority, not simulator ladder** — 權威是偏序，不是固定階梯 |
| P28 | **Default-deny sensitive ingestion** — 未分類資料預設最嚴格 |

---

# 4. 目標狀態 — 完成後實驗室會變成什麼樣

```
研究生跑完一組 CHARGE sweep
  -> Run manifest 自動保存(solver version / mesh / bias / script commit)
  -> Cj(V)、Rs(V) 由 backend-agnostic extractor 產生 Observation
  -> 系統比對既有 hypothesis predictions
  -> Rs 異常 -> Case-Based Retriever 找歷史相似 failure
  -> Critic 產生 contact / mesh / extraction 三個競爭原因
  -> Verification Planner 選最便宜的區辨測試
  -> 確認 root cause -> FailureAnalysis + Heuristic candidate
  -> 下一個遇到同樣症狀的人,系統先講這三個原因與各自的驗證方式
```

---

# 5. 核心物件總覽

## 5.1 科學狀態物件

| 物件 | 角色 |
|---|---|
| **Artifact** | 不可變原始/衍生研究資產，content-addressed |
| **SourceWork** | 同一件學術著作的身分（preprint / 正式版 / 鏡像 皆指向它） |
| **Claim** | 可被不同來源見證的科學命題身分 |
| **Observation** | 內部 backend 產生的客觀數值/事件，直接連 Run/Artifact |
| **Attestation** | 某來源在特定 locator/conditions 下對 Claim/Observation 的具名見證 |
| **RelationJudgment** | 帶 provenance 的關係判斷（SUPPORTS / CONTRADICTS / ...） |
| **Hypothesis** | 可證偽假說；狀態是投影，不是可寫欄位 |
| **Prediction** | 假說對某可觀測量的具名預測，含關係效果模板 |
| **BeliefRevisionEvent** | append-only 信念轉移紀錄 |
| **EpistemicStateProjection** | 由 event 重建的當前信念投影 |
| **Conflict** | 具型別的衝突紀錄，可阻擋狀態轉移 |
| **ResearchEpisode** | 一次完整研究演繹 |
| **VerificationPlan** | 排序後的驗證行動計畫 |
| **Decision** | 明確決策紀錄 |
| **FailureAnalysis** | 失敗根因分析 |
| **Heuristic** | 經人類核准的實驗室經驗規則 |

## 5.2 執行與治理物件

| 物件 | 角色 |
|---|---|
| **Actor / ProjectMembership** | 身分與授權 |
| **Job** | 長時工作，支援 suspend/resume/idempotent callback |
| **Run** | 一次 backend 執行，含 manifest 與 backend validity |
| **Capability** | 驗證後端的能力描述（planner 只讀這個） |
| **CostEntry / Budget** | 成本帳與預算閘 |
| **ExecutionSpan** | 執行可觀測性（trace） |
| **ReviewItem** | 人類審核佇列項目 |
| **IngestionItem / ErrorRecord** | 使用者層狀態與錯誤投影 |

## 5.3 Canonical Scientific State Path（SYS-001）

```
Artifact / SourceWork
  -> Claim / Observation
  -> Attestation
  -> RelationJudgment
  -> TransitionPolicy
  -> BeliefRevisionEvent
  -> EpistemicStateProjection
```

**任何繞過這條路徑直接改信念狀態的實作都必須被靜態測試拒絕。**

---

# 6. Knowledge & Evidence Architecture

## 6.1 Artifact Layer

所有進入系統的東西先成為 Artifact：論文 PDF、simulation project、script、輸出陣列、圖片、meeting transcript、外部 repo snapshot。

Artifact 是 **content-addressed**：`artifact_id` 由內容 hash 決定。改 1 byte 就是另一個 artifact。人類意義上的「版本」由 `lineage_id` / `lineage_revision` / `previous_artifact_id` 表達，與 content-addressing 不衝突。

## 6.2 Claim / Observation / Attestation 分離

本規格將「命題」與「證據」分離：

```
NOT:  Evidence = 論文裡提到的一個數字
YES:  Claim        = 科學命題身分(可被多個來源見證)
      Observation  = 內部 backend 產生的事實(直接連 Run/Artifact)
      Attestation  = 某來源對 Claim/Observation 的具名見證
```

**為什麼必須分開**：同一個 claim 被 5 篇論文引用，若直接產生 5 筆互不相關的 evidence，系統會把「1 次量測被轉引 4 次」誤算成「5 個獨立支持」。這會系統性污染每一次信念更新。

## 6.3 Evidence Field Status

每個重要條件/參數**獨立**持有 status，而不是整筆 evidence 只有一個 confidence：

```
EXPLICIT | DERIVED | INFERRED | UNKNOWN | NOT_REPORTED
| REFERENCED_EXTERNALLY | CONFLICTING
```

只有 `EXPLICIT` / `VERIFIED_DERIVED` 可直接作為 condition filtering 的高權重依據。
`INFERRED` 必須被標記為非原始 evidence。

## 6.4 Progressive Evidence Enrichment

```
Stage A  metadata 層(title/DOI/authors/venue)
Stage B  結構抽取(table/figure caption/equation)
Stage C  深度補強(正文 / SI / 引用來源)
Stage D  人工確認(升級為 human-verified)
```

Stage 之間必須可停留。未完成的 stage 以 `UNKNOWN` 呈現，**不得由模型補值**（P14 / EVI-002）。

## 6.5 外部來源類型

| 來源 | 取什麼 | 注意 |
|---|---|---|
| 論文 / preprint | claim + conditions + locator | 需 retraction 檢查 |
| Patent | prior art | 不等同 peer-reviewed evidence |
| GitHub | 技術實作 / prior art | 不得自動升級為科學證據（GH-003） |
| Web | 補充脈絡 | 最低 trust class |
| 內部 Run | Observation | 最高 directness |
| 歷史 Episode | 相似案例 | 注意歷史偏見 |
| Expert heuristic | 診斷捷徑 | 需人類核准（P16） |

## 6.6 儲存策略 — PostgreSQL First

v1 使用 **PostgreSQL + JSONB + pgvector** 作為單一真實來源。

> **重要修正**：不設固定節點數門檻決定何時換 graph DB。遷移由**實測 traversal workload** 觸發，而非預估規模。abstraction 只能降低替換成本，不能宣稱零成本。

上層 cognition / retrieval 只依賴 `GraphRepository` contract（§17.12）。

## 6.7 文件解析

Layout-aware parsing：claim 與其 supporting table / figure / caption 不應被切散。
Figure 與 eye diagram 等影像內容需要 VISION slot（§7.3），未啟用時相關欄位維持 `UNKNOWN`。

## 6.8 Condition-aware Retrieval

先以科學操作條件判斷 comparability，再做 semantic ranking。
波長、偏壓、溫度、幾何、doping、平台不同的資料**不得**被直接合併。

## 6.9 Case-Based Retrieval

歷史 `ResearchEpisode` 與 `FailureAnalysis` 是一等檢索目標。同類症狀再出現時，系統先提示過去的競爭原因與各自的驗證方式。

## 6.10 Failure Analysis

```
FailureAnalysis {
  failure_analysis_id, episode_id,
  symptom, expected_behavior, observed_behavior,
  candidate_causes[], confirmed_root_cause?,
  root_cause_evidence_ids[], failure_class,
  fix?, prevention_rule?, resolution_status
}
```

## 6.11 Heuristic Layer

Heuristic Miner 的輸出**不是**直接入庫的 active rule，而是 `CandidateHeuristic`，必須引用來源、保留原句 locator，並等待人類 approval（P16）。

## 6.12 Numerical Store

大型數值陣列存 parquet + raw passthrough；不在 v1 同時維護三套格式。

## 6.13 Embedding Layer

向量檢索**必須**依 `embedding_model` + version 過濾。混合不同 embedding space 的 cosine 距離是靜默垃圾（EVI-007）。

## 6.14 Ingestion 非侵入原則

研究員不應被迫填大量表單。系統以 watcher + 自動抽取為主，人類只補「決策理由」與「根因結論」。

## 6.15 Heuristic Miner

從 approved transcript / episode 中挖掘候選規則。只從授權來源產生，不得自行升級。

## 6.16 External Source & GitHub Contract

所有外部知識取得**必須**經 `ExternalSourceAdapter` / `SourceRouter`；provider-specific SDK 不得滲入 cognition / domain core。

```
SRC-001  provider-agnostic boundary
SRC-002  intent-aware SourcePolicy + high-stakes inverted retrieval
GH-001   public repo discovery + ref/commit-pinned fetch + normalized provenance
GH-002   private repo 需 explicit auth/allowlist/security policy;未授權必須 fail closed
GH-003   GitHub 技術/prior-art evidence 不得自動升級為 peer-reviewed scientific evidence
```

**Connector failure policy**：rate limit、authentication failure、repository removed、ref drift、network unavailable 都必須回傳 structured connector error；**不得由 LLM 猜測缺失內容**。若某 prior-art conclusion 依賴的 GitHub material 已消失，狀態改為 `SOURCE_UNAVAILABLE` 並保留既有 snapshot（若合法且先前已保存）。

## 6.17 Claim Identity & Evidence Independence

```
EvidenceIndependence {
  a_id, b_id,
  relation: INDEPENDENT | DERIVED_FROM | SAME_WORK | CITES | UNKNOWN,
  rationale_ref
}
```

**計數規則（EVI-004）**：

```
DEPENDENCE_UNKNOWN 對 independent-attestation count 的貢獻固定為 0。
它保留為 supporting context,但不足以滿足 min_independent_attestations。
若因此無法達到門檻,TransitionPolicy MUST 回傳 NEED_MORE_EVIDENCE 或
NEED_HUMAN_REVIEW,不得猜測為獨立。
```

**獨立性層級（FIX-6）**：

```
v3.3 只實作 WORK-level independence (SAME_WORK_AS / CITES / DERIVED_FROM)。

GROUP / SAMPLE / INSTRUMENT / METHOD 為 DEFERRED:
同一實驗室、同一批 wafer、同一台儀器造成的相關性尚未建模,
這是 corroboration 膨脹剩下的一半。

TransitionPolicy 若宣告 independence_basis 高於 WORK,
MUST 回傳 NEED_HUMAN_REVIEW 而非假裝已滿足。
```

## 6.18 Belief Replay & Contamination Rollback

信念轉移採 append-only `BeliefRevisionEvent`。`EpistemicStateProjection` 可由全量 replay 或 checkpoint + delta 重建。

**污染回滾流程**：

```
發現某 extractor_version 有系統性錯誤
  -> quarantine 該版本產生的所有 Attestation
  -> replay BeliefRevisionEvent,略過被隔離的 triggering attestation
  -> 得到可驗證的新 EpistemicStateProjection
  -> 不得靠手改 current status
```

任何 manual correction **也必須**形成 event，不可直接 UPDATE current belief row（EPI-003 / AGT-009）。

## 6.19 Versioned Condition Schema Registry

```
ConditionSchemaRegistration { domain, schema_id, version, json_schema_ref, comparator_version }
```

每筆 condition-aware record 必須帶 `conditions_schema_version`。資料庫寫入時驗證 schema；不符者拒絕或隔離（EVI-005）。

`ConditionMatch` 語意由 DomainPack 註冊的 comparator 提供，且受版本控制。

## 6.20 Embedding Version & Re-index Policy

```
- retrieval MUST 依 embedding_model + version 過濾,不得跨 space 比較
- 換 model 時採 dual-index:新舊並存,以 benchmark recall 驗證後才 cutover
- cutover 前後都必須可回答「這筆檢索用的是哪個 embedding version」
```

## 6.21 Retraction / Erratum / Source-Work Dedup Gate

外部 reported evidence 要支撐重大 belief revision 前，**應**通過：

```
1. source-work version 檢查(preprint vs 正式版)
2. retraction / erratum 檢查
3. source-work dedup(避免同一 work 重複計數)

檢查狀態 MUST 被記錄(EVI-008),即使檢查結果是 UNKNOWN。
```

`PriorArtSearchRecord`（§17.20）保存 novelty 判斷的搜尋覆蓋範圍。**沒有覆蓋率記錄的 novelty status 不可稽核。**

---

# 7. Cognitive / Multi-Agent Architecture

Laboratory Innovation Brain 的「多 Agent」是 **cognitive decomposition**，不是很多聊天機器人。

Core 固定 **6 個科研職責**；DomainPack 可動態註冊 **N 個 SpecialistRole**；Model Router 提供 **6 個 LLM logical slots**（PRIMARY / ADVERSARIAL / FAST / CODE / PRIVATE_LOCAL / VISION）+ **1 個 EMBEDDING slot**。

角色之間**只**透過有 schema 的物件溝通：`EvidenceBundle`、`Position`、`Hypothesis`、`CritiqueReport`、`VerificationPlan`、`RelationJudgment` 與 Shared Scientific State。

## 7.1 Core Cognitive Functions

| Function | 主要職責 | 能讀什麼 | 不能做什麼 |
|---|---|---|---|
| **Supervisor / PI** | goal decomposition、budget、priority、termination、human gates | project state、role outputs、verification cost/capabilities | 不能自行宣告物理真理或把未驗證 idea 升級成 verified |
| **Evidence Researcher** | 找內外部 evidence、condition match、provenance、conflict collection | papers、internal runs、episodes、approved heuristics、external metadata | 不能用自己生成文字補證據 |
| **Hypothesis Engine** | generate、structure、dedup、evolve competing hypotheses | evidence bundle、open questions、specialist positions | 不能把 hypothesis 寫回 evidence |
| **Adversarial Critic** | 攻擊 assumptions、confounders、causal gaps、counterexamples、falsifier | all admitted hypotheses + evidence summaries + specialist positions | 不負責 final truth；不能只靠語言說服力淘汰假說 |
| **Verification Planner** | 把爭議轉成可觀察 predictions；在 literature / analytical / historical / numerical / surrogate / simulation / measurement 中選最低成本充分驗證 | hypothesis predictions、available capabilities、cost、privacy、fidelity policy | 不能預設一定要 simulation；不能執行任意 script |
| **Novelty Auditor** | 外部 papers / patents / GitHub prior-art audit；區分 known / partially novel / novelty candidate | sanitized concept、public sources、approved metadata | 預設不看 private raw data；沒搜到不能宣告全球唯一 |
| **Domain Specialist(s)** *(by DomainPack)* | 依領域提供獨立機制判斷、conditions/validators、predictions | 只讀該 DomainPack 授權的 evidence、rules、tools、historical cases | 不是 core；不得直接改 core epistemic semantics 或 evaluator |

**Heuristic Miner** 屬於 knowledge-extraction service，不算核心科研角色。

## 7.2 Structured Scientific Debate Protocol

```
Default 3-stage protocol (stake-adaptive):
  Stage A - Independent positions from selected roles / specialists
  Stage B - Critic performs inverted retrieval + cross-examination
  Stage C - Surviving disagreement becomes explicit predictions + VerificationPlan

Escalate to deeper rounds only when:
  - decision may REJECT a hypothesis,
  - action is expensive/irreversible,
  - evidence bundles materially conflict, or
  - human requests deeper debate.
```

Structured Debate 的 anti-groupthink 來源**不是**「角色很多」，而是：獨立 initial position、Critic 自己重跑 inverted retrieval、不同 EvidenceBundle、external evidence adjudication。

系統 **MUST** 記錄 position diversity、bundle divergence、Critic 是否改變決策；簡單問題不得固定跑 8 rounds。

```
當 decision.stakes >= SourcePolicy.inverted_retrieval_threshold 時:
  Critic MUST 執行 inverted retrieval
  CritiqueReport.inverted_bundle_id 為條件式必填
  未完成該步驟時 decision 不得進入 BELIEF_REVISION
```

## 7.3 Model Routing — 6 個可拔 model slots + 1 embedding slot（不是 6 顆必備模型）

| Logical Slot (6 LLM + 1 non-LLM) | 主要用途 | 典型角色 / 工作 |
|---|---|---|
| `REASONING_PRIMARY` | 主要科研推理 | Hypothesis、Semiconductor、Optical、RF/System、Verification Planner |
| `REASONING_ADVERSARIAL` | 獨立反方與第二意見 | Adversarial Critic / high-stakes independent critique path；provider can differ but **evidence-path independence is primary** |
| `FAST_UTILITY` | 便宜快速的結構化工作 | query rewrite、分類、欄位抽取、routing、輕量 rerank |
| `CODE` | 程式與工具整合 | parser、typed-tool adapter、analysis code；受 contract / test 約束 |
| `PRIVATE_LOCAL` | 敏感/離線任務 | NDA、未公開 idea、air-gapped extraction / reasoning；可映射 local model |
| `VISION` | 多模態科學文件/圖表解析 | figure/table/SEM/eye/field plot；只在 multimodal ingestion 啟用時需要 |
| `EMBEDDING` (non-LLM) | retrieval / similarity / proximity | documents、evidence、case、hypothesis dedup / clustering |

## 7.4 Cognitive Role I/O Contract — 6 Core Roles + N Domain Specialists

| Role | Input | Output | 主要資料 |
|---|---|---|---|
| Supervisor / PI | Human goal + current episode state | ResearchContract、task order、budget/gates | project state、cost、role summaries |
| Evidence Researcher | Structured question + missing evidence fields | EvidenceBundle + conflicts + source locators | internal artifacts/runs、papers、episodes、approved web |
| Hypothesis Engine | EvidenceBundle + open unknowns | 2+ competing Hypothesis Certificates | normalized evidence、mechanism graph、prior hypotheses |
| Adversarial Critic | All positions + hypotheses + evidence map | CritiqueReport、falsifiers、missing controls | same shared state；read-only on evidence |
| Verification Planner | Surviving hypotheses + disagreements + capabilities/cost | ranked VerificationPlan(s) | capability registry、historical data、fidelity/privacy policies |
| Novelty Auditor | Sanitized surviving concept | Prior-art matrix + novelty status + PriorArtSearchRecord | external paper/patent/GitHub/web only as allowed |
| Domain Specialist(s) | Question + selected claims/hypotheses + domain evidence | independent Position + predictions/confounders | DomainPack-specific evidence/rules/tools；N roles dynamically registered |

## 7.5 Evidence Source Router — 資料選擇層怎麼選

Evidence Researcher 不把全部資料一次塞給 LLM。SourceRouter 先過 privacy/rights/ACL，再依 **research intent** 選 SourcePolicy，最後做 condition compatibility、source-work independence、authority/directness、semantic relevance、recency（**按領域規則**）與 retrieval cost。

| Research intent | SourcePolicy | 目的 / 防偏差 |
|---|---|---|
| `DIAGNOSIS` | Internal matched runs / measurements / failure episodes first | 快速找 root cause；仍需 contradiction check，避免只相信 lab history |
| `MECHANISM_DISCOVERY` | Internal evidence + peer-reviewed literature + contradictory evidence | 比較 competing mechanisms；要求至少一條外部反證搜尋 |
| `NOVELTY_AUDIT` | External literature + patents + GitHub/technical prior art | 保存 PriorArtSearchRecord；不得用 internal novelty 代替 global novelty |
| `CROSS_DOMAIN_INNOVATION` | Adjacent-domain sources with exploration quota | 避免歷史 bias；強制跨領域類比但 evidence type 分級 |
| `REPLICATION` | Original work + independent replications + condition match | 去除 preprint/journal/review 重複計數；優先可重現方法 |

```
Always: ACL/privacy -> condition/schema compatibility -> source-work dedup
        -> authority/directness -> relevance -> time/cost.
```

## 7.6 Model Independence & Inference Provenance

不同 provider **不是**科學獨立性的充分條件。

```
重大 REJECT / irreversible action 必須經 independent critique path:
  至少改變 retrieval bundle、reasoning policy 或 model route,
  並由 external evidence / verification adjudicate。

所有 LLM 產物保存 InferenceProvenance;
無 provenance 的舊推論不可作為新 belief transition 的依據。
```

---

# 8. Hypothesis & Epistemic Model

Laboratory Innovation Brain 必須把「idea」與「scientific hypothesis」分開。Idea 可以先自由生成；只有通過 **Hypothesis Admission Gate**，補齊 mechanism、prediction、falsifier、assumptions、confounders 與 minimum test，才可佔用昂貴 simulation budget。

## 8.1 Hypothesis Certificate

```
Hypothesis {
  hypothesis_id, statement, mechanism, assumptions[],
  prediction_ids[],                      # references Prediction (17.5.1), not free text
  falsifier, confounders[], minimal_test_ref?, parent_id?,
  status_projection, belief_level_projection,
  created_in_episode, inference_provenance_id
}

No evidence_for[] / evidence_against[] / triggering_evidence_ids[] arrays.
Support/contradiction is resolved only through RelationJudgment.
Status is rebuilt from BeliefRevisionEvent + TransitionPolicy.
predictions are typed objects, not prose; the planner cannot infer outcome effects
from free text.
```

Confidence 在 v1 **不使用** 0.58 這類未校準機率。建議先用 ordinal belief：`LOW / MEDIUM / HIGH` + support/contradiction counts + evidence quality dimensions。未來有足夠 benchmark 後，再導入 Bayesian posterior 或 calibrated score。

## 8.2 Hypothesis Lifecycle

```
DRAFT -> ADMITTED -> ACTIVE -> {SUPPORTED | CHALLENGED | CONTRADICTED | INCONCLUSIVE}
                         \-> EVOLVED / SUPERSEDED

No LLM may directly assign a scientific transition.
Transition = TransitionPolicy.evaluate(...) -> TransitionDecision   # canonical signature in 8.2.1
Every accepted transition emits BeliefRevisionEvent.
```

## 8.2.1 TransitionPolicy — belief 轉移不是 LLM 投票

TransitionPolicy 是版本化、可測試的 **deterministic-first policy**。LLM 可以產生 RelationJudgment 或解釋 rationale，但**不得**直接把 ACTIVE 改成 SUPPORTED/REJECTED。DomainPack 可擴充 authority/condition 規則；core 負責 event、policy version 與 projector。

```
TransitionPolicy {
  policy_id, version, domain?,
  from_state, candidate_to_state,
  required_relation_types[],
  required_authority_rule,
  required_condition_match[],
  min_independent_attestations?,
  independence_basis?,           # WORK | GROUP | SAMPLE | INSTRUMENT | METHOD
  blocking_conflict_policy,      # conflict_type[] ; see 17.19.3
  human_gate?,
  effective_from, supersedes?
}
```

### Canonical transition operator（規範性簽章）

```
# This signature is normative (EPI-005).
# No other name or arity may appear elsewhere in this specification.

TransitionPolicy.evaluate(
    hypothesis,
    admitted_relations,        # RelationJudgment[]
    authority_policy,          # DomainPack-registered AuthorityPolicy
    condition_matches,         # ConditionMatch[]
    independence_summary,      # resolved EvidenceIndependence rollup
    candidate_to_state
) -> TransitionDecision

TransitionDecision {
  outcome: ALLOW | DENY | NEED_MORE_EVIDENCE | NEED_HUMAN_REVIEW,
  reason_code,
  policy_id, policy_version,
  blocking_conflict_ids[],        # see 17.19.3 Conflict
  required_authority_gap?,
  independent_attestation_count,  # DEPENDENCE_UNKNOWN contributes 0
  review_item_spec?               # populated when outcome = NEED_HUMAN_REVIEW
}

Deterministic: identical inputs + identical policy_version MUST return
identical TransitionDecision.
```

### INCOMPARABLE 的處置（EPI-004）

```
If any required AuthorityPolicy.compare() result is INCOMPARABLE:
  -> outcome = NEED_HUMAN_REVIEW
  -> auto-create ReviewItem(subject_type=AUTHORITY_CONFLICT,
                            subject_id=hypothesis_id,
                            stakes=hypothesis.stakes)
  -> no BeliefRevisionEvent may promote/reject until the review resolves
```

---

# 9. Verification Planning — Least-Cost Sufficient Verification

Verification Planner 是 **domain-agnostic** 的。Literature、analytical、historical、numerical、surrogate、simulation、measurement 與 human review 都是可插拔的 Capability。

## 9.1 Sufficiency — 可計算定義

```
sufficient(action) =
  exists y in declared_outcome_space(action) such that
      plausible(y)
  and (
        TransitionPolicy.evaluate_hypothetical(state, relations_from(y)).outcome
          != TransitionPolicy.evaluate(state).outcome
     or y resolves at least one Conflict where blocking = true
      )

relations_from(y) =
  for each Prediction p bound to an ACTIVE hypothesis where p.observable_ref
  matches action.produces and y is comparable to p.expected_outcome:
      instantiate p.relation_effect_if_observed

If no ACTIVE hypothesis declares a Prediction over action.produces,
the action is NOT sufficient. Absence of a declared prediction is not
evidence of discriminative power.
```

### plausible(outcome) 的定義（VER-004）

```
plausible(y, action, domain_policy) is true iff ALL hold:
  1. y is a member of a declared, versioned OutcomeSpace for this action/hypothesis
  2. y is not excluded by an existing EXPLICIT-status condition or validity bound
  3. y passes the DomainPack validator (ValidationReport.status != FAIL)
  4. the producing Capability can actually yield y under current conditions

Planner MUST NOT invent outcomes. An outcome that is merely imaginable is not plausible.
```

### Disagreement metric

```
Disagreement metrics are DomainPack / BenchmarkPolicy contracts:
they MUST be deterministic, versioned and defined over the declared OutcomeSpace.
Core does not hard-code one universal distance.
```

## 9.2 Information Gain 的處理立場

v1 **不**使用未校準機率做 expected information gain。排序依據為：
1. 能否改變決策（sufficiency，二元）
2. 預測分歧程度（DomainPack 宣告的 disagreement metric）
3. CostVector 上的 Pareto 支配關係
4. 版本化 SelectionPolicy 的 lexicographic fallback

## 9.3 Verification Action Types

| Action type | 典型成本特徵 |
|---|---|
| existing evidence lookup | 近乎 0 |
| analytical / rule check | 低 |
| historical case comparison | 低 |
| numerical / surrogate | 中 |
| simulation | 中–高 |
| measurement | 高 |
| fabrication | 極高 + 高延遲 + 不可逆 |
| human expert review | 低金錢成本，**但人力有限**（見 §14.4.1） |

## 9.4 CostVector — 成本不是純量

```
CostVector {
  wall_clock_s,
  human_minutes,
  money_estimate,
  compute_units,
  license_seat_s,
  earliest_available_at,
  irreversible,            # bool
  dependency_risk
}
```

**不得**把全部成本壓縮成單一 `normalized_cost` 作為唯一決策依據（VER-003）。6 週 MPW shuttle 不是「高成本」，是「高延遲 + 不可逆 + 排程耦合」。

## 9.5 Capability Registry

Planner 只讀 Capability descriptor，不知道 backend 名稱：

```
estimate_cost(params) -> CostVector
```

沒有 Capability descriptor 的 backend **不可被規劃**（VER-002）。

## 9.6 Deterministic Selection Policy

Pareto filtering 之後，候選常常仍不唯一（7 維 CostVector 幾乎所有候選都非受支配）。因此：

```
SelectionPolicy {
  policy_id, version,
  pareto_dimensions[],
  lexicographic_fallback[],   # ordered dimension list, e.g.
                              # [irreversible_last, human_minutes, wall_clock_s, money]
  tie_break_rule,
  effective_from
}

After Pareto filtering, planner MUST apply a versioned deterministic SelectionPolicy.
Identical input + identical policy version MUST return an identical ranked plan (VER-005).
```

---

# 10. Tool & Simulation Architecture

## 10.1 Backend Types

```
existing evidence | analytical | historical | numerical | surrogate
| simulation | measurement | human review
```

Core 只知道 **VerificationAction types** 與 Capability descriptors；不知道任何 solver 名稱。

## 10.2 Typed Tools Only — 不使用 arbitrary eval_script

所有工具有固定 input/output schema、provenance 與 validator。**不提供** arbitrary script execution（P19）。

### 10.2.1 Tool Naming Classes（規範性）

```
All DomainPack tools MUST use one of four verb prefixes.
The prefix declares the contract, not merely the name.

  run_*       backend-bound; executes a solver/instrument; produces numerical artifacts
              + Observation; carries BackendValidity.
  extract_*   backend-agnostic; consumes typed arrays + conditions; produces metrics with
              normalization basis and method provenance. MUST accept both simulated and
              measured fixtures (DOM-SP-002).
  inspect_*   reads geometry/config/state without solving; produces Observation.
  validate_*  returns ValidationReport; MUST NOT mutate raw evidence (Appendix H).

Tool identity uses a single scheme: DOM-SP-TOOL-xxx.
The legacy SP-CH-xx / SP-MO-xx / SP-IC-xx scheme is retired.
```

### 10.2.2 Silicon Photonics Canonical Tool Set

| Canonical name | Class | ID | 首條 vertical |
|---|---|---|---|
| `run_charge_dc_sweep` | run | DOM-SP-TOOL-001 | ✅ |
| `run_charge_ac_sweep` | run | DOM-SP-TOOL-002 | ✅ |
| `run_mesh_sensitivity` | run | DOM-SP-TOOL-003 | ✅ |
| `extract_cj_rs` | extract | DOM-SP-TOOL-004 | ✅ |
| `inspect_contact_connectivity` | inspect | DOM-SP-TOOL-005 | ✅ |
| `validate_expected_trends` | validate | DOM-SP-TOOL-006 | ✅ |
| `run_mode_solve` | run | DOM-SP-TOOL-007 | M6 |
| `extract_eo_delta` | extract | DOM-SP-TOOL-008 | M6 |
| `run_ring_spectrum` | run | DOM-SP-TOOL-009 | M6 |
| `run_nrz_eye_workflow` | run | DOM-SP-TOOL-010 | M6 |
| `run_thermal_lock_workflow` | run | DOM-SP-TOOL-011 | M6 |

```
`extract_cj_rs` produces Cj_per_length and Rs_per_length in one contract, with shared
units / normalization basis / bias / frequency conditions / extraction method. Splitting it
would allow simulated and measured paths to diverge in normalization (DOM-SP-002).

`run_nrz_eye_workflow` and `run_thermal_lock_workflow` are workflows, not primitive tools:
drive states, receiver settings and DSP assumptions MUST be bound into the Run manifest
as conditions, or cross-run BER comparison is invalid.
```

## 10.3 Run Manifest

每次 backend 執行必須產生可重播的 manifest（§17.4）。缺少任一必要欄位即拒絕升級為正式 evidence（SIM-001）。

## 10.4 No Single Scalar FoM

不可只看單一 scalar FoM 判斷設計好壞。多目標 trade-off 必須被保留與呈現（P10）。

## 10.5 EvidenceAuthority — 不是固定 simulator ladder

Core 只有 `EvidenceAuthority` 抽象；「measurement 永遠最高」**不是** core 假設。權威是 `(method, calibration, validated_range fit)` 的函數。

### 10.5.1 AuthorityPolicy Comparator

```
AuthorityPolicy.compare(a, b) -> AuthorityComparison

AuthorityComparison: STRONGER | WEAKER | EQUIVALENT | INCOMPARABLE

Authority is a PARTIAL ORDER, not a total order.
INCOMPARABLE is a legitimate result and MUST NOT be silently coerced into an ordering.
AuthorityPolicy.meets(required_rule, candidate) -> bool
```

DomainPack **MUST** expose `compare`（EPI-004）。

## 10.6 Sim-to-Real Conflict

模擬與量測不一致時，**不得**以「measurement 永遠真」抹平。必須保留 `SIM_TO_REAL_CONFLICT`，並依 AuthorityPolicy / TransitionPolicy 決定是否 escalate。

## 10.7 Job Queue / License Seat / Retry

長時 tool 與外部動作必須 Job 化（OPS-001）：

```
- idempotency_key 防止重複 callback 產生第二個 run
- retry_policy / timeout_policy / max_attempts
- resource_requirements(含 license seat)
- WAITING_RESOURCE 狀態用於 license/seat 競用
- structured_error 供 ErrorRecord 投影(§17.23)
```

---

# 11. DomainPack — 領域知識掛載

第一個 DomainPack 是 Silicon Photonics。它提供 condition schema、EvidenceAuthority policy、backend validity、physical validators、metric extractors、specialist roles、Lumerical bindings 與 benchmarks。

Core **MUST NOT** import 任何 domain 模組（AGT-011）。詳見 §24。

---

# 12. Orchestration & Execution Model

## 12.1 Episode State Machine

```
CREATED
  -> EVIDENCE_GATHERING
  -> HYPOTHESIS_FORMATION
  -> DEBATE
  -> VERIFICATION_PLANNING
  -> ACTION_DISPATCH
       -> AWAITING_JOB              # long-running tool / simulation / measurement
       -> AWAITING_HUMAN            # ReviewItem pending
       -> AWAITING_EXTERNAL_SOURCE  # connector unavailable / rate limited
  -> EVIDENCE_ADMISSION
  -> BELIEF_REVISION
  -> [NOVELTY_AUDIT]
  -> OUTPUT_CANDIDATE
  -> CLOSED
```

`AWAITING_*` 狀態使 episode 可 suspend/resume，不會因為一個 6 小時 FDTD 或一個 6 週 fab run 而永久阻塞。

## 12.2 Termination

終止條件包含：evidence saturation、budget exhausted、human stop、所有 ACTIVE hypothesis 皆達終態、無 sufficient action 可執行。

## 12.3 Unit of Work

artifact store 與 PostgreSQL 的跨界寫入必須在同一 unit of work 內補償，避免 orphan artifact 或 dangling ref。

## 12.4 Idempotency

所有外部 callback 與 retry 必須 idempotent（OPS-001）。

## 12.5 Trace

`trace_id` 貫穿 episode → retrieval → LLM call → job → run → artifact。Critique 與所有 LLM 產物保存 provenance（OPS-003）。

---

# 13. Long-term Learning

> **NOTE（敘述性章節）**

Laboratory Innovation Brain 的「學習」不應一開始就等於 fine-tune。最先產生價值的是**可檢索的高品質 research episodes 與 failure cases**。Weights 應學 procedural / research policy；快速更新的 papers、PDK、measurement 仍留在外部 memory。

## 13.1 Learning Ladder

| 階段 | 方法 | 學到什麼 | 風險 |
|---|---|---|---|
| L0 | RAG + structured evidence | 知道最新/內部 facts | retrieval quality |
| L1 | Case-based reasoning | 遇到新 anomaly 能找相似 episode / failure | case representation quality |
| L2 | Hypothesis pattern mining | 常見 mechanism / confounder / test template | 可能強化歷史偏見 |
| L3 | Trajectory distillation / SFT | Evidence→Hypothesis→Experiment→Revision 的 research policy | data leakage / teacher bias |
| L4 | Preference learning | 偏好較可證偽、較省成本、較物理合理的 proposal | preference target 設錯 |
| L5 | RL / offline RL from evaluators | 在 bounded design/search tasks 學 action policy | reward hacking / simulator exploitation |
| L6 | Continual domain adaptation | domain terminology / procedural competence | catastrophic forgetting / data governance |

**L3 以上為 DEFERRED M8。** 沒有 50 個真實 episode 之前，trajectory dataset 沒有母體。

## 13.2 三種 Memory vs Weights

| 類型 | 內容 | 是否進 weights |
|---|---|---|
| Semantic / explicit | papers、PDK、最新數據 | 通常不；RAG / DB |
| Episodic | 我們試過什麼、結果、失敗 | 先 case memory；可蒸餾成 trajectories |
| Procedural / policy | 如何診斷、如何設 experiment、如何選 fidelity | 最值得後期 SFT / preference / RL |

## 13.3 不建議即時 Online Gradient Update

一次 simulation 的結果可能是 solver failure、bad mesh、錯誤 extraction 或真正 scientific negative result。若立即更新 weights，很容易把 artifact 學成物理定律。建議：每輪只更新 structured memory；訓練採批次、審核、版本化、可回滾。

---

# 14. Security, Privacy & Governance

## 14.1 Sensitivity Labels

| 標籤 | 例子 | 外部使用 |
|---|---|---|
| `RESTRICTED_NDA` | foundry PDK、NDA docs、private process rules | 禁止外部 API / cloud model |
| `CONFIDENTIAL_LAB` | unpublished topology、measurement、patentable idea | 預設 local；需 explicit project policy |
| `INTERNAL` | meeting、thesis draft、internal report | 可依 policy 使用內部/approved cloud processing |
| `PUBLIC` | published paper、public patent、open-source repo | 可外部搜尋與雲端模型 |

## 14.2 Modes

| Mode | 資料來源 | 外部連線 | 用途 |
|---|---|---|---|
| Private Mode | local artifacts / local model / local tools | No egress | NDA / unpublished idea / sensitive analysis |
| Research Mode | local evidence + approved external literature | sanitized query / approved model | 一般研究與文獻補充 |
| Novelty Audit | sanitized hypothesis summary + public prior-art search | papers / patents / GitHub / web | 檢查 open-world novelty；與內部 reasoning 分離 |

## 14.3 Governance Gates

- **外部查詢 gate**：private identifiers / exact confidential geometry 不得送出
- **昂貴計算 gate**：超出 session solver budget 需 supervisor/human approval
- **Fabrication gate**：版圖/製程送件必須由 human sign-off
- **Memory admission gate**：任何 inferred claim 標為 inferred；measurement/simulation 需 artifact reference
- **Deletion/governance**：科研資料預設 append-only / supersede；仍保留依法律、NDA、個資治理真正刪除的能力

## 14.4 Actor / ACL / Review Queue — 沒有「誰」就沒有真 governance

最小 Actor 模型包含 human、service account、agent role；ACL 至少支援 project membership、sensitivity clearance、approval authority。所有 external egress、private repo access、human approval 與 destructive governance action 都要記 `actor_id`。

Human ReviewQueue 必須有 stakes、created_at、SLA/expiry policy 與 queue capacity，避免所有 uncertain item 永久卡在 PENDING。

### 14.4.1 ReviewQueue 必須接回 Verification Planner

Human review 是一個 **Capability**，不是無限免費資源。

```
HumanReviewCapability.availability <- ReviewQueue capacity + actor schedule
```

ReviewQueue 的 queue depth、reviewer availability、SLA 與 expiry 會更新 human-review Capability 的 `availability` / `earliest_available_at` / `estimated human_minutes`；Planner 因此會把教授/研究員的注意力當成真正成本（OPS-002）。

## 14.5 Secret / License Ingestion Guard

Watcher 在 immutable ingest **前**先做 secret scanning；疑似 credential 不得直接永久封存，需 quarantine/redaction policy（SEC-003）。

External code 保存 `license_class = PERMISSIVE | COPYLEFT | PROPRIETARY | UNKNOWN`；`UNKNOWN`/`COPYLEFT` 原始碼不得默認進入 code-generation context，除非 project policy 明確允許（SEC-004）。

---

# 15. Evaluation & Benchmark Suite

## 15.1 Benchmark Classes

| Benchmark | 任務 | Ground truth / 評估 |
|---|---|---|
| Anomaly Diagnosis | 由異常 observation 找 root cause + minimal verification | 已知故障注入 / 歷史真實 case |
| Mechanism Discrimination | 多 competing mechanisms，選下一個 test | synthetic/analytical simulator + known causal model |
| Hypothesis Quality | 從 evidence 提出可證偽 hypothesis | expert rubric + prediction/falsifier completeness + evidence grounding |
| Experiment Efficiency | 在有限 solver budget 下得到正確 conclusion | number of calls / cost / regret / information gained |
| Design Discovery | 找 Pareto-improved design 並說明 mechanism | baseline optimizer comparison + robustness |
| Cross-paper Synthesis | 跨 subfield evidence 形成 non-obvious connection | held-out known discovery / expert review |
| Novelty Audit | 判斷 internal idea 是否有 prior art | date-cutoff literature / patent corpus |
| Sim-to-Real | 用 measurement 修正 simulator-based belief | held-out fabrication/measurement result |
| Longitudinal Learning | 第 N 次遇到相似問題是否更快 | episode history ablation / time-split benchmark |

**M0–M4 只需前三類 + Experiment Efficiency。** 其餘 DEFERRED。

## 15.2 Core Metrics

| 面向 | Metric examples |
|---|---|
| Validity | physics constraint violations、root-cause accuracy、prediction calibration |
| Evidence grounding | citation/locator correctness、condition match、**unsupported claim rate** |
| Falsifiability | 有明確 falsifier 的 hypothesis 比例、prediction executability |
| Efficiency | solver calls、wall time、cost-to-correct-conclusion、invalid run rate |
| Innovation | prior-art distance、non-obvious cross-domain connection、expert novelty rating |
| Mechanistic insight | 能否提出 transferable mechanism，不只 design-specific correlation |
| Robustness | process corners / hidden conditions / independent rerun performance |
| Memory value | similar-case retrieval hit rate、repeated-failure reduction |
| Human usefulness | PI/student acceptance、time saved、decision quality、explanation usefulness |

## 15.3 Required Ablations

```
A. Strong single LLM
B. + RAG
C. + Structured Evidence
D. + Hypothesis Certificate / Critic
E. + Multi-specialist reasoning
F. + Active Experiment Selection
G. + Episodic / Failure Memory
H. Full Laboratory Innovation Brain
```

這樣可以回答最重要的問題：「到底是多 call 幾次模型比較強，還是哪個 architecture mechanism 真正有用？」

## 15.4 Structured Debate / Retrieval Independence Metrics

Structured Debate 是否減少 groupthink **必須可證偽**。最低指標：

```
- Stage A position pairwise semantic diversity
- Critic evidence-bundle divergence
- Critic 改變最終 hypothesis set 的比例
- surviving-hypothesis diversity
- additional evidence cost
```

若增加多 Agent 只增加 token 而不改善這些指標，應縮減角色/round。

**門檻由校準產生（LLM-002）**：hard gates 必須引用版本化的 `BenchmarkPolicy`，且校準證據可追溯。**校準前不得任意 hard-code 門檻數字。**

---

# 16. Roadmap

| Narrative Stage | 對應 Milestone | 說明（非獨立 gate） |
|---|---|---|
| Foundation | M0a + M0b | 資料 identity/schema/CI 與 actor/budget/event/trace 地基；正式 Exit Gate 只看 §26.1 |
| Research Memory | M1 | Ingestion、condition/source policy、provenance、async job、**IngestionItem/ErrorRecord 契約** |
| Silicon Photonics Tools | M2 | DomainPack、Capability、run/extract、backend validity |
| Hypothesis Brain | M3 | 6 core roles + specialists、debate、inverted retrieval |
| First Vertical | M4 | VS-SP-001 end-to-end |
| External Evidence Expansion | DEFERRED M5 | GitHub/Literature/Patent/Web 等 connector 擴張 |
| Multi-physics Ring | DEFERRED M6 | MODE/INTERCONNECT + ring mechanism benchmark |
| Operational Lab Brain | DEFERRED M7 | approved transcript miner、ELN/Git watchers、approvals、**Web Knowledge Inbox / System Health** |
| Learning / Second Domain | DEFERRED M8 | case-based retrieval、trajectory export、second DomainPack |

## 16.1 可衍生研究題目（副產品，不限制 Laboratory Innovation Brain）

- Evidence-grounded hypothesis competition for silicon photonics
- Active discriminative multiphysics verification action selection
- Condition-aware scientific RAG / evidence normalization for photonic devices
- Failure-memory / case-based diagnosis of photonic simulations
- Simulator-grounded belief revision vs LLM self-critique
- Longitudinal learning of a laboratory research agent from experiment trajectories
- Sim-to-real scientific belief update for photonic device modeling

---

# 17. Implementation Contracts & Schemas — 核心資料結構

本章提供可直接採用 Pydantic / SQLAlchemy / event-store pattern 實作的概念 schema。

## 17.1 Artifact Schema

```
Artifact {
  artifact_id, content_hash, media_type, uri,
  lineage_id?, lineage_revision?, previous_artifact_id?,
  source_origin, sensitivity_label, project_id,
  created_at, captured_at, author_or_device?, actor_id?,
  parser_version?, derived_from_artifact_ids[],
  rights_metadata?, secret_scan_status, metadata{}
}

artifact_id is content-addressed identity.
Changing 1 byte creates a new artifact_id/hash.
lineage_id + lineage_revision express human/version lineage when needed.
```

## 17.2 Claim / Observation / Attestation Schema

```
Claim {
  claim_id, normalized_proposition, domain?, scope{},
  identity_status, created_at
}

Observation {
  observation_id, run_id?/artifact_id, metric_or_event, value_ref?,
  conditions{}, conditions_schema_version, method_ref, created_at
}

Attestation {
  attestation_id, claim_id?/observation_id?, epistemic_type,
  source_artifact_id?/source_work_id?/run_id?, locator,
  conditions{}, conditions_schema_version, field_states{},
  units?, uncertainty?, method{}, extraction_status, verification_status,
  authority_class?, created_at, extractor_version, extraction_provenance
}

No support_targets[] / contradict_targets[] here. Those are RelationJudgments.
```

### 17.2.1 Observation / Attestation Creation Rule

Internal backend outputs **first create Observation** linked directly to Run/Artifact；它不需要再建立一筆「自我 Attestation」才能存在。

Attestation 主要表示**外部/報告型來源**對 Claim 或 Observation 的具名見證。若 internal result 被寫入 paper/report，再建立 SourceWork/Attestation 表示「該文件如何報告它」，避免把 observation 與報告它的文件混成同一物件。

## 17.3 Research Episode Schema

```
ResearchEpisode {
  episode_id, project_id, goal, research_contract_id, trace_id,
  parent_episode_id?, state, start_time, end_time?,
  hypothesis_ids[], verification_plan_ids[], job_ids[], run_ids[],
  decision_ids[], outcome_status, failure_analysis_id?,
  human_annotations[], cost_ledger_id?
}
```

## 17.4 Run Manifest Schema

```
Run {
  run_id, job_id, capability_id, backend_id, domain?, trace_id,
  input_artifacts[], input_parameters{}, conditions{}, conditions_schema_version,
  environment{}, code_provenance, backend_validity{},
  status, warnings[], output_artifacts[], numerical_array_refs[],
  start_time, end_time, reproducibility_manifest_hash
}

Core MUST NOT hard-code solver_settings / mesh_convergence / calibration fields.
Domain/backend validity schema owns those semantics.
```

## 17.5 Hypothesis Schema

```
Hypothesis {
  hypothesis_id, statement, mechanism, assumptions[],
  prediction_ids[],
  falsifier, confounders[], minimal_test_ref?, parent_id?,
  status_projection, belief_level_projection,
  created_in_episode, inference_provenance_id
}

No evidence_for[] / evidence_against[] / triggering_evidence_ids[] arrays.
Support/contradiction is resolved only through RelationJudgment.
Status is rebuilt from BeliefRevisionEvent + TransitionPolicy.
```

### 17.5.1 Prediction & Hypothetical Evaluation Contract

Prediction 把「假說預測什麼」變成機器可解的物件。沒有它，Verification Planner 只能讓 LLM 猜測某個 outcome 是否會改變信念狀態，等於繞過 TransitionPolicy。

```
Prediction {
  prediction_id, hypothesis_id,
  observable_ref,                     # what is measured or computed
  outcome_space_id, outcome_space_version,
  expected_outcome,                   # MUST be a member of the declared OutcomeSpace
  direction?,                         # ordinal direction when the space is ordered
  conditions{}, conditions_schema_version,
  relation_effect_if_observed[],      # RelationJudgmentTemplate[]
  inference_provenance_id
}

RelationJudgmentTemplate {
  relation_type,                      # SUPPORTS | CONTRADICTS | TESTS | PREDICTS
  to_entity_id,                       # hypothesis_id
  implied_authority_class,            # authority the producing Capability would yield
  implied_condition_match             # expected ConditionMatch state
}

TransitionPolicy.evaluate_hypothetical(
    hypothesis,
    admitted_relations,
    hypothetical_relations,           # instantiated from RelationJudgmentTemplate
    authority_policy, condition_matches, independence_summary,
    candidate_to_state
) -> TransitionDecision

Rules:
- evaluate_hypothetical MUST be side-effect free: it MUST NOT persist RelationJudgment,
  MUST NOT emit BeliefRevisionEvent, and MUST NOT mutate any projection.
- hypothetical_relations MUST be instantiated from declared Predictions, never invented
  by the planner or by an LLM at planning time.
- A Prediction whose expected_outcome is not a member of its declared OutcomeSpace
  version MUST be rejected at admission.
```

## 17.6 Failure Analysis Schema

```
FailureAnalysis {
  failure_analysis_id, episode_id,
  symptom, expected_behavior, observed_behavior,
  candidate_causes[], confirmed_root_cause?,
  root_cause_evidence_ids[], failure_class,
  fix?, prevention_rule?, resolution_status
}
```

## 17.7 Expert Heuristic Schema

```
Heuristic {
  heuristic_id, trigger_pattern, context_constraints{},
  suggested_checks[], rationale, source_person_or_episode,
  source_artifact_ids[], derived_from_failures[], validated_on_episodes[],
  status, approval_status, approved_by_actor_id?, approved_at?,
  last_reviewed_at
}
```

## 17.8 Graph Edge Schema

```
RelationJudgment {
  relation_id, from_entity_id, to_entity_id, relation_type,
  attributes{}, supporting_attestation_ids[],
  condition_match_ref?, inference_provenance_id?,
  actor_id?, valid_from, valid_to?, created_at
}

Core relations: SUPPORTS, CONTRADICTS, TESTS, PREDICTS,
PRODUCES, DERIVED_FROM, INSTANTIATES, SUPERSEDES, SAME_WORK_AS,
CITES, SUGGESTS_CHECK.

Relation is the single source of truth for support/contradict semantics.
```

## 17.9 Evidence Field Status Contract

每個重要條件/參數可獨立持有 field status，而不是整個 Evidence 只有一個 confidence。推薦枚舉：`EXPLICIT`、`DERIVED`、`INFERRED`、`UNKNOWN`、`NOT_REPORTED`、`REFERENCED_EXTERNALLY`、`CONFLICTING`。只有 `EXPLICIT` / `VERIFIED_DERIVED` 可直接作 condition filtering 的高權重依據；`INFERRED` 必須被標記為非原始 evidence。

```
EvidenceField { name, value?, unit?, status, locator?, derivation?, source_refs[], review_id? }

review_id references ReviewItem (17.19.1). A field-level review is a queued item with
stakes and SLA, not a free-floating status string.
```

## 17.10 EvidenceAuthority / BackendValidity Contract

重大 belief revision 所用 evidence 必須帶 EvidenceAuthority + BackendValidity；simulator-specific validity 由 DomainPack/backend schema 提供。

```
Silicon Photonics SimulatorValidityV1 is a DomainPack-specific BackendValidity schema;
core has no standalone SimulatorValidity table.
```

## 17.11 Candidate Heuristic Certificate

```
CandidateHeuristic {
  candidate_id, trigger_pattern, suggested_checks[], rationale,
  source_artifact_ids[], source_locators[], source_episode_ids[],
  miner_model_version, status=PENDING_REVIEW,
  proposed_scope{}, conflicts_with_existing_rules[]
}
```

## 17.12 GraphRepository Interface Contract

上層 cognition/retrieval 只依賴 GraphRepository contract；v1 backend 為 PostgreSQL。任何未來 graph backend 必須先通過 relation semantics、provenance trace、transaction consistency 與 regression tests，再允許切換。

```
GraphRepository {
  neighbors(entity_id, relation_types?, as_of?, limit, cursor?)
  find_paths(start, goal?, relation_types?, max_depth, as_of?, limit)
  trace_provenance(entity_id, as_of?, limit)
  find_support_chain(target_id, as_of?, limit)
  find_contradictions(target_id, as_of?, limit)
  find_related_failures(query, limit)
  upsert_relation(...)
  invalidate_relation(relation_id, reason, actor_id)
  batch_upsert(...)
}

All traversal APIs MUST be bounded; as_of semantics are required for historical replay.
```

## 17.13 BeliefRevisionEvent & EpistemicState Projection

Belief revision 採 append-only event；EpistemicState projector 可由全量 event replay 或 checkpoint + delta 重建。任何 manual correction 也必須形成 event，不可直接 UPDATE current belief row。

```
BeliefRevisionEvent {
  event_id, target_type, target_id,
  from_state?, to_state,
  triggering_attestation_ids[], triggering_relation_ids[],
  policy_version, actor_id?, inference_provenance_id?,
  rationale_artifact_or_record_ref?, occurred_at, trace_id
}

EpistemicStateProjection {
  target_id, current_state, belief_level?, unresolved_conflicts[],
  last_event_id, projection_version, projected_at
}

unresolved_conflicts[] holds conflict_id references (17.19.3),
not inline conflict payloads.
```

## 17.14 InferenceProvenance Contract

所有 LLM 生成/判斷物件必填。evidence bundle hash 讓同一 prompt/model 但不同 retrieval context 可區分。

```
InferenceProvenance {
  inference_id, role, logical_slot,
  provider?, model_id, model_version,
  prompt_id, prompt_version,
  evidence_bundle_hash, source_policy_version?,
  parameters{temperature?, seed?, reasoning_mode?},
  created_at, trace_id
}
```

### 17.14.1 EvidenceBundle / Debate Objects / VerificationPlan Contracts

EvidenceBundle 是 retrieval 的可重現封裝，也是所有 LLM 科研推理 provenance 的輸入 identity。Canonical hash 使用 deterministic serialization：固定 schema version、排序後 attestation IDs、query/policy/condition filters 與 source snapshot refs；不得 hash 任意 JSON 字串順序。

```
EvidenceBundle {
  bundle_id, schema_version, research_intent,
  query_text, query_hash, source_policy_id, source_policy_version,
  condition_filter{}, condition_schema_versions{},
  ordered_attestation_ids[], source_snapshot_refs[],
  retrieval_trace_id, created_at, canonical_hash
}

canonical_hash(bundle) = SHA256(JCS/RFC8785 canonical JSON of hash_fields)

Position {
  position_id, role_id, episode_id, hypothesis_refs[],
  mechanism_view, supporting_relation_ids[], uncertainties[],
  proposed_predictions[], confounders[], bundle_id, inference_provenance_id
}

proposed_predictions[] are debate-stage proposals, NOT admitted Predictions.
They MUST be materialized as typed Prediction objects (17.5.1) bound to a declared
OutcomeSpace version before they can participate in sufficiency computation (VER-006).
A Position alone never makes an action sufficient.

CritiqueReport {
  critique_id, target_ids[], objections[], alternative_mechanisms[],
  falsifier_challenges[], blocking_conflicts[],
  primary_bundle_id, inverted_bundle_id,
  inference_provenance_id, created_at
}

VerificationPlan {
  plan_id, episode_id, candidate_action_ids[], ranked_action_ids[],
  sufficiency_results{}, pareto_front_ids[],
  selection_policy_id, selection_policy_version,
  chosen_action_id?, rationale_ref, created_at
}

ResearchContract {
  contract_id, project_id, question, intent, success_criteria[],
  constraints{}, privacy_mode, budget_id?, stop_conditions[], actor_id
}

Decision {
  decision_id, episode_id, decision_type, subject_id,
  result, policy_refs[], triggering_event_ids[], actor_id?, created_at
}
```

## 17.15 Actor / ACL Contract

```
Actor { actor_id, actor_type:HUMAN|SERVICE|AGENT_ROLE, display_name?, active }
ProjectMembership { actor_id, project_id, role, sensitivity_clearance[], approval_scopes[] }

Default rule: new internal artifact sensitivity is fail-closed;
explicit authorized action is required to lower classification.
```

## 17.16 Job / Suspend-Resume Contract

```
Job {
  job_id, episode_id, capability_id, trace_id, idempotency_key,
  state:QUEUED|RUNNING|WAITING_RESOURCE|SUCCEEDED|FAILED|CANCELLED,
  attempt_count, max_attempts, submitted_at, started_at?, finished_at?,
  retry_policy{}, timeout_policy{}, resource_requirements{},
  result_run_id?, structured_error?
}
```

## 17.17 CostLedger & Budget Gate

```
CostEntry {
  cost_entry_id, episode_id, actor_or_slot, action_ref,
  tokens_in?, tokens_out?, wall_clock_s?, human_minutes?,
  money_estimate?, compute_units?, license_seat_s?,
  earliest_available_at?, irreversible?, recorded_at
}

Before each LLM/tool call, BudgetGate MUST check project/episode caps.
Exceed -> refuse/escalate; never silently continue.
```

## 17.18 Capability Descriptor

```
Capability {
  capability_id, domain?, action_type, backend_id,
  requires[], produces[], authority_class, availability,
  conditions_schema_version?, privacy_constraints[], license_constraints[],
  irreversible, earliest_available_at?,
  estimate_cost_contract,        # reference to the implementation of
                                 # estimate_cost(params) -> CostVector  (see 9.5)
  version
}
```

## 17.19 Condition Schema / ConditionMatch

```
ConditionSchemaRegistration { domain, schema_id, version, json_schema_ref, comparator_version }

ConditionMatch {
  state:EXACT|COMPATIBLE|PARTIAL|INCOMPATIBLE|UNKNOWN,
  matched_fields[], mismatches[], unknowns[],
  tolerance_policy_version, rationale_ref?
}
```

### 17.19.1 Budget / ReviewItem / Observability Contract

BudgetGate 需要明確 scope 與可調整權限；ReviewQueue/observability 也必須是可測試 contract，而不是只有 prose。

```
Budget {
  budget_id, project_id, episode_id?,
  hard_caps{}, soft_caps{}, currency?,
  effective_from, expires_at?, approved_by_actor_id, version
}

ReviewItem {
  review_id, project_id, episode_id, trace_id,
  subject_type, subject_id, stakes, reason,
  required_authority?, required_role?,
  created_at, due_at?, expires_at?,
  status: QUEUED|ASSIGNED|APPROVED|CORRECTED|REJECTED|EXPIRED,
  assigned_actor_id?, decision_ref?, estimated_human_minutes
}

ExecutionSpan {
  span_id, trace_id, parent_span_id?, span_type,
  episode_id?, actor_id?, model_call_id?/job_id?/retrieval_id?,
  start_time, end_time?, status, cost_entry_ids[], metadata{}
}
```

### 17.19.2 BenchmarkPolicy / OutcomeSpace / ValidationReport

```
BenchmarkPolicy {
  policy_id, domain, benchmark_set_id,
  metric_key, threshold, direction?,
  calibrated_at, sample_size,
  calibration_artifact_refs[], version, active
}

OutcomeSpace {
  outcome_space_id, domain, action_type, hypothesis_type?,
  schema_version, outcomes[], order_or_metric_ref?,
  explicit_exclusions[], validity_bounds{}, version
}

ValidationReport {
  report_id, subject_type, subject_id,
  validator_id, validator_version,
  status:PASS|WARN|FAIL|UNKNOWN,
  findings[], failed_rules[], provenance_refs[], created_at
}

DisagreementMetric {
  metric_id, outcome_space_id, implementation_ref,
  version, deterministic:true
}

Rules:
- LLM-002 gates MUST reference a versioned BenchmarkPolicy; calibration evidence
  must be traceable.
- VER-004 plausible outcomes MUST resolve to a concrete OutcomeSpace version.
- DomainPack validators MUST return ValidationReport, never an unstructured
  boolean/string.
- The disagreement metric MAY differ by domain, but MUST be declared, deterministic
  and versioned.
```

### 17.19.3 Conflict Contract

Conflict 是 `blocking_conflict_policy`、`unresolved_conflicts[]` 與 `ReviewItem(CONFLICT)` 共用的唯一物件。衝突不得只以字串或散落旗標表示。

```
Conflict {
  conflict_id, project_id, episode_id?, trace_id,
  conflict_type,
  subject_refs[],                  # hypothesis / attestation / observation / relation ids
  blocking,                        # bool; consumed by TransitionPolicy.blocking_conflict_policy
  detected_at, detected_by_actor_or_slot,
  supporting_refs[],
  review_id?,                      # ReviewItem when escalated
  resolution_status, resolved_at?, resolution_event_id?
}

conflict_type:
  PROVENANCE_CONFLICT          # missing or contradictory provenance chain
| CONDITION_CONFLICT           # ConditionMatch = INCOMPATIBLE / UNKNOWN at a required gate
| VALIDITY_CONFLICT            # BackendValidity insufficient for the claimed authority
| AUTHORITY_CONFLICT           # AuthorityPolicy.compare returned INCOMPARABLE
| SIM_TO_REAL_CONFLICT         # simulated and measured evidence disagree
| SOURCE_RETRACTION_CONFLICT   # supporting source retracted or errata-flagged
| INDEPENDENCE_UNRESOLVED      # DEPENDENCE_UNKNOWN blocks a required independence threshold

resolution_status:
  OPEN | UNDER_REVIEW | RESOLVED | ACCEPTED_AS_OPEN_QUESTION | EXPIRED

Rules:
- EpistemicStateProjection.unresolved_conflicts[] holds conflict_id references.
- ReviewItem(subject_type=CONFLICT | AUTHORITY_CONFLICT).subject_id is a conflict_id.
- TransitionPolicy.blocking_conflict_policy is a list of conflict_type values that
  force outcome != ALLOW while any matching Conflict has blocking = true.
- Conflicts are never silently deleted. Closing a Conflict is a state change and MUST
  record resolution_event_id.
```

## 17.20 PriorArtSearchRecord

```
PriorArtSearchRecord {
  search_id, episode_id, intent, sources[], queries[],
  date_range?, retrieved_at, source_policy_version,
  result_count, deduped_work_count, limitations[], coverage_notes,
  external_source_record_ids[], inference_provenance_id?
}
```

## 17.21 ExternalSourceAdapter Interface Contract

所有外部 source provider 必須正規化成同一個 contract；SourceRouter 只依賴 capabilities / policy / normalized records，不知道 provider 實作細節。

```
ExternalSourceAdapter {
  provider_id() -> str
  capabilities() -> SourceCapabilities
  healthcheck() -> SourceHealth
  search(query: SourceQuery, policy: AccessPolicy) -> list[ExternalSourceRecord]
  fetch(locator: SourceLocator, policy: AccessPolicy) -> ExternalSourceRecord
  snapshot(locator_or_record, ref?, policy) -> ArtifactRef
}

ExternalSourceRecord {
  provider, source_type, canonical_locator, title?, authors/owner?,
  retrieved_at, visibility, version_ref?, content_hash?, snapshot_artifact_id?,
  rights_status?, license_metadata?, sensitivity, trust_class,
  metadata{}, raw_payload_ref?
}
```

## 17.22 IngestionItem / StageResult Contract

IngestionItem 是使用者在 Knowledge Inbox 看到的那一列。它是**投影，不是真相來源**：state 由 Job / ExecutionSpan / Artifact / ReviewItem / Conflict 推導，不得由前端或人工直接指定。

```
IngestionItem {
  item_id, project_id, actor_id, trace_id,
  raw_artifact_id,                  # MUST exist before any parsing stage runs
  source_kind,                      # UPLOAD | WATCHER | CONNECTOR
  display_name, submitted_at,
  state,                            # derived; see below
  stage_results[],                  # StageResult[]
  duplicate_of_artifact_id?,        # identical bytes
  duplicate_of_source_work_id?,     # same underlying work, different bytes
  review_ids[], conflict_ids[],
  error_ids[],                      # ErrorRecord refs
  job_ids[], last_updated_at
}

state:
  PROCESSING | READY | PARTIAL | NEEDS_REVIEW | DUPLICATE | BLOCKED | FAILED

StageResult {
  stage,                            # SECRET_SCAN | RAW_STORE | PARSE_TEXT | PARSE_TABLE
                                    # | PARSE_FIGURE | CLAIM_EXTRACT | EMBED | INDEX
  status: SUCCEEDED | FAILED | SKIPPED | PENDING | DEGRADED,
  job_id?, span_id?, error_id?,
  output_refs[], started_at, finished_at?
}
```

### State derivation（規範性，依此順序求值）

```
BLOCKED       if any StageResult failed with error_class = POLICY_BLOCK
FAILED        if RAW_STORE failed, or all value-producing stages failed
PARTIAL       if >=1 value-producing stage SUCCEEDED and >=1 FAILED
NEEDS_REVIEW  if any open ReviewItem or blocking Conflict is attached
DUPLICATE     if duplicate_of_artifact_id is set (identical bytes)
PROCESSING    if any stage is PENDING or a Job is QUEUED/RUNNING/WAITING_RESOURCE
READY         otherwise
```

### DUPLICATE 的兩種語意不得混為一談

```
duplicate_of_artifact_id     identical bytes  -> no new scientific value; safe to skip
duplicate_of_source_work_id  same work, different bytes (preprint vs journal vs mirror)
                             -> NOT a discardable duplicate. MUST still create
                                SourceWork/Attestation so EVI-004 can resolve independence.
                                Silently dropping it corrupts corroboration counting.
```

### Ordering rule（與 SEC-003 的交互）

```
receive -> SECRET_SCAN -> (quarantine | RAW_STORE) -> parsing stages

Raw artifact is preserved before parsing so that a parser failure never requires re-upload.
But a file that fails or times out SECRET_SCAN goes to quarantine, NOT to raw store,
and surfaces as BLOCKED (not FAILED).
```

## 17.23 ErrorRecord & Error Classification Contract

ErrorRecord 是 `Job.structured_error` + `ExecutionSpan` 的使用者層投影，不是第二個真相來源。錯誤分類的目的不是好看，而是決定**「誰要動手」**。

```
ErrorRecord {
  error_id,                         # ERR-YYYYMMDD-NNNN ; stable, project-scoped
  project_id, trace_id, job_id?, span_id?, item_id?,
  error_class, reason_code,         # reason_code keys into MessageCatalog
  component,                        # e.g. EmbeddingWorker, FigureParser, GitHubConnector
  occurred_at, attempt_count, max_attempts, next_retry_at?,
  technical_detail_ref,             # pointer; NOT inlined into user payload
  remediation_actions[],            # RemediationAction[]
  resolved_at?, resolution_note_ref?
}
```

| error_class | 意義 | 預設處置 | 自動 retry |
|---|---|---|---|
| `USER_INPUT_ERROR` | 檔案損壞/加密/無文字層/URL 錯 | 使用者處理 | **MUST NOT** |
| `EXTRACTION_WARNING` | AI/Parser 抽取不完整或不確定 | 人工 review | **MUST NOT** |
| `POLICY_BLOCK` | ACL / NDA / license / budget | 阻擋並稽核 | **MUST NOT** |
| `EXTERNAL_SERVICE_ERROR` | provider 逾時/rate limit/離線 | 系統自動重試 | MUST (bounded) |
| `SYSTEM_ERROR` | DB / storage / worker / queue | 系統重試 + 通知 admin | MUST (bounded) |

```
RemediationAction {
  action_key,                       # RETRY | RETRY_WITH_OCR | IGNORE_STAGE | MARK_UNKNOWN
                                    # | CORRECT_VALUE | ACCEPT | REUPLOAD | REQUEST_ACCESS
                                    # | ESCALATE_HUMAN | VIEW_TECHNICAL
  label_key,                        # MessageCatalog key, not literal text
  requires_scope?,                  # ACL scope needed to offer this action
  cost_estimate?                    # CostVector when the action spends budget
}
```

### Rules

```
- POLICY_BLOCK MUST NOT be auto-retried. A retry loop against an ACL is indistinguishable
  from an attack and MUST instead emit an audit event (SEC-001/SEC-002).
- USER_INPUT_ERROR MUST NOT be auto-retried; retrying a corrupt file burns budget forever.
- Auto-retry consumes budget through BudgetGate (COST-001) and stops at Job.max_attempts;
  exhausted retries transition the surface to FAILED with next_retry_at cleared.
- Budget exhaustion is POLICY_BLOCK, not FAILED. The system is healthy; the policy stopped it.
- EXTRACTION_WARNING MUST NOT be rendered with failure styling. It is the UNKNOWN discipline
  working correctly (EVI-002). Rendering it as an error trains users to click ACCEPT to clear
  it, which silently reintroduces hallucinated completion.
```

### Stability tiers

```
FROZEN   error_class 的五個值。新增第六類 MUST 經 ADR。
         理由:error_class 決定「誰動手」與 retry 政策,下游分支邏輯依賴它。

GROWING  reason_code 詞彙與 MessageCatalog entries。
         M1 期間可自由新增,不需 ADR,但每個新 reason_code MUST 在 catalog
         有對應 entry 且對應到一個既有 error_class。
         M1 exit 時盤點一次實際分布;若某個 error_class 佔比 > 60% 或有一類從未出現,
         提 ADR 檢討分類。
```

## 17.24 Two-Tier Disclosure & Message Catalog

```
MessageCatalog {
  catalog_id, locale, version,
  entries[]: { reason_code, user_summary, user_cause, user_next_steps[], severity }
}
```

### Rules

```
- User-facing text MUST come from a versioned MessageCatalog keyed by reason_code.
  It MUST NOT be generated by an LLM at render time. An LLM-written failure explanation is an
  ungrounded inference presented as system fact, which contradicts P3 / EVI-003.
  (An LLM MAY be used offline to draft catalog entries; entries are then reviewed and versioned.)
- technical_detail_ref is NOT inlined in the default payload. Expanding it is an authorization
  decision, not a UI toggle: it requires an ACL scope (VIEW_TECHNICAL_DIAGNOSTICS) checked
  server-side (SEC-002). Technical detail may contain NDA filenames, private repository paths,
  restricted prompt fragments and query content; leaking it bypasses SEC-001.
- Technical detail MUST be redacted against the requesting Actor's sensitivity_clearance before
  return; redaction MUST preserve trace_id / job_id / span_id so the audit trail survives.
- error_id lookup MUST be scoped by project membership. An error_id from another project
  returns not-found, never a permission-denied that confirms existence.
```

### System Health 是推導的，不是手維護的

```
component status <- Capability.availability (17.18)
                  + ExternalSourceAdapter.healthcheck() -> SourceHealth (17.21)
                  + Job queue depth + ReviewQueue depth (17.19.1)

A Lumerical seat shortage surfaces as degraded availability, not as an error.
```

---

# 18. Final Repository Tree

以下目錄樹以「長期 Laboratory Innovation Brain」為目標，同時避免一開始過度 microservice 化。`core/` 為 domain-agnostic；`domains/silicon_photonics/` 才包含 photonics physics 與 Lumerical specifics。

```
laboratory-innovation-brain/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── compose.yaml
├── Makefile
├── IMPLEMENTATION_STATUS.md
├── CHANGELOG.md
│
├── docs/
│   ├── SAI_3.3.pdf
│   ├── architecture/
│   │   ├── epistemic_event_model.md
│   │   ├── execution_model.md
│   │   ├── source_policy.md
│   │   ├── security_boundary.md
│   │   └── domain_extension.md
│   ├── adr/
│   │   ├── ADR-0001-postgres-first.md
│   │   ├── ADR-0002-event-sourced-belief.md
│   │   ├── ADR-0003-claim-attestation-separation.md
│   │   ├── ADR-0004-intent-aware-source-policy.md
│   │   ├── ADR-0005-cost-vector.md
│   │   ├── ADR-0006-run-extractor-separation.md
│   │   ├── ADR-0007-core-evidence-authority.md
│   │   ├── ADR-0008-typed-predictions-and-hypothetical-evaluation.md
│   │   └── ADR-0009-two-tier-error-disclosure.md
│   ├── normative_statements.yaml
│   ├── spec_coverage_audit/            # per-milestone human audit records
│   └── implementation/
│       ├── M0-foundation.md
│       ├── M1-epistemic-memory.md
│       ├── M2-silicon-photonics-tools.md
│       ├── M3-hypothesis-brain.md
│       └── M4-first-vertical.md
│
├── configs/
│   ├── system.yaml
│   ├── storage.yaml
│   ├── model_routing.yaml
│   ├── privacy_policies.yaml
│   ├── source_policies.yaml
│   ├── evidence_authority.yaml
│   ├── budgets.yaml
│   ├── message_catalog/zh_TW.yaml
│   ├── message_catalog/en.yaml
│   └── domains/silicon_photonics.yaml
│
├── src/lab_brain/
│   ├── bootstrap.py
│   ├── core/                            # domain-agnostic
│   │   ├── models/
│   │   │   ├── artifact.py
│   │   │   ├── source_work.py
│   │   │   ├── claim.py
│   │   │   ├── observation.py
│   │   │   ├── attestation.py
│   │   │   ├── relation.py
│   │   │   ├── hypothesis.py
│   │   │   ├── prediction.py
│   │   │   ├── episode.py
│   │   │   ├── decision.py
│   │   │   ├── actor.py
│   │   │   ├── job.py
│   │   │   ├── capability.py
│   │   │   ├── benchmark_policy.py
│   │   │   ├── outcome_space.py
│   │   │   ├── validation_report.py
│   │   │   ├── review_item.py
│   │   │   ├── conflict.py
│   │   │   └── cost.py
│   │   ├── epistemic/
│   │   │   ├── events.py                # BeliefRevisionEvent
│   │   │   ├── projector.py             # EpistemicState projection
│   │   │   ├── replay.py
│   │   │   └── quarantine.py
│   │   ├── provenance/
│   │   │   ├── inference.py
│   │   │   ├── execution.py
│   │   │   └── trace.py
│   │   ├── repositories/
│   │   │   ├── artifact_repository.py
│   │   │   ├── claim_repository.py
│   │   │   ├── attestation_repository.py
│   │   │   ├── event_repository.py
│   │   │   ├── episode_repository.py
│   │   │   ├── graph_repository.py
│   │   │   └── unit_of_work.py
│   │   ├── orchestration/
│   │   │   ├── state_machine.py
│   │   │   ├── job_queue.py
│   │   │   ├── resume.py
│   │   │   └── termination.py
│   │   └── policies/
│   │       ├── admission.py
│   │       ├── source_policy.py
│   │       ├── evidence_authority.py
│   │       ├── budget.py
│   │       └── lifecycle.py             # TransitionPolicy + evaluate_hypothetical
│   │
│   ├── storage/
│   │   ├── postgres/
│   │   │   ├── repositories.py
│   │   │   ├── event_store.py
│   │   │   └── graph_repository.py
│   │   ├── artifacts/{interface.py,local.py,s3.py}
│   │   └── numerical/{parquet_store.py,raw_passthrough.py}
│   │
│   ├── ingestion/
│   │   ├── pipeline.py
│   │   ├── admission_gate.py
│   │   ├── progressive_enrichment.py
│   │   ├── source_work_resolution.py
│   │   ├── claim_resolution.py
│   │   ├── secret_scanner.py
│   │   ├── parsers/{documents.py,tables.py,figures.py}
│   │   └── watchers/{filesystem.py,git.py,approved_transcripts.py}
│   │
│   ├── evidence/
│   │   ├── extractor.py
│   │   ├── normalizer.py
│   │   ├── condition_schema_registry.py
│   │   ├── condition_matcher.py
│   │   ├── independence.py
│   │   ├── retriever.py
│   │   ├── inverted_retriever.py
│   │   ├── source_router.py
│   │   └── retraction_erratum.py
│   │
│   ├── cognition/                       # 6 core roles only
│   │   ├── supervisor.py
│   │   ├── evidence_researcher.py
│   │   ├── hypothesis_engine.py
│   │   ├── critic.py
│   │   ├── verification_planner.py
│   │   ├── novelty_auditor.py
│   │   ├── protocols/stake_adaptive_debate.py
│   │   ├── benchmark_policy.py
│   │   ├── model_router.py
│   │   ├── model_slots.py
│   │   └── inference_provenance.py
│   │
│   ├── verification/
│   │   ├── planner.py
│   │   ├── sufficiency.py
│   │   ├── cost_vector.py
│   │   ├── capability_registry.py
│   │   ├── capability_router.py
│   │   ├── disagreement.py
│   │   ├── outcome_space.py
│   │   ├── validation.py
│   │   ├── authority.py
│   │   └── verification_gate.py
│   │
│   ├── tools/
│   │   ├── registry.py
│   │   ├── contracts.py
│   │   ├── execution.py
│   │   └── job_adapter.py
│   │
│   ├── domains/
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── silicon_photonics/
│   │       ├── plugin.py
│   │       ├── condition_schema/
│   │       ├── authority_policy.py
│   │       ├── backend_validity.py
│   │       ├── validators/
│   │       ├── extractors/              # backend-agnostic Cj/Rs/Q/ER/...
│   │       ├── specialists/{semiconductor.py,optical.py,rf_system.py,thermal_control.py}
│   │       ├── capabilities/
│   │       ├── workflows/
│   │       ├── verification/
│   │       └── benchmarks/
│   │
│   ├── tool_providers/lumerical/        # backend-bound run_* only
│   │   ├── bridge.py
│   │   ├── session.py
│   │   ├── license_pool.py
│   │   ├── charge.py
│   │   ├── mode.py
│   │   ├── fdtd.py
│   │   ├── interconnect.py
│   │   └── mock.py
│   │
│   ├── integrations/
│   │   ├── external_sources/
│   │   │   ├── literature/
│   │   │   ├── github/
│   │   │   ├── patents/                 # deferred after M4
│   │   │   └── web/                     # deferred after M4
│   │   └── git/local_provenance.py
│   │
│   ├── security/
│   │   ├── actors.py
│   │   ├── acl.py
│   │   ├── classification.py
│   │   ├── egress_guard.py
│   │   ├── license_policy.py
│   │   └── audit_log.py
│   │
│   ├── operations/
│   │   ├── cost_ledger.py
│   │   ├── budget_gate.py
│   │   ├── review_queue.py
│   │   ├── observability.py
│   │   ├── ingestion_status.py          # IngestionItem projection
│   │   ├── error_record.py
│   │   ├── health.py
│   │   └── backup_restore.py
│   │
│   └── interfaces/
│       ├── cli.py
│       ├── inbox.py                     # lab-brain inbox / explain <error_id>
│       └── approvals.py
│
├── migrations/
│   ├── 001_actors_projects.sql
│   ├── 002_artifacts_sourceworks.sql
│   ├── 003_claims_observations_attestations.sql
│   ├── 004_relations.sql
│   ├── 005_epistemic_events_transition_policies.sql
│   ├── 006_jobs_runs.sql
│   ├── 007_capabilities_costs.sql
│   ├── 008_conditions.sql
│   ├── 009_vectors.sql
│   ├── 010_review_observability_benchmark_policies.sql
│   ├── 011_predictions_conflicts.sql
│   └── 012_ingestion_items_errors.sql
│
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── e2e/
│   ├── security/
│   ├── ux/
│   ├── spec/test_requirement_traceability.py
│   ├── spec/test_normative_statement_coverage.py
│   └── domains/silicon_photonics/
│
├── benchmarks/
│   ├── core/{epistemic_replay,evidence_independence,source_policy,debate_diversity}/
│   └── silicon_photonics/{rs_contact_gap,mesh_artifact,condition_matching,hypothesis_discrimination}/
│
├── fixtures/
├── scripts/{bootstrap_dev.py,migrate.py,ingest.py,replay_beliefs.py,run_benchmark.py,verify_environment.py}
└── deployment/local/                    # lab_server / air_gapped deferred until needed
```

## 18.1 這些資料夾第一版先不實作

- `learning/sft`、`preference`、`offline_rl`：先建立 trajectory dataset 再做
- `interfaces/dashboard`：CLI / notebook 先跑通 verification loop，UI 後做
- `integrations/lims`：若實驗室沒有 LIMS，不要為了完整性先做
- `domains/silicon_photonics/fabrication`、`thermal_control`：先留 interface / schema，Ring v1 可延後
- `retrieval/graph_paths`：Phase 1 用 relation tables 即可，無需專用 graph engine

---

# 19. GitHub Attribution Matrix — 每一模組從哪裡取材

> **NOTE（敘述性章節）**：本表視為 architecture references，不代表 Laboratory Innovation Brain 直接複製其程式碼。實際 fork / copy 前應逐一確認最新 license、版本、維護狀態與第三方依賴條款。

| 目標系統模組 | 參考來源 | 取什麼 | 不取什麼 | 目標系統新設計 |
|---|---|---|---|---|
| Hypothesis Generation/Reflection/Evolution | Kaimen Co-Scientist / Google AI Co-Scientist | Generation, Reflection, Ranking, Evolution, Proximity | Elo 決定 truth | 用 tournament 分配 simulation attention；truth 交給 evidence |
| Scientific Evidence Retrieval | FutureHouse PaperQA2 | scientific search + evidence gathering + citation grounding | 把 QA output 當 memory | 增加 condition normalization、evidence object、provenance |
| Cross-domain Graph Reasoning | MIT SciAgents | graph paths / multi-agent scientific connection | 大型 ontology upfront | Phase 2 再引入 graph reasoning；v1 relation tables |
| Photonic Execution Loop | Flexcompute AutoPhotonicDesign | DRC → simulate → analyze → journal | 單 scalar FoM keep/discard | 改成 hypothesis-discriminating experiment + multi-fidelity |
| Research Tree Exploration | Sakana AI Scientist v2 | best-first / progressive branching | 無限制 tree expansion | budget-aware hypothesis portfolio；昂貴 solver cost model |
| Research Team Protocol | Stanford Virtual Lab | PI / specialist meeting concept | 自由聊天 | 獨立 position + cross-examination + experiment proposal |
| Workflow Separation | Agent Laboratory | literature / experiment / report stage separation | paper writing 當核心 | 用 evidence/hypothesis/run stage isolation 防 confirmation bias |
| Perspective-Guided Questions | STORM / Co-STORM | 多視角問題與 shared conceptual space | 把 mind map 當 scientific truth | 用於 research gap / question discovery |
| Experimental Feedback | FutureHouse Robin | 實驗資料回流 candidate generation | 生醫 specific pipeline | 抽象成 observation→belief update |
| Principle-Guided Discovery | PriM | physics/chemistry principles + virtual experiments | property optimizer = discovery | 把 principles 轉 validators/falsifiers |
| Research Infrastructure | ARI | MCP plugins、claim-evidence gate、reproducibility/BFTS pattern | 完整 paper automation | 借 tool plugin/provenance/evaluator pattern |
| Lumerical Bridge | lumerical-mcp | lumapi multi-product session pattern | arbitrary eval_script | typed domain tools + immutable manifests |
| Document Parsing | Docling | layout-aware scientific ingestion | parser-specific data model | adapter → Laboratory Brain normalized artifact/evidence |
| Stateful Orchestration | LangGraph | explicit state graph / checkpoint idea | raw data in graph state | 只傳 entity IDs / structured summaries |
| External Source Connectivity | GitHub remote repository interface pattern + provider-agnostic adapter architecture | discovery、ref-pinned retrieval、commit provenance、capability-based connector registry | 直接依賴 GitHub SDK；不把 README/stars 當 scientific truth；不假設可複製任何程式碼 | Adapter + GitHubConnector + SourceRouter + privacy/rights/provenance gate，可替換成 GitLab/Gitea/其他 provider |

---

# 20. Risk Register — P0/P1/P2 風險與防線

| Priority | 風險 | 後果 | 防線 |
|---|---|---|---|
| P0 | Epistemic contamination | LLM inference 被寫成 evidence，數月後自我引用成「已知事實」 | schema-level epistemic type + admission gate + provenance audit |
| P0 | Private data leakage | NDA PDK / unpublished idea 被送外部 search/model | local privacy gateway + labels + private mode + egress logs |
| P0 | Evaluator corruption | Agent 改 metric extractor / solver config 讓自己「看起來變好」 | typed tools + immutable evaluator + hidden validation gate |
| P0 | Unreproducible runs | simulation 沒記 version/mesh/material/script commit | mandatory run manifest + artifact hash + replay tests |
| P0 | Evidence extraction hallucinated completion | 抽取器為填滿 schema 自行補 doping/bias/geometry，污染後續 condition-aware reasoning | field-level status + UNKNOWN/NOT_REPORTED + targeted enrichment + human escalation |
| P0 | Low-fidelity false falsification | coarse mesh / 簡化模型的 numerical artifact 被當成物理反例，正確 hypothesis 被過早淘汰 | fidelity-aware epistemic authority + PROVISIONAL_CHALLENGE + standard/validation fidelity escalation |
| P0 | Private repository / query leakage | 授權 private repo 或 unpublished concept 被混入不受控外部 search | explicit auth scope + allowlist + egress policy + audit；no secret in provenance |
| P0 | **Belief revision not replayable** | 錯誤 evidence/extractor 被發現後無法重新推導目前 belief；audit/trajectory dataset 失效 | append-only BeliefRevisionEvent + projector + quarantine/replay tests |
| P0 | **Evidence independence inflation** | preprint/正式版/review/轉引被重複算成獨立支持 | Claim/SourceWork identity + Attestation + SAME_WORK_AS/CITES + independence policy |
| P0 | **LLM reasoning without provenance** | Hypothesis/critique/support judgment 無法重現 | InferenceProvenance mandatory on every LLM-produced scientific object/relation |
| P0 | **No actor/ACL enforcement** | NDA、approval、egress 無法回答「誰有權」 | Actor + ProjectMembership + sensitivity clearance + default-deny labeling |
| P0 | **Cost / license runaway** | 多角色/長時 solver/API 造成不可控費用與資源爭用 | CostLedger + BudgetGate + Capability estimate_cost + license pool/job queue |
| P0 | **Async scientific workflow missing** | FDTD/measurement/fabrication 使同步 episode 永久阻塞 | Job entity + AWAITING_* states + suspend/resume events |
| P0 | **Unruled belief transition** | Event 可重播但狀態仍由 LLM 任意決定 | versioned TransitionPolicy + deterministic evaluate + EPI-005 test |
| P0 | **Authority comparison undefined** | 重大 contradiction gate 無法決定 | AuthorityPolicy partial-order comparator + INCOMPARABLE handling |
| P1 | Overengineering | 過早部署多 DB / graph / swarm，團隊無法維護 | PostgreSQL-first + measured scale-out + phase gates |
| P1 | Groupthink | 多 Agent 互相附和造成假共識 | stake-adaptive independent positions + Critic inverted retrieval + bundle-divergence/diversity metrics + external verification |
| P1 | Condition mismatch | 不同 wavelength/bias/platform paper 被錯誤跟合併 | condition-aware evidence + structured filters |
| P1 | Simulator overfit | Agent 找 solver artifact 而非 robust design | multi-fidelity / hidden corners / independent rerun / measurement |
| P1 | Memory write friction | 研究員被迫填大量 schema，最後停止使用 | non-invasive ingestion + auto extraction + only decision/root-cause annotation |
| P1 | Historical bias | 長期 memory 讓系統只重複實驗室既有思路 | external novelty audit + exploration budget + graph cross-domain search |
| P1 | Simulator treated as ground truth | 模型/材料/mesh 系統誤差被忽略，sim-to-real conflict 被錯誤抹平 | EvidenceAuthority + AuthorityPolicy.compare + backend validity + conflict preservation；no fixed simulator>measurement ordering |
| P1 | Tacit-knowledge capture friction | 教授/學生不願填複雜表單，Heuristic layer 長期空洞 | authorized-source Heuristic Miner + candidate certificate + approve/correct/reject workflow |
| P1 | Graph backend coupling | Agent/service 直接依賴 Raw SQL CTE，未來 traversal workload 變化難以遷移 | GraphRepository abstraction + conformance/regression tests + benchmark-triggered migration |
| P1 | External source/provider coupling | Agent code 直接綁 GitHub/某 paper API，provider 改版或換平台時 cognition 層一起壞 | ExternalSourceAdapter + connector registry + contract tests |
| P1 | Remote source drift / deletion | GitHub branch、README、release 更新後無法重現當時 reasoning | ref/commit pinning + snapshot hash + SOURCE_UNAVAILABLE lifecycle |
| P1 | JSONB condition semantic drift | 多年後 condition-aware retrieval 靜默退化 | versioned Domain ConditionSchema + DB validation + migration/backfill policy |
| P1 | Embedding-space mixing | 換 embedding model 後 cosine 距離失真 | model-version filtered retrieval + dual-index re-embed migration |
| P1 | Source corroboration / retraction blind spot | 撤稿或同源重複資料持續支持 belief | source-work dedup + retraction/erratum check + PriorArtSearchRecord |
| P1 | Human review backlog | 所有 uncertainty 都流向教授造成永久 PENDING | ReviewItem schema + ReviewQueue capacity/SLA/expiry + human-review Capability availability fed into Planner |
| P1 | **Warning fatigue destroys UNKNOWN discipline** | EXTRACTION_WARNING 以失敗樣式呈現，使用者學會一律按「接受」清掉，hallucinated completion 從 UI 端重新進入知識庫，EVI-002 形同虛設 | EXTRACTION_WARNING 與 error 分離呈現（§17.23）；NEEDS_REVIEW 走 ReviewItem 並受 SLA/expiry 治理（UX-005）；ACCEPT 動作必須記 actor_id + InferenceProvenance 對照，並納入 §15.2 unsupported claim rate 指標 |
| P1 | **Lumerical license unavailable for real replay** | TST-001 要求「以真實 Lumerical project 在有 license 的環境重播」；若 CI 或人工 gate 取不到 seat，M2 / M4 的 DoD 按字面無法達成 | M0 期間盤點 seat 可用性與並行上限；`license_pool.py` 實作 seat 佇列；real-run 改為 nightly / 人工觸發 gate 而非每次 CI；IMPLEMENTATION_STATUS.md 的 `Lumerical availability:` 為 blocker 欄 |
| P1 | **No ground-truth case set for M4 benchmark** | M4 exit gate 要求 fixed benchmark set（not cherry-picked）；若實驗室沒有一批已定案、可重播的歷史 Rs/Cj 異常案例，M4 沒有資料可驗收 | M0/M1 期間平行整理 5–10 個歷史 case 的 root cause + 原始 artifact + 當時結論；以 `benchmarks/silicon_photonics/` fixture 形式入庫；case 數不足時 M4 gate 順延而非降標 |
| P1 | Spec prose not enforced | 散文 MUST 沒 requirement/test，Coding Agent 不實作 | Normative Statement Registry + T-SPEC-002 coverage lint + 人工 coverage audit |
| P2 | Model/provider churn | API / model names 迅速變動 | model abstraction + capability routing, not model-name coupling |
| P2 | Storage product churn | S3/vector/graph product 維護狀態改變 | protocol/interface abstraction + exportable open formats |
| P2 | Copyright/rights | 外部 full text cache policy 不一致 | rights metadata + source-specific retention；no blanket fair-use assumption |

---

# 21. Day-to-Day Lab Operation — 完成後每天怎麼運作

以下情境描述 Laboratory Innovation Brain 完成後在實驗室的日常角色。重點不是「每件事都自動」，而是所有重要研究事件都回到共同 scientific memory，讓下一個人能繼續。

## 21.1 早上：新論文進來

1. External connector 發現或研究員加入新 paper
2. Parser 保存 artifact、DOI、版本與 rights metadata；抽取 section/table/figure/equation
3. Evidence Normalizer 產生 claim + condition + locator，並與既有 hypotheses / claims 做 condition-aware match
4. 若 paper contradicts active hypothesis，Epistemic State 必須建立 `ReviewItem(subject_type=CONFLICT)`，保留衝突與來源，不得直接覆蓋舊結論
5. Evidence Agent 在下次相關 episode 會優先提示這個新衝突

## 21.2 下午：學生完成一組 CHARGE sweep

1. Typed tool 自動產生 Run manifest：project hash、bias、AC frequency、mesh、solver version、script commit
2. Raw output / plots / arrays 進 Artifact Layer；metric extractor 產生 Cj(V)、Rs(V) Observation
3. 系統比對原 hypothesis predictions
4. 若 Rs trend 異常，Case-Based Retriever 找歷史相似 failure；Critic 產生 contact / mesh / extraction 等 competing causes
5. Verification Planner 建議最便宜的區辨測試；學生或 Supervisor 核准後執行
6. 確認 root cause 後，FailureAnalysis 與 Heuristic 更新；未來再遇到同症狀會先查這些

## 21.3 Meeting：教授提出「能不能把熱漂移與控制一起做？」

1. Supervisor 建立 ResearchEpisode 與 privacy scope
2. Evidence Function 分 semiconductor / optical / thermal / control perspectives 搜集內外部證據
3. 各 specialist 獨立提出 position，不先互相看答案
4. Hypothesis Engine 形成 competing mechanisms / design hypotheses
5. Critic 要求每個 hypothesis 有 falsifier 與 confounder
6. Verification Planner 選擇能以 MODE / INTERCONNECT 最快區分的 simulation
7. 結果回寫後，meeting 紀錄只需補充人類決策理由與下一步

## 21.4 一年後：新學生加入

新學生不需要從零翻學長資料夾。他可以問：「我們過去所有 ring modulator Rs 異常有哪些原因？哪幾次是 contact gap、哪幾次是 mesh？各自怎麼驗證？」

Laboratory Innovation Brain 應回傳 evidence-linked episodes，而不是一段沒有來源的總結。**這才是它的傳承價值。**

---

# 22. Acceptance Criteria — Phase-1 System Acceptance

| 層級 | Acceptance Criteria |
|---|---|
| Data/Provenance | 任一引用的 internal simulation metric 可在 2-3 hops 內追到 Run + Artifact hash + backend validity |
| Evidence | 系統不允許 INFERRED / HYPOTHESIS 物件被當成 measured/simulated evidence |
| Retrieval | 對 ring modulator benchmark，可依 wavelength/bias/device conditions 過濾不相容 evidence |
| Hypothesis | 每個 admitted hypothesis 具有 mechanism、prediction、falsifier、confounders、minimum test |
| Verification | Planner 只選 declared plausible outcome 可改變 policy decision 的 sufficient actions；Pareto 後使用 versioned deterministic SelectionPolicy |
| Simulation | 至少 CHARGE + MODE + INTERCONNECT 具有 typed tools 與 reproducible run manifest |
| Memory | 同一真實 failure case 再出現時，系統可找回歷史 episode 並減少無效 solver calls |
| Privacy | Private Mode 的受限資料不產生外部 network request；Audit 可驗證 |
| Benchmark | 能比較 Single LLM / RAG / Structured Evidence / Full Laboratory Innovation Brain 的 root-cause accuracy、solver cost、unsupported claim rate |
| Human Value | 教授/研究生能從 episode lineage 快速理解「做過什麼、為什麼、結果、下一步」，不依賴原作者在場 |
| Extraction Integrity | 關鍵 evidence 欄位無法確認時輸出 UNKNOWN/NOT_REPORTED；測試集中不得以模型常識偷偷補值 |
| Fidelity Integrity | Exploratory/low-fidelity evidence 不可單獨將核心 Hypothesis 標為 REJECTED；需能觸發 escalation |
| Evidence Authority | 任一重大 belief revision 所用 evidence 可由 AuthorityPolicy 比較；INCOMPARABLE 不得硬排序 |
| Tacit Knowledge Governance | Heuristic Miner 只從 approved sources 產生 Candidate Heuristic；未經人類核准不得升級為 lab rule |
| Graph Abstraction | Cognition/retrieval 不得直接依賴 backend-specific SQL/Cypher；GraphRepository contract 必須通過 conformance/regression tests |
| External Sources | Literature/GitHub/Web/ELN 等來源透過同一 ExternalSourceAdapter boundary；停用 GitHub connector 後 core cognition 仍可啟動 |
| GitHub Provenance | 任何被引用的 GitHub file/code/release 能追到 repository identity + resolved commit/ref + retrieved_at + content/snapshot hash |
| Private GitHub Security | 未配置明確 authentication + allowlist/project scope 時，系統不得讀 private repo；restricted context 不得被用於 uncontrolled public search |
| Epistemic Replay | 隔離一筆曾導致 belief transition 的 Attestation 後，可 replay events / relations 並得到可驗證的新 EpistemicState；不得靠手改 current status |
| Claim Independence | 同一 work 的 preprint + journal + review fixture 不得被計成三個獨立 corroborations |
| Inference Provenance | 任一 Hypothesis/Critique/SUPPORTS judgment 可追到 model/version + prompt version + evidence bundle hash + source policy |
| Actor/ACL | 未授權 actor 無法讀取/egress restricted project；所有 approval 與 egress 有 actor_id audit |
| Async Jobs | mock 6-hour job 可 submit→AWAITING_JOB→event→resume；duplicate callback 不產生重複 run（idempotent） |
| Cost Governance | LLM/tool call 前 budget gate 可預估/檢查成本；超限 fail-closed 或 human approval |
| Condition Versioning | 每筆 condition-aware record 具 schema version；不符合 schema 的 write 被拒絕或 quarantine |
| Sim-to-Real Extractor | 同一 backend-agnostic metric extractor 可接受 simulation array 與 measurement array fixture，輸出可比較且記 normalization/method |
| Source Intent Policy | DIAGNOSIS 與 NOVELTY_AUDIT 使用不同 SourcePolicy；Critic 可產 inverted evidence bundle |
| Spec Integrity | Requirement ID 唯一，且每個 normative requirement 至少映射一個 test；不存在 test 指向未知 ID |
| Transition Governance | 所有 scientific state transition 由 TransitionPolicy 允許；LLM 不可直接改 Hypothesis status |
| Bundle Reproducibility | 任一 LLM scientific output 可追到 canonical EvidenceBundle hash，重建相同 ordered evidence set |
| Human Capacity | human-review Capability availability 會隨 ReviewQueue capacity/depth 改變，Planner 不把人類審核視為免費無限資源 |
| Operational Guardrails | secret/license/embedding-version/retraction/observability 至少各有 Requirement ID + automated/fixture test |
| **Prediction Computability** | Hypothesis 的 prediction 是 typed 物件並綁定 declared OutcomeSpace version；sufficiency 由 side-effect-free `evaluate_hypothetical` 計算，planner/LLM 不得自行發明 hypothetical relation |
| **Conflict Governance** | blocking Conflict 會阻止 ALLOW 並出現在 TransitionDecision.blocking_conflict_ids；關閉 Conflict 必須記錄 resolution event |
| **User Surface Integrity** | IngestionItem state 由後端推導；byte-duplicate 與 same-work duplicate 正確區分；POLICY_BLOCK/USER_INPUT_ERROR 不自動重試；技術診斷需 ACL 且經 redaction；使用者錯誤文字來自 versioned MessageCatalog |

---

# 23. Agent Implementation Protocol — 讓 Coding Agent 直接照規格施工

本章把 architecture vision 轉成 Agent 可以執行、Human 可以逐步驗收的施工契約。Agent 不應一次「把整個系統做完」；應按 milestone 建立可運行 vertical slices，每一個 requirement 都有輸出檔案、測試與狀態。

## 23.1 Implementation Agent Operating Rules

| ID | Normative requirement | Definition of Done |
|---|---|---|
| AGT-001 | Agent MUST 先讀 SAI 3.3、IMPLEMENTATION_STATUS.md、現有 ADR 與目前 milestone，再修改程式 | 每次工作輸出列出讀過的規格版本與 requirement IDs |
| AGT-002 | Agent MUST 一次完成一個可驗收 slice；不得同時大改 storage、schema、agents、UI | PR/patch 可被單獨測試與回退 |
| AGT-003 | Agent MUST 更新 IMPLEMENTATION_STATUS.md：完成、部分完成、blocked、測試結果、下一步 | 文件與實作狀態一致 |
| AGT-004 | Agent MUST NOT silent schema drift。任何 migration 都要有 schema version 與向前/向後策略 | migrations + contract tests 通過 |
| AGT-005 | 若偏離 SHOULD 或變更 MUST，Agent MUST 建 ADR；碰到 P0 contract 必須等待 Human approval | ADR 被記錄並列出 affected requirements |
| AGT-006 | Agent SHOULD 優先 CLI + tests，不應先做 Dashboard | 無 GUI 仍可跑核心 vertical slice |
| AGT-007 | Agent MUST 提供 mock/fake boundaries，使 CI 在沒有 Lumerical license、外網或雲端 LLM 時仍可驗證核心邏輯 | CI 可以用 mock simulator 跑核心 contract/e2e tests |
| AGT-008 | Agent MUST implement external provider access behind ExternalSourceAdapter; cognition/domain code MUST NOT call GitHub/Web/Literature provider SDK directly | Connector contract tests pass; disabling/replacing one provider does not require cognition source changes |
| AGT-009 | Agent MUST NOT mutate EpistemicState directly; all scientific state transitions go through BeliefRevisionEvent/event projector | Static/contract tests reject direct repository update path |
| AGT-010 | Agent MUST attach InferenceProvenance to every LLM-produced hypothesis/critique/relation judgment | Missing provenance prevents admission/transition |
| AGT-011 | Agent MUST keep core domain-agnostic: simulator-specific validity fields belong to DomainPack/backend schemas | Core model imports contain no mesh/CHARGE/MODE-specific fields |
| AGT-012 | Agent MUST implement long-running external/tool actions as Jobs with idempotent resume events | Mock delayed job e2e passes and can recover after process restart |
| AGT-013 | Agent MUST enforce budget/ACL before external/model/tool execution, not after | Security/cost tests show no side effect when gate denies |
| AGT-014 | Agent MUST separate backend-bound `run_*` from backend-agnostic `extract_*` metric logic | Same extractor contract passes simulation and measurement fixtures |
| AGT-015 | Agent MUST NOT resolve spec conflicts via "newer-looking" prose; conflicting normative contracts block the slice and require spec issue/ADR | Spec lint / review must report direct conflicts before implementation |
| AGT-016 | Agent MUST use TransitionPolicy/AuthorityPolicy operators; LLM output alone cannot cause scientific status transition | Contract tests reject direct status assignment from cognition path |
| AGT-017 | Agent MUST construct canonical EvidenceBundle before any scientific LLM call and persist bundle hash in InferenceProvenance | LLM call wrapper refuses missing bundle_id/hash |

## 23.2 Requirement ID Namespace

```
SYS-xxx     system/core architecture
ART-xxx     artifact/source-work/provenance
EVI-xxx     claim/evidence/retrieval/source routing
EPI-xxx     belief events / epistemic projection / hypothesis
VER-xxx     verification planning / capability / authority
SIM-xxx     simulator/backend contracts
DOM-SP-xxx  silicon photonics domain
SEC-xxx     actor/ACL/privacy/egress
OPS-xxx     job queue / observability / review operations
COST-xxx    cost ledger / budget gates
SRC-xxx     external source / intent-aware routing
GH-xxx      external code-hosting provider (GitHub and equivalents)
HEU-xxx     tacit knowledge / heuristic governance
LLM-xxx     model router / inference provenance
EXT-xxx     domain extension
UX-xxx      user-facing state / error surface / recovery
TST-xxx     meta/spec/CI requirements
```

## 23.3 Mandatory Development Loop

```
Read spec + current status
      ↓
Select next unblocked Requirement IDs
      ↓
Implement smallest coherent slice
      ↓
Unit + Contract tests
      ↓
Integration / Mock-simulator test
      ↓
Update IMPLEMENTATION_STATUS.md
      ↓
If architecture changed → ADR
      ↓
Human reviews evidence, not code volume
      ↓
Proceed to next slice
```

## 23.4 Human Steering Points

Human 不需要逐行指揮 Agent 寫 code；Human 應控制 **scientific semantics 與 scope**。下列決策不可默默交給 Agent 自行定義：Evidence 何時可升級成 verified、什麼 fidelity 足以反駁 hypothesis、哪些 external connector 可接、哪些資料屬於 NDA/CONFIDENTIAL、Silicon Photonics benchmark ground truth、以及何時將某個 experimental heuristic 升級成 hard validator。

| Human 決策點 | Agent 可自行做 | Agent 不可自行做 |
|---|---|---|
| Database implementation | index、query optimization、repository code | 把 Evidence semantics 改成單純 vector chunk；移除 provenance |
| Lumerical adapter | session management、serialization、retry | 改變物理模型或 validator 標準來讓測試過 |
| Agent prompts/models | prompt wording、model adapter | 用 LLM vote 取代 simulator/measurement evidence adjudication |
| Domain extension | 建立符合 DomainPack contract 的新 plugin | 在 core 寫 domain-specific if/else |
| Security | policy engine implementation | 自動把 restricted context 送到外部 LLM/search |
| **Error surface** | message catalog wording、UI rendering | 新增第六個 error_class；把 EXTRACTION_WARNING 改成 error 樣式；把技術診斷變成無 ACL 的公開欄位 |

## 23.5 Normative Architecture Coverage Rule

§6–§16 為 normative architecture。為維持人類可讀性，不要求每一句 MUST 都在正文尾端塞 ID；改用 Normative Statement Registry 讓每條硬性規範可唯一映射到 Requirement ID、Test ID 或明確 DEFERRED rationale。

T-SPEC-001 檢查 ID/traceability；T-SPEC-002 檢查 registry 內部一致性與 test 對應。

**Coverage 的兩段責任必須分清楚，否則會誤以為 CI 已保證完整性：**

```
(1) 機器可檢查 — T-SPEC-002:
    registry 內每條 statement 有唯一 requirement_id、至少一個 test 或明確 DEFERRED rationale;
    不存在指向未知 requirement/test 的條目。

(2) 人工可檢查 — Spec Coverage Audit:
    「正文每一條 hard MUST 都已進入 registry」無法由 lint 從散文推得。
    除非正文帶 inline key(見 23.6),否則此項為 human review gate:
      owner       = spec maintainer
      cadence     = 每個 milestone exit 前一次
      artifact    = docs/spec_coverage_audit/<milestone>.md
      pass        = 逐節列出該節 hard MUST 數與已登錄數,差額為 0 或有具名 DEFERRED

未登錄的 hard MUST 仍視為 spec defect;但發現它的是 (2) 不是 (1)。
Coding Agent 不得因 T-SPEC-002 通過就推論 registry 完整。
```

## 23.6 Normative Statement Registry

Registry 可由文件旁的 machine-readable YAML/JSON 維護，至少含 `statement_key`、`section`、`normative_level`、`requirement_id`、`test_ids`、`deferred_rationale`。

```yaml
normative_statements:
  - key: belief.transition.policy
    section: 8.2.1
    level: MUST
    requirement_id: EPI-005
    tests: [T-EPI-005]
  - key: authority.incomparable.review
    section: 8.2.1
    level: MUST
    requirement_id: EPI-004
    tests: [T-EPI-004]
  - key: critic.inverted_retrieval.high_stakes
    section: 7.2
    level: MUST
    requirement_id: SRC-002
    tests: [T-SRC-002]
  - key: review.capacity.planner
    section: 14.4.1
    level: MUST
    requirement_id: OPS-002
    tests: [T-OPS-002]
  - key: benchmark.policy.calibration
    section: 15.4
    level: MUST
    requirement_id: LLM-002
    tests: [T-LLM-002]
  - key: prediction.typed.contract
    section: 17.5.1
    level: MUST
    requirement_id: VER-006
    tests: [T-VER-006]
  - key: sufficiency.hypothetical.sideeffect_free
    section: 9.1
    level: MUST
    requirement_id: VER-006
    tests: [T-VER-006]
  - key: conflict.typed.blocking
    section: 17.19.3
    level: MUST
    requirement_id: EPI-006
    tests: [T-EPI-006]
  - key: ingestion.state.derived
    section: 17.22
    level: MUST
    requirement_id: UX-001
    tests: [T-UX-001]
  - key: ingestion.duplicate.work_vs_bytes
    section: 17.22
    level: MUST
    requirement_id: UX-001
    tests: [T-UX-001]
  - key: error.class.retry_policy
    section: 17.23
    level: MUST
    requirement_id: UX-002
    tests: [T-UX-002]
  - key: error.disclosure.acl_gated
    section: 17.24
    level: MUST
    requirement_id: UX-003
    tests: [T-UX-003]
  - key: ingestion.raw_first.stage_retry
    section: 27.2
    level: MUST
    requirement_id: UX-004
    tests: [T-UX-004]
  - key: review.surface.single_queue
    section: 27.3
    level: MUST
    requirement_id: UX-005
    tests: [T-UX-005]
  - key: message.catalog.not_llm
    section: 17.24
    level: MUST
    requirement_id: UX-006
    tests: [T-UX-006]
  - key: health.derived.from_capability
    section: 17.24
    level: MUST
    requirement_id: UX-007
    tests: [T-UX-007]
  - key: independence.basis.beyond_work
    section: 6.17
    level: MUST
    requirement_id: EVI-004
    tests: [T-EVI-004]
    deferred_rationale: >
      Non-work-level independence (same group / wafer / instrument / method) is not modeled
      in v3.3. Policies requiring it must escalate to human review rather than silently
      treating attestations as independent. Review at M4 exit.
```

> **NOTE**：以上為節錄示例。完整 registry 維護於 `docs/normative_statements.yaml`，其完整性由 §23.5 (2) 的人工稽核保證。

---

# 24. Domain Extensibility Contract — 先光子、核心不寫死

SAI 3.3 的實作優先級不是「先做一個抽象到什麼都能支援的框架」，而是「先把 Silicon Photonics 做深，但把 dependency direction 與 extension points 設對」。換句話說：**先 vertical-first，再 interface-stable；不要先做空泛 universal ontology。**

## 24.1 Core vs Domain Boundary

| Core MUST know | Core MUST NOT know | Silicon Photonics DomainPack owns |
|---|---|---|
| Artifact / SourceWork / Claim / Observation / Attestation / Relation / Hypothesis / Prediction / Episode / Job / Actor / Capability / CostVector / BeliefRevisionEvent / Conflict | Cj、Rs、Q、FSR、ring radius、PN doping、CHARGE/MODE command names、mesh convergence field names | 光子 condition schema、EvidenceAuthority policy、backend validity、physical validators、metric extractors、specialist roles、Lumerical bindings、benchmarks |
| InferenceProvenance、SourcePolicy contract、EvidenceAuthority abstraction、ACL、budget、event replay、IngestionItem/ErrorRecord | 「measurement 永遠最高」、「1550 nm 是預設」、任何 solver-specific hierarchy | 波長/偏壓/溫度/幾何/doping/driver-load semantics、mesh/solver/calibration validity rules |
| Tool registry、VerificationAction types、DomainPack registry、graph/evidence repositories、cost/fidelity concepts | 某一個 solver 的參數細節；不得假設所有 domain 都有 simulator | CHARGE/MODE/FDTD/INTERCONNECT typed adapters、domain analytical checks、measurement bindings |

## 24.2 Dependency Rule

```
ALLOWED:
  domains.silicon_photonics  → core
  domains.silicon_photonics  → tools/simulators interfaces
  cognition                  → DomainPack registry/interface

FORBIDDEN:
  core                       → domains.silicon_photonics
  evidence generic layer     → ring-specific constants
  orchestration              → direct CHARGE/MODE imports
  database schema            → hard-coded ring-only columns unless isolated in domain
                               extension tables
```

## 24.3 DomainPack Protocol

```python
class DomainPack(Protocol):
    id: str
    version: str

    def register_condition_schema(self, registry): ...
    def register_condition_comparator(self, registry): ...
    def register_evidence_authority_policy(self, registry): ...
    def compare_authority(self, a, b) -> AuthorityComparison: ...
    def register_backend_validity_schemas(self, registry): ...
    def register_validators(self, registry): ...
    def register_metric_extractors(self, registry): ...
    def register_capabilities(self, registry): ...
    def register_tools(self, registry): ...
    def register_specialists(self, registry): ...
    def register_workflows(self, registry): ...
    def register_benchmarks(self, registry): ...
    def register_disagreement_metrics(self, registry): ...

    def validate_attestation(self, attestation) -> ValidationReport: ...
    def compare_conditions(self, a, b) -> ConditionMatch: ...
    def declared_outcome_space(self, action, hypothesis) -> OutcomeSpace: ...
    def disagreement_metric(self, outcome_space) -> DisagreementMetric: ...
```

## 24.4 Deferred Extension Examples（Informative, not M0-M4 scope）

以下領域只作為 extension-boundary examples，不是 v3.3 M0-M4 交付範圍，也不是固定優先順序。真正擴充時以研究需求、共享 evidence/tool boundary 與 EXT-001 benchmark 決定。

| Priority | Extension Domain | Why it is adjacent | Core reuse |
|---|---|---|---|
| 1 | Optical Communication / WDM System | ring/MZM/PD/link budget/BER 與現有 INTERCONNECT、system metrics 直接相連 | Evidence/Hypothesis/Episode/VerificationPlan 幾乎全部重用 |
| 2 | RF / High-Speed Electronics | modulator electrode、impedance、S-parameter、driver/load 是高速 SiPho 的直接瓶頸 | Numerical store、condition matching、active verification planning |
| 3 | Thermal / Control | ring resonance drift、heater locking、temperature perturbation | multi-fidelity + causal hypothesis + control verification actions |
| 4 | Semiconductor Device / Process | PN junction、contact、implant、mobility、process corners | CHARGE workflow、failure diagnosis、fabrication evidence |
| 5 | Photonic Packaging / Test | coupling loss、alignment、fiber attach、measurement calibration | measurement provenance、failure analysis、sim-to-real |
| 6 | Materials / Heterogeneous Integration | SiN/III-V/LN/Ge 等新材料系統 | 核心保留，但需要新的 condition/entity/validator/tool packs |

## 24.5 Extensibility Acceptance Test

**EXT-001**：在不修改 core models、core repositories 與 orchestration state machine 的前提下，加入一個 ToyDomain 或第二個真實 domain，並能註冊 condition schema、validator、tool 與 benchmark。若必須修改 core 才能加入第二 domain，代表 extension boundary 失敗。

---

# 25. Silicon Photonics First Vertical — 第一條可驗收端到端實作

第一版不要從「自動讀全世界論文 + 多 Agent + 完整 Lumerical 全家桶」開始。第一條 vertical slice 應以已知可驗證案例串起 Memory、Evidence、Hypothesis、Verification Planner、Typed Tool、Verification Gate 與 Failure Analysis。重點不是一定要跑最多 solver，而是系統能否先用便宜檢查縮小原因，再只跑必要的 targeted verification。

**推薦第一案例：PN junction Rs 異常診斷。**

## 25.1 Vertical Slice VS-SP-001 — Rs Bias-Insensitive Anomaly

```
INPUT
  Existing CHARGE project / normalized mock equivalent
  Bias sweep: 0 → reverse bias
  Observation: Cj trend plausible; Rs extremely high and weakly bias-dependent

EXPECTED RESEARCH LOOP
  Artifact ingest
    → Run Manifest
    → Evidence extraction (Cj(V), Rs(V), backend validity)
    → Anomaly detection
    → competing hypotheses
        H1 access/contact discontinuity
        H2 mesh / convergence artifact
        H3 contact/material/normalization model issue
    → experiment candidates
        connectivity inspection / mesh sensitivity / model check
    → choose cheapest discriminative check
    → run typed tool
    → confirmed finding
    → FailureAnalysis + Heuristic candidate
    → belief update + provenance graph
```

## 25.2 Required Typed Tools for First Vertical

命名與 ID 依 §10.2.1 / §10.2.2 canonical 表。

| Tool ID | Canonical name | Class | 最低輸出 |
|---|---|---|---|
| DOM-SP-TOOL-001 | `run_charge_dc_sweep` | run | carrier profiles、IV、bias points、run manifest、convergence status、raw artifact refs |
| DOM-SP-TOOL-002 | `run_charge_ac_sweep` | run | complex current / impedance、frequency conditions |
| DOM-SP-TOOL-003 | `run_mesh_sensitivity` | run | mesh variants、extracted metrics、stability delta、validity report |
| DOM-SP-TOOL-004 | `extract_cj_rs` | extract | Cj_per_length、Rs_per_length、units、normalization basis、method、bias/frequency conditions |
| DOM-SP-TOOL-005 | `inspect_contact_connectivity` | inspect | regions、contacts、connectivity violations、current path、artifact refs |
| DOM-SP-TOOL-006 | `validate_expected_trends` | validate | ValidationReport with domain rule version；never changes raw evidence |

## 25.3 First Vertical Requirements

> EXT-001 定義於 §24.5，不在本表重複。本表 57 條 + EXT-001 = **58 條 normative requirements**。

| Requirement | MUST |
|---|---|
| SYS-001 | Core scientific state path MUST be Artifact/SourceWork → Claim/Observation → Attestation → RelationJudgment → TransitionPolicy → BeliefRevisionEvent → EpistemicStateProjection. |
| ART-001 | 每個輸入 project/script/result 必須有 immutable artifact ID + hash + source + timestamp。 |
| SIM-001 | 每次 CHARGE run 必須保存 solver version、project hash、mesh/bias/config、exit/convergence status。 |
| SIM-002 | coarse/low-fidelity contradiction 只能標記 CHALLENGED；要 REJECT hypothesis 必須過 standard/validation fidelity gate。 |
| SIM-003 | Tool invocation MUST occur through a typed ToolRegistry. No tool, Capability or backend adapter may expose an arbitrary script-execution entry point (`eval_script`-class public interface). Untyped execution paths MUST be rejected by static conformance test. |
| EVI-001 | Cj/Rs evidence 必須含 unit、normalization basis、bias/frequency conditions 與 extraction method。 |
| EVI-002 | 缺失欄位必須是 UNKNOWN/NOT_REPORTED，不得由 LLM 補常見值。 |
| EVI-003 | LLM-generated interpretation/inference MUST NOT be admitted as OBSERVED/SIMULATED/MEASURED evidence; it remains an inference/RelationJudgment with InferenceProvenance. |
| EVI-004 | 同一 underlying work / derived source 必須經 Claim/SourceWork resolution；corroboration 不得重複計數。DEPENDENCE_UNKNOWN contributes 0 to min_independent_attestations until resolved. |
| EVI-005 | Domain condition records 必須含 conditions_schema_version；ConditionMatch 語意由 DomainPack 註冊。 |
| EVI-006 | Every scientific LLM call MUST use a canonical EvidenceBundle with deterministic hash over ordered attestation IDs + query/policy/condition snapshot. |
| EVI-007 | Vector retrieval MUST filter by compatible embedding model/version; embedding migration uses dual-index + verified cutover. |
| EVI-008 | Major belief revision from external reported evidence SHOULD pass source-work version/retraction/erratum check; check status MUST be recorded. |
| EVI-009 | Evidence admitted as MEASURED or SIMULATED MUST reference the Run and/or Artifact it was derived from; a record without that reference is refused at admission and MUST NOT be admitted first and back-filled later（§14.3 memory admission gate）。 |
| EPI-001 | 至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被升級成 confirmed root cause。 |
| EPI-002 | confirmed root cause 必須可以 trace 回 Run/Evidence/Artifact；LLM statement 不可作為證據。 |
| EPI-003 | 所有 hypothesis status 變更必須產生 BeliefRevisionEvent；EpistemicState 可由 event replay 重建。 |
| EPI-004 | DomainPack MUST expose AuthorityPolicy.compare returning STRONGER/WEAKER/EQUIVALENT/INCOMPARABLE. INCOMPARABLE at a required transition gate MUST yield NEED_HUMAN_REVIEW + ReviewItem(AUTHORITY_CONFLICT); no silent promotion/rejection. |
| EPI-005 | Hypothesis state transition MUST be authorized by versioned TransitionPolicy and emitted as BeliefRevisionEvent; LLM cannot directly mutate status. The canonical operator signature is `TransitionPolicy.evaluate(...) -> TransitionDecision` (§8.2.1); no other name or arity may be used. |
| EPI-006 | Conflicts MUST be first-class typed Conflict records with a declared conflict_type and blocking flag. `blocking_conflict_policy` MUST resolve against conflict_type; a blocking Conflict MUST prevent ALLOW; closing a Conflict MUST record a resolution event. |
| VER-001 | 下一個 verification action 必須有 predicted discriminatory outcome + estimated cost；若較便宜 evidence 已足夠，不得無理由升級到 simulator。 |
| VER-002 | Verification Planner 必須使用 Capability descriptors；sufficient candidate 有明確 state-transition/blocked-conflict criterion。 |
| VER-003 | Verification cost 使用 CostVector；不可只存 normalized_cost 作唯一決策依據。 |
| VER-004 | Plausible outcomes MUST come from a declared, versioned OutcomeSpace and pass explicit constraints/ValidationReport checks; planner may not invent outcomes. |
| VER-005 | After Pareto filtering, planner MUST apply a versioned deterministic SelectionPolicy; identical input+policy returns identical ranked plan. |
| VER-006 | Hypothesis predictions MUST be typed Prediction objects bound to a declared OutcomeSpace version, carrying RelationJudgmentTemplate effects. Sufficiency MUST be computed via side-effect-free `TransitionPolicy.evaluate_hypothetical`; planner or LLM MUST NOT invent hypothetical relations. |
| VER-007 | Candidate/design comparison MUST preserve and present multi-objective trade-offs. A single scalar figure of merit MUST NOT be the sole keep/discard criterion (P10). |
| VER-008 | Any `DisagreementMetric` used for verification ranking MUST be bound to a declared OutcomeSpace, MUST carry a version, and MUST be deterministic: identical input plus identical metric version MUST yield an identical result. Core MUST NOT hard-code one universal distance. |
| DOM-SP-001 | Silicon photonics rule/validator 版本必須記錄；core 不得內建 Rs 趨勢規則。 |
| DOM-SP-002 | Cj/Rs/Q/ER 等 extractor 必須 backend-agnostic；simulation 與 measurement 共用定義與 normalization provenance。 |
| SRC-001 | 所有外部知識取得經 ExternalSourceAdapter/SourceRouter；provider-specific SDK 不得滲入 cognition/domain core。 |
| SRC-002 | SourcePolicy 依 research intent 切換；當 decision.stakes >= policy threshold，Critic MUST 執行 inverted retrieval、保存 inverted EvidenceBundle，否則該 decision 不得進入 BELIEF_REVISION。**§7.6 的 independent critique path 有兩個 trigger，非只一個：重大 REJECT **與** irreversible action。標記為 irreversible 的 Capability/action MUST NOT 被 dispatch，除非 independent critique 已完成 —— 即使該 action 完全不造成 belief transition。critique 的獨立性要求 retrieval bundle、reasoning policy 或 model route 至少一項與原推論不同，且 adjudication 引用 external evidence 或 verification result。human approval 本身不可取代 critique：approval 回答「誰負責」，critique 回答「這個結論是否被獨立挑戰過」，兩者不互換。** |
| SRC-003 | 任何 novelty status MUST 引用 `PriorArtSearchRecord`，記錄 sources、queries、date range 與 limitations。無覆蓋率記錄的 novelty status MUST 被拒絕；internal novelty MUST NOT 被當作 global novelty 呈現。 |
| GH-001 | GitHubConnector 至少支援 public repo discovery + ref/commit-pinned file fetch + normalized provenance record。 |
| GH-002 | private repo access 需 explicit auth/allowlist/security policy；未授權時必須 fail closed。 |
| GH-003 | GitHub technical/prior-art evidence 不得自動升級為 peer-reviewed scientific evidence；repo/ref/commit 必須保存。 |
| HEU-001 | `CandidateHeuristic` MUST 保存 source_artifact_ids 與 source_locators，MUST 以 `PENDING_REVIEW` 起始，且 MUST NOT 在缺少帶 `approved_by_actor_id` 的人類核准紀錄下成為 active lab rule。Heuristic Miner MUST 只從 approved sources 產生候選（P16）。 |
| LLM-001 | 所有 LLM scientific outputs 必須帶 InferenceProvenance：model/version、slot、prompt version、evidence bundle hash。 |
| LLM-002 | Structured Debate MUST collect diversity/bundle-divergence/cost metrics; hard gates use a versioned BenchmarkPolicy calibrated on a fixed domain benchmark before enforcement. |
| SEC-001 | RESTRICTED_NDA/CONFIDENTIAL context MUST NOT leave the approved boundary; external connector/model egress requires policy + Actor clearance, otherwise fail closed and emit audit evidence. |
| SEC-002 | 所有 actor/approval/egress/private-source access 必須經 Actor+ACL；新 internal artifact sensitivity 預設 fail-closed。 |
| SEC-003 | Immutable ingestion MUST run secret scan first; suspected credentials go to quarantine/redaction flow, not permanent normal artifact storage. |
| SEC-004 | External code MUST carry license_class; UNKNOWN/COPYLEFT source code is blocked from code-generation context unless project policy explicitly permits. |
| OPS-001 | long-running tool/external actions 必須 Job 化並支援 suspend/resume/idempotent callback。 |
| OPS-002 | Human ReviewQueue MUST have capacity, stakes, SLA/expiry and feed availability/earliest_available_at into human-review Capability. |
| OPS-003 | Execution observability MUST persist trace/span contract linking episode → retrieval/LLM/job/run/artifact with status and cost refs. |
| OPS-004 | Cross-store writes (artifact store + PostgreSQL) MUST be compensated within a single unit of work. A failure between stores MUST leave no dangling reference; the compensating path MUST be verified by fault injection. |
| COST-001 | 每次 LLM/tool action 前必須經 BudgetGate；CostLedger 至少記 wall-clock/tokens/money/license-seat estimates。**超出 session budget 時 BudgetGate MUST 提供 supervisor/human approval path，approval 本身記為帶 `actor_id` 的事件；只會永久拒絕、不存在 approval path 的實作不滿足本要求（§14.3 昂貴計算 gate）。** |
| UX-001 | IngestionItem state MUST be derived from Job / ExecutionSpan / Artifact / ReviewItem / Conflict by the documented precedence order; it MUST NOT be set directly by a client or by an LLM. Identical-bytes duplicates and same-work duplicates MUST be distinguished; same-work duplicates MUST still create SourceWork/Attestation. |
| UX-002 | Every surfaced failure MUST carry an error_class from {USER_INPUT_ERROR, EXTRACTION_WARNING, POLICY_BLOCK, EXTERNAL_SERVICE_ERROR, SYSTEM_ERROR} and a reason_code. POLICY_BLOCK and USER_INPUT_ERROR MUST NOT be auto-retried. Auto-retry MUST pass BudgetGate and stop at Job.max_attempts. Budget exhaustion MUST classify as POLICY_BLOCK, not FAILED. |
| UX-003 | Technical diagnostics MUST NOT be included in the default user payload. Expansion requires a server-side ACL scope check and MUST be redacted against the requesting Actor's sensitivity_clearance while preserving trace_id/job_id/span_id. error_id lookup MUST be scoped by project membership. |
| UX-004 | The raw artifact MUST be durably stored (after SECRET_SCAN) before any parsing stage runs. Retry MUST resume at the failed stage reusing raw_artifact_id and Job idempotency, never requiring re-upload or a full re-run. |
| UX-005 | NEEDS_REVIEW MUST be represented by a ReviewItem so it feeds ReviewQueue capacity and human-review Capability availability (OPS-002). A parallel review surface that bypasses ReviewQueue is prohibited. |
| UX-006 | User-facing error text MUST come from a versioned MessageCatalog keyed by reason_code and MUST NOT be generated by an LLM at render time. |
| UX-007 | System Health MUST be derived from Capability.availability, ExternalSourceAdapter.healthcheck(), Job queue depth and ReviewQueue depth. It MUST NOT be a separately maintained status list. |
| TST-001 | 同一案例要能以 mock dataset 在 CI 重播，並以真實 Lumerical project 在有 license 的環境重播。 |
| TST-002 | 規格一致性測試必須檢查 requirement ID 唯一與 requirement↔test traceability。 |
| TST-003 | Spec CI MUST verify normative-statement registry coverage: every registered MUST/SHOULD maps to a unique Requirement ID and at least one test or explicit DEFERRED rationale. |

## 25.4 Vertical Slice Definition of Done

VS-SP-001 只有在以下條件全部成立才算完成：

- CLI 可從一個 project/fixture 建立 episode
- raw artifacts 被 hash 且在 parsing 前已durably 保存
- Cj/Rs 被抽成 structured evidence，含 unit / normalization basis / conditions / method
- 系統提出並保存 ≥2 個 competing hypotheses，每個都有 typed Prediction
- Verification Planner 先檢查 historical case / connectivity / extraction consistency 等低成本動作，再在需要時升級 simulator
- mock/real backend 都走 typed contract
- 結果觸發 fidelity-aware update，且轉移由 TransitionPolicy 授權並產生 BeliefRevisionEvent
- confirmed root cause 可追溯到 Run/Evidence/Artifact
- 同類失敗形成可審核 heuristic candidate
- 整個流程在 Knowledge Inbox 中呈現為一個 IngestionItem + episode，錯誤（若有）帶 error_class 與 remediation actions

## 25.5 Second Vertical — Ring Modulator Mechanism Chain

完成 VS-SP-001 後，第二條 vertical 才擴充到 CHARGE → MODE → INTERCONNECT：以 bias-dependent Cj/Rs、neff/loss、resonance/ER/IL/BER/eye 為 observation chain，測試 Laboratory Brain 是否能區分「電性 RC 改善」「光學 overlap/loss 改變」「操作 detuning」「thermal drift」等 competing mechanisms。此時才需要 system-level specialist 與更多 active experiment logic。

---

# 26. Requirement-to-Test Traceability — 規格到測試的追溯矩陣

Agent 寫出很多 code 不等於系統完成。SAI 3.3 以 traceability matrix 將需求直接綁到測試；IMPLEMENTATION_STATUS.md 應引用這些 Requirement IDs 與 Test IDs。

**59 requirements ↔ 59 tests。**

| Requirement | Test ID | Test type | Pass condition |
|---|---|---|---|
| SYS-001 | T-SYS-001 | architecture | static/conformance test rejects bypass from cognition directly to EpistemicState update or support arrays on Attestation/Hypothesis. |
| ART-001 | T-ART-001 | contract | 同一 bytes 得到同一 content hash/artifact identity；修改 1 byte 必須產生新 artifact_id/hash；若同一人類文件 lineage，lineage_revision 遞增並保留 previous_artifact_id。 |
| SIM-001 | T-SIM-001 | contract | run manifest 缺 solver/project/conditions/validity 任一必要欄位即拒絕升級正式 evidence。 |
| SIM-002 | T-SIM-002 | e2e | low-fidelity contradiction 只使 hypothesis → CHALLENGED，不得直接 → REJECTED。 |
| SIM-003 | T-SIM-003 | architecture | static test rejects any public tool/Capability/backend-adapter interface accepting arbitrary script or code text for execution (`eval_script`-class); every tool invocation resolves through the typed ToolRegistry. |
| EVI-001 | T-EVI-001 | contract/domain | Cj/Rs fixture missing unit、normalization basis、bias/frequency condition 或 extraction method 時 admission fail；完整 fixture 可 round-trip。 |
| EVI-002 | T-EVI-002 | unit | parser 缺欄位時輸出 UNKNOWN/NOT_REPORTED，不得生成 default scientific value。 |
| EVI-003 | T-EVI-003 | integration | LLM-generated interpretation 無法被 evidence admission gate 當作 observed/simulated evidence。 |
| EVI-004 | T-EVI-004 | integration | preprint/journal/review fixture resolve 為同一 source work；DEPENDENCE_UNKNOWN fixture contributes 0 to independent count until resolved; promotion requiring independence stays blocked。 |
| EVI-005 | T-EVI-005 | contract | 錯誤 condition schema version/write 被拒絕；ConditionMatch 回傳受版本控制。 |
| EVI-006 | T-EVI-006 | contract | permuted JSON key order yields same canonical bundle hash; changed attestation order/policy/query snapshot changes hash as defined. |
| EVI-007 | T-EVI-007 | integration | mixed embedding versions are never compared; dual-index migration preserves benchmark recall within threshold before cutover. |
| EVI-008 | T-EVI-008 | integration | retracted/erratum fixture records source status and blocks/flags major belief promotion per SourcePolicy. |
| EVI-009 | T-EVI-009 | contract | a MEASURED/SIMULATED evidence fixture with no run/artifact reference is refused at admission; one with a reference round-trips and the reference resolves to an existing Artifact; admitting first and back-filling the reference is refused; an INFERRED record is not subject to the reference requirement but still cannot be typed MEASURED/SIMULATED (EVI-003). |
| EPI-001 | T-EPI-001 | e2e | root-cause episode 在驗證前保留至少兩個 active/competing hypotheses。 |
| EPI-002 | T-EPI-002 | e2e/provenance | confirmed root cause query 必須 trace 到 Relation/Attestation or Observation → Run → Artifact；只有 LLM statement 的 fixture 不得確認 root cause。 |
| EPI-003 | T-EPI-003 | e2e | 隔離 triggering attestation 後 replay，EpistemicState 投影改變且 history 保留。 |
| EPI-004 | T-EPI-004 | unit | authority fixtures cover stronger/weaker/equivalent/incomparable; required INCOMPARABLE returns NEED_HUMAN_REVIEW, auto-creates ReviewItem(AUTHORITY_CONFLICT), and blocks belief promotion/rejection. |
| EPI-005 | T-EPI-005 | contract/e2e | direct LLM status assignment is rejected; admitted RelationJudgments + policy produce event and replayable projection; only `evaluate` signature exists in the codebase (no `should_transition`); **identical inputs + identical `policy_version` MUST yield an identical `TransitionDecision`, compared under canonical serialization -- a policy whose result varies across repeated calls on the same inputs, or which reads wall-clock/random/ambient state, must FAIL (§8.2.1).** |
| EPI-006 | T-EPI-006 | contract/e2e | A blocking Conflict of a type listed in blocking_conflict_policy forces TransitionDecision.outcome != ALLOW and appears in blocking_conflict_ids[]; AUTHORITY_CONFLICT from an INCOMPARABLE comparison creates a Conflict linked to the auto-created ReviewItem; resolving a Conflict without a resolution_event_id is rejected. |
| VER-001 | T-VER-001 | e2e | Planner 先檢查已存在 evidence / cheap actions；只有較便宜層不足時才升級 simulator，並記錄選擇理由。 |
| VER-002 | T-VER-002 | unit | Planner 對無 capability descriptor 的 backend 不可規劃；有 descriptor 時依 produces/requires match。 |
| VER-003 | T-VER-003 | unit | CostVector 可表達時間/人力/錢/license/不可逆；Planner 不依賴單一 normalized_cost。 |
| VER-004 | T-VER-004 | unit | outcome outside declared OutcomeSpace 或被 explicit constraint/ValidationReport 排除時不可算 plausible；合法 outcome version 可重現 sufficiency result。 |
| VER-005 | T-VER-005 | unit | same actions/state/policy produce identical ranking across repeated runs; tie is resolved by configured lexicographic fallback. |
| VER-006 | T-VER-006 | contract/unit | Prediction with out-of-space expected_outcome is rejected at admission; `evaluate_hypothetical` persists nothing (no relation rows, no BeliefRevisionEvent, projection unchanged); an action with no bound Prediction over its produces is reported NOT sufficient; identical inputs return identical TransitionDecision. |
| VER-007 | T-VER-007 | unit | a single scalar figure of merit cannot decide keep/discard; multi-objective trade-offs are preserved and presented; a scalar-only OutcomeSpace over design quality requires explicit declared justification. |
| VER-008 | T-VER-008 | unit | a DisagreementMetric with no declared OutcomeSpace binding or no version is rejected; identical input plus identical metric version returns an identical result across repeated runs; two domains may register different metrics and neither is core-supplied. |
| DOM-SP-001 | T-DOM-SP-001 | domain | Rs trend validator 只存在 Silicon Photonics DomainPack，移除 plugin 後 core 仍可啟動。 |
| DOM-SP-002 | T-DOM-SP-002 | domain | 同一 `extract_cj_rs` contract 通過 simulated impedance 與 measured impedance fixtures。 |
| SRC-001 | T-SRC-001 | contract | 以 fake GitHub/Literature connectors 替換真 provider 時 SourceRouter/cognition 不需修改；normalized record schema 相同。 |
| SRC-002 | T-SRC-002 | e2e | DIAGNOSIS/NOVELTY 使用不同 source policies；high-stakes decision 未執行 inverted retrieval 時 BELIEF_REVISION 被拒絕；執行後 CritiqueReport.inverted_bundle_id 與 bundle divergence 可追溯；**該 critique path MUST 在 retrieval bundle、reasoning policy 或 model route 至少一項與原推論不同，且 adjudication MUST 引用 external evidence 或 verification result，不得由另一次 model opinion 裁定（§7.6）。**負面 fixture：標記 irreversible 的 action 在 critique 未完成時 MUST NOT dispatch，即使 `causes_belief_revision = false`；且帶有效 human approval 但無 critique 時仍 MUST NOT dispatch。** |
| SRC-003 | T-SRC-003 | integration | novelty fixture without a `PriorArtSearchRecord` is rejected; recorded coverage (sources / queries / date range / limitations) is retrievable; an internal-only search cannot yield a global-novelty claim. |
| GH-001 | T-GH-001 | integration | public fixture repo 可 search/fetch；requested ref 解析到固定 commit SHA，file content hash 與 locator 被保存。 |
| GH-002 | T-GH-002 | security | 未授權 private repo request 被 fail-closed 並產生 audit event；不洩漏 query/private context。 |
| GH-003 | T-GH-003 | epistemic | GitHub record 能被標為 technical/prior-art source；admission gate 不允許其自動冒充 measured/peer-reviewed evidence。 |
| HEU-001 | T-HEU-001 | security/governance | a mined candidate starts `PENDING_REVIEW` and carries source artifact IDs plus locators; promotion without `approved_by_actor_id` is rejected; a miner fixture drawing from an unapproved source yields no candidate. |
| LLM-001 | T-LLM-001 | contract | Hypothesis/Critique/Relation 缺 model/prompt/bundle provenance 時 admission fail；**且既存於庫中而無 InferenceProvenance 的舊推論不得作為新 belief transition 的依據 -- 以該推論為唯一 basis 的 transition 被拒絕，理由可追溯（§7.6）。僅測 admission 不足以通過。** |
| LLM-002 | T-LLM-002 | benchmark | fixed SiPho benchmark produces baseline distributions; the benchmark MUST compare the debate mechanism against a baseline/disabled condition on the same cases, so a claim of groupthink reduction can be refuted by the result and not merely illustrated; BenchmarkPolicy schema stores metric/threshold/sample size/calibration artifacts/version; no hard gate before calibration; **the benchmark MUST record per-case round count and show it varies with case difficulty, so an implementation that always runs the configured maximum number of rounds FAILS even when every metric is recorded correctly (§7.2).** |
| SEC-001 | T-SEC-001 | security | RESTRICTED_NDA context 嘗試送 external connector 時被 policy engine 阻擋並留下 audit event。 |
| SEC-002 | T-SEC-002 | security | 未授權 actor 被 ACL/egress gate 拒絕；新 artifact 未分類時預設 restricted。 |
| SEC-003 | T-SEC-003 | security | fixture secret is quarantined before immutable normal ingest; redacted derivative preserves audit linkage. |
| SEC-004 | T-SEC-004 | security | UNKNOWN/COPYLEFT code fixture is blocked from generation context unless explicit policy fixture allows it. |
| OPS-001 | T-OPS-001 | e2e | delayed mock job 可 suspend/resume；重複 completion event 不建立第二個 run。 |
| OPS-002 | T-OPS-002 | unit/integration | queue depth/capacity changes human-review capability availability and planner earliest_available_at; **a ReviewItem without `stakes` or without an SLA/expiry policy is refused at creation, and an item past its expiry leaves PENDING via the declared policy rather than parking there indefinitely (§14.4).** |
| OPS-003 | T-OPS-003 | e2e | one episode trace reconstructs retrieval → LLM → job → run → artifact and associated cost entries. |
| OPS-004 | T-OPS-004 | integration | fault injection between the artifact-store write and the database commit leaves no dangling artifact reference; the compensating path is exercised and the partial state is either completed or removed. |
| COST-001 | T-COST-001 | integration | 預算不足時 model/tool call 在產生外部 side effect 前被阻擋；**該阻擋可經 supervisor/human approval 解除，approval 以帶 `actor_id` 的事件記錄，未經 approval 的重試仍被阻擋。只實作永久拒絕、沒有 approval path 者必須 FAIL。** |
| UX-001 | T-UX-001 | contract/integration | Fixture set drives every state through the documented precedence (BLOCKED > FAILED > PARTIAL > NEEDS_REVIEW > DUPLICATE > PROCESSING > READY); direct client state assignment is rejected; preprint-vs-journal fixture yields DUPLICATE-by-work **and** a persisted SourceWork/Attestation, while byte-identical fixture yields DUPLICATE with no new Attestation. |
| UX-002 | T-UX-002 | unit/integration | POLICY_BLOCK and USER_INPUT_ERROR fixtures produce zero retry attempts and, for POLICY_BLOCK, one audit event; EXTERNAL_SERVICE_ERROR retries until max_attempts then surfaces FAILED with next_retry_at cleared; budget-exhausted fixture classifies POLICY_BLOCK. |
| UX-003 | T-UX-003 | security | Default payload contains no stack trace, file path, repo name or prompt fragment; expansion without scope is denied; expansion with scope but lower clearance returns redacted detail retaining trace_id/job_id/span_id; cross-project error_id returns not-found (not permission-denied). |
| UX-004 | T-UX-004 | e2e | Parser-failure fixture leaves a retrievable raw artifact; stage retry re-runs only the failed stage, reuses raw_artifact_id, and duplicate retry callbacks create no second Run; secret-scan-timeout fixture lands in quarantine and surfaces BLOCKED, not FAILED. |
| UX-005 | T-UX-005 | integration | A low-confidence extraction fixture creates a ReviewItem visible in ReviewQueue depth and measurably changes human-review Capability availability. |
| UX-006 | T-UX-006 | contract | Every reason_code emitted by fixtures resolves in MessageCatalog; an unknown reason_code fails closed to a generic catalog entry; no render path invokes a model slot. |
| UX-007 | T-UX-007 | integration | Marking an embedding Capability unavailable and a connector healthcheck degraded is reflected in System Health without touching any status table; Lumerical seat exhaustion appears as degraded availability, not as an error. |
| EXT-001 | T-EXT-001 | architecture | 新增 ToyDomain 時 core package 無 source modification；plugin registration 即運作。 |
| TST-001 | T-E2E-SP-001 | vertical e2e | Rs anomaly mock fixture 完整跑通 ingest → diagnose → test → evidence → failure/heuristic candidate。 |
| TST-002 | T-SPEC-001 | spec | 所有 requirement IDs 唯一；每個 normative ID 至少一個 test；test 不引用未知 ID。 |
| TST-003 | T-SPEC-002 | spec | `statement_key` MUST be unique across the registry; each registry entry MUST reference exactly one valid Requirement ID. One Requirement ID MAY be referenced by multiple entries when it covers distinct normative statements in different sections. Every entry maps to at least one existing Test ID or carries an explicit DEFERRED rationale with review date; no entry references an unknown requirement or test. Registry completeness against prose is a human audit gate (§23.5), not asserted by this test. |

## 26.1 Milestone Gate Order

| Milestone | Scope | Exit gate |
|---|---|---|
| **M0a Scientific Identity Foundation** | Postgres migrations 001–004、008；Artifact/SourceWork/Claim/Observation/Attestation/Relation schema；canonical EvidenceBundle；condition schema version；CI + T-SPEC-001/002 | artifact/claim identity + bundle hash + schema/spec conformance pass；**無 Actor/LLM/Simulator 也可測** |
| **M0b Execution/Governance Foundation** | Actor/ACL、Budget/CostLedger、BeliefRevisionEvent + TransitionPolicy/AuthorityPolicy、Prediction/Conflict、trace/span、Job primitives、ReviewItem minimum schema；migrations 005–007、010–011 | event replay + transition/authority tests + ACL/budget/trace contracts pass；**無 DomainPack 也可測** |
| **M1 Research Memory** | Evidence ingestion、SourcePolicy、Claim/source-work resolution、GraphRepository(as_of/bounded)、InferenceProvenance、async Job suspend/resume wiring、**IngestionItem/ErrorRecord/MessageCatalog + CLI inbox**；migration 012 | local document/run ingest；source-work dedup；delayed mock job resumes episode；all scientific LLM calls persist bundle+provenance；**UX-001~007 tests pass** |
| **M2 Silicon Photonics Tool Layer** | Silicon Photonics DomainPack、Capability registry、Lumerical mock/`run_*`、backend-agnostic `extract_cj_rs`、backend validity | simulated + measured fixtures use same extractor contract；license/resource queue mock pass |
| **M3 Hypothesis Brain** | 6 core roles、selected Domain Specialists、PRIMARY/FAST/EMBEDDING minimum routing、stake-adaptive debate、Critic inverted retrieval | role I/O + Position/Critique contracts pass；Critic bundle divergence measurable；benchmark thresholds are calibrated and stored in BenchmarkPolicy before gate enforcement |
| **M4 First Vertical** | VS-SP-001 full loop：intent-aware retrieval → competing hypotheses → capability/cost planning → Job → evidence → belief event → failure/heuristic candidate | fixed benchmark set (**not cherry-picked**) demonstrates root-cause correctness and avoids unnecessary high-cost action in predefined cases |
| DEFERRED M5 External Evidence Expansion | ExternalSourceAdapter registry、PaperQA-style literature adapter、GitHubConnector（public + policy-gated private）、progressive enrichment、novelty audit boundary、ref-pinned snapshot/cache | external evidence enters with source/condition/rights/provenance metadata；GitHub source 可追到 repo + resolved commit/ref；移除 GitHub provider 不影響 core cognition |
| DEFERRED M6 Multi-physics Ring | MODE/INTERCONNECT + ring mechanism benchmark | end-to-end mechanism discrimination benchmark |
| DEFERRED M7 Operational Lab Brain | approved transcript miner、ELN/Git watchers、approvals、security modes、**Web Knowledge Inbox / System Health 面板** | real lab workflow pilot with low human write friction |
| DEFERRED M8 Learning / Second Domain | case-based retrieval、trajectory export、second DomainPack | EXT-001 demonstrated on adjacent domain |

---

# 27. Frontend Error & Recovery Contract — 使用者看得懂，後端追得到

系統對使用者誠實的最低標準：分開顯示「資料本身有問題」「AI 不確定」「權限阻擋」「外部服務故障」「系統壞掉」，每一種都說明下一步能做什麼，且每一筆都能由 `error_id → trace_id → ExecutionSpan → Job → Run → Artifact` 完整追回。

## 27.0 範圍與里程碑歸屬

```
本契約 = 資料契約,不是 UI 實作。

M1  : IngestionItem / ErrorRecord / StageResult / MessageCatalog 落地;
      由 CLI 消費(lab-brain inbox / lab-brain explain <error_id>)。
M7  : Web「Knowledge Inbox」與 System Health 面板(DEFERRED,與 Operational Lab Brain 同期)。

AGT-006 仍然成立:先 CLI + tests,不先做 Dashboard。
同一組 IngestionItem/ErrorRecord 結構必須同時能被 CLI 與未來 Web 消費;
若某個欄位只有 Web 用得到,它不屬於這個契約。
```

## 27.1 Knowledge Inbox

Inbox 是 IngestionItem 的彙總視圖。每個 state 的計數與清單必須可由 CLI 取得（`lab-brain inbox`），Web 面板只是同一份資料的第二個 renderer。

```
READY / PROCESSING / PARTIAL / NEEDS_REVIEW / DUPLICATE / BLOCKED / FAILED
```

點進單一 item 必須能回答四個問題，且四個都來自結構化欄位而非自由文字：

```
what succeeded    <- stage_results[status = SUCCEEDED]
what failed       <- stage_results[status = FAILED] + ErrorRecord.reason_code
what next (系統)  <- error_class 的預設處置 + next_retry_at
what next (你)    <- remediation_actions[] filtered by actor scope
```

## 27.2 Recovery 原則

```
原始檔優先保存:RAW_STORE 成功之後,任何後續 stage 失敗都不得要求使用者重新上傳。

Stage 級重試:retry 從失敗的 stage 恢復,重用 raw_artifact_id 與既有 StageResult,
            並沿用 Job idempotency_key(OPS-001),不得整條重跑。

部分可用:PARTIAL 的成功產物仍可被檢索,但必須帶 stage 缺口標記;
        圖表抽取失敗的文件不得被當成完整證據來源。
```

## 27.3 三種「看起來像錯誤」但不是錯誤的情況

```
EXTRACTION_WARNING   科學證據不足,系統正常。走 ReviewItem,不走 error banner。
DUPLICATE(same work) 不是重複,是第二個 Attestation。必須入庫供 EVI-004 判斷獨立性。
POLICY_BLOCK         系統正常,政策擋下。顯示缺哪個授權與如何申請,不顯示 retry。
```

---

# 結論 — SAI 3.3 的正確用途與 Executable Epistemic Architecture 北極星

> **North Star**：Laboratory Innovation Brain 不應儲存「AI 說過什麼」，而應儲存「實驗室知道什麼、為什麼知道、在什麼條件下知道、哪些地方仍不確定，以及下一個哪種最低成本驗證最有價值」。

SAI 3.3 不是系統名稱，而是能交給 Agent 實作、也能讓人類理解與約束 Agent 的 System Analysis with AI 規格。它的成功標準不是「文件寫得完整」，而是能讓不同 Agent/工程師在不同時間依同一組 scientific contracts 建出相容、可驗證、可延伸的 Laboratory Innovation Brain。

如果只完成 RAG、多 Agent 與自動 Lumerical，Laboratory Innovation Brain 仍然只是工程助理；真正的核心是：

```
Artifact/SourceWork → Claim/Observation → Attestation → RelationJudgment
  → TransitionPolicy → BeliefRevisionEvent → EpistemicStateProjection
```

配合 competing hypotheses、adversarial retrieval 與最低成本充分驗證。

Silicon Photonics 是第一個非常合適的 sandbox：物理鏈明確、多 simulator 可 objective verification、設計空間存在多目標 trade-off，又有大量歷史 paper / internal simulation / measurement 可以形成 evidence。完成第一個 ring modulator closed loop 後，Laboratory Brain core 應能在不改 memory/orchestration kernel 的前提下掛入新的 domain pack。

SAI 3.3 進一步明確化：Laboratory Innovation Brain 的成熟度不只看「能不能找答案/跑模擬」，還要看它是否知道什麼時候根本不需要跑模擬、能否安全承認未知、是否避免低精度數值假象、是否保存 backend validity，並以最低人類摩擦把 tacit knowledge 轉成可審核 operational memory——**以及當事情出錯時，是否能讓使用者看懂發生了什麼、下一步能做什麼，而不是丟出一段 traceback。**

---

# Appendix A — Canonical Database Migrations (No Duplicate Schema)

```
Appendix A intentionally does NOT redefine tables.
Canonical database semantics live in §17 contracts + versioned migrations:

001_actors_projects.sql
002_artifacts_sourceworks.sql
003_claims_observations_attestations.sql
004_relations.sql
005_epistemic_events_transition_policies.sql
006_jobs_runs.sql
007_capabilities_costs.sql
008_conditions.sql
009_vectors.sql
010_review_observability_benchmark_policies.sql
011_predictions_conflicts.sql
012_ingestion_items_errors.sql

Rule: Appendix A is an index only. If migration semantics conflict with §17 + Requirement IDs,
CI MUST fail T-SPEC-002; Coding Agent may not choose one silently.
```

---

# Appendix B — Silicon Photonics DomainPack Tool Set (canonical names, see §10.2.2 / §25.2)

| ID | Canonical name | Class | 最低輸入 | 最低輸出 |
|---|---|---|---|---|
| DOM-SP-TOOL-001 | `run_charge_dc_sweep` | run | project, bias range | carrier profiles, IV, convergence, run manifest |
| DOM-SP-TOOL-002 | `run_charge_ac_sweep` | run | project, DC points, f range | complex current / impedance |
| DOM-SP-TOOL-003 | `run_mesh_sensitivity` | run | project, mesh variants | mesh variants, extracted metrics, stability delta, validity report |
| DOM-SP-TOOL-004 | `extract_cj_rs` | extract | run refs / measured arrays, geometry normalization | Cj/length, Rs/length, units, normalization basis, method |
| DOM-SP-TOOL-005 | `inspect_contact_connectivity` | inspect | geometry artifact | connectivity warnings / current path |
| DOM-SP-TOOL-006 | `validate_expected_trends` | validate | metrics + domain rule version | ValidationReport；never changes raw evidence |
| DOM-SP-TOOL-007 | `run_mode_solve` | run | geometry/material/bias state | neff, loss, field artifact |
| DOM-SP-TOOL-008 | `extract_eo_delta` | extract | two or more bias states | delta neff, delta loss, overlap |
| DOM-SP-TOOL-009 | `run_ring_spectrum` | run | ring model + wavelength range | Q, FSR, resonance, ER/IL |
| DOM-SP-TOOL-010 | `run_nrz_eye_workflow` | run | bitrate, drive states, CW wavelength | BER, Q, eye width, jitter, ER |
| DOM-SP-TOOL-011 | `run_thermal_lock_workflow` | run | drift source + heater/control | lock error, power, transient metrics |

---

# Appendix C — Innovation Brain Evaluation Checklist

- 是否能指出 claim 的原始 artifact / locator？
- 是否保存適用條件，而不是只存一個數值？
- 是否明確區分 observation / inference / hypothesis？
- 是否能產生至少兩個相互可區分的 mechanisms？
- 是否明確寫出 falsifier？
- 下一個 verification action 是否真的能區分 predictions，而且沒有更便宜的充分證據？
- 若結果與預期不同，是否更新 hypothesis，而非修改敘事硬合理化？
- 是否記得過去相似 failure / episode？
- 是否能在 privacy policy 下決定是否可連外？
- 若 simulator 與 measurement 不一致，是否保留 conflict 而非抹平？
- Evidence extractor 是否允許 UNKNOWN / NOT_REPORTED，而不是被 schema 逼著猜值？
- Low-authority contradiction 是否只形成 provisional challenge，並依 AuthorityPolicy / TransitionPolicy 決定 escalation？
- 任何重大 belief revision 的 evidence 是否附可比較的 EvidenceAuthority + BackendValidity，而不是把 backend output 直接當 ground truth？
- Heuristic 是否能追到授權來源，且由人類核准後才成為 active lab rule？
- 多跳關係查詢是否經 GraphRepository，而不是散落 backend-specific query？
- Prediction 是否為 typed 物件並綁定 declared OutcomeSpace，而不是自由文字？
- 錯誤呈現是否分五類，且 EXTRACTION_WARNING 沒有被當成系統故障？

---

# Appendix D — Glossary

| 名詞 | 定義 |
|---|---|
| Artifact | 原始或衍生的不可變研究資產；由 content hash / provenance 綁定 |
| SourceWork | 同一件學術著作的身分；preprint / 正式版 / 鏡像皆指向它 |
| Claim | 可被不同來源/Attestation 指向的科學命題 identity；先解 identity 再算 corroboration |
| Observation | 內部 backend 產生的客觀數值/事件，直接連 Run/Artifact |
| Attestation | 某來源在特定 locator/conditions 下對 Claim/Observation 的具名見證 |
| RelationJudgment | 帶 provenance 的關係判斷；support/contradict 的唯一真實來源 |
| Epistemic State | 系統目前的科研信念狀態；由 BeliefRevisionEvent 重建 |
| BeliefRevisionEvent | append-only scientific state transition record |
| TransitionPolicy | 決定 hypothesis 是否允許狀態轉移的版本化規則；不是 LLM 投票 |
| AuthorityPolicy | 比較 EvidenceAuthority 的版本化偏序規則；可回傳 INCOMPARABLE |
| Prediction | 假說對某可觀測量的具名預測，綁定 OutcomeSpace 並攜帶關係效果模板 |
| Conflict | 具型別的衝突紀錄；blocking 時可阻止狀態轉移 |
| EvidenceBundle | 一次 retrieval 的可重現、可 hash 證據封裝；是 LLM inference provenance 的輸入 identity |
| Research Episode | 一次有 goal、hypothesis、run、observation、decision 的完整研究演繹 |
| Hypothesis Certificate | 讓 idea 進入昂貴驗證前必須具備的 mechanism/prediction/falsifier 等欄位 |
| Falsifier | 若觀察到某結果，應使 hypothesis 被削弱/推翻的明確條件 |
| Condition-aware Retrieval | 先以科學操作條件判斷 comparability，再做 semantic ranking |
| Typed Tool | 有固定 input/output schema、provenance、validator 的工具；不讓 LLM 任意修改 evaluator |
| Multi-Fidelity | 依成本與需要，從 analytical/surrogate/coarse simulation 逐步升級到 high-fidelity / measurement |
| Case-based Reasoning | 從歷史 research episodes / failures 找相似 case 幫助當前診斷 |
| Novelty Auditor | 與 internal reasoning 分離的外部 prior-art 檢查功能 |
| IngestionItem | 使用者在 Knowledge Inbox 看到的一列；狀態由後端推導 |
| ErrorRecord | Job.structured_error + ExecutionSpan 的使用者層投影 |
| MessageCatalog | 版本化的使用者訊息表；錯誤文字不得由 LLM 即時生成 |

---

# Appendix E — Reference Repositories & Architecture Sources

| 來源 | URL |
|---|---|
| Flexcompute AutoPhotonicDesign | https://github.com/flexcompute/autophotonicdesign |
| Kaimen Co-Scientist | https://github.com/Kaimen-Inc/Co-Scientist |
| FutureHouse PaperQA / PaperQA2 | https://github.com/Future-House/paper-qa |
| MIT SciAgents Discovery | https://github.com/lamm-mit/SciAgentsDiscovery |
| Sakana AI Scientist v2 | https://github.com/SakanaAI/AI-Scientist-v2 |
| Stanford Virtual Lab | https://github.com/zou-group/virtual-lab |
| Agent Laboratory | https://github.com/SamuelSchmidgall/AgentLaboratory |
| Stanford STORM / Co-STORM | https://github.com/stanford-oval/storm |
| FutureHouse Robin | https://github.com/Future-House/robin |
| PriM | https://github.com/amair-lab/PriM |
| ARI — Autonomous Research Infrastructure | https://github.com/kotama7/ARI |
| Lumerical MCP (reference implementation) | https://github.com/leisymqaz/lumerical-mcp |
| Docling | https://github.com/docling-project/docling |
| LangGraph | https://github.com/langchain-ai/langgraph |
| Microsoft AutoGen | https://github.com/microsoft/autogen |
| pgvector | https://github.com/pgvector/pgvector |
| Zarr Python | https://github.com/zarr-developers/zarr-python |
| DuckDB | https://github.com/duckdb/duckdb |
| AiiDA Core | https://github.com/aiidateam/aiida-core |
| DVC | https://github.com/iterative/dvc |
| MLflow | https://github.com/mlflow/mlflow |

> **註**：本文件將這些專案視為 architecture references，不代表 Laboratory Innovation Brain 直接複製其程式碼。實際 fork / copy 前應逐一確認最新 license、版本、維護狀態與第三方依賴條款；Laboratory Innovation Brain 盡量透過 adapter / clean-room reimplementation 保持核心可替換。

---

# Appendix F — Implementation Agent Boot Prompt

以下 Prompt 可直接給 Coding Agent 作為初始施工指令；每次只替換 CURRENT MILESTONE 與 repository state，不要刪除 architecture guardrails。

```
You are the implementation agent for the target system described by SAI 3.3
(System Analysis with AI).

IMPORTANT TERMINOLOGY
- SAI 3.3 is the specification document, NOT the product name.
- The target system is Laboratory Innovation Brain.
- Silicon Photonics is the first DomainPack, not a core hard-code.

BEFORE CODING
1. Read SAI 3.3, IMPLEMENTATION_STATUS.md, accepted ADRs, current milestone and
   Requirement/Test IDs.
2. Run spec-conformance checks. A normative conflict BLOCKS the slice; do not resolve
   by choosing the most code-like paragraph.
3. Implement the smallest coherent slice. M0a and M0b are separate gates.

SCIENTIFIC STATE RULES
- Canonical path: Artifact/SourceWork -> Claim/Observation -> Attestation -> RelationJudgment
  -> TransitionPolicy -> BeliefRevisionEvent -> EpistemicStateProjection.
- NEVER mutate EpistemicState or Hypothesis status directly.
- NEVER store evidence_for/evidence_against/support_targets arrays as parallel truth.
- Resolve source-work/claim identity before corroboration counts.
- Inference is not Evidence. Unknown is valid; do not invent missing scientific values.
- Every scientific LLM output/relation requires InferenceProvenance and canonical
  EvidenceBundle hash.
- Authority comparisons use AuthorityPolicy.compare(); required INCOMPARABLE MUST create
  ReviewItem(AUTHORITY_CONFLICT) and block promotion/rejection until reviewed.
- The only transition operator is TransitionPolicy.evaluate(...) -> TransitionDecision.
  Do not introduce should_transition() or any other arity.
- Hypothesis predictions are typed Prediction objects. Sufficiency uses
  evaluate_hypothetical(), which MUST persist nothing.

COGNITION / MODELS
- Core cognition = 6 roles: Supervisor, Evidence Researcher, Hypothesis Engine,
  Adversarial Critic, Verification Planner, Novelty Auditor.
- Domain specialists are registered by DomainPack.
- Model Router exposes 6 LLM slots: PRIMARY, ADVERSARIAL, FAST, CODE, PRIVATE_LOCAL,
  VISION + EMBEDDING (non-LLM).
- High-stakes decisions MUST execute Critic inverted retrieval and persist
  inverted_bundle_id before BELIEF_REVISION. Major REJECT/irreversible actions also require
  an independent critique path and external evidence/verification adjudication;
  provider diversity alone is not truth.

VERIFICATION
- Verification Planner is domain-agnostic. Literature, analytical, historical, numerical,
  surrogate, simulation, measurement and human review are pluggable Capabilities.
- A candidate is sufficient only via a declared/versioned OutcomeSpace +
  ValidationReport-compatible plausible outcome + TransitionPolicy effect or
  blocking-conflict resolution.
- Use CostVector + Pareto filtering + versioned deterministic SelectionPolicy;
  never hide all cost in one scalar.
- Human review is a finite Capability whose availability comes from ReviewQueue capacity.
- run_* is backend-bound; extract_* is backend-agnostic; inspect_* reads without solving;
  validate_* returns ValidationReport.

SECURITY / OPERATIONS
- Enforce Actor/ACL, privacy/rights, secret scan, license policy and BudgetGate
  BEFORE side effects.
- Long-running actions are Jobs with suspend/resume, idempotency, retry/backoff and trace_id.
- External providers go through ExternalSourceAdapter/SourceRouter. Local Git provenance
  and remote GitHub retrieval are separate.
- Preserve repository + resolved ref/commit + content/snapshot hash for cited external code.
- Private/restricted access fails closed.
- Vector retrieval never mixes incompatible embedding spaces.
- Surfaced failures carry one of five error classes; POLICY_BLOCK and USER_INPUT_ERROR are
  never auto-retried.
- Raw artifact is stored after secret scan and before parsing; retry resumes at the
  failed stage.
- User-facing error text comes from the versioned MessageCatalog, never from a model call.

CHANGE CONTROL
- Core MUST NOT import silicon_photonics.
- No silent schema drift. Use migrations + schema versions.
- MUST change -> Requirement/Test update. Architecture boundary change -> ADR.
  P0 scientific/security semantics -> human approval.
- Do not add dashboard, extra DB, graph service or swarm complexity before the
  milestone requires it.

AFTER EACH SLICE
- Run unit/contract/integration/spec tests.
- Update IMPLEMENTATION_STATUS.md with Requirement IDs, files, tests, blockers, costs
  and next smallest slice.
```

---

# Appendix G — Architecture Decision Record (ADR) Template

```
# ADR-XXXX: <Decision Title>
Status: Proposed | Accepted | Rejected | Superseded
Date:
Affected Requirements:
Human Approval Required: Yes/No

## Context
What problem forces a design decision?

## Constraints
Scientific semantics, security, domain boundary, existing data migration, environment.

## Options Considered
1. ...
2. ...
3. ...

## Decision
Chosen option and why.

## Consequences
Positive, negative, operational cost, scientific risks.

## Migration / Rollback
How existing data/code is migrated; how to revert.

## Tests / Evidence
What benchmark or test validates this decision.
```

---

# Appendix H — DomainPack Interface Acceptance Checklist

| Check | Required |
|---|---|
| Manifest declares domain id/version/capabilities | MUST |
| Condition schema can represent UNKNOWN and source status | MUST |
| Domain validators return ValidationReport; they do not mutate raw evidence | MUST |
| Domain exposes `compare_authority` returning AuthorityComparison | MUST |
| Domain declares OutcomeSpace and a deterministic, versioned disagreement metric | MUST |
| Domain tools register through generic ToolRegistry using canonical verb prefixes | MUST |
| Core imports no module from concrete domain package | MUST |
| Domain pack supplies at least one contract fixture + benchmark | MUST |
| Second domain can coexist without changing core entity semantics | MUST |
| Specialist prompts/models are replaceable and are not truth authorities | MUST |
| Domain-specific ontology may expand incrementally | SHOULD |
| Dedicated graph DB / custom model training | MAY |

---

# Appendix I — IMPLEMENTATION_STATUS.md Template

```
# Laboratory Innovation Brain - Implementation Status
Spec: SAI 3.3
System Version: 0.x.y
Current Milestone: M0a/M0b/M1/...
Last Updated:

## Environment
- Python:
- PostgreSQL:
- Lumerical availability:
- Lumerical seats available / concurrent limit:
- Real-run gate mode: CI / nightly / manual
- Ground-truth benchmark cases collected: N / target
- Configured LLM slots:
- Verification backends available:
- External network mode:
- Configured external source adapters:
- GitHub connector auth mode / scope:

## Requirement Status
| ID | Status | Files | Tests | Notes |
|---|---|---|---|---|
| ART-001 | TODO | | | |

Statuses: TODO / IN_PROGRESS / BLOCKED / DONE / DEFERRED

## Tests
- Unit:
- Contract:
- Integration:
- E2E:
- UX:
- Spec:
- Lumerical real-run:

## Architecture Decisions
- ADR-XXXX ...

## Spec Coverage Audit
- Last audit milestone:
- Unregistered hard MUST found:
- Audit artifact:

## Known Risks / Technical Debt
1. ...

## Next Recommended Task
<one small coherent slice, with requirement IDs>
```

---

# Version Notes

| 版本 | 日期 | 主要決策 |
|---|---|---|
| v1.0 | 2026-09-09 | 確立 Laboratory Innovation Brain 長期定位；Silicon Photonics 為第一 domain；採 Artifact→Evidence→Epistemic State 三層；PostgreSQL-first；typed Lumerical tools；competing hypothesis + active experiment selection；privacy modes；完整 repo tree。 |
| v1.1 | 2026-09-10 | Evidence Integrity & Operational Learning Revision：新增 Progressive Evidence Enrichment / Extraction Abstention、GraphRepository abstraction、Fidelity-aware Evidence Authority、Simulator Validity Metadata、Heuristic Miner + Human Approval。 |
| v2.0 | 2026-09-10 | SAI = System Analysis with AI；目標系統名稱與規格名稱分離；新增 Agent-executable requirements、ADR/change control、DomainPack extension contract、Silicon Photonics vertical slice、requirement-to-test traceability 與 Agent execution templates。 |
| v2.1 | 2026-09-10 | Verification-in-the-Loop revision：Simulation/Experiment 從 core 抽象為 Evidence-Producing Action；新增 Least-Cost Sufficient Verification、Verification Planner、cognitive role I/O contracts、Evidence Source Router、Innovation Candidate dual-axis。 |
| v2.2 | 2026-09-10 | External Source Adapter / GitHub Connector revision：補齊 dataset ingress、provider-agnostic connectors、public/private repo policy、commit/ref provenance、snapshot/cache、rights/security 與 connector tests。 |
| v3.0 | 2026-09-10 | Executable Epistemic Architecture：Claim/Attestation、belief event replay、inference provenance、Actor/ACL、Job/Cost/Capability、intent-aware retrieval、run/extract 分離、6 core + N specialists、M0-M4 收斂。 |
| v3.1 | 2026-09-10 | Specification Closure Release：移除 v2.x/v3.0 殘留；補 AuthorityPolicy/TransitionPolicy/EvidenceBundle/Position/Critique/Plan/Review contracts、plausible outcome、deterministic SelectionPolicy、ReviewQueue capacity、secret/license/embedding/retraction/observability requirements；拆 M0a/M0b。 |
| v3.2 | 2026-09-10 | Release Candidate Closure：修 T-SPEC 自我一致性；補 EVI-003/SEC-001 條文與 EVI-001/EPI-002 tests；定義 INCOMPARABLE→human review、BenchmarkPolicy/OutcomeSpace/ValidationReport、DEPENDENCE_UNKNOWN 計數、high-stakes inverted retrieval；補 migration 010、normative registry/spec lint 與懸空 FK/actor references。 |
| **v3.3** | **2026-09-11** | **Implementation Readiness + User Surface Release**：統一 `TransitionPolicy.evaluate` 單一簽章與 `TransitionDecision` 回傳；新增 typed `Prediction` 與 side-effect-free `evaluate_hypothetical`，使 sufficiency 可確定性計算（VER-006）；新增 `Conflict` 型別使 `blocking_conflict_policy` 可實作（EPI-006）；統一 DomainPack tool 命名類別（`run_*`/`extract_*`/`inspect_*`/`validate_*`）與單一 ID scheme `DOM-SP-TOOL-xxx`；將 registry 完整性拆為 CI 檢查與人工稽核兩段；補 `independence_basis` 值域與 DEFERRED rationale、`estimate_cost_contract`、`EvidenceField.review_id`；補 Lumerical seat 與 ground-truth benchmark 兩項外部依賴風險。新增 **Frontend Error & Recovery Contract**：IngestionItem 七態推導、五類 FROZEN error taxonomy 與 GROWING reason_code、retry 政策、ACL-gated 兩層診斷揭露、raw-artifact-first 與 stage-level retry、NEEDS_REVIEW 併入單一 ReviewQueue、versioned MessageCatalog（禁止 LLM 生成使用者錯誤文字）、derived System Health（UX-001~007）。Requirement ↔ Test：**52 ↔ 52**。無架構方向變更。 |
| **v3.3-a1** | **2026-09-12** | **Maintainer amendment (P2-fix)**：裁決 SPEC-ISSUE-001 採 Reading B —— §26 T-SPEC-002 pass condition 改為「`statement_key` 唯一；每筆 entry 恰好引用一個合法 Requirement ID；一個 Requirement ID 可被多筆 entry 引用（涵蓋不同章節的相異 normative statements）」，消除與 §23.6 範例的自相矛盾。裁決 SPEC-ISSUE-003 採 Option 1 —— 新增 **SIM-003 / T-SIM-003**（typed ToolRegistry；禁止 `eval_script`-class 公開工具介面），SIM-003 配置至 M2。Requirement ↔ Test：**52 ↔ 52 → 53 ↔ 53**。無架構方向變更。 |
| **v3.3-a2** | **2026-09-12** | **Maintainer amendment (P3-fix / M0a sign-off patch)**：裁決 M0a Spec Coverage Audit 提出的五項未登錄 hard MUST。新增 **HEU-001 / T-HEU-001**（heuristic 核准治理，P16，配置 M7）、**SRC-003 / T-SRC-003**（PriorArtSearchRecord novelty 覆蓋率，配置 M3）、**VER-007 / T-VER-007**（P10 多目標 trade-off；單一 scalar FoM 不得單獨決定去留，配置 M4）、**OPS-004 / T-OPS-004**（跨儲存 unit of work 補償，需 fault-injection 驗證，配置 M1）。SPEC-ISSUE-008（fabrication sign-off）不新增 requirement，以 **SEC-002** 登錄並標為 DEFERRED（review_at = FIRST_FABRICATION_CAPABILITY）。SPEC-ISSUE-002：§23.2 namespace 表補 `GH-xxx`，並新增 `HEU-xxx`。Requirement ↔ Test：**53 ↔ 53 → 57 ↔ 57**。無架構方向變更。 |
| **v3.3-a3** | **2026-09-12** | **Maintainer amendment (M0a coverage fix)**：精確化 `T-LLM-002` pass condition —— fixed benchmark 必須將 debate mechanism 與 baseline/disabled condition 在相同案例上比較，使「groupthink reduction」之主張可被結果反駁而非僅被例示。未新增 Requirement/Test ID；Requirement ↔ Test 維持 **57 ↔ 57**。無架構方向變更。 |
| **v3.3-a4** | **2026-09-12** | **Maintainer amendment (M0a coverage fix, round 2)**：M0a Spec Coverage Audit 於 §9.1 發現第五條未登錄 hard MUST —— 「Disagreement metrics MUST be deterministic, versioned and defined over the declared OutcomeSpace」。新增 **VER-008 / T-VER-008**（不併入 VER-004：後者管 plausible outcome 來自declared OutcomeSpace，前者管排序所用 metric 本身的 determinism 與版本綁定），配置 M3。同時修正 §10.5 / §10.5.1 的 registry 歸屬：`fidelity.low_cannot_reject` 在 §6–§16 正文無對應敘述，其 prose home 為 §25.3；§10.5.1 的兩條 MUST（INCOMPARABLE 不得被強制排序、DomainPack MUST expose compare）補登。Requirement ↔ Test：**57 ↔ 57 → 58 ↔ 58**。無架構方向變更。 |
| **v3.3-a5** | **2026-09-12** | **Maintainer amendment (M0a occurrence inventory)**：將 §23.5 (2) coverage audit 自 section-level 計數推進到 occurrence-level。§6–§16 每一個明確 `MUST / MUST NOT / 必須 / 不得 / 不可` 出現處都必須被分類為 REGISTERED(statement_key)、RESTATEMENT_OF(statement_key) 或 NON_NORMATIVE_WITH_RATIONALE；不再允許以「已在別節註冊」把本節計為 0 而不指名對應 statement。新增四筆 registry statement 對應先前無主的義務：§7.2 round count 不得固定（LLM-002）、§7.6 重大 REJECT 需 independent critique path（SRC-002）、§7.6 無 provenance 舊推論不可用（LLM-001）、§8.2.1 TransitionDecision 決定性（EPI-005）。修正兩筆 section 歸屬：`extractor.backend_agnostic` 10.2 → 10.2.1、`hypothesis.admission.certificate_fields` 8.1 → 8。**未新增 Requirement/Test ID**；Requirement ↔ Test 維持 **58 ↔ 58**。無架構方向變更。 |
| **v3.3-a6** | **2026-09-13** | **Maintainer amendment (occurrence targets must be dischargeable)**：§23.2 要求 registry 的 Test IDs 必須真能 discharge 該 statement，而非僅存在。本修訂修正 v3.3-a5 留下的兩類缺口。（a）§14.3 兩筆誤判為 RESTATEMENT_OF 的義務改為真正義務：「solver budget 超標需 supervisor/human approval」不等於 COST-001 的 refuse/escalate（永久拒絕即可滿足舊條文），故 COST-001 與 T-COST-001 增列 approval path；「measurement/simulation 需 artifact reference」不等於 EPI-002（後者僅在 confirmed root cause 時成立，且屬 M4），故**新增 EVI-009 / T-EVI-009**，配置 M1，Requirement ↔ Test **58 ↔ 58 改為 59 ↔ 59**。（b）補齊四筆 pass condition 使新 statement 可 discharge：T-EPI-005 增列 identical inputs + policy_version 決定性、T-LLM-002 增列 per-case round count 須隨難度變化、T-OPS-002 增列 stakes / SLA / expiry、T-SRC-002 增列 critique path 獨立性與 external adjudication。T-LLM-001 另增列「無 provenance 舊推論不可作為 transition basis」（僅測 admission 不足）。無架構方向變更。 |
| **v3.3-a7** | **2026-09-13** | **Maintainer amendment (§7.6 第二個 trigger)**：§7.6 「重大 REJECT / irreversible action 必須經 independent critique path」是一條規則的兩個 trigger，而 v3.3-a6 只綁定了第一個 —— 不造成 belief transition 的 irreversible dispatch（版圖送件、MPW shuttle 訂位）因此無人管。**擴充既有 SRC-002 / T-SRC-002**，不新增 Requirement：irreversible Capability/action 在 independent critique 完成前 MUST NOT dispatch，且 human approval 不可取代 critique。Requirement ↔ Test 維持 **59 ↔ 59**。無架構方向變更。 |
