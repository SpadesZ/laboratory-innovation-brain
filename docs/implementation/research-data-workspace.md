# Research Data, the input-selection workflow and the researcher workspace (UX pass)

Date: 2026-09-29
Scope: making Research Data a first-class input surface, turning New Research into an
input-selection workflow, a strict UX parity pass of the AI model settings against three reference
implementations, a native Traditional Chinese (Taiwan) language pass, and a System Status page that
answers operational questions. **Not a milestone.** No Requirement or Test ID was added and no
milestone status changed. M6 was not started, no simulation was implemented, and the Lumi Agent
blind benchmark was not run.

## 1. P0/P1 findings of this pass

Method: the partial work was brought up against a freshly migrated database and driven in a real
browser (import → states → New Research → confirmation → start → research task), then each defect
was reproduced before it was fixed.

| # | Finding | Class | Resolution |
|---|---|---|---|
| 1 | **A duplicate re-declared the original.** Importing the same bytes again with another kind changed the kind the New Research selector pre-selected for the ORIGINAL artifact (it took the latest declaration across items). Reproduced: a measurement report was then used as `EXPERT_HEURISTIC` evidence. | **P1** | `ResearchData.usable` takes the kind of the item actually used (the first arrival); a DUPLICATE declares nothing. Test + mutation `research_data_duplicate_redeclares_the_original`. |
| 2 | **Data stored under a label its uploader cannot read.** An import declared above the uploader's clearance was stored; the uploader could then neither read nor select it. | P1 | Refused before any write (`LabelNotCleared`); the form shows such levels disabled, with the reason. Test + mutation. |
| 3 | **The confirmation did not show everything the run would use.** Literature file, query and verification input were entered on the confirmation page itself, after the summary. | P1 (the confirmation's contract) | Moved to step 5 of New Research; the confirmation shows them and carries exactly those bytes to the start. Test + mutation `confirmation_does_not_carry_the_literature`. |
| 4 | A file re-uploaded during New Research that duplicated project data was shown as "new". | P2 | Shown as "same content as …, the existing one is used, once". |
| 5 | Importing answered the POST with a page: reloading it imported again (a DUPLICATE item each time). | P2 | Post/Redirect/Get to `/data?project=…&added=…`. |
| 6 | The start request was validated before project authorization: a non-member's malformed request got 400, not the one refusal. | P2 | Authorization first. Mutation `start_reads_the_form_before_authorizing`. |
| 7 | A mutation-battery anchor (`product_research_without_membership`) went stale when the partial work refactored `ResearchEpisodeService.run`; the battery would have reported the guard as having no teeth. | tooling | Anchor updated; every one of the battery's anchors is checked before the run. |
| 8 | Same bytes declared with a STRICTER label keep the first arrival's label (content identity: one occurrence per artifact per project). | P2, surfaced — **not changed** | Pre-existing M1 semantics; raising a label needs a reclassification path, which is a contract change outside this pass. The declared label is now recorded (`012g.declared_label`) and the page shows both and tells the researcher to ask the operator. No exposure is added: the bytes were already in the project under the first label. |

No P0 was found.

## 2. UX parity matrix (AI model settings)

Compared against the actual implementations: `SpadesZ/PC-MEF` (`pcmef/admin/templates/llm_setup.html`,
`pcmef/admin/services.py`), `SpadesZ/roothinks-1.0.1` (`app/templates/lava_setup.html`,
`app/static/js/lava_setup.js`), `SpadesZ/rootmedicals-a` (`ebm-rag/app/template/lava_setup.html`,
`ebm-rag/app/static/js/lava_setup.js`). PC-MEF is the reference for operator guidance.

| Interaction | PC-MEF | roothinks-1.0.1 | rootmedicals-a | Lab Brain before (`dabc255`) | Lab Brain now |
|---|---|---|---|---|---|
| Page narrative | Four numbered cards = four steps of one line | Three cards (connections, CPU, binding) | Three cards (add, list, bindings) | Seven-pill step list over raw tables | Four numbered cards: 新增模型連線 → 取得、測試並確認模型 → 指派模型給研究工作 → 檢查並套用配置 |
| Add a connection | One row: Provider / 名稱 / API Key / ＋新增線路; secret ref, base URL, timeout, notes folded under 進階設定 | "新增線路" adds an empty row; vendor + key typed in the row | Provider / API Key / Name → Fetch Models | 名稱 (lower-case), Base URL, LOCAL/EXTERNAL, three credential radios -- deployment internals first | 模型服務（Provider） / 名稱（選填） / API 金鑰 (or the environment-variable name when there is no secure store) / ＋ 新增; service URL, type and env reference under 進階設定 |
| Get models | Fetch per row, disabled until possible | Fetch per row | Fetch Models | 取得模型清單 on a separate page | 取得可用模型 in the connection's row |
| Choose a model | Dropdown + Set, or type an id | Dropdown after fetch | List select | Every model a link to its own page | Dropdown 要測試的模型 in the row; add-by-name on the details page |
| Test | Test (chat / vision / JSON), verified vs declared badges | Test = connectivity alert | Test Chat / Test Embedding | Checkbox list of eight probes on the model page | 執行模型能力測試 in the row; results listed as 通過：… per model |
| Lock / confirm | Connect (lock) / Unlock | Connect with confirm dialog | Connect | 鎖定 on the model page | 確認此模型 appears in the row once a tested model passed; 取消確認 on the details page |
| Assign | Table per agent; dropdown lists only Locked + compatible; Test / Lock / Unlock always visible | Service binding, Locked only | Bindings filtered by capability; a stale binding kept and flagged | Create a runtime draft first, then a slot table on its own page | Table per 模型用途 (slot): its purpose, the tests it needs, the research roles fixed to it, a dropdown of confirmed models that proved them; the draft is created on the first assignment; an applied configuration is never edited in place |
| What is missing | 還差什麼 / 怎麼補 checklist; an unmatched reason shown verbatim; hashes under 技術細節 | none (badges) | none (tags, last error) | 阻擋項目: the server's rule text, humanized | 尚待處理 / 怎麼完成 checklist; unmatched rule text kept verbatim; 注意事項 for warnings; the rule text itself under 技術細節 |
| Next step | Per row: 下一步：… | implicit (buttons enable) | status line | none | Page-level 下一步：… and per connection 下一步：… at every stage |
| Apply | No web apply (CLI freeze, by design) | Connect confirm | none | 啟用 on the runtime page | One 套用配置 button, shown only when the checklist is empty; 檢查配置; 停用目前的配置 |
| Credentials | Vault, `****abcd`, never refilled; key field disabled without a backend | Password input in the row | Password input | `env:` / `wincred:` references + fingerprint, never echoed | Same guarantees; the simple form asks for the environment-variable name when no secure store exists (the Docker case) |
| Architecture | task → model | task → connection | task → connection by capability | CognitiveRole → LogicalSlot → Model | **Preserved**: CognitiveRole → LogicalSlot fixed in code and shown read-only; the administrator chooses only Model per slot |

Adopted from PC-MEF: numbered-card narrative; the short add form with an advanced fold; a next step
for every row; the plain checklist with the verbatim fallback ("看得到總比消失好"); technical values
under details. Deliberately not adopted: a web "Lock" of bindings as a personal marker (Lab Brain's
confirm is a capability freeze the database enforces), the CLI-only freeze (Lab Brain applies in the
web by design, fail-closed on a live check), JavaScript dialogs (the workspace's CSP allows no
script).

Every stage now names its next step (exact zh-TW text):

| State | 下一步 | 尚待處理 |
|---|---|---|
| no connection | 新增模型連線（步驟 1）。 | 尚未新增模型連線 |
| connected, no models | 取得「名稱」的可用模型。 | 「名稱」還沒有可用模型 |
| models, none tested | 選一個「名稱」的模型，執行模型能力測試。 | 「名稱」的模型還沒有測試 |
| tested, not confirmed | 確認「模型」這個模型。 | 「模型」已測試，還沒確認 |
| confirmed, 主要推理 unassigned | 替「主要推理」指派模型（步驟 3）。 | 「主要推理」還沒有模型 |
| 快速處理 unassigned | 替「快速處理」指派模型（步驟 3）。 | 「快速處理」還沒有模型 |
| connection never checked / failing | 檢查配置（步驟 4）。 | 「用途」使用的模型連線「名稱」還沒檢查過 / 最近一次檢查失敗 |
| ready | 套用配置「名稱」（步驟 4）。 — one 套用配置 button | 沒有尚待處理的項目。 |
| applied | 不需要處理：配置「名稱」已套用，新的研究會使用它。 | — |

## 3. First-time researcher walkthrough

1. Open `http://127.0.0.1:8765/` → **首頁（研究工作台）**. It says 下一步：把研究資料匯入研究專案。 and
   offers **＋ 匯入研究資料** and **＋ 開始新研究**. The navigation's first entry after 首頁 is
   **研究資料**, whose tooltip reads 「要把資料交給 Lab Brain，就是來這裡」.
2. **＋ 匯入研究資料** → 研究資料. (With several projects: choose the 研究專案, 切換.) In the card
   **＋ 匯入研究資料 匯入到「專案」**: ① 選擇檔案 (.md / .txt / .csv / .json, several at once);
   ② 這是哪一類資料？ — 量測報告或實驗紀錄 / 模擬或運算紀錄 / 筆記、想法或文獻摘錄 (required, none
   pre-selected); ③ 資料分級 — 公開 / 實驗室內部 / 實驗室機密 / 保密協議（NDA）(required, none
   pre-selected; levels outside your access are shown disabled with the reason); **匯入**.
3. The result box lists each file with its status and what to do; the table below lists all of the
   project's data (狀態與下一步 for each); 狀態說明 explains every status.
4. **新增研究** → ① 研究問題 and its 分級 (required, no default), optional 問題背景; ② 研究專案
   (切換研究專案 keeps what you typed); ③ 選擇既有資料 — tick, 作為 pre-filled with the declared
   kind; ④ optional new files with their kind and 分級; ⑤ optional external sources: a local
   literature file + a query you confirm may be public, and an optional verification input;
   **下一步：確認輸入**.
5. **確認研究輸入** lists exactly what will be used: question and its classification, project, every
   data item with its kind and classification (new ones marked 新加入), background, external
   sources, verification input, AI model, external transfer, simulation. **開始研究** or 返回修改.
6. **研究任務**: the question as the heading; 目前狀態 (e.g. 等待中，可以繼續 — 正在等待這裡無法執行
   的模擬（cap:sp.mesh_sensitivity）); **繼續研究**; 執行紀錄 (第 1 次 … 暫停等待（初步結論） ·
   查看報告 · 下載 Markdown); 研究報告 (stored text, as written). Identifiers are under 技術細節.
7. **研究紀錄** lists every research task; **系統狀態** says what works and what does not.

## 4. Research Data intake workflow

`GET /data?project=<id>`; `POST /data` (multipart: `files`, `kind`, `sensitivity`, `project`,
`csrf`) → `303 /data?project=<id>&added=<item ids>#result`.

Order of checks — nothing is written before the last one passes:

1. allowed Host, CSRF token, same Origin, body ≤ 25 MB (the workspace, unchanged);
2. the project is one the read gate admits the actor to — else 403 無法進行研究;
3. at least one file; `kind` ∈ {measurement, run_record, note}; `sensitivity` ∈ the four labels —
   else 400 with the missing declaration named;
4. `ResearchData.add`: `read_gate().require_project` (active account AND active membership) →
   the kind is research material → the label is in the actor's clearance in that project — else
   403 `LabelNotCleared` ("系統沒有儲存任何內容").

Then, per file, the one authoritative path, unchanged: `IngestionService.submit` (a job with no
episode) → `ingest` (secret scan → raw store and the occurrence under the declared label → parse,
segment → evidence units → the inbox item) → one `research_data_declarations` row (kind, label, file
name). Media types follow the CLI's table; anything else is read as `application/octet-stream`.

| State (canonical) | 繁體中文 | What happened / what to do |
|---|---|---|
| READY | 可用於研究 | 不需要處理：可以在「新增研究」直接選用。 |
| PARTIAL | 部分可用 | 有一部分無法讀取，可讀取的部分仍可選用；缺少的部分重要時修正後重新匯入。 |
| PROCESSING | 處理中 | 系統仍在處理，請稍後重新整理。 |
| NEEDS_REVIEW | 需要人工確認 | 有內容需要人工確認（例如與既有資料矛盾），確認後才會變成可用；聯絡審查者。 |
| DUPLICATE | 與既有檔案內容相同 | 內容和「原檔」完全相同，沒有重複加入；請選用原本那一份；分級沿用原檔（and, if a different label was declared, says so）。 |
| BLOCKED | 已被安全規則擋下 | 儲存前就被擋下（例如疑似含有密碼或私鑰）；移除敏感內容後重新匯入。 + 原因 |
| FAILED | 處理失敗 | 無法讀取；看原因、修正檔案後重新匯入。 + 原因 |

The 原因 is the M1 message catalog's summary for the item's error, authorized as `lab-brain
explain` is; the ingestion codes have Traditional Chinese renderings, any other code shows the
catalog's sentence. The canonical state, item id, artifact id, declared kind and labels, units and
error ids are under 技術細節; the state is also each badge's tooltip.

Who sees what: the inbox's rule — an actor the gate admits to the project sees its items' names and
states, never evidence bodies; data under a label the actor cannot read is listed with
"分級高於你在這個研究專案的閱讀權限：會列出，但你無法使用" and never offered for research.

## 5. New Research data-selection workflow

Routes: `GET /runs/new?project=<id>`; `POST /runs/new` (switch project: typed text kept, ticks
dropped when the project changes — another project's data is never carried); `POST /runs/review`
(confirm); `POST /runs` (start).

- **The selector** is `ResearchData.usable`: this project's items only; one per artifact (its first
  arrival); READY or PARTIAL; at least one evidence unit; under a label the actor can read now. The
  kind is pre-selected from the first arrival's declaration; the researcher may choose another for
  this run (the trust class of a run's statement is always the researcher's declaration, §6.5).
- **Confirm** validates everything before writing anything (question and its label, every ticked
  item ∈ the selector with a kind, new files' kind and label, the literature pair and its public
  confirmation, the literature file's shape); then imports new files through §4 (clearance first);
  then shows the exact inputs. A new file identical to project data resolves to the existing
  artifact — used once, shown as such. The page's hidden fields carry exactly what it shows; the
  literature file and the verification input travel as base64 of the bytes that were sent.
- **Start** authorizes the project first, re-validates everything (hidden fields are client data),
  and calls `ResearchEpisodeService.run` with `project_data`. The service authorizes every artifact
  (`gate.authorize_artifact`) before any write, then admits the artifact's EXISTING units through the
  same `StatementAdmitter` an uploaded document uses — no second ingestion, no copied unit, no second
  scientific identity. The report lists each as role `research data`, "already in the project; used
  as ingested, not ingested again".
- **Cross-project data** is never listed, and is refused at confirm (400), at start (400) and in the
  service (`ScientificReadRefused`), with nothing written.

## 6. Traditional Chinese terminology (Taiwan)

One vocabulary, applied on every primary page. Canonical identifiers are unchanged in the database,
in reports and under 技術細節; a report's own text is never translated.

| Concept (canonical / English UI) | 繁體中文 (chosen) | Replaced |
|---|---|---|
| Research workspace | 研究工作台 | 研究工作區 |
| Research data / Import research data | 研究資料 / 匯入研究資料 | — |
| Project | 研究專案 | project, Project |
| Episode | 研究任務 | 研究 episode, Episode |
| Research run | 執行 / 第 N 次 / 執行紀錄 | run, Run 數, research run |
| Continue (an episode) | 繼續研究 | 續跑 episode |
| Material kind (trust class) | 資料類型 (量測報告或實驗紀錄 / 模擬或運算紀錄 / 筆記、想法或文獻摘錄) | 宣告為, INTERNAL_MEASUREMENT … |
| Sensitivity label | 資料分級 (公開 / 實驗室內部 / 實驗室機密 / 保密協議（NDA）) | 機密分級, PUBLIC … |
| Clearance | 閱讀權限 | 權限 |
| Evidence unit | 段落 | 單元 |
| LLM settings | AI 模型設定 | LLM 設定 |
| Runtime | 模型配置 | 執行環境 |
| Runtime readiness | 配置檢查 | 執行環境就緒狀態 |
| Activate / Deactivate | 套用配置 / 停用目前的配置 | 啟用 / 停用 |
| Connection | 模型連線 | 連線 |
| Fetch models | 取得可用模型 | 取得模型清單 |
| Declare a model | 手動加入模型名稱 | 宣告模型 |
| Capability test | 模型能力測試 | 能力測試 |
| Lock / Locked / Unlock | 確認此模型 / 已確認 / 取消確認 | 鎖定 |
| Proven capabilities | 最近一次測試結果 / 通過：… | 已證實能力 |
| Lifecycle | 狀態 | 生命週期 |
| Slot (LogicalSlot) | 模型用途 (主要推理 / 快速處理 / 獨立批判 / 本機私有模型 …) | Slot, 快速輔助 |
| Role (CognitiveRole) | 研究角色 | 角色 |
| LOCAL / EXTERNAL | 本機模型 / 外部 API | LOCAL / EXTERNAL, 本機 / 外部服務 |
| Egress / egress policy | 外部傳輸 / 外部傳輸設定 | 外送, 外部模型外送 |
| Egress gate | 外部傳輸規則 | 外送閘門 |
| Blockers / Warnings | 尚待處理 / 注意事項 | 阻擋項目 / 警告 |
| Governed moves (belief) | 狀態變更紀錄 | 受治理的轉移 |
| Belief state | 各假說目前的狀態 | 信念狀態 |
| Provenance | 來源追溯 | 溯源 |
| Technical details | 技術細節 | — |

Enforced by `test_the_primary_chinese_pages_speak_the_researchers_language` (no legacy phrase on
any primary page; no English backend noun — project, episode, run, runtime, slot, egress, lifecycle
— outside the technical details and the stored report) and by
`test_the_english_interface_is_complete`.

## 7. No scientific or runtime contract changed

Changed: the web layer (`interfaces/web/*`, new `workspace_pages.py`, `llm_guide.py`); the new
`research/data.py`; the new table `012g_research_data_declarations` (append-only; stores what was
declared, nothing else); `ResearchRequest.project_data` (additive: existing units admitted through
the same admitter; a request without it behaves exactly as before); `ResearchEpisodeService.
capabilities()` (a read); `LLMSettings.credential_problem` (a read-only accessor over the existing
check); `compose.yaml` (`TZ` for displayed times).

Unchanged: the ingestion pipeline and content identity; the secret scan; the admission gate and
trust classes; segmentation; debate, critique, verification planning and execution; the belief
path; the report and its renderers; the continuation path; LLM registry rules, probes, locks,
bindings, readiness and activation (the database's rules on `012e`/`012f`); the egress gate; every
migration before `012g`; the CLI. Stored scientific evidence and reports are never rewritten by the
locale: `test_the_interface_switches_language_and_the_research_does_not` still holds byte-for-byte.

## 8. Docker usage

```powershell
docker compose up --build        # open http://127.0.0.1:8765/
```

Navigation: 首頁 `/` · 研究資料 `/data` · 新增研究 `/runs/new` · 研究紀錄 `/episodes` · AI 模型設定
`/settings/llm` (LLM administrators only) · 系統狀態 `/status`. The current model configuration is
`/runtime`; a project's external transfer setting is `/projects/<id>/egress`. `LAB_BRAIN_TZ`
(default `Asia/Taipei`) sets the time zone pages show times in; stored times are UTC and unchanged.
In the container no secure key store exists: the AI model settings ask for the name of an
environment variable from `deployment/docker/llm-keys.env`.

## 9. Verification

On the final code, locally (Windows, Python 3.12, PostgreSQL 17 + pgvector):

| Check | Result |
|---|---|
| `ruff check src tests scripts`, `ruff format --check` | clean (425 files) |
| `mypy` (strict) | no issues in 236 source files |
| backend-free suite `pytest -q` | 1645 passed, 787 skipped (backend-gated) |
| fresh database: 54 migrations applied, `migrate.py --status` idempotent | yes |
| PostgreSQL suite `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` on that fresh database | 2430 passed, 2 skipped (Lumerical, network) |
| executed-coverage gate, `update_status.py --check`, obligation inventory `--check` | current |
| evidence, debate and root-cause benchmark reports `--check` | current |
| mutation battery (PostgreSQL profile, its own fresh database) | 311/311 killed; each of the 18 new mutations killed by the test written for it |

In a browser (the development server, then the rebuilt Docker deployment): import → READY,
DUPLICATE (with the stricter-label notice), BLOCKED (a private key), FAILED (a binary file) →
New Research with existing data, a new note, a duplicate re-upload, a literature file with a public
query and a verification input → confirmation → start → research task SUSPENDED on the missing
simulator, report recorded. The AI model settings were walked with a real local model (Ollama,
qwen2.5:7b) through add → get models → test → confirm → assign 主要推理 and 快速處理 → apply, the
next step and the checklist correct at every stage, in the development database only.

**CI.** GitHub Actions run 36482135433 at `7f795c0` succeeded: commit hygiene, spec conformance,
lint / types / full suite, and the PostgreSQL backend profile (fresh 54-migration apply).

**Deployed.** `docker compose up --build -d` from `7f795c0`: `init` applied `012g` to the existing
deployment database (53 → 54 migrations, an upgrade, nothing reset), every service healthy, pages
in Asia/Taipei time. In the deployed browser UI at `http://127.0.0.1:8765/` (繁體中文), in project
`prj:lab`: 研究資料 → 匯入 the demo report as 量測報告或實驗紀錄 / 實驗室內部 → 可用於研究 →
新增研究 (default project `prj:lab`, the report listed once, pre-selected as measurement) → a new
note and a verification input → 確認研究輸入 listing exactly those → 開始研究 → 研究任務 等待中，可以
繼續, waiting on `cap:sp.mesh_sensitivity`, the report recorded with both items as research data
"used as ingested". 系統狀態: database, storage, import, Ollama reachable, no external API, Lumerical
a known limit. AI 模型設定: the local setup's confirmed models are listed and the page says
下一步：替「主要推理」指派模型 — the binding is left to the user. The Lumi Agent benchmark project
was not touched.
