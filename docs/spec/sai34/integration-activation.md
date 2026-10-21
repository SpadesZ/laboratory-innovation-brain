# SAI 3.4 — 整合、授權與變更影響紀錄

Profile：`3.4.0-phased.1`｜日期：2026-10-21。
本紀錄是文件／治理整合，不是 runtime 交付或科學接受。
`READY_FOR_REAL_RESEARCH = false`

## 1. Owner 授權收據

授權 ID：`OWNER-SAI34-20261021-INTEGRATION`。
來源：本次 Human Owner 的「SiPh Lab — SAI 3.4 Integration & Phased Activation」使用者訊息。
原話包括：

> The Human Owner authorizes documentation integration and the start of phased SAI 3.4 activation procedures.

> Integrate into `integration-integrity-accounts` only if the verified changes are strictly authorized documentation/governance changes and no protected runtime behavior is altered. Otherwise stop at an Owner Gate.

已授權：批准 Candidate.2 的文件整合、分期啟用準備，使 G0 可靠度工作與授權前自主建模
準備可依本 profile 各自開始。整合只在隔離分支驗證為文件／治理 diff 後進行。
這不是額外授權本次實作 runtime；本次只有文件、對照、檢查與 Git 整合。

未授權／未接受：合併 main、部署、正式資料操作、付費 API、licensed simulations、SP 1.1.0、
關閉 D-01–D-08、核准任何未定物理精度/樣本/成功率、特定 license/資料權利、A3/A9/A12
安全處置或將 readiness 設為 true。來源、actor、egress、預算與不可逆動作仍適用原 gate。
本收據補充前一輪「只修文件」授權；不是追溯改寫 Candidate.2 當時的批准狀態。

## 2. 初始祖先與未合併狀態

| 角色 | 分支／SHA | 檢查與效力 |
|---|---|---|
| 整合目標基準 | `integration-integrity-accounts`／`f3fadf6eaa7676d27b0129beeb40239cba2e1723` | 取自 fetch＋GitHub branches API；是本次 protected-tree 比較基準 |
| 已批准來源 | `docs/sai-3.4-autonomous-modeling-candidate`／`eaea2c03e24b968c62ef9d60e7032f279f5e136c` | 相對目標為 0/2 commits；共同祖先即 f3fadf6；12 個文件／CI 檔，無 runtime/test 差異 |
| 隔離整合 | `docs/sai34-phased-integration`，候選合併點 `e430bc142ad8183331118e1ac1e27098fa4d8aea` | 從目標建獨立 worktree，`--no-ff` 合併批准來源；ort 無衝突，不曾以 ours/theirs 覆蓋檔案 |
| Agent A 隔離來源 | `pre-lumerical-acceptance`／`567dee323e515eb16c697ebbb9dcebe6f4f096da` | 自 f3fadf6 分出，13 個未合併提交；初始相關 worktrees 乾淨；本次只讀、不合併 |
| SP 1.1.0 候選 | `sp-declarations-candidate`／`7d2cd09605db5c1097b5384688d69ae294510ded` | 未整入、未啟用 |
| main | `d0ab848646dd7250fc4eadb1a37600860685e6ca` | 本次不更新；不能把 main 到 f3fadf6 的既有程式堆疊誤算為本次差異 |

新提交與 CI 的精確 SHA 由 Git history 與 final delivery 列出。隔離驗證通過後只發布同一 SHA，
不另改內容。發布前重新核對 remote target；若它前進，重新檢視祖先、差異與衝突，不 force push。
任何不在 allowlist 的 source、tests、scripts、migration、artifact/evidence 改動都觸發 Owner Gate。

## 3. 與 Agent A 的協調邊界

本次沒有訊息派工、啟動模型、重跑其 real-model tests 或變更其 worktree。
讀取 Agent A 的 report 與 branch diff，只用來確認未合併範圍與證據邊界。
其 report 明說真實模型路徑仍不穩，沒有宣稱 LLM 研究流程已驗收；本次不將它改成 G0 PASS。
其 live-model/API 使用是該分支先前的授權與歷史證據，不是本次付費呼叫。

| 邊界 | 現在的處理 | 日後如另獲准整合 Agent A |
|---|---|---|
| `src/`、`tests/`、`scripts/mutation_battery.py` | 完整保留目標 f3fadf6；不取 Agent A 版本 | 以當時最新整合線為基準，由 Agent A/指定整合者獨立審查與跑適用回歸 |
| `docs/audit/pre-lumerical-acceptance-2026-10-21/` | 報告、截圖、provenance、live run 與 mutation 證據全留在原分支 | 保留每個原始檔/hash、成功/失敗與 source SHA，不挑成功紀錄冒充整體接受 |
| `IMPLEMENTATION_STATUS.md` | 加入手寫架構狀態；舊 generated blocks 不變 | 這是目前唯一共同修改檔；合併時保留雙方手寫紀錄，以合併後完整測試重新產生 inventory，不能整檔覆蓋 |
| G0 規格與實作 | 本 profile 定義接受條件；Agent A 的程式與測試未被接受/合併 | 功能/可靠度、認證、科學可用性、雙語內容/匯出、provenance 五類條件逐項評估，mock 不補 genuine-LLM 缺口 |
| API、schema、warrant、帳號語意 | 本次沒有改動 | 任何改動先說明 scope、P0/Owner 決策、相依與回歸；不能以文件啟用自動放行 |

Agent A 的 head 可以因其合法工作繼續前進；本次不 reset、不覆蓋、不刪分支，也不把新 head
假定為已審。新工作的出現不應被本文件的歷史 snapshot 否定。

## 4. 正式 activation mapping 與相容

| 項目 | 已準備的對照 | 仍未完成的事 |
|---|---|---|
| 架構入口 | `SAI_3.4.md`＋`ACTIVE_SPEC.yaml`，明定 scope 與生效條件 | 完整 runtime profile 遷移 |
| 歷史 3.3 | 原 60 條 requirement/§26 test bindings、113 個 registry statements、M0a–M8 完整繼承；三個基準檔案 hash 固定 | 不重開 hard-lock、不改舊簽核或補造 Run/決策史 |
| ASM-001–018 | 每條保持 candidate key/section/pass condition/T-ASM-*；逐條列 legacy requirement/test 相依、P-G0/P-MODEL、後期 gates、Owner 決策與 ADR | 全部 `SPECIFIED`，沒有新增已執行的 runtime tests |
| 規範 registry | `activation.yaml` 作正式分期架構 registry；candidate registry 保持原始 bytes | 不把它冒充舊 parser 已接受 ASM namespace；P-FULL-RUNTIME 具名 DEFERRED |
| Milestones | P0-BASIS、獨立 P-G0/P-MODEL、P-LICENSED、P-PHYSICAL、P-PORTABILITY、P-FULL-RUNTIME | 原 `docs/milestones.yaml` 簽核與執行 ratchet 保留；新階段沒有因此被簽 DONE |
| ADRs | ADR-0014 接受本次限範圍架構整合；ADR-0013 固定作候選歷史 | D-01–D-08、A3/A9/A12 仍 OPEN |
| Test obligations | legacy 原測試照跑，candidate/activation 文件 checker 各自 self-test，CI 保留 full quality＋postgres ratchet | G0 genuine LLM、licensed/physical、跨 worker/站點與新 runtime coverage 不在本次執行 |

每條 ASM 的 deferral 有理由、`review_at: 2026-11-20`、具名 scope 及 milestone trigger；
review date 到期不視為批准。既有來源/條件/authority/immutability/ACL/budget/ReviewQueue
仍是前置約束；planned tests 不計入 60 條既有測試的完成數或執行覆蓋。

## 5. 完成的啟用前置條件與驗證方式

- 授權來源、批准 candidate SHA、整合基準、Agent A 隔離點已記錄。
- 60 條歷史＋18 條 ASM 的 requirements/test/registry/milestone/ADR 對照與 deferrals 已準備。
- G0 與 P-MODEL 的起跑相依分開；後期 license、物理、部署、runtime conformance gate 具名保留。
- 九份批准契約/檢查文件與三份 legacy 基準檔案 SHA-256 固定；candidate 原狀態作歷史而不被追溯改寫。
- 完整 CI 成功與發布到整合線，是 P0-BASIS 生效的最後兩個可機器核對條件；以 final SHA/Actions run/remote ref 為證據，不由本段預先宣稱。

離線檢查：

```powershell
python docs/spec/sai34/check_candidate.py --self-test
python docs/spec/sai34/check_activation.py --self-test
python -m pytest tests/spec -q
python scripts/rebuild_obligation_inventory.py --check
python scripts/update_status.py --check --requirements-only
git diff --check
```

CI 在同 SHA 另跑 ruff/format/mypy/full suite、PostgreSQL migrations＋full suite、
executed-coverage ratchet 及 status check。沒有改 marker、放寬測試或重新簽里程碑。

## 6. 批判性自我審查

| 風險／矛盾 | 本次處理 | 接受邊界 |
|---|---|---|
| 文件啟用被讀成科學就緒 | architecture/executable/acceptance 分開；全部新實作仍 SPECIFIED，readiness false | G0、G1–G9 未因 CI 而 PASS |
| 規格出現兩個互相競爭的 truth source | 3.4 是正式架構入口；3.3 是完整繼承的歷史/執行 profile；候選只保留當時狀態與固定契約正文 | 不是 newer-looking override；直接矛盾仍依 AGT-015 處理 |
| A0 全數等待後期決策 | 以本次授權開啟 P-G0/P-MODEL 兩線，license/精度/部署在各自 gate | 不默認批准特定外送、權利或支出 |
| G0 被建構器或 license 阻擋 | P-G0 僅依賴 P0，接受仍要求真實 LLM 的全部 G0 條件 | fake/catalog 沒有替代資格 |
| Agent A 的較新 source、測試、證據被覆蓋 | 不合併該分支；protected-tree equality 對目標全體非 allowlist 檔案成立 | 只在未來另授權時處理 status 重疊與 G0 缺口 |
| 新增 planned IDs 被當成測試已實作 | `tests: []`＋DEFERRED＋review date，舊 ratchet 不變 | P-FULL-RUNTIME 尚欠獨立實作 slice，不聲稱全面 3.4 conformance |
| 單站結果被稱為跨站 | G7-SITE/G7-WORKER/目標站資格分開 | 單站可先驗，不擴張未證明的範圍 |
| 角色／科學 authority 因架構啟用而擴張 | ADMIN/MEMBER 不增新帳號角色；CWG V1.1、現有簽核與 A3/A9/A12 保留 | 不啟用 SP 1.1.0 或擴大 DISCRIMINATION/多原因 |

本節是文件整合自我審查，不稱為獨立科學審查。尚待 Owner 的範圍與條件以本 profile §5
及保留的 D-01–D-08 清單為準。
