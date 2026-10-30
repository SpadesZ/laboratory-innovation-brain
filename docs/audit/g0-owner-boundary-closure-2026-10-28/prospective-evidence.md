# 前瞻證據的漏洞收尾與「授權的篩檢後驗證」

日期:2026-10-29
分支:`g0-owner-boundary-closure`
狀態:工程候選。沒有物理驗證。沒有真實 LLM 執行。成本為零。

## 1. 要解決的問題

篩檢後的假說,是作者看過篩檢讀值以後才提出的。
這種假說不能被「已經存在的證據」支持。
011p 用時間與種類判斷證據是不是前瞻的。
但 011p 留下四個漏洞。另外,產品從不登記 capability,
所以篩檢後的假說在產品裡**永遠**拿不到支持。

## 2. 先證明漏洞(在 011r,也就是 011p 生效時)

測試:`tests/e2e/test_g0_prospective_evidence_postgres.py`。
在 011s 之前執行,11 個測試全部失敗,訊息都是 `DID NOT RAISE`。
意思是:下面每一種基礎,都被接受成篩檢後假說的支持。

| 漏洞 | 例子 | 011p | 011s |
|---|---|---|---|
| 擷取時間未知 | 上傳的量測匯出檔,沒有 `captured_at`(當輸出) | 接受 | 拒絕 |
| 擷取時間未知 | 模擬讀入一個沒有擷取時間的舊量測檔(當輸入) | 接受 | 拒絕 |
| 血緣 | 輸出由 2020 年的量測衍生 | 接受 | 拒絕 |
| 血緣 | 輸入由篩檢輸出衍生 | 接受 | 拒絕 |
| 血緣 | 三層間接衍生自篩檢輸出 | 接受 | 拒絕 |
| 血緣 | 血緣形成循環 | 接受 | 拒絕 |
| 血緣 | 血緣超過 16 層 | 接受 | 拒絕 |
| 分類 | 應用程式把「查詢」寫成 MEASUREMENT | 接受 | 拒絕 |
| 分類 | 用 UPDATE 改掉已登記的種類 | 允許 | 拒絕 |
| 分類 | 規則檢查重讀同一個設計檔 | 接受 | 拒絕 |
| 授權 | 新的量測,但沒有人事先登記 | 接受 | 拒絕 |

## 3. 規則(011s)

對有篩檢條件記錄的假說,SUPPORTS 的每一個基礎觀測
(來源,以及每個被引用的 attestation 背後的觀測)都要通過:

1. 011p 的 (a)–(g),內容與訊息不變。
2. **(h) 有宣告**:capability 的種類來自 DomainPack 程式碼的宣告
   (`capability_declarations`),並且與 `capabilities` 一致。
3. **(i) 種類能產生新證據**:
   - 查詢既有證據、歷史案例比對、專家審閱:永遠不行。它們讀或判斷已有的東西。
   - 規則檢查、數值代理模型:只對「新的實證資料」才算。
     對設計檔,或對假說之前就存在的東西做確定性分析,結果在假說提出前就已固定,也讀得到。
   - 模擬:可以讀宣告過的設計規格。它在假說之後算出設計檔沒寫的結果。
     但它仍只是關於「設計中的元件」的證據。
   - 量測、製作:產生實證資料,擷取時間必須已知。
4. **(j) 擷取時間**:實證資料(不是它讀的設計規格,也不是計算類的 RUN_OUTPUT)
   必須有已知的擷取時間。NULL 一律拒絕:不知道,不等於新。
   它輸出的,或當實證資料讀入的東西,不能在假說前就已記錄。
5. **(k) 血緣**:沿著 `derived_from_artifact_ids` 與 `previous_artifact_id` 遞迴往上走,
   最多 16 層。不能碰到篩檢執行的輸出、假說前開始的執行的輸出、
   假說前擷取或記錄的實證資料、擷取時間未知的資料、或沒有記錄的 artifact。
   循環或超過 16 層:拒絕(fail closed)。
6. **(l) 事先授權**:執行的 Job 必須綁定一筆授權。授權要指名這個假說、
   這個 capability(與當時的宣告雜湊)、以及關係所主張的那個預測。
   執行開始時間,以及量測資料的擷取時間,都不能早於授權。

設計檔與實證資料怎麼分:由 pack 宣告。矽光子 pack 宣告
`sp.device_project`(媒體類型 `application/vnd.lab-brain.sp-device-project+json`)
是設計規格。它還必須是上傳或 watcher 來源。其他一律當實證資料。不確定時就當實證資料。

## 4. 分類為什麼現在有權威

- `capability_declarations` 只有**資料表擁有者**(營運者的 migrator)能寫入。
  觸發器檢查 `current_user`,所以服務角色就算有列權限,也寫不進去。
- 宣告存入 pack 程式碼產生的正規 JSON 與 SHA-256。資料庫重新計算雜湊,
  並逐欄比對 `capabilities`。
- 宣告只能新增,不能改、不能刪。已宣告的 capability,`capabilities` 裡的契約欄位也不能改
  (availability 例外,它是狀態)。
- 已用**非超級使用者**證明:`tests/integration/test_g0_prospective_roles_postgres.py`
  建立臨時角色,用 `grant_database_roles` 授權,以服務角色連線,
  無法登記種類、無法改種類、無法刪除或 TRUNCATE。
- 研究流程以擁有者身分執行時,會自己登記 pack 的宣告(測試就是這樣)。
  以服務角色執行時,缺少的宣告就保持缺少,該 capability 不能支持篩檢後假說。

**不需要修改 `deployment.py` 的授權。** 邊界在觸發器,不在權限。

## 5. 授權的篩檢後驗證(合法的路)

`src/lab_brain/verification/prospective.py`:

1. **授權**:專案中有效的「人」(HUMAN、啟用、專案成員)事先登記一個測試。
   時間由資料庫時鐘決定,寫入者不能倒填。必須晚於假說。只能新增。
2. **綁定**:一筆授權只能授權一個 Job,而且要在 Job 還是 QUEUED、沒有 Run 時綁定。
   一次登記只跑一次,不能一直重跑到結果符合為止。
3. **記錄**:`record_authorized_measurement` 記下人做的量測:
   Job → Run(輸出是匯出檔,帶擷取時間)→ 觀測 → attestation(經過 admission gate)→ 關係。
   驗證迴圈用 `AuthorizedJobs` 綁定被授權 capability 的 Job。
4. 資料庫會拒絕的 SUPPORTS,改記成 `CITES`,並寫下拒絕原因(`ProspectiveEvidenceSink`)。
   證據保留成背景資料,但不算支持,驗證也不會因此失敗。

端對端(離線,stand-in 模型,網頁研究流程):
授權後的量測被存成 SUPPORTS,收集器所有事實都是 false,scorer 判為可採用。
晚授權、或回溯資料的量測,被存成 CITES,不算支持。沒有授權就無法記錄。

## 6. 保留不變的事

- 回溯證據仍可用 `CITES` 記在篩檢後假說上(測試證明)。
- 回溯證據仍可支持篩檢**之前**形成的假說(測試證明)。
- 篩檢讀值本身、重複的檢查、同樣的輸出位元組,仍然不能支持(自我支持仍被禁止)。

## 7. 收集器與 scorer

收集器新增四個事實,scorer 版本升為 **2.2.0**:
`unknown_capture_time`、`lineage_before_hypothesis`、`unclassified_capability`、
`unauthorized_verification`。`retrospective_basis` 的定義更精確
(加入:宣告的種類不能產生新證據,以及假說前就已記錄的 artifact)。
這四個事實用的是守門員同一組 SQL 函式,但在現在的資料上重新讀,
所以守門員被關掉或資料被手改,仍會被報告。
2.1.0 格式的紀錄缺少新事實,會被判為 MALFORMED,不會被猜。
`benchmarks/g0_screening/score.py` 不用改:它先呼叫 `record_problems`。

另外(依協調者要求):`prompts_captured == False` 的完成紀錄,
`no_input_leak` 判為**不適用**(不是通過),摘要以 `input_leak_unverified` 計數。
沒有這個欄位的紀錄,視為已擷取(與 matrix harness 相容)。

## 8. 工程有效 vs 科學有效

- 被接受的支持,只表示:**就紀錄而言**,這是事先登記、新的、獨立的檢查。
- 它**不是**物理確認。模擬只是關於設計中的元件。量測結果也可能錯。
- 紀錄的真實性取決於寫入者。寫入者漏填或填錯擷取時間、血緣或媒體類型,系統偵測不到。

## 9. 剩餘風險

1. 擷取時間、血緣、媒體類型、`runs.start_time` 都由寫入者提供。
   位元組不同、又沒宣告血緣的複本,無法偵測。
2. 授權的「人」只由資料庫斷言。有服務角色權限的寫入者,可以替一個真實成員寫授權。
   要防止這點,需要簽章(例如沿用 reviewer 的 Ed25519 金鑰),目前沒有做。
3. 宣告的權威等於 migrator 的權威。擁有 migrator 權限的人可以宣告任何種類(營運者信任根)。
4. 「模擬可以讀設計檔」是一個判斷。如果作者其實已經看過同等的模擬結果,這個區分就不成立。
5. 產品目前沒有網頁介面可以建立授權或上傳量測;只有 Python API。
   研究流程以服務角色執行時,需要營運者先用 migrator 登記宣告:
   `lab-brain admin declare-capabilities`(只有資料表擁有者可以執行;服務角色執行會被拒絕,
   測試:`tests/integration/test_g0_prospective_roles_postgres.py`)。
6. 離線環境沒有模擬器,所以「授權的模擬」只測到 Job 綁定,沒有跑完整個迴圈。

## 10. 檔案

- `migrations/011s_prospective_evidence_authorization.sql`(新)
- `src/lab_brain/verification/prospective.py`(新)
- `src/lab_brain/storage/postgres/capabilities.py`、`src/lab_brain/research/service.py`
- `src/lab_brain/domains/silicon_photonics/vertical.py`、`plugin.py`(只加宣告)
- `src/lab_brain/evaluation/collect.py`、`scoring.py`
- 測試:`tests/e2e/test_g0_prospective_evidence_postgres.py`、
  `tests/e2e/test_g0_prospective_verification_postgres.py`、
  `tests/integration/test_g0_prospective_roles_postgres.py`,以及更新的既有測試。
