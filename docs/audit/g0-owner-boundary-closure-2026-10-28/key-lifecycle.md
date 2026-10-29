# 互動簽署金鑰的生命週期

日期：2026-10-28（分支 `g0-owner-boundary-closure`）

程式：`src/lab_brain/security/key_lifecycle.py`、`src/lab_brain/security/interaction_attestation.py`。
命令：`lab-brain interaction-key ...`。這個命令只處理檔案，不連資料庫。

## 1. 修改前的缺口（先用失敗的測試證明）

測試檔 `tests/unit/test_g0_key_lifecycle_gaps.py` 只用原本就有的 API。
在修改前，五個測試全部失敗（紀錄：`evidence/key_lifecycle_gaps_before.log`）：

1. 群組或任何人都能讀的私鑰檔（例如 0644），網頁層啟動時仍然接受。
2. 沒有釘選的私鑰（或根本沒有公鑰檔），啟動時仍然接受。它簽的陳述永遠無法驗證，而且沒有任何提示。
3. 已經用 `until=` 退役的私鑰，啟動時仍然接受，並繼續簽署無法驗證的陳述。
4. 放在 git 工作目錄裡的私鑰（可能被提交），啟動時仍然接受。
5. 沒有撤銷的方法。`revoked=` 會被解析器拒絕；只要金鑰還在釘選檔裡，它的陳述就一直能驗證。

修改後，這五個測試全部通過。

## 2. 檔案

| 檔案 | 內容 | 權限與擁有者 | 設定 |
|---|---|---|---|
| 私鑰 | PEM（PKCS8）Ed25519，可用密語加密 | 0600，擁有者是服務使用者 | `LAB_BRAIN_INTERACTION_SIGNING_KEY` |
| 密語 | 只放在環境變數，不放在命令列 | — | `LAB_BRAIN_INTERACTION_KEY_PASSPHRASE` |
| 公鑰釘選檔 | 每行一把金鑰 | 0644，擁有者是維運者，服務使用者不能寫 | `LAB_BRAIN_INTERACTION_AUTHORITIES` |

釘選檔每一行的格式：

```
web:<名稱> ed25519:<base64 公鑰> [until=<含時區的時間>] [revoked=<含時區的時間>]
```

兩個選項的順序不限，但每個最多出現一次，而且一定要有時區。

私鑰和釘選檔都不放在資料庫，也不放在任何 git 工作目錄裡。

## 3. 退役和撤銷的差別

| 動作 | 用途 | 效果 |
|---|---|---|
| 退役 `until=T` | 計畫中的換鑰 | 簽署時間早於 T 的陳述仍然有效；T 之後的無效。 |
| 撤銷 `revoked=T` | 懷疑或確認金鑰外洩 | 這把金鑰的**所有**陳述都不再有效，包括簽署時間早於 T 的。 |

為什麼撤銷要讓 T 以前的陳述也失效：

- 陳述裡的 `signed_at` 是由持有私鑰的人自己寫的。
- 偷到私鑰的人可以把偽造的陳述日期寫成撤銷前一年。
- 陳述以外，沒有任何東西記錄它真正被簽署的時間（資料庫的時間也可以被寫入者改）。
- 所以「從 T 起不信任這把金鑰」唯一合理的意思是：這把金鑰的簽章不能再證明任何事。

結果：這些執行會降為 `SESSION_RECORDED_UNVERIFIED`，原因寫明「金鑰已撤銷」。
紀錄本身不刪除，產品照常運作。T 只記錄維運者採取行動的時間。

## 4. 維運者命令

先建立只有自己能進入的目錄（不在 repository 裡）：

```
install -d -m 700 /etc/lab-brain/keys
install -d -m 755 /etc/lab-brain/trust
```

產生金鑰並釘選：

```
lab-brain interaction-key generate --out /etc/lab-brain/keys/web-2026-10.pem \
    --label web:primary --authorities /etc/lab-brain/trust/interaction-authorities
```

- 私鑰以 0600 寫入，不會覆蓋已有的檔案。
- 畫面只印出金鑰識別碼和公鑰那一行，不印私鑰。
- 不加 `--authorities` 時，只印出那一行，由維運者自己加進釘選檔。
- 加 `--encrypt` 時，密語從 `LAB_BRAIN_INTERACTION_KEY_PASSPHRASE` 讀取（至少 12 個字元）。

以下情況會拒絕產生：目標在 git 工作目錄或本專案原始碼目錄內；
目錄的群組或其他人有任何權限（不是 0700）；目錄不屬於執行者；目標檔案已存在。

換鑰（新金鑰立即釘選，其他仍有效的金鑰從 `--at` 起退役）：

```
lab-brain interaction-key rotate --authorities /etc/lab-brain/trust/interaction-authorities \
    --out /etc/lab-brain/keys/web-2026-11.pem --label web:2026-11 --at 2026-11-01T09:30:00+08:00
```

換鑰步驟：

1. 執行 `rotate`，`--at` 設在幾分鐘之後，讓舊程序在重新啟動前還能簽署。
2. 把 `LAB_BRAIN_INTERACTION_SIGNING_KEY` 改成新檔案。
3. 在 `--at` 之前重新啟動網頁層。
4. 執行 `check`（見下方）。
5. 確認沒有問題後，刪除舊私鑰檔。舊公鑰那一行要保留，舊的陳述才能繼續驗證。

退役一把金鑰：

```
lab-brain interaction-key retire --authorities <釘選檔> --key-id ik:<32 個十六進位字元> [--at <時間>]
```

撤銷外洩的金鑰：

```
lab-brain interaction-key revoke --authorities <釘選檔> --key-id ik:<32 個十六進位字元> [--at <時間>]
```

撤銷步驟：

1. 先 `rotate` 產生新金鑰（或 `generate` 再釘選）。
2. 對外洩的金鑰執行 `revoke`。網頁層用這把金鑰時將無法啟動。
3. 改設定，重新啟動網頁層，執行 `check`。
4. 告知使用者：這把金鑰簽過的執行都會顯示為未驗證。

釘選檔的改寫是原子操作（先寫暫存檔再改名），註解會保留，新檔案權限為 0644。
改寫前和改寫後都會完整解析一次；檔案有錯誤時拒絕改寫。

## 5. 啟動檢查

網頁層在 `InteractionSigner.from_environment` 讀取私鑰時執行檢查。
只要有一項不通過，網頁層就拒絕啟動，並說明原因。沒有設定私鑰時不檢查，執行照常記錄為未驗證。

| 檢查 | 證明什麼 |
|---|---|
| 私鑰檔存在、是一般檔案、不是符號連結 | 不會被引導去讀別的檔案。 |
| 私鑰權限沒有群組或其他人的位元（077） | 只有擁有者能讀寫私鑰。 |
| 私鑰擁有者等於服務的有效使用者 | 不是別人放進來的檔案。 |
| 私鑰所在目錄群組或其他人不能寫 | 別人不能替換私鑰檔。 |
| 私鑰不在 git 工作目錄或本專案原始碼目錄內 | 私鑰不容易被意外提交。 |
| 有設定釘選檔，而且能讀取和解析 | 部署確實有信任錨點。 |
| 釘選檔和它的目錄群組或其他人不能寫 | 其他使用者不能改信任錨點。 |
| 服務使用者（非 root 時）不是釘選檔或其目錄的擁有者 | 服務本身不能改寫它用來驗證的公鑰。 |
| 私鑰已釘選、沒有撤銷、沒有在現在之前退役 | 這把金鑰簽的陳述能通過驗證。 |

### 不能用可攜方式檢查的部分（老實說明）

- 以 root 執行的程序可以寫任何檔案。所以服務以 root 執行時，「服務不能寫釘選檔」這項檢查沒有意義。
  這時網頁層仍會啟動（其他檢查仍然有效），但 `lab-brain interaction-key check` 會拒絕 root。
  部署應該以服務使用者身分執行這個命令。
- 檢查只讀取 `stat`。POSIX ACL、Linux capabilities、掛載選項，以及忽略權限的檔案系統都不檢查。

## 6. 維運者的檢查命令

以服務使用者身分執行：

```
sudo -u lab-brain-web env LAB_BRAIN_INTERACTION_SIGNING_KEY=... \
    LAB_BRAIN_INTERACTION_AUTHORITIES=... lab-brain interaction-key check
```

- 列出每一把釘選的金鑰和狀態（有效、何時退役、已退役、已撤銷）。
- 執行和啟動時相同的檢查，另外再拒絕 root。
- 全部通過時結束碼為 0；有任何問題時印出 `REFUSED:` 並以結束碼 2 結束。

## 7. 測試

```
.venv/bin/python -m pytest tests/unit/test_g0_key_lifecycle.py tests/unit/test_g0_key_lifecycle_gaps.py
```

15 項通過。所有金鑰都在 pytest 的暫存目錄產生，repository 裡沒有任何私鑰。
「服務使用者擁有釘選檔」的測試以 root 把檔案交給 uid 65534（nobody）來模擬非 root 服務。
不是 root 時，這個測試會跳過。

另外修改了一個既有測試：`tests/unit/test_g0_interaction_attestation.py::test_the_signer_is_optional_and_never_shows_its_key`
原本在沒有釘選檔的情況下啟動簽署者。新規則會拒絕這種情況，所以測試改成先釘選公鑰。

## 8. 剩下的風險

- 持有私鑰的人，或能控制部署設定（環境變數和釘選檔）的人，仍然可以讓陳述通過驗證。這是部署的信任根。
- 撤銷後，外洩以前的真實執行也會顯示為未驗證。這是刻意的保守選擇。
- 換鑰時如果在 `--at` 之後才重新啟動，舊程序在這段時間簽的陳述無法驗證。
- 正在執行的程序不會重新讀取釘選檔；撤銷後一定要重新啟動網頁層。
