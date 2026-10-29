# 金額上限的管理權限(2026-10-28)

狀態:已實作。只用本機 PostgreSQL 與本機假服務測試。沒有呼叫真實模型服務,沒有付費呼叫。

相關檔案:

- migration:`migrations/011t_llm_spend_administration.sql`(接在 `011r` 之後)
- 程式:`src/lab_brain/llm_runtime/spend.py`、`src/lab_brain/llm_runtime/provider.py`、
  `src/lab_brain/interfaces/deployment.py`(`grant_database_roles`)、
  `src/lab_brain/evaluation/live_budget.py`
- 測試:`tests/integration/test_g0_spend_admin_postgres.py`、`tests/unit/test_g0_spend_admin_policy.py`

## 1. 修改前的問題(先寫會失敗的測試)

測試用 `lab_brain` 連線沒有意義,因為它是 superuser。
所以測試建立部署實際使用的低權限角色(`service_roles.ensure_roles` + `grant_database_roles`),
再**用應用程式角色連線**做每一個動作。

修改前執行 `tests/integration/test_g0_spend_admin_postgres.py`:14 個測試中 12 個失敗。
應用程式角色可以做到下列事情:

| 缺口 | 修改前 | 證明的測試 |
|---|---|---|
| 自己調高上限 | 成功(`llm_spend_set_ceiling` 任何角色都能執行) | `test_the_app_cannot_raise_its_own_ceiling` |
| 關閉 overrun 打開的電路 | 成功 | `test_the_app_cannot_close_an_open_circuit` |
| 建立新預算 | 成功(資料表有 INSERT 權限) | `test_the_app_cannot_create_a_budget` |
| 宣告單價(例如 0 元) | 成功 | `test_the_app_cannot_declare_or_alter_a_price` |
| 偽造 writer 旗標,把已收費改成 0 | 成功(旗標任何角色都能設) | `test_a_forged_writer_flag_writes_nothing` |
| 有資料表寫入權限時,旗標就足夠 | 成功 | `test_the_flag_is_not_enough_even_where_table_writes_were_granted_by_mistake` |
| 本機代理(例如 localhost 上的 LiteLLM)沒有計量 | 送出,不記帳 | `test_a_local_proxy_is_metered_unless_the_owner_declares_it_free` |

另外,產品預設:沒有設定預算時,遠端請求直接送出,不計金額
(只有 `LAB_BRAIN_LLM_SPEND_REQUIRED=1` 才拒絕)。

## 2. 角色:誰可以做什麼

| 角色 | 是什麼 | 可以 | 不可以 |
|---|---|---|---|
| migrator(`lab_brain`,superuser) | 擁有 schema,執行 migration 與 `db-roles` | 全部 | — 它是信任根(見 §5) |
| `lab_brain_spend_admin` | 新角色,NOLOGIN。Owner 的金額管理 | 建立預算、宣告單價、改上限、關電路、宣告免費端點、撤銷免費端點 | 直接寫資料表 |
| Owner 的登入角色 | operator 建立,並授予 `lab_brain_spend_admin` | 同上(經由成員身分) | — |
| `lab_brain_app`(服務) | web、local-models 連線用 | 預留、結算、保留(`llm_spend_reserve/settle/retain`);讀取 | 上表所有管理動作;寫入、刪除、TRUNCATE 金額資料表;停用觸發器;`SET ROLE lab_brain_spend_admin`;設定 `session_replication_role` |
| `lab_brain_reader`(稽核) | 只讀 | 讀取 | 執行任何金額函式 |

## 3. 設計

### 3.1 管理函式只給 Owner

- 管理函式是 `SECURITY DEFINER`,由 migrator 擁有,`search_path` 固定為 `public, pg_temp`。
- 每個函式先檢查 `pg_has_role(session_user, 'lab_brain_spend_admin', 'MEMBER')`。
  用 `session_user`,不是 `current_user`:`SET ROLE` 或旗標都不能通過。
- `EXECUTE` 從 PUBLIC 收回,只授予 `lab_brain_spend_admin`。
- 函式:`llm_spend_declare_budget`、`llm_spend_declare_price`、`llm_spend_set_ceiling`、
  `llm_spend_declare_free`、`llm_spend_revoke_free`。

### 3.2 服務只能預留、結算、保留

- `llm_spend_reserve`、`llm_spend_settle`、`llm_spend_retain` 改成 `SECURITY DEFINER`(固定 `search_path`)。
- `EXECUTE` 從 PUBLIC 收回。`grant_database_roles`(`lab-brain admin db-roles`)只授予服務角色。
- `grant_database_roles` 收回服務角色在金額資料表上的 INSERT、UPDATE、DELETE、TRUNCATE,以及序列權限。
  每次執行都會重做,所以是冪等的。
- `grant_database_roles` 拒絕:服務角色或稽核角色是 `lab_brain_spend_admin` 的成員。

### 3.3 旗標不能偽造

- 觸發器現在要求兩件事:旗標是 `on`,**而且** `current_user` 是資料表的擁有者(migrator)。
- 只有在 migrator 擁有的 `SECURITY DEFINER` 函式裡面,`current_user` 才是擁有者。
- 所以服務角色自己設旗標沒有用。就算部署不小心給了資料表寫入權限,觸發器仍然拒絕。
- 預算的建立、單價的新增、免費端點的新增,也都要經過這個檢查。
- 每一列都記錄 `db_role`(`session_user`):是誰的資料庫登入寫的。

### 3.4 遠端請求:預設拒絕

- 有 body、目的地不是本機的請求,沒有預算時一律拒絕,一個 byte 都不送出。
- 沒有環境變數可以關掉這個規則。`LAB_BRAIN_LLM_SPEND_REQUIRED` 已經沒有作用(一律等於 1)。
- 唯一例外:Owner 用 `llm_spend_declare_free` 宣告這個端點免費。服務角色不能宣告。
- 有資料庫(`LAB_BRAIN_DATABASE_URL` 或 `LAB_BRAIN_LLM_SPEND_DSN`)但沒有預算時,
  guard 只放行已宣告免費的端點,其他都拒絕。

### 3.5 本機代理

- 有設定預算時,本機端點**也計量**。沒有單價 → 拒絕。只有 Owner 宣告免費的端點不計量。
- 免費宣告是每個端點(`host:port`)加一個模型,或 `*`(這個端點的所有模型),並附上原因。
- 宣告只能新增。撤銷是新的一列(`free = FALSE`)。最新的一列決定。
- 即時評估:`install_live_spend_guard` 也計量本機。本機的 critic / utility 要用
  `LAB_BRAIN_LIVE_FREE_ENDPOINTS` 與 `LAB_BRAIN_LIVE_FREE_REASON` 宣告免費,否則被拒絕。
- 只用本機模型的評估:`install_local_free_guard` 要求每個本機端點都宣告免費,其他一律拒絕。

### 3.6 剩下的例外(要 Owner 決定)

- **完全沒有預算**的部署:本機請求仍然不計量,也不檢查免費宣告。
  原因:現有的本機測試與本機 Ollama 流程都在這種設定下執行,改成拒絕會讓它們全部停止。
- 這表示:沒有預算的部署,如果 LOCAL 連線指向一個轉送到付費服務的代理,這個代理不會被計量。
- Owner 可以關閉這個例外:設定一個預算(本機就會計量),或設定 `LAB_BRAIN_LLM_SPEND_METER_LOCAL=1`
  (沒有預算時,未宣告免費的本機端點也會被拒絕)。
- 測試 `test_with_no_ceiling_at_all_this_machine_is_the_documented_residual` 記錄這個行為。

## 4. 對抗測試(真實 PostgreSQL,用服務角色連線)

`tests/integration/test_g0_spend_admin_postgres.py`:

- 服務角色被拒絕:調高上限、關電路、建立預算、宣告或修改單價、新增/修改/刪除帳本、
  偽造旗標(包括有寫入權限時)、呼叫任何管理函式、`SET ROLE lab_brain_spend_admin`、
  TRUNCATE、`ALTER TABLE ... DISABLE TRIGGER`、`SET session_replication_role`、替換 `llm_spend_writer()`。
- 服務角色可以:預留、結算、保留、讀取。帳本列記錄它的 `db_role`。
- 16 個執行緒,各自用服務角色連線同時預留:不超過上限(5 個成功、11 個拒絕)。
- Owner 的登入角色(`lab_brain_spend_admin` 成員)可以:建立預算、宣告單價、改上限、關電路。
- `db-roles` 拒絕是 `lab_brain_spend_admin` 成員的服務角色;執行兩次結果相同。
- 本機代理:有預算、沒有單價、沒有免費宣告 → 拒絕,不送出;服務角色不能宣告免費;
  Owner 宣告後才送出且不記帳;同一端點的其他模型仍被拒絕;撤銷後又被拒絕。
- 即時評估:本機 critic 沒有宣告 → 拒絕;用服務角色設定評估金額 → 拒絕;宣告後才送出。

`tests/unit/test_g0_spend_admin_policy.py`:遠端沒有 guard 一律拒絕(不管旗標);
免費端點不預留;沒有預算的 guard 拒絕未宣告的端點;環境變數如何選 guard;預算會計量本機。

## 5. 剩下的信任根(與 A12 有關,A12 沒有解決)

- **migrator / superuser**:擁有資料表與函式,可以改任何東西、停用觸發器、改 migration。
  本工作只把它和一般研究執行分開,沒有讓它變得可信。
- **持有 `lab_brain_spend_admin` 的人**:決定預算、單價、上限、免費端點。宣告錯了,上限就錯了。
- **服務行程本身**:它持有服務商金鑰。被入侵的服務行程可以不經過 guard 直接呼叫服務商,
  也可以回報假的 body 大小或用量給 `llm_spend_reserve / settle`。資料庫只保證它不能改上限、單價與帳本,
  不保證它誠實回報。服務商端的硬上限是唯一能擋住這種情況的地方。

## 6. 服務商端的剩餘風險

1. 服務商必須遵守 `max_tokens`,包括推理 / thinking token。每個服務商都要 Owner 確認。
   不遵守時只能在結算時偵測(OVERRUN,電路打開),那一個請求已經付費。
2. 「一個 token 至少一個 byte」的假設。特殊 tokenizer 可能例外;用安全倍數與 overhead 處理,結算時偵測。
3. 有些服務商要 `max_completion_tokens` 而不是 `max_tokens`;這種請求會 400 失敗,保留最壞金額。
4. 快取折扣、分級價格不計入(只會高估)。
5. 建議在服務商端另外設定預算警示或硬上限。

## 7. Owner 的步驟

以下用 migrator(資料庫初始 superuser)連線執行,密碼不要放進版本控制。

### 7.1 套用 migration 並重新授權

```sh
python scripts/migrate.py            # 會套用 011t(建立 lab_brain_spend_admin)
lab-brain admin db-roles --app-role lab_brain_app --reader-role lab_brain_reader
```

### 7.2 建立 Owner 的登入角色,並授予管理角色

```sql
CREATE ROLE owner_spend LOGIN PASSWORD '<Owner 自己的密碼>'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT lab_brain_spend_admin TO owner_spend;
```

不要把 `lab_brain_spend_admin` 授予 `lab_brain_app` 或 `lab_brain_reader`(`db-roles` 會拒絕)。

### 7.3 用 Owner 的登入角色宣告預算、單價、免費端點

```sh
psql "postgresql://owner_spend@<host>:<port>/<db>"
```

```sql
-- 預算:id、幣別、上限、宣告者、安全倍數、每張圖的 token、每個請求的 overhead token
SELECT llm_spend_declare_budget('prod-2026-11', 'USD', 25, 'act:owner', 1, 4096, 1024);

-- 單價:預算、幣別、endpoint host(含 port 時要寫)、模型、輸入/輸出每百萬 token、來源、日期、宣告者
SELECT llm_spend_declare_price('prod-2026-11', 'USD', 'generativelanguage.googleapis.com',
    'models/gemini-3.1-pro-preview', 1.25, 10, '<官方價格頁網址>', '2026-10-28', 'act:owner');

-- 真的免費的本機模型服務(不是代理):
SELECT llm_spend_declare_free('127.0.0.1:11434', '*', '本機 Ollama,不轉送', 'act:owner');

-- 撤銷免費宣告:
SELECT llm_spend_revoke_free('127.0.0.1:11434', '*', '改成代理', 'act:owner');

-- 改上限;檢查 overrun 後關電路(新上限要 ≥ 已收費):
SELECT llm_spend_set_ceiling('prod-2026-11', 30, 'act:owner', '加預算', FALSE);
SELECT llm_spend_set_ceiling('prod-2026-11', 30, 'act:owner', '已檢查 overrun', TRUE);
```

### 7.4 讓服務使用預算

服務的環境變數:`LAB_BRAIN_LLM_SPEND_BUDGET=prod-2026-11`(資料庫用 `LAB_BRAIN_DATABASE_URL`,
即服務角色的連線)。設定後,遠端與本機請求都計量,只有宣告免費的端點例外。
