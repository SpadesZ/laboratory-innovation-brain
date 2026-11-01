# G0 剩下的 Owner 決定(彙整)

日期:2026-10-30
分支:`g0-owner-boundary-closure`
狀態:這些都還**沒有**決定。程式沒有替 Owner 做任何一項。G0 未通過。

每一項寫:要決定什麼、目前預設、建議、細節文件。

## A. 金額上限

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| A1 | 建立 Owner 的登入角色,授予 `lab_brain_spend_admin` | 沒有成員:沒有人能宣告預算或單價 | 建立一個只給 Owner 的登入角色 | `docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md` §7.2 |
| A2 | 正式環境的預算、金額上限、每個模型的官方單價(來源、日期) | 沒有預算:所有遠端請求在送出前拒絕 | 有遠端模型才宣告 | 同上 §7.3 |
| A3 | 沒有預算時,本機端點要不要計量(`LAB_BRAIN_LLM_SPEND_METER_LOCAL=1`) | 不計量(本機代理可能轉送到付費服務) | 開啟,並宣告真正免費的本機模型 | 同上 §3.6 |
| A4 | 哪些本機端點是真的免費(`llm_spend_declare_free`) | 沒有宣告 | 只宣告確認過的本機模型(例如 Ollama) | 同上 §7.3 |
| A5 | 每個服務商是否遵守 `max_tokens`(含 thinking token);服務商端是否另設硬上限 | 假設遵守;沒有第二層 | 確認後再授權付費執行;服務商端另設上限 | `docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md` §3 |

## B. 篩檢後的前瞻驗證(011s)

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| B1 | 審查 011s 的規則(擷取時間、血緣、種類、預先授權) | 已啟用(只會更嚴格) | 審查 §3 的規則 (h)–(l) | `docs/audit/g0-owner-boundary-closure-2026-10-28/prospective-evidence.md` |
| B2 | 用 migrator 執行 `lab-brain admin declare-capabilities` 登記 capability 種類 | 沒有登記:任何檢查都不能支持篩檢後假說(fail closed) | 審查宣告內容後登記 | 同上 §4、§9.5 |
| B3 | 誰可以預先授權驗證(必須是專案中的 HUMAN 成員);要不要加簽章 | 資料庫只檢查成員身分,沒有簽章 | 先限定少數人;之後加 Ed25519 簽章 | 同上 §9.2 |
| B4 | 「模擬可以讀設計檔」這個判斷是否接受 | 接受 | 接受,但報告中標明 | 同上 §9.4 |
| B5 | 產品要不要提供網頁介面來建立授權、上傳量測 | 只有 Python API | 等 B1–B3 決定後再做 | 同上 §9.5 |

## C. 互動簽章金鑰

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| C1 | 誰產生、保管網頁層簽章私鑰;放在哪裡 | 沒有金鑰:網頁執行標示為未驗證 | `lab-brain interaction-key generate` 在 repo 外、權限 600 | `docs/audit/g0-owner-boundary-closure-2026-10-28/key-lifecycle.md` §4 |
| C2 | 換鑰週期、撤銷流程、誰能改釘選檔 | 沒有週期 | 定期換鑰;撤銷後一定重新啟動網頁層 | 同上 §3、§8 |

## D. A12(直接 SQL 修改角色或成員)

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| D1 | 是否接受「偵測但不阻止」作為目前狀態 | 011u 留下雜湊鏈紀錄;不阻止 | 暫時接受,並做 D2 | `docs/audit/g0-owner-boundary-closure-2026-10-28/a12-boundary.md` §8 |
| D2 | 做哪些部署控制(migrator 帳密分開、pgaudit、WAL 封存、雙人規則) | 都沒有做 | 至少分開 migrator 帳密並封存日誌 | 同上 §7 |
| D3 | 鏈頭(`lab-brain admin account-audit` 印出)存在資料庫外的哪裡、多久比對一次 | 沒有保存 | 每天保存到另一台機器 | 同上 §8.3 |
| D4 | 操作者命令列的成員變更要不要也寫帳號事件 | 不寫(會列為「沒有事件」) | 要寫 | 同上 §8.4 |

## E. 評估

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| E1 | 指派獨立評估者(不能是實作者),封存盲測集 | 沒有 | 指派 | `docs/evaluation/G0-blind-evaluation-protocol.zh-TW.md` §6 |
| E2 | 核准本機模型、協定值(指標、門檻、污染政策、seed) | 沒有 | 依協定核准 | 同上 |
| E3 | 是否授權付費的真實 LLM 評估(建議上限 USD 25) | 不授權 | 先做零成本本機盲測 | `docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md` §7 |

## F. Repo

| # | 決定 | 目前預設 | 建議 |
|---|---|---|---|
| F1 | `main` 的 branch rule(必要 check、禁止 force push、Code Owner 審查) | 沒有設定 | 設定 |
| F2 | 是否合併本分支 | 不合併,等 Independent Chief Auditor 審查 | 審查後由 Owner 決定 |
| F3 | G0 是否通過 | 未通過 | 只能由獨立審查決定 |
