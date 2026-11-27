# SAI 3.4 Candidate — 可量測自主建模驗收

版本：`3.4.0-candidate.2`；細化 ASM-001/002、008–014、016–018；保留原六層建模驗收。
**目前只能支持候選設計可審；不能支持任何新增建模能力或真實物理精度已達標。**

## 1. 驗收單位與協定

G0 的單位是預先註冊的研究問題/案例與其授權來源集；不能以同一報告切成多段虛增 n。
物理驗收的實驗單位是獨立器件/模型族及其條件集合，不是同一曲線的點數或同一專案重跑次數。
重跑用於估計數值重現；不能擴大獨立樣本 n。dataset split 依器件、製程批次與來源依賴 family，
防止同一範例的改版流到兩邊。凍結失敗與排除規則，所有已註冊案例均列入分母。

`AcceptanceProtocol@1` 在建構與評估前封存：case IDs、experimental unit、n 與依據、
輸入分布、工作範圍、rivals、baseline、每 observable metric/單位/容差、measurement uncertainty、
數值誤差預算、missing-data/FAIL/BLOCKED 規則、split/family/scorer hashes、可見資料角色、
seeds/repeats、max attempts/wall/seat cost、停止與統計方法、簽核者及時間。
缺任一適用門檻是 **BLOCKED**，不能由實作人員填一個容易過的數字。

G0 是獨立的授權前研究驗收；六個認知層次 G1–G6 各自出結果；G7–G9 是橫向條件。
G7-SITE 是單站基線，G7-WORKER 只在聲稱跨 worker 可移植時適用。每個 gate 綁定適用的
spec/build/run/protocol hashes、case IDs、executor/evaluator identity 與證據；
G0 使用 research episode/run/bundle/report refs，不捏造不存在的 solver Run 或 model/build refs。
各 gate 採 PASS/WARN/FAIL/UNKNOWN/BLOCKED；未要求的跨 worker 範圍記 NOT_CLAIMED，
其子 gate 記 BLOCKED/未評估且不納入單站接受的必過集合，不把它當 PASS。
下層通過不推論上層通過；WARN 不能算 fully validated。

## 2. G0 與 G1–G9

| ID | 接受什麼 | 可量測 pass condition | 反例/失敗行為 | 所需環境 |
|---|---|---|---|---|
| G0 | Pre-Lumerical Research Acceptance Gate | 通過登入驗證且有專案權限的研究者，以真實受治理 LLM 完成端到端研究；全部必要科學內容有英文/繁中版本與匯出、可核查來源鏈，未執行模擬逐項標示；通過 §2.1 全部條件 | CatalogReasoner/mock/fake/canned responses、只換 UI 標籤、沒有科學可用性或冒稱 solver 已執行均不能 PASS | 真實 LLM＋經認證的產品研究流程；不需 Lumerical；本次未執行 |
| G1 | 模型建構成功 | 空白工作區無預建 vendor 專案；從 typed spec 產生新專案；必要物件/材料/接觸/邊界/mesh/solver readback 100% 對應；差異只在預註冊容差內 | 成功存檔但漏 contact/單位錯即 FAIL；無必要參數則 BLOCKED，猜值率 0 | 離線可驗 compiler；真實 readback REQUIRES_LICENSE |
| G2 | solver 執行成功 | 正確產品/版本及真實 entitlement；每 attempt 有 start/end、exit、log、輸出 arrays、完整 manifest；資格化成功案例全部產生預定輸出 | 無 seat → WAITING_RESOURCE/BLOCKED；crash/空 arrays/錯產品 → FAIL；不把 mock 算入 | REQUIRES_LICENSE |
| G3 | 數值收斂 | 所有指定 observable 的殘差、守恆與離散化誤差低於已凍結限值；至少 3 層 mesh/適用步階與外域研究；全部 bias/frequency/time 點覆蓋 | 單一 solver convergence flag 不過關；非單調/非漸近/多分支時 UNKNOWN 或 FAIL，保留原始資料 | 真實 solver；解析 manufactured cases 可先離線 |
| G4 | 獨立參考吻合 | 完全封存 holdout；每 observable 通過核准的絕對/相對/形狀與最差案例條件；報完整配對誤差分布、CI 與 reference 不確定度 | 公開範例、共享建構來源、專家專案已洩漏不具獨立性；缺 reference → BLOCKED；不可用平均掩蓋最差案例 | 獨立 reference＋REQUIRES_LICENSE |
| G5 | 指定範圍物理有效 | G3/G4 合格，模型假設與器件/條件可比；獨立守恆/對稱/極限及實測資料檢查均過；total predictive uncertainty 在核准用途誤差內 | 跨 solver 相符、趨勢合理、參數被擬合均不能單獨通過；模型失配與 sim-to-real conflict 留存 | 獨立物理資料＋REQUIRES_LICENSE |
| G6 | 科學結論有 warrant | 100% 的支持/反駁/確認主張可重推導至合法 relation、warrant、signed review（適用時）、Decision/event/policy；競爭假說與可辨識性有紀錄 | 結果吻合卻無法區分 rival 時不確認原因；不支援或欠授權的 CONFIRMED 數 0 | policy/SQL 可先離線或 postgres；實際主張另需前述證據 |
| G7 | 分範圍可重現 | G7-SITE：同一合格安裝至少 3 次乾淨 session 的 licensed 重建/重跑在容差內；G7-WORKER：另由第二獨立合格 worker 完成相同協定；兩者各別出結果 | 沒有第二 worker 不阻擋單站接受，但不能聲稱跨 worker；同站多 worker 不等於跨站，binary metadata 不要求 byte-identical | G7-SITE 只需單站 licensed 安裝；G7-WORKER 另需第二合格 worker |
| G8 | 安全、隔離、預算與復原 | 所有列明拒絕案例在副作用前拒絕；注入每個 durable 邊界 crash/duplicate/late callback，接納結果唯一、歷史完整、全部 attempt 可對帳，無越權寫入/外送/超限執行 | 認領 lease 成功不算 solver 只跑一次；outcome UNKNOWN 先對帳；取消不抹除成本 | 離線/fake/postgres；checkout/失聯部分 REQUIRES_LICENSE |
| G9 | 產品自主性與可用介面 | 模型族內未見過的有效案例：移除/封鎖外部 coding agent 後從問題到完整報告；每例依預註冊時間/成本與適用 gates 計分，整體達核准成功率及覆蓋門檻；兩語狀態/數值一致 | 預建專案、人工寫模型碼、手改 DB/manifest、偷偷接開發 agent 都是 FAIL；必要 ReviewItem 不算錯誤接受，但不算「無人完成」 | 部署等效＋REQUIRES_LICENSE；離線只驗流程 |

「100%」針對預先註冊的結構/治理不變量與適用案例，並非聲稱所有未來科學問題都能成功。
自主成功率、有效輸入覆蓋、合理棄答率、錯誤接受率、人工接觸次數與時間、seat/cost、
修復率均各自報告；G3–G5/G9 物理/自主建模的有效案例通過比例與用途精度由 D-02 核准，
未決時不能簽這些 gate。G0 使用先凍結的研究案例與 §2.1 rubric，不等待未定的器件精度門檻。

### 2.1 G0 — Pre-Lumerical Research Acceptance Gate

G0 掛在 ASM-002/012/014/016/018 及各自 planned tests，不新增 ASM 需求。
離線 mock tests 與以下真實研究驗收各自標示；文件 CI 通過不代表 G0 已執行。

| 條件 | 可測 pass condition 與必要證據 | 不接受的替代品 |
|---|---|---|
| G0-A authenticated workflow | 有效 ADMIN/MEMBER 帳號登入產品，依當前 project membership/clearance 開啟 research episode、讀取授權來源、取得報告並續跑/匯出；保存 session 的非秘密稽核 ref、actor/project/run/trace 與拒絕未登入/跨專案請求的測試 | 手改 DB、直呼內部函式繞過認證或 ADMIN 自動具有科學 reviewer 權限 |
| G0-L genuine governed LLM | 已資格化且啟用的實際 LLM runtime，經 ScientificLLM/ModelRouter、EvidenceBundle、ACL/egress/BudgetGate；保存 model/provider/version、route、request/response 或受分級保護的 hash/定位、usage/cost、InferenceProvenance，並有實際推論服務/worker 呼叫證據可交叉核對；所需 provider 認證成功 | CatalogReasoner、mock/fake SDK、回放/硬編碼/canned responses、由測試輸出偽填 provider 名稱；無可核查真實推論證據為 BLOCKED |
| G0-S scientific usefulness | 執行前凍結案例與 rubric；報告有 ≥2 個 competing hypotheses、可反駁 predictions、實際來源支持的 observations、分開的 interpretations、uncertainty、warranted conclusions/未定、limitations 與 least-cost next checks；具領域資格且獨立於產生者的審查者逐項判可用，無捏造 observation/引用或無 warrant 的確認 | 僅格式正確、字數達標、LLM 自評、重述問題或展示模型名稱；結論可保留 UNKNOWN，但需清楚有用的下一步 |
| G0-B bilingual science/export | 上列八類科學內容在英文及繁中頁面/報告與所有提供的匯出格式皆有對應；適用非空欄位覆蓋率 100%，數值/單位/ID/條件/否定/不確定度/claim strength/狀態一致；獨立雙語審查＋結構化 parity 檢查，canonical hashes/簽章/事件不變 | 只翻譯標籤、只有其中一語有科研正文、匯出回到單語，或翻譯新增觀察/提高 authority |
| G0-P provenance and honest scope | 每個 observation/citation 可回查授權 ArtifactOccurrence/SourceWork/EvidenceUnit、精確 locator/hash；推理另帶 bundle/InferenceProvenance；原始 canonical records 前後 hash 不變；每項計畫中的模擬列為 NOT_PERFORMED，附原因/所需條件且沒有偽造 solver Run/result | 以預測代觀察、隱藏待做模擬、把 synthetic/mock 數值寫成已跑實機、原文被翻譯覆寫 |

缺模型、認證、來源權利、實際推論紀錄或合格審查者時 G0 為 BLOCKED；內容錯誤、越權或
以 mock 冒充時 FAIL。不能用不需 Lumerical 為由免除真實 LLM、認證與科學內容要求。
G0 接受的是已明示限制的研究工作流程與有用報告，不接受未執行的模型建構、物理精度、
模擬結果或最終 readiness。真實 LLM 可是合規本機或核准外部 provider，沒有指定付費服務。

### 2.2 G7-SITE 與 G7-WORKER 的接受範圍

G7-SITE 固定單一安裝/站點的 solver、OS、硬體、SDK、材料庫、執行緒/種子及 protocol，
清空工作 session 後至少三次重建/重跑/重抽取/評分，逐 observable 比較凍結容差，並保留
canonical lowering/input hashes 與每份原始輸出 hash。只在這個站點/版本/envelope 宣稱單站可重現。

G7-WORKER 使用同一封存輸入與 protocol，在第二個有獨立資格紀錄的 worker 比較數值、
環境差異與成本；不能用同安裝重啟程序代替。若兩 worker 位於同站，只支持跨 worker。
跨站主張另需第二站的安裝/license/環境資格與相同重播；單一安裝永不產生跨站證據。
G7-WORKER 未評估/失敗時保留該結果，單站 G7-SITE 仍可獨立接受，禁止宣稱更廣資格。

## 3. observable 專屬誤差與容差

這些是候選評分方法，不是宣稱已校準的精度。最終容差取自用途需求、測量誤差與解析度，
在開發集校準後由 Owner 凍結 BenchmarkPolicy；不根據 holdout 結果修改。

| observable | 指標與規範化 | 適用性檢查 |
|---|---|---|
| CHARGE DC I–V | 絕對電流誤差＋有明示 floor 的相對誤差；跨多數量級時用事先選定區域的 log-magnitude 誤差並另檢查符號 | 近零、反向電流、breakdown/模型適用域；不能對負值直接取 log |
| Cj(V,f) | fF/µm 或總 F 的 MAE、最大 absolute/relative error、曲線斜率與形狀；所有正規化條件一致 | extraction method、bias 符號、frequency 與小訊號有效域；異常負 C 不直接刪除 |
| Rs(V,f) | Ω·µm 或總 Ω 的 absolute/relative error、worst-case、bias dependence | 幾何 normalization、寄生/接觸模型、抽取可識別性；禁止靠裁掉高誤差點過關 |
| 空間場/載流子/電勢 | domain-aware L2/L∞、界面 jump/積分電荷與電流守恆 | 座標映射、網格內插誤差、材料不連續；不得把插值細點當更多獨立資料 |
| MODE neff / loss | complex neff 的實部/虛部絕對誤差與每長度損耗；mode overlap/追蹤 | 模態錯配、degeneracy、偏振與邊界；不能只比較 mode index |
| FDTD spectrum / resonance | 功率/能量守恆、頻譜 absolute error、共振位置、linewidth/Q 誤差 | source/monitor normalization、時間窗、PML/domain/mesh、頻寬及動態範圍 |
| INTERCONNECT eye / BER | 相同 pattern/seed/receiver/DSP 下的 eye 指標、log-BER 與區間 | bit/sample count、零錯誤的上限而非 BER=0、共同輸入資料依賴 |
| multiphysics transfer | 介面積分守恆、場映射誤差、耦合殘差與最終 observable | 每 solver 誤差＋轉換誤差；單向與雙向、穩態與暫態不能混比 |

例：relative error 分母為 `max(abs(reference), floor_observable)`，floor 帶相同單位並預先凍結。
離散化誤差可報 `abs(q_fine-q_medium)`；只有確認漸近階數與 grid-ratio 適用後才報外推誤差。
電流守恆殘差以帶方向的邊界通量及適用 transient displacement/storage 項計算，不能只強求
兩端 conduction current 在所有暫態下相等。物理規則由模型族明訂。

不確定度分列：數值、輸入參數/材料、量測 reference、模型形式、抽取及 mapping。
只有獨立性/分布假設成立時才以平方和合併；否則保留 covariance 或保守 bounds。
參數敏感度既報局部標準化斜率，也對有交互作用的參數採已凍結的 global/screening 方法。
未識別參數保留不確定度，不靠精準擬合一條曲線宣稱參數為真。

## 4. 獨立 benchmark 與專家比較

至少包含以下固定 case strata；數量與範圍由 D-02 在執行前核准：

| 組別 | 目的/變因 | 參考與結論邊界 |
|---|---|---|
| 解析/極限 | 尺寸、摻雜、bias 的已知極限，對稱/守恆與單位 | 可驗實作，不能代替實測 predictive validation |
| 建構開發 | 公開 Ansys 範例、授權文獻、核准模板的首次 typed 重建 | 可驗建構與回歸，全部從 holdout 排除 |
| 獨立器件 holdout | 未見器件/製程批次、材料/偏壓/溫度域，保留 uncertainty | expert 專案與真值由 evaluator 控制，生成器不可讀 |
| 負例 | 缺參數、錯單位、接觸斷路、網格振盪、不收斂、非適用域、多解、reference 衝突 | 事先定預期棄答/FAIL/BLOCKED，錯誤確認數 0；不從分母排除 |
| 作業故障 | license 中斷、worker crash、quota exhausted、重送、撤權、跨 project | 檢查 G8；不解讀為物理模型準確度 |

比較三個 baseline：同一物理 brief 的專家手建、已核准模板的參數掃描、候選首次建構器。
專家只見與候選相同的合法輸入；建構者、模型參數校準者與獨立 evaluator 分離。
專家專案只供評估/結構比較，不回饋 builder。雙方使用相同 solver、版本、資源及數值容差，
另報建模人時、首次成功率、錯誤接受/棄答、修改次數及每 observable 誤差。
專家結果是比較對象，沒有測量/獨立物理 reference 時不自動成為 ground truth。

對配對獨立器件報效應與區間；曲線點不用於虛增 n。non-inferiority margin、
重複數、CI/bootstrap group、coverage 與多 observable/多比較處理先凍結。
窮舉的確定性結構案例無需 statistical power；器件預測的推論則需 sample-size/power 或
精度/區間寬度依據。沒有足夠獨立資料時標 exploratory，不簽正式精度驗收。

最小 ablation 比較「固定數值設定」與「有受控數值細化」，以及「固定參數」與「開發集校準」。
評估不把更多模型 token、更多 solver 時間或多代理當作無成本；配對資源上限並報所有成本。
任何較好、相當或較差結果都保留；重跑不挑最好的 seed 或排除不收斂器件。

## 5. 授權前後的量測階梯

1. deterministic schema/compiler/readback-double、解析單位、權限/惡意輸入與完整性。
2. fake SDK/worker 小型端到端，故障、超限、取消、續跑與兩語報告。
3. 中等規模 synthetic case matrix 與 lease/queue 壓力；只推論軟體邊界與累積故障。
4. **獨立的 G0 真實 LLM 研究驗收**：認證產品流程、科學雙語正文/匯出、provenance、未做模擬。它不是 synthetic matrix，也不需等待 license 決策結案。
5. 真實 licensed smoke：空白建模、readback、一次求解、封存與單站 G7-SITE 重播。
6. 真實中等案例與收斂/敏感度，通過後才跑 sealed holdout。
7. 正式獨立評估、單站用途範圍審查與 Owner 接受；跨 worker/站點資格依主張另驗，不能提前宣稱。

每階段有固定 inputs、environment、resources、outputs、完成條件與失敗判定。
離線 fixtures 上的 PASS 不能填到 G0 或 licensed gate；這次未執行第 4–7 階段。
