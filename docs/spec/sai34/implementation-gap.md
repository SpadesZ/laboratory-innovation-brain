# SAI 3.4 Candidate — 實作差距與證據邊界

版本：`3.4.0-candidate.1`。2026-10-20 以 GitHub API、`git fetch` 與 source inspection 核對。
主評估基準：`f3fadf6eaa7676d27b0129beeb40239cba2e1723`。
GitHub `main`：`d0ab848646dd7250fc4eadb1a37600860685e6ca`，未包含下表所有較新功能。
本候選疊在未合併的整合分支上；不能將整合分支實作寫成 main 已發布或部署已更新。

`READY_FOR_REAL_RESEARCH = false`

## 1. 狀態詞

- **IMPLEMENTED**：基準有具體實作與可定位測試；適用的執行證據仍要看指定 SHA/profile。
- **PARTIAL**：有可重用底層，但尚不滿足完整產品能力。
- **SPECIFIED**：本候選定義契約，沒有對應新增 runtime。
- **DEFERRED**：後續階段，未承諾本 slice 或當前里程碑完成。
- **REQUIRES_LICENSE**：真實產品/站點/授權環境才能接受的外部 gate；不是已實作的同義詞。

實作進度與環境 gate 是兩軸。尚未寫的 provider 不能只標 REQUIRES_LICENSE 來暗示「只差 license」。

## 2. Source-to-claim 矩陣

下表的相對連結都指向本分支凍結基準中的檔案；證據是軟體契約與既有稽核，不是新跑的物理實驗。

| 能力 | 實況 | 檔案/測試證據 | 仍缺什麼 |
|---|---|---|---|
| provider-independent simulation | IMPLEMENTED | [simulation.py](../../../src/lab_brain/tools/simulation.py)、[契約測試](../../../tests/contract/test_simulation_contract.py)：SimulationRequest/BackendExecution/SimulationBackend、manifest/validity 檢查 | 真實 provider、站點相容性；此 seam 不產生首次模型 |
| typed tool registry/dispatcher | IMPLEMENTED | [contracts.py](../../../src/lab_brain/tools/contracts.py)、[dispatch.py](../../../src/lab_brain/tools/dispatch.py)、[dispatch 測試](../../../tests/contract/test_dispatch_seam.py) | 新建構 workflow 及其封閉 operation 集合尚未實作 |
| Job/Run、resume、資源與預算 | IMPLEMENTED（現有邊界） | [execution.py](../../../src/lab_brain/tools/execution.py)、[resources.py](../../../src/lab_brain/tools/resources.py)、[Job 測試](../../../tests/contract/test_job_lifecycle.py)、[需求綁定](../../../tests/contract/test_resource_demand_binding.py)、[持久化測試](../../../tests/integration/test_jobs_runs_postgres.py) | 真實 vendor checkout/孤兒 process 對帳、多產品 entitlement、worker fencing 的產品整合與 licensed 故障注入 |
| CHARGE mock | IMPLEMENTED（deterministic mock） | [mock.py](../../../src/lab_brain/tool_providers/lumerical/mock.py)、[mock_vertical.py](../../../src/lab_brain/tool_providers/lumerical/mock_vertical.py) | RC/fixture arithmetic 只證明資料流；沒有執行 Lumerical，沒有器件精度證據 |
| CHARGE 抽取與 validity | PARTIAL（可用底層） | [extractors.py](../../../src/lab_brain/domains/silicon_photonics/extractors.py)、[backend_validity.py](../../../src/lab_brain/domains/silicon_photonics/backend_validity.py)、[共同抽取契約](../../../tests/domains/test_shared_extractor_contract.py) | `convergence_status` 欄位、趨勢 validator 不等於完整空間/步階收斂、uncertainty 或物理有效性 |
| product research workflow | PARTIAL（目前診斷 vertical） | [product.py](../../../src/lab_brain/domains/silicon_photonics/product.py)、[product-vertical.md](../../implementation/product-vertical.md) | 未接 licensed simulator 時 simulation capability 明列 UNAVAILABLE；不會拿 mock 在正式研究頂替 |
| 外部來源/文獻 | PARTIAL | [GitHub connector](../../../src/lab_brain/tool_providers/github/connector.py)、[literature corpus adapter](../../../src/lab_brain/tool_providers/literature/corpus.py)、[M5 readiness](../../implementation/M5-readiness.md) | 授權 Ansys example discovery/active-content 防線、field-level 參數來源、build/calibration/holdout family 隔離的完整產品流程 |
| 自主 PhysicalModelSpec / builder | SPECIFIED | [本候選 §3–4](../SAI_3.4_Candidate.md#3-型別化物理模型契約) | source tree 無本候選的完整 geometry/material/doping/boundary 模型 schema、確定性 compiler、首次建構與 vendor readback |
| licensed provider/worker | SPECIFIED；外部 gate REQUIRES_LICENSE | [provider slot](../../../src/lab_brain/tool_providers/lumerical/__init__.py) 明示 mock only；[M4 §11](../../implementation/M4-readiness.md) | 真實 SDK/session adapter、安裝/entitlement、worker sandbox、首次建構、求解及封存重播均未證明 |
| convergence / sensitivity / uncertainty | SPECIFIED（完整方案） | [驗收 G3–G5](acceptance.md#2-九道-gate)；既有 [validators.py](../../../src/lab_brain/domains/silicon_photonics/validators.py) 只是趨勢規則 | 獨立數值研究、已核准 thresholds、uncertainty budget、器件驗證與 failure matrix |
| autonomous bounded refinement | SPECIFIED | [候選 §6](../SAI_3.4_Candidate.md#6-自動細化與停止) | immutable patch 分類、assumption policy、數值/校準/科學變更分支及受限 loop |
| evidence/event provenance | IMPLEMENTED（現有邊界） | [M1 readiness](../../implementation/M1-readiness.md)、[研究完整性稽核](../../audit/research-integrity-2026-10-20/REPORT.zh-TW.md)、`012q/012r/012s` | 新模型 lineage 與 validation refs 的 domain extension；不准回填捏造既有歷史 |
| Causal Warrant Gate V1.1 | IMPLEMENTED 於整合候選；科學範圍有限 | [warrant.py](../../../src/lab_brain/core/warrant.py)、[reviewer identity](../../../src/lab_brain/security/reviewer_identity.py)、[V1.1 契約](../../implementation/causal-warrant-gate-v1.1.md) | 擴大模型族/多原因/DISCRIMINATION 等仍待 Owner；驗證結果不能自行鑄造 warrant |
| 專案、帳號與分級 | IMPLEMENTED 於整合候選 | [帳號安全稽核](../../audit/account-security-integration-2026-10-20/REPORT.zh-TW.md)、[路由矩陣](../../../tests/security/test_web_access_matrix_postgres.py) | 新 worker 與 evaluator identity 的 project-scoped 接線；A3/A12 等治理選擇仍未決 |
| 雙語介面 | PARTIAL（既有介面存在） | [web-workspace-v2.md](../../implementation/web-workspace-v2.md)、[產品稽核](../../audit/product-2026-10-15/REPORT.zh-TW.md) | 六層模型驗證 UI、validation packet 與兩語一致性尚未實作 |
| MODE/FDTD/INTERCONNECT/multiphysics | DEFERRED；真實部分 REQUIRES_LICENSE | 3.3 §10/§18/§26 與現有 M6；目錄樹是目標，不是實作證據 | 各產品 schema/compiler/provider/驗收；不能從 CHARGE mock 外推 |
| 外部 coding-agent-free autonomous modeling | SPECIFIED | [候選 ASM-001](../SAI_3.4_Candidate.md#1-必達產品目標與自主性邊界) | 目前不能證明首次建模完整鏈；G9 需真實新問題、乾淨部署與封鎖開發 agent |

## 3. 近期稽核的效力與限制

- 帳號安全整合稽核修正了降級後的讀取、project scope、ADMIN 監督紀錄與角色管理。
  源碼與報告可定位；這些安全證據不能替代新 worker 的隔離測試。
- V1.1 的 domain/signature/confirmation 驗證是因果保護的一部分；仍需核准的科學 declarations。
  不擅自啟用 `sp-declarations-candidate`（`7d2cd09605db5c1097b5384688d69ae294510ded`）。
- M0a–M3 原簽核不重開；M2 mock contract 的完成不補掉 M4 `TST-001` 的 licensed replay。
  現有 VS-SP-001 的 deterministic 診斷 benchmark 不是首次物理建模準確度 benchmark。
- 已 live 核對基準 CI：[39425497592](https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/39425497592)
  對應 `f3fadf6eaa7676d27b0129beeb40239cba2e1723`，四工作成功。這是基準軟體證據，不能冒充本次分支的 CI。

本次分支的檢查與最終 SHA 由 commit 和其 GitHub Actions run 識別；交付報告附連結。
沒有在本次執行新的 runtime 功能、授權模擬、正式資料庫操作或部署。
