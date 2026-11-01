# G0 剩下的 Owner 決定(彙整)

日期:2026-10-30(2026-11-01 更新:`g0-reliability-authenticity-closure`)
分支:`g0-owner-boundary-closure`,之後 `g0-reliability-authenticity-closure`
狀態:這些都還**沒有**決定。程式沒有替 Owner 做任何一項。G0 未通過。

每一項寫:要決定什麼、目前預設、建議、細節文件。

## A. 金額上限

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| A1 | 建立 Owner 的登入角色,授予 `lab_brain_spend_admin` | 沒有成員:沒有人能宣告預算或單價 | 建立一個只給 Owner 的登入角色 | `docs/audit/g0-owner-boundary-closure-2026-10-28/spend-administration.md` §7.2 |
| A2 | 正式環境的預算、金額上限、每個模型的官方單價(來源、日期) | 沒有預算:所有遠端請求在送出前拒絕 | 有遠端模型才宣告 | 同上 §7.3 |
| A3 | ~~沒有預算時,本機端點要不要計量~~ | **已由 011v 關閉**:本機一律計量,沒有開關可以關 | — | `docs/audit/g0-reliability-authenticity-2026-11-01/design.md` §1 |
| A4 | 哪些本機模型是真的免費(`llm_spend_declare_free`,一個模型一筆,不能用 `*`) | 沒有宣告:本機模型的請求在送出前拒絕 | 只宣告確認過的本機模型(例如 Ollama 的某個模型) | 同上 |
| A6 | 免費宣告要不要過期、要不要綁定模型摘要(SPEC-ISSUE-017) | 不過期、不綁定 | 90 天過期並綁定伺服器回報的摘要 | `docs/spec_issues/SPEC-ISSUE-017-*.md` |
| A5 | 每個服務商是否遵守 `max_tokens`(含 thinking token);服務商端是否另設硬上限 | 假設遵守;沒有第二層 | 確認後再授權付費執行;服務商端另設上限 | `docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md` §3 |

## B. 篩檢後的前瞻驗證(011s)

| # | 決定 | 目前預設 | 建議 | 細節 |
|---|---|---|---|---|
| B1 | 審查 011s 的規則(擷取時間、血緣、種類、預先授權) | 已啟用(只會更嚴格) | 審查 §3 的規則 (h)–(l) | `docs/audit/g0-owner-boundary-closure-2026-10-28/prospective-evidence.md` |
| B2 | 用 migrator 執行 `lab-brain admin declare-capabilities` 登記 capability 種類 | 沒有登記:任何檢查都不能支持篩檢後假說(fail closed) | 審查宣告內容後登記 | 同上 §4、§9.5 |
| B3 | 誰可以預先授權驗證 | **011w 已加簽章**:要有 review authority 為此人登記的授權金鑰;沒有登記就不能授權 | 先限定少數人 | `docs/audit/g0-reliability-authenticity-2026-11-01/design.md` §2 |
| B6 | 誰是「驗證授權」的 review authority;要不要和 warrant authority 分開(SPEC-ISSUE-018) | 和 warrant 用同一個 `LAB_BRAIN_REVIEW_AUTHORITIES` 檔 | 分開:另一個人保管 | `docs/spec_issues/SPEC-ISSUE-018-*.md` |
| B7 | 授權的人可不可以同時是執行 episode 的人或假說作者 | 可以(還沒限制) | 比照 warrant:不可以 | 同上 |
| B8 | 授權金鑰的換鑰週期與撤銷流程 | 沒有週期 | 定期換鑰;懷疑外洩時,撤銷日期設在外洩之前 | 同上 |
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
| E4 | 哪些環境差異算「不同的實驗」(SPEC-ISSUE-019) | 任何差異都算(最嚴格) | 維持最嚴格,除非評估者寫明理由 | `docs/spec_issues/SPEC-ISSUE-019-*.md` |
| E5 | 模型摘要只有「宣告」、伺服器量不到時,可不可以用在驗收執行 | 可以,但紀錄寫 `declared` | 驗收執行不可以;只用會回報摘要的本機伺服器 | 同上 |

## F. Repo

| # | 決定 | 目前預設 | 建議 |
|---|---|---|---|
| F1 | `main` 的 branch rule(必要 check、禁止 force push、Code Owner 審查) | 沒有設定 | 設定 |
| F2 | 是否合併本分支 | 不合併,等 Independent Chief Auditor 審查 | 審查後由 Owner 決定 |
| F4 | 三條分支的整合順序(G0、Discovery、SAI 3.5) | 都不整合 | G0 分支審查通過後先整合;Discovery 之後;SAI 3.5 只是候選 |
| F5 | SAI 3.5 候選要不要放進 SAI 3.4 整合線的允許清單(OD-10) | 候選分支有一個獨立提交擴充清單 | 審查 SAI 3.5 後再決定;不同意就丟掉那個提交 |
| F3 | G0 是否通過 | 未通過 | 只能由獨立審查決定 |
