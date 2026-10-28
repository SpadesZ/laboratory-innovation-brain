# 測試證據對帳(2026-10-28)

目的:每份 G0 報告寫的變異測試數字,都要對得上 repo 裡的證據檔。
規則:證據檔最後一行是那一次執行的結果。報告數字若合併了「第一次執行 + 之後的重跑」,
而重跑沒有另存檔案,就標為 **合併計算(重跑沒有證據檔)**。不改寫舊報告的歷史內容,只在舊報告加勘誤註記。

| 報告 | 報告寫的 | 證據檔 | 證據檔的結果 | 對帳結果 |
|---|---|---|---|---|
| `g0-research-reliability-2026-10-21` | 701 條中 695 被抓到 | `evidence/mutation_battery_full_8fefade.log` | 695/701 | 一致(報告沒有宣稱全部抓到) |
| `g0-exploratory-screening-2026-10-27` | 20/20 | `evidence/mutation_battery_g0_screening.log` | 20/20(其中 1 條 ERROR 經手動重跑判定為真擊殺,報告已說明) | 一致,但手動重跑沒有證據檔 |
| `g0-screening-v2-closure-2026-10-27` | 52/52 | `evidence/mutation-targeted-52.log` | 51/52 | **合併計算**:第一輪 51/52 + 修正後重跑 1/1;重跑沒有證據檔 |
| `g0-offline-integrity-closure-2026-10-27` | 756/756 | `evidence/mutation-full-756.log` | 756/756 | 一致(一次完整執行) |
| 同上(目標 76 項) | 72/76 後重跑 6/6 | `evidence/mutation-targeted-76-first-run.log` | 72/76 | 一致(報告寫明是兩次);重跑沒有證據檔 |
| `g0-reliability-bilingual-closure-2026-10-28` | 778/778 | `evidence/mutation-full-778.log` | 777/778 | **合併計算**:777/778 + 補測試後重跑 1/1;重跑沒有證據檔 |
| `g0-evidence-auth-cost-closure-2026-10-28` | 最終 795/795(一次完整執行) | `evidence/mutation-full-795-final-50c2c15.log` | 795/795 | 一致;另兩個中間執行(793、794)也保存並在報告列出 |

## 結論

- 兩份報告(screening V2、bilingual)的「全部抓到」是合併計算,不是一次完整執行。
  它們修正的缺口在後續完整執行中都被抓到(`mutation-full-756.log`、`mutation-full-795-final-50c2c15.log` 都包含相同項目),
  所以結論沒有錯,但當時的數字沒有單一證據檔支持。已在兩份報告加勘誤。
- 從 `g0-evidence-auth-cost-closure` 開始的規則:報告的變異測試數字**必須**是一次完整執行、且證據檔存在;中間執行另存並列出。
- 本分支的最終數字依同一規則產生,見本分支報告。
