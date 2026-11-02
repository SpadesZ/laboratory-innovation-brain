# SAI 3.5 Discovery Candidate 報告

日期：2026-11-01
版本：`3.5.0-discovery-candidate.1`
分支：`sai-3.5-discovery-candidate`
起點：`integration-integrity-accounts` @ `a38ad63`
狀態：**候選。未啟用。未整合。** 不改 SAI 3.4，也不改 G0–G9。

`READY_FOR_REAL_RESEARCH = false`。G0 未通過。沒有任何 G-D 等級被評估。

## 1. 寫了什麼

- 主規格：[SAI_3.5_Discovery_Candidate.md](../SAI_3.5_Discovery_Candidate.md)（英文）。
  46 條需求，編號 `D-001` 到 `D-046`。
- 產品願景：一個自主的 AI 科學家。
  它能發現研究問題，提出真正新穎、可否證的物理假說。
  研究失敗時，它能重新框定問題。它的科學發現要被獨立驗證。
  這是目標，不是現況。
- 端到端架構：文獻搜尋、從零建模。
  設定幾何、材料、摻雜、網格、求解器。
  由內部 worker 執行有授權的 Lumerical CHARGE/MODE/FDTD/INTERCONNECT。
  執行要有 license、要有 Owner 授權、要控管成本。
  還有參數掃描、收斂研究、有界的模型細化、獨立物理驗證、中英雙語報告。
- 硬性要求（D-006）：正式研究不能依賴 Codex、Claude Code 或任何外部 coding agent。
  這條有可測的驗收檢查。
- Discovery Loop：
  - 問題發現。
  - 用「可區分的機制類別」計數，不算假說數量。
  - 異常有明確狀態。
  - 研究失敗時的重新框定只能附加。不能刪除失敗紀錄。
    也不能把失敗的假說變成支持。
  - 依「每單位成本能區分多少機制」選實驗。
- 發現與驗證分開：發現只提出，驗證獨立判定。
  驗證要事先登記。不能用既有的證據支持自己（和 G0 的 011p/011s 一致）。
  只有 Causal Warrant Gate 能給 CONFIRMED。
- 系統要能停下來。`INSUFFICIENT_VALIDATION` 或 `STOPPED` 是治理成功，不是失敗。
- 獨立的 G-D 驗收（G-D0 到 G-D4）。
  G0–G9 全部完成，也**不代表**能做出發現。
  G-D 只能由獨立評估者判定通過。
- 三組比較：(A) 單一 LLM、(B) 現有 LIB、(C) LIB 加 Discovery。
  同模型、同預算、同工具、同時間、同 seed。盲評。測試集要先封存。
  五個指標：真機制發現率、可區分的多樣性、實驗效率、錯誤發現、可重現性。
  先做零成本階段，再談付費。
- 附屬文件在 `docs/spec/sai35/`：
  驗收、比較協定、架構、實作現況、路線圖、Owner 決定、
  規範登錄（yaml）、對照表、檢查程式。
- ADR-0016：提出 SAI 3.5，但不啟用。說明為什麼分支不整合。
- CI：新增一步 `python docs/spec/sai35/check_candidate.py --self-test`。
  SAI 3.4 邊界那一步改成透過提案 A' 的包裝程式執行；SAI 3.4 的檢查程式本身沒有改。

## 2. 沒有做的事

- 沒有寫任何執行程式、migration、測試或相依套件。
- 沒有啟用 SAI 3.5。`ACTIVE_SPEC.yaml` 一個位元組都沒改。
- 沒有改 SAI 3.3、SAI 3.4 的規範文字、milestones 或既有 registry。
  沒有例外。之前有一個提交（`9d44198`）改了 SAI 3.4 的允許清單，已經用 revert 還原。
- 沒有合併或 cherry-pick 其他分支。
- 沒有執行任何 G-D 評估、盲測、真實 LLM、付費 API 或 Lumerical。
- 沒有任何科學結果。檢查程式通過，只代表文件結構正確。

## 3. 已知問題

- SAI 3.4 的 `check_activation.py` 只允許固定的文件清單。新檔案會讓它失敗。
  之前的做法是改 SAI 3.4 的允許清單（`9d44198`），已經還原。
  現在的**提案 A'**（待 Owner 決定 OD-10）：`candidate-paths.txt` 列出 SAI 3.5 新增的每個路徑。
  `check_sai34_boundary_without_candidate.py` 在暫時的 worktree 刪掉這些路徑，
  再執行**未修改的** SAI 3.4 檢查。路徑若碰到受保護檔案、程式、migration、測試或 scripts，就拒絕。
  Owner 也可以選 (B) 核准修改允許清單，或 (C) SAI 3.5 不放在整合線上。
- 主規格用英文寫。SAI 3.3/3.4 主要是繁體中文。要不要翻譯是 OD-13。
- 前瞻證據規則（011p/011s）和評估工具只在 G0 分支（`58c68be`）。
  它們還沒整合進這條線。
- `discovery-loop-offline` 分支（`118a4ac`）有離線 Discovery Loop v0 原型與合成基準測試。
  沒有整合，也沒有獨立審查。它的結果只是合成世界上的工程證據，不是 G-D 判定。
  B0 是固定規則的替身，**不是** LLM；比較協定的 A 組（單一 LLM）還沒有實作。

## 4. 需要 Owner 決定

全部尚未決定。完整清單在 [decisions-and-review.md](decisions-and-review.md)。

| 編號 | 要決定什麼 | 建議 |
|---|---|---|
| OD-01 | 是否接受此候選供審查 | 審查；G-D0 凍結前保持未啟用 |
| OD-02 | 指派獨立評估者與標籤保管人 | 指派；不能是實作者 |
| OD-03 | 協定數值（主要指標、最小效果、權重、樣本數） | 先用開發用的世界做小型試跑 |
| OD-04 | 零成本階段用的本機模型 | 一個固定版本的開源本機模型，宣告為免費 |
| OD-05 | 是否授權付費模型階段 | 零成本結果出來後再決定，並設上限 |
| OD-06 | 文獻案例的來源與權利 | 由評估者挑選，逐一確認權利 |
| OD-07 | 有授權的模擬（G-D3） | 等 SAI 3.4 P-LICENSED |
| OD-08 | 實體實驗與發表（G-D4） | 每次實驗、每次發表分別授權 |
| OD-09 | 三條分支的整合順序 | G0 分支審查後先整合，再處理 Discovery |
| OD-10 | SAI 3.5 檔案如何放在 SAI 3.4 整合線上，而不改 SAI 3.4 | 提案 A'（不含候選檔的樹上跑未修改的 SAI 3.4 檢查） |
| OD-11 | 宣稱「新穎」前要搜尋多廣 | 至少文獻和專利，要有覆蓋紀錄 |
| OD-12 | 重新框定的次數上限 | 合成階段每個問題 2 次 |
| OD-13 | 規範文字的語言 | 審查用英文；啟用前做繁中版 |
