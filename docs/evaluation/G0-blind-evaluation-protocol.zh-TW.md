# G0 盲測評估協定(零成本、可獨立重現)

狀態:協定與工具已就緒。**還沒有任何真正的盲測執行**,也沒有獨立評估者。
本協定產生的分數是「真實 LLM(本機開源模型)在封存案例上的研究表現」證據,
**不是**物理驗證,也**不是** G0 通過。G0 是否通過由 Independent Chief Auditor 與 Owner 決定。

## 1. 為什麼是零成本

- 模型必須在評估者自己的機器上執行(例如 Ollama 上的開源權重模型)。不呼叫任何付費 API。
- 環境紀錄工具(`scripts/g0_eval_environment.py`)會**拒絕**不是本機的模型端點;
  要用遠端付費模型,必須另外取得 Owner 授權,而且紀錄會寫明「不是零成本」。
- 本機端點也要由 Owner 在費用管理中宣告為「真的免費」(見 `docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md`);
  沒有宣告的本機端點視為可能付費(例如轉送到付費服務的本機代理)。
- 不使用 Lumerical 或任何授權求解器;需要模擬的檢查在報告中標 NOT_PERFORMED。

## 2. 角色與分隔

| 角色 | 做什麼 | 不可以 |
|---|---|---|
| Owner | 授權評估、指定獨立評估者、核准協定值(指標、門檻、污染政策、seed)、最後簽核 | 把案例或真值交給實作者 |
| 獨立評估者 | 撰寫案例與真值;真值放 repo 外;封存;檢查污染;凍結;執行生成端;揭露並評分 | 在評分前把案例內容或真值告訴實作者;凍結後修改任何東西 |
| 實作者(本系統開發者) | 不參與。只在評分後收到結果 | 讀取真值、看到案例、依結果調整後重跑 |

評估者與實作者不能是同一人。這一點軟體無法驗證,是 Owner 的責任。

## 3. 步驟(每一步都有指令與可檢查的產物)

前提:評估者 clone 本 repo 的**指定 commit**,建立新的 PostgreSQL 資料庫並執行 `scripts/migrate.py`,
在本機啟動模型。

1. **記錄環境**(凍結前):
   ```
   python scripts/g0_eval_environment.py capture --model-endpoint http://127.0.0.1:11434/v1 \
       --model-id <模型名稱> --model-digest <本機模型內容摘要> --out environment.json
   ```
   會拒絕有未提交修改的工作區,與不是本機的模型。印出的 `environment_sha256` 寫進評估者的紀錄。
2. **撰寫並封存真值**(真值檔放 repo 外):`scripts/g0_eval_seal.py`。公開的只有 commitments。
3. **檢查污染**:`scripts/g0_eval_check_contamination.py`,比對已曝光的 `benchmarks/g0_screening` 案例與任何開發集。
4. **凍結**:`scripts/g0_eval_freeze.py`。凍結協定、評分程式碼 hash、所有輸入檔 hash、案例清單、承諾、污染結果。
5. **盲跑生成端**:`lab_brain.evaluation.runner.run_blind`。
   - 先確認 manifest 雜湊正確、生成端套件就是凍結的那一份,否則什麼都不跑。
   - 每個凍結案例都有一筆輸出;執行失敗記為 CRASHED,留在分母。
   - 輸出綁定 manifest 雜湊與環境雜湊。
   - 正式產品不儲存提示原文,所以本機真實模型的執行會記錄 `prompts_captured: false`;
     這時「輸入洩漏」檢查是 **NOT VERIFIED**,不是通過。生成端從頭到尾沒有拿到真值,這是由封存與套件載入器保證。
6. **重現檢查**(評分前):用同一份 `environment.json` 執行 `g0_eval_environment.py verify`;有任何差異就不評分。
7. **揭露並評分**:`scripts/g0_eval_score.py`(scorer 2.1.0 以上)。揭露的真值必須符合凍結的承諾。
   報告每個指標的 n、k、比例、Wilson 95% 區間、固定 seed 的 bootstrap 區間,以及把排除案例算失敗的保守數字。
8. **獨立審查**:G0-S 的「科學有用性」需要具領域資格、獨立於產生者的審查者逐項判斷;分數只是必要條件。

## 4. 別人怎麼重現

另一位評估者拿到:commit SHA、`environment.json`、manifest、commitments、生成端套件、輸出、
(評分後)封存的真值。
- 用 `verify` 確認環境相同(同 commit、同 migration、同套件版本、同評分程式、同模型摘要)。
- 重新評分必須得到相同數字(評分是確定性的;bootstrap 用固定 seed)。
- 重新執行生成端:本機模型在 temperature 0 下仍可能因硬體/版本不同而輸出不同;
  這種差異要報告,不能隱藏。分數的可重現性指的是「同一份輸出 → 同一個分數」。

## 5. 結果怎麼讀

| 可以說 | 不可以說 |
|---|---|
| 在這些封存案例上,這個本機模型 + 這版系統的指標是多少 | G0 通過 |
| 治理不變量(假確認、不可採用支持、洩漏)在真實模型下是否為 0 | 元件或製程已被物理驗證 |
| 篩檢前/篩檢後發現的比例 | 結果適用於其他模型或付費模型 |

## 6. 需要 Owner 決定

1. 指定獨立評估者(不是實作者)。
2. 核准協定值(`benchmarks/g0_evaluation/protocol.example.json` 的複本)。
3. 核准使用的本機模型,並在費用管理中宣告該本機端點為免費。
4. 是否另外授權付費模型(會離開零成本協定,需金額上限)。
