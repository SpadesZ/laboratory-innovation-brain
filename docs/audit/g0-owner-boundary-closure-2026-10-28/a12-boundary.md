# A12 的部署邊界：直接 SQL 修改帳號

日期：2026-10-28（分支 `g0-owner-boundary-closure`）

**結論：A12 仍然是開放的 Owner 決定。** 這次的修改讓直接 SQL 修改「留下證據」（tamper-evident），
但沒有讓它「無法發生」（不是 tamper-proof）。超級使用者和資料表擁有者仍然可以繞過。

## 1. A12 是什麼

帳號安全稽核（2026-10-20，§7 和 §8）：擁有資料庫寫入或 migration 權限的人，
可以直接用 SQL 改帳號的角色或狀態，而且不會留下帳號事件。
最小權限角色只限制服務本身。

修改前的證據：`evidence/a12_before_011u.log`（稽核表不存在，直接修改沒有任何紀錄）。

## 2. 信任邊界（文字圖）

```
   [網頁使用者] --HTTPS--> [網頁層 / lab_brain_app 角色]
                               |  資料列權限；觸發器約束它
                               v
 +--------------------------- PostgreSQL ---------------------------+
 |  accounts / project_memberships / account_events                  |
 |     | AFTER 觸發器（ENABLE ALWAYS，SECURITY DEFINER）               |
 |     v                                                             |
 |  account_change_audit（只能新增，雜湊鏈）+ account_change_audit_head |
 |                                                                   |
 |  ===== 以下不受觸發器約束（信任根）=====                              |
 |  superuser、資料表擁有者（migrator `lab_brain`）                     |
 |     可以：DISABLE TRIGGER、DROP、TRUNCATE、改寫稽核表並重算雜湊鏈      |
 +-------------------------------------------------------------------+
                               |
     lab-brain admin account-audit  -->  印出鏈頭 SEQ:DIGEST
                               |
                               v
               [資料庫以外的紀錄]（Owner 決定要不要建立）
               只有在這裡保存過的鏈頭，才能發現超級使用者的改寫
```

## 3. Migration `011u_account_change_audit.sql`

記錄的內容（對所有受觸發器約束的寫入者都一樣）：

| 資料表 | 記錄的操作 |
|---|---|
| `accounts` | INSERT；UPDATE 角色、狀態、email 驗證、核准、密碼雜湊（只記 `password_replaced`，不記雜湊）；DELETE；TRUNCATE |
| `project_memberships` | INSERT；UPDATE 角色、clearance、核准範圍、`active`、授權者；DELETE；TRUNCATE |
| `account_events` | INSERT（應用程式自己的事件）；TRUNCATE |

每一列稽核紀錄包含：舊值和新值、登入角色（`session_user`）、`SET ROLE` 的值、
`application_name`、交易編號（txid）、資料庫時間，以及雜湊鏈欄位。

保護方式：

- 記錄用的觸發器函式是 SECURITY DEFINER，擁有者是 migrator。稽核列以 migrator 身分寫入。
- 稽核表的 BEFORE INSERT 觸發器（以呼叫者身分執行）只接受擁有者寫入。服務角色直接 INSERT（偽造）會被拒絕。
- 稽核表的 UPDATE、DELETE、TRUNCATE 一律拒絕。鏈頭表只能由寫入稽核列的過程移動。
- 所有觸發器都設為 ENABLE ALWAYS，所以 `session_replication_role = replica` 也不會略過它們。
- 每一列的 `row_digest` = SHA-256（前一列的 digest 和這一列的欄位）。鏈頭表的列鎖讓並行寫入排隊，不會分岔。

`lab-brain admin account-audit` 會：

1. 在 Python 端重新計算每一列的 digest，並檢查鏈從起點到鏈頭是否完整；
2. 用 `--expect-head SEQ:DIGEST` 比對先前保存在資料庫以外的鏈頭；
3. 列出「同一個交易裡沒有同一帳號的應用程式事件」的變更。

鏈損壞或鏈頭不符時，結束碼為 2。

套用方式（lead 會把 011u 加在 `scripts/migrate.py` 的 011t 之後）：

```
psql -v ON_ERROR_STOP=1 -f migrations/011u_account_change_audit.sql "$DATABASE_URL"
```

這個檔案可以重複套用。

## 4. 偵測到什麼、阻止了什麼

| 情況 | 結果 |
|---|---|
| 服務角色直接把帳號改成 ADMIN | **不阻止**（改動會生效）。**會偵測**：留下稽核列，報告列為「沒有應用程式事件」。 |
| 服務角色直接新增成員資格 | 不阻止。會偵測。 |
| 服務角色更新、刪除、TRUNCATE、偽造稽核列 | **阻止**。 |
| 服務角色移動鏈頭、停用觸發器、設定 replica 模式、DROP 或替換函式 | **阻止**。 |
| 操作者命令列 `lab-brain admin member` | 會記錄，並列為「沒有應用程式事件」（寫入者是 migrator）。這是預期的，應定期檢視。 |
| 服務角色同時寫入一筆假的帳號事件 | 報告會顯示為「已有事件」，但稽核列仍保留登入角色、舊值和新值。事件只是應用程式的說法，不是證明。 |
| 超級使用者或擁有者先停用觸發器再修改 | **不偵測**。沒有任何稽核列。 |
| 超級使用者刪除稽核列 | 如果沒有同時修改鏈頭：會偵測（鏈頭不符）。 |
| 超級使用者刪除稽核列並重算鏈頭 | 只有比對資料庫以外保存的鏈頭才能發現。 |

## 5. 測試（以非超級使用者連線證明）

測試資料庫的使用者 `lab_brain` 是 SUPERUSER。所以關於服務角色的每一項主張，
都是用一個臨時的非超級使用者角色連線證明的。這個角色由 `deployment.grant_database_roles`
（也就是 `lab-brain admin db-roles`）授權，跟正式部署的 `lab_brain_app` 一樣，測試後刪除。

```
LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_wpc \
  .venv/bin/python -m pytest tests/integration/test_g0_a12_boundary_postgres.py
```

6 項通過：

1. 服務角色直接改角色：改動生效（A12 未關閉），並被記錄、被列為沒有事件；命令列報告也顯示它。
2. 應用程式自己的變更（核准、改角色、停權、恢復、建立專案、加入、修改、移除成員）都有對應事件，報告一項都不列。
3. 服務角色不能更新、刪除、TRUNCATE、偽造稽核列，不能移動鏈頭，不能停用觸發器，不能設定 replica 模式，不能 DROP 或替換函式。
4. 超級使用者仍然可以繞過（照文件所說）：停用觸發器後的修改沒有紀錄；刪除稽核列會讓鏈損壞；
   連鏈頭一起改寫後，資料庫內看起來完整，只有比對外部保存的鏈頭才會失敗。最後整個交易回滾。
5. 鏈頭不符時，命令以結束碼 2 拒絕。
6. 兩個並行寫入者：第二個會等第一個提交，鏈不會分岔。

## 6. 需要的部署設定變更（在 `deployment.py`，由負責的 agent 加入）

觸發器已經擋住服務角色。以下是縱深防禦，建議加在 `grant_database_roles` 的 `statements` 裡（表存在時）：

```
REVOKE INSERT, UPDATE, DELETE ON account_change_audit, account_change_audit_head FROM "<app_role>"
```

稽核表沒有密碼雜湊，稽核角色保留 SELECT 即可。

## 7. 能關閉 A12 的部署控制（都還沒有做，不聲稱已完成）

- migrator 的帳密和服務分開，離線保管，只在 migration 時使用。
- 任何服務都不用超級使用者連線；日常也不用 migrator 連線。
- 用 pgaudit 記錄 DDL 和角色變更，並把日誌和 WAL 封存到資料庫以外、只能新增的儲存空間。
- 定期把 `account-audit` 印出的鏈頭保存到資料庫以外（例如另一台機器或簽章的紀錄）。
- 對 migrator 的使用採取雙人規則。
- 或者（2026-10-20 報告 §8 第 3 點）：讓觸發器直接拒絕沒有 ADMIN 事件的角色或狀態變更。代價是操作者命令列也必須經過帳號系統。

## 8. Owner 決定

1. A12 是否接受「偵測但不阻止」作為目前的狀態。
2. 上面第 7 節的部署控制要做哪些、由誰負責。
3. 鏈頭要保存在哪裡、多久保存一次、由誰比對。
4. 操作者命令列的成員資格變更要不要也寫帳號事件（目前會被列為「沒有事件」）。
