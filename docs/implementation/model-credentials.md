# Pasting a model-provider key, and the local model without one

Date: 2026-10-04
Scope: a product-usability and security slice of the AI model settings. **Not a milestone.** No
Requirement or Test ID was added and no milestone status changed. Scientific reasoning, LLM routing
semantics, the CognitiveRole / LogicalSlot contracts, capability requirements, project egress
policy, provenance, the Product Vertical and simulation are unchanged. The Lumi Agent benchmark was
not run.

## 1. The problem

- In the Docker deployment a researcher could not paste an API key: the container has no
  operating-system credential store, so a typed key was refused, and the only path was editing
  `deployment/docker/llm-keys.env`, restarting Docker and typing the variable's name.
- Choosing 本機模型（Ollama） still showed a key field, though Ollama needs no credential.

## 2. Secret-storage design

| Where the key is | Reference in PostgreSQL | Used when |
|---|---|---|
| The deployment's credential directory (`DirectoryCredentialStore`) | `file:lab-brain/llm/<uuid>` | `lab-brain web --credential-dir DIR` -- the Docker deployment |
| Windows Credential Manager (`WindowsCredentialStore`) | `wincred:lab-brain/llm/<uuid>` | the workspace runs natively on Windows (unchanged) |
| An environment variable of the workspace | `env:NAME` | under 進階設定 (unchanged) |

- **One boundary.** Every read goes through `SecretStore.resolve(parse_secret_ref(ref))`; every
  write through `SecretStore.store`, which returns a fresh opaque reference. A reference is resolved
  only by the kind of store it names.
- **The directory.** One file per key, named by the reference's UUID and holding the trimmed key
  and nothing else (no connection, provider or project beside it). Written to a temporary file
  opened `O_CREAT|O_EXCL` with mode 0600, fsync'd, then atomically renamed; the directory is
  (re)set to 0700. A name that is not exactly `lab-brain/llm/<uuid>` never reaches the filesystem
  (no path traversal).
- **Docker.** A named volume `credentials`, mounted at `/var/lib/lab-brain/credentials` on the
  `web` service only (not `db`, `init`, `local-models` or `secrets`); the image creates that
  directory owned by the unprivileged `labbrain` user with mode 0700, which the empty volume
  inherits. The build context is an allowlist (`.dockerignore`), so no credential file can enter
  the image; the web server has no route that serves files from it. `docker compose down` keeps the
  volume, `docker compose down -v` deletes it.
- **PostgreSQL** holds the reference and a fingerprint only (`012h` widens the `secret_ref` CHECK
  to admit `file:`). The fingerprint is HMAC-SHA256 under the deployment's salt, first four hex
  digits: non-reversible, and it contains no character of the key.
- **Pasted-key checks**, before anything is written: not empty, at most 4096 characters, no
  whitespace, line break or control character inside. A refusal never repeats the paste.
- **Rotation** (更換 API 金鑰): the new key is stored and referenced first; then the old key is
  deleted -- unless another live connection references the same stored key. Saving runs the
  connection check (檢查連線) with the new key at once, so a card that said 金鑰被拒絕 shows the new
  key's result instead of asking for a fix already made; the check changes no lifecycle.
- **Removal** (移除, `RETIRED`): the connection's stored key is deleted unless another live
  connection references it. An `env:` variable is the operator's and is never touched.
- **No orphan.** A key stored for a connection the database then refuses is deleted at once.
- **Restart.** Nothing is cached: each use resolves the reference again, so a restarted container
  (same volume) finds every key; a removed volume is reported as such (see §5).

## 3. What is and is not encrypted

- **Not encrypted**: the credential directory. It is filesystem isolation -- a dedicated volume
  mounted on one container, a 0700 directory, 0600 files owned by the workspace's user. Anyone who
  can read the Docker volume (root on the host, a Docker administrator, a backup of the volume) can
  read the keys. The page says so: 「以檔案權限保護，未加密」.
- **Windows Credential Manager** is the operating system's per-user store; the page names it and
  claims nothing more.
- **In transit** the key goes only to the provider, in the `Authorization` header: over `https://`
  to any other host, plain `http://` only to this machine, and never on to a redirect's target --
  see [model-transport.md](model-transport.md).
- **Never anywhere else**: not in PostgreSQL, a page, a log, a health record, a probe record, an
  error, a report or a fingerprint. A provider's authentication refusal (HTTP 401/403) is no longer
  read at all: providers quote the key back, often masked (`sk-proj-abc****wxyz`), a shape no
  redaction can recognise -- the record says `HTTP 401: the provider refused the credential`.

## 4. The forms

Step 1 of AI 模型設定 asks first what kind of model, and shows one of two forms (chosen by two
radio buttons and CSS alone: the workspace allows no script; without `:has()` both forms show):

- **本機模型（Ollama）**: no credential field at all. It checks Ollama right away and says
  「✓ 已連上本機 Ollama（N 個模型）」 or what to do if it does not answer. One button,
  **取得可用模型**, creates the LOCAL connection (once; afterwards it is reused) and fetches its
  models -- after checking that Ollama answers, so an unreachable Ollama creates nothing. A custom
  Ollama URL is under 進階設定.
- **外部 API**: 模型服務（Provider） / 名稱 / **API 金鑰** (a password field never filled back in) /
  **＋ 新增**. Under 進階設定: 改用既有環境變數, 改用既有憑證參照, 自訂服務網址, 類型. Exactly one
  credential source; more than one is refused.

The lifecycle after that is unchanged: get models → capability test → confirm → assign → check →
apply. The connection's details page shows 「已保存在憑證儲存空間，指紋 ****abcd」; the reference
itself is under 技術細節.

## 5. Errors, in the researcher's words

| Case | What the page says (zh-TW) |
|---|---|
| no credential storage | 這個部署目前沒有可用的憑證儲存空間…請在「進階設定」改用既有環境變數，或請部署管理者啟用憑證儲存空間。 |
| write failed | 金鑰沒有保存成功（憑證儲存空間無法寫入），也沒有新增連線。 |
| not a key (spaces, line breaks, …) | 這不是一把有效的 API 金鑰…沒有保存任何內容。 |
| a key pasted as a reference | 你在「既有憑證參照」貼上的是金鑰本身。請把金鑰貼到「API 金鑰」欄位… |
| more than one source | API 金鑰、環境變數、憑證參照只能擇一填寫。 |
| provider refused the key | 服務拒絕了這把 API 金鑰（驗證失敗）…到連線詳細頁按「更換 API 金鑰」。 (and the connection's next step becomes 修正「名稱」的 API 金鑰) |
| key missing after restart (store cleared) | 讀不到這個連線的 API 金鑰。請到連線詳細頁按「更換 API 金鑰」。 |
| Ollama not answering | 目前連不上本機 Ollama，所以沒有新增任何連線。請確認這台電腦已安裝並啟動 Ollama（ollama serve）… |

The server's rule text stays under 技術細節 with the refusal's code.

## 6. Contracts unchanged

Changed: `llm_runtime.secrets` (the directory store, the `file:` scheme, coded errors, pasted-key
checks), `llm_runtime.provider` (an authentication refusal's body is not read), `LLMSettings`
(credential modes, release on rotation/removal, coded refusals), the web forms and pages,
`lab-brain web --credential-dir/--ollama-url`, `012h`, the Dockerfile and `compose.yaml`.
Unchanged: capability probes and their judgement, lock fingerprints, slot eligibility, readiness,
activation, the active runtime's routing, the egress gate and every project's egress policy,
provenance, the research service. `test_web_llm_runtime_postgres`, `test_web_llm_authority_postgres`
and the integration LLM tests pass unchanged except two assertions: one made independent of HTML
attribute order, and the unit test of an authentication refusal, which now requires the provider's
body to be absent from the record (it used to require it, redacted).
`test_a_runtime_on_a_pasted_key_reasons_research_through_the_same_gates` shows the same refusal
without project egress and the same routing with it.

## 7. Verification

Code: `4159294` (the slice) and `c37647c` (a replaced key is checked at once -- found in the deployed
walkthrough below). CI run `37193251908` (`4159294`) and `37193982471` (`c37647c`): commit hygiene,
spec conformance, lint/types/full suite and the PostgreSQL backend profile, all green.

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| backend-free `pytest` | 1657 passed, 798 skipped (PostgreSQL / Lumerical / network) |
| fresh PostgreSQL database (55 migrations), whole suite | 2451 passed, 2 skipped (Lumerical, network), 1 failed: an assertion that still required a 401 body to be kept redacted -- now that body is not read at all; corrected, and the two LLM e2e files re-run: 22 passed. `c37647c`'s whole suite ran in CI's PostgreSQL job |
| `update_status.py --check`, obligation inventory `--check`, `verify_environment.py` | current |
| evidence, debate and root-cause benchmark reports `--check` | current (offline reports; the Lumi Agent benchmark was not run) |
| mutation battery, credential entries (fresh database) | 15/15 killed, then `rotation_leaves_the_old_refusal_standing` killed |
| mutation battery, all entries (fresh database, PostgreSQL profile) | 325/325 killed, no anchor missing (`c37647c`, 35 min) |

**Deployed** (`docker compose -p lab-brain-workspace up --build -d` from `4159294`, then `c37647c`;
`init` applied `012h`). The `credentials` volume is mounted on `web` only (`db`, `init`,
`local-models`, `secrets` do not have it); in the container the directory is 0700
`labbrain:labbrain`, each key a 0600 file of exactly the key's bytes; the image's directory is empty
and `/var/lib/lab-brain/credentials/`, `/credentials` and a `..` path answer 404. The external
provider was this machine's OpenAI-compatible stand-in (the tests' `FakeProvider`, a throwaway
random key, reached as `http://host.docker.internal:18555/v1`) -- no real provider key was used.

- **External, by the normal form**: AI 模型設定 → 外部 API → 其他 OpenAI 相容服務 + 自訂服務網址 under
  進階設定 → name, pasted key → ＋ 新增 → 取得可用模型 (連線正常, 3 個模型) → fake-reasoner →
  執行模型能力測試 (every capability passed) → 確認此模型 (已確認; offered for 主要推理 in step 3; not
  assigned -- the researcher's draft runtime was left as it was). No page contained the key; the
  database row held `file:lab-brain/llm/<uuid>` and `****59d3`.
- **A refused key**: a stale key gave 金鑰被拒絕 and the next step 修正「standin-deploy」的 API 金鑰; the
  health record is `HTTP 401: the provider refused the credential` -- the stand-in's echo of the key
  is not kept. 更換 API 金鑰 replaced the file (the old one deleted) -- and still showed the old
  refusal until 檢查連線, which `c37647c` fixed: re-done on the rebuilt deployment, the record showed
  連線正常 at the moment of saving.
- **Ollama**: 本機模型（Ollama） hides the external form; the page shows 「✓ 已連上本機 Ollama（4 個模型）」,
  取得可用模型 and 進階設定 (a custom Ollama URL) -- no key, variable or reference field.
  取得可用模型 reused the existing `ollama` connection (no new row) and refreshed its 4 models.
- **Persistence**: after `docker compose restart web`, and again after `docker compose down` +
  `up -d` (volumes kept), the same two files were there and 取得可用模型 answered 連線正常 with the
  stored key. **Removal**: a separate throwaway project (`-p lbsecretcheck`, port 8799) took a key
  pasted through the same form (0600 file, `file:` reference, fingerprint `****2bc8` -- the salt is
  per deployment); `docker compose down -v` removed its `credentials` volume, and after `up` the
  directory was empty and the database new. The throwaway project and its volumes were then removed.
- Afterwards the two stand-in connections were **disabled** (停用, reversible) so the stand-in's
  model is not offered for assignment; step 3 again offers only the Ollama models.
