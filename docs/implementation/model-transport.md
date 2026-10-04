# Where a model-provider call may go: https, and no redirects

Date: 2026-10-04
Scope: a transport-security follow-up to [model-credentials.md](model-credentials.md), closing two
P1s of its review, and a locality follow-up closing a third (§6). **Not a milestone.** No Requirement or Test ID was added and no milestone status
changed. The credential UI, the secret store, the runtime's routing, project egress, provenance and
the scientific workflow are unchanged. The Lumi Agent benchmark was not run.

## 1. The problems

- **P1-A, plaintext.** A custom EXTERNAL connection accepted `http://` to any host. Every call
  carries `Authorization: Bearer <key>`, and a research call carries the prompt with its evidence,
  so a remote `http://` endpoint would receive both in clear -- on every network in between.
- **P1-B, redirects.** `urllib` follows 301/302/303/307/308 and copies the request's headers,
  `Authorization` included, to whatever the answer names: another host, or `https://` down to
  `http://`.

## 2. The rule

**Plaintext `http://` only to this machine; every other host is `https://`.** "This machine" is
loopback (`127.0.0.0/8`, `localhost`, `[::1]`) -- intrinsically -- plus exactly the hosts the
RUNNING deployment declares (`local_hosts`). The container deployment declares the Docker host
(`--host-gateway host.docker.internal`); a deployment that does not declare it treats that name as
any other remote host. Nothing infers locality from a host name. Therefore:

| Connection | Allowed |
|---|---|
| LOCAL (this machine by definition, `012e`/`012f`) | `http://` or `https://` |
| EXTERNAL on another host | `https://` only |
| EXTERNAL on this machine (a local gateway; the tests' stand-in) | `http://` or `https://` -- plaintext never leaves the machine |

It holds wherever the credential comes from (pasted, environment variable, existing reference) and
for a connection with none.

**Redirects: none is followed**, the same-origin ones included. A 3xx ends the call as a
`PROTOCOL_ERROR` ("the endpoint redirected the call, and a model-provider call never follows a
redirect"). Neither its body nor its `Location` is read into any record, error or page. One rule
with no judgement of which target is "safe": a provider that moved is re-added at its new
`https://` address.

## 3. Where it is enforced

The rules are two functions of `llm_runtime.provider`, both taking the deployment's declaration
as a REQUIRED argument -- there is no default to fall back on: `plaintext_refusal(url,
local_hosts)`, and `endpoint_refusal(url, reach, local_hosts)`, which is what a stored row must meet
at the moment of use: `plaintext_refusal`, and a LOCAL row is this machine (LOCAL skips the egress
gate, so a LOCAL row naming an undeclared host would carry research off the machine unguarded).
They are applied at every boundary a call or a row passes:

| Boundary | What happens to a refused endpoint |
|---|---|
| `LLMSettings.add_connection` | refused (`url.plaintext`) BEFORE the credential is stored, resolved or parsed -- for every credential mode |
| database, `012i` (coarse) | `CHECK` on `llm_connections`: an ENABLED row is `https://` or a this-machine name (loopback, `host.docker.internal`). `NOT VALID`: an older row does not stop the migration. Still enforced on every later INSERT/UPDATE, so such a row can be disabled or retired, never (re-)enabled. **Defense in depth only** -- see below |
| fetch models, health check, capability test, key rotation, enabling | `endpoint_refusal` under the deployment's declaration: refused (`url.plaintext`, or `local_remote` for a LOCAL row on an undeclared host) before the key is read; nothing is recorded or sent |
| readiness | a blocker on the slot: the runtime cannot be activated |
| `load_active_runtime(..., local_hosts=...)` | the LAST boundary before research reaches a network: `endpoint_refusal` under the running deployment's declaration (required argument; the workspace passes its own from one helper), raising `RuntimeUnavailable` before the key is read; each route's client is built with the same declaration |
| `OpenAICompatibleClient(..., local_hosts=...)` | the backstop for any caller: refused before a request is built or a connection opened. Built without a declaration, a client treats every host but loopback as remote |
| `OpenAICompatibleClient` opener | `_NoRedirects`: every 3xx refused, for discovery, health, probes and inference alike |

### Why the authoritative boundary is at use, not in the row

Which hosts are "this machine" is a property of the running deployment (its `--host-gateway`), not
of a row: the same database can be read by the container deployment, where `host.docker.internal`
is the machine the workspace runs on, and by a native one, where that name means nothing -- or
resolves somewhere else. A row cannot carry that fact and the database cannot see it. So the
database constraints (`012f` for LOCAL, `012i` for plaintext) are COARSE: they admit
`host.docker.internal` for any deployment and keep out what is wrong everywhere (a remote
`http://` host). **An ENABLED row is not proof that its endpoint is usable here.** The decision is
taken where the declaration is known -- by the process that was started with it -- and as late as
possible: in `LLMSettings` for every settings step, in `load_active_runtime` for research, and in
the client itself, each given the declaration explicitly. A boundary that is not given one fails
closed (loopback only).

The page says (zh-TW) 「外部服務的網址必須是 https://。只有這台電腦上的模型（例如本機 Ollama）可以使用
http://；連到其他主機時，API 金鑰與研究內容會以未加密方式傳送。沒有保存或傳送任何內容。」; the service-URL
hint says `https://` unless the service is on this machine; the protocol-error explanation now names a
redirect as one cause.

## 4. Tests

`tests/unit/test_llm_transport.py` -- real sockets; TLS endpoints with a throwaway CA made by
`openssl` for the session and trusted through `SSL_CERT_FILE` (the client is not configured for the
test; without the CA the same endpoint is refused, which the last test shows):

| # | Proven |
|---|---|
| 5 | `https://` → `http://` redirect, each of 301/302/303/307/308, GET and POST: the plain target -- which answers as a provider -- receives no request |
| 6 | `https://127.0.0.1` → `https://localhost` (another origin): no request reaches it |
| 7 | through `RouteCompletion` (research inference): the evidence-bearing prompt reaches only the named endpoint |
| 8 | a same-origin `https://` redirect is refused too; the other path is never requested |
| 9 | `https://` providers work: models listed, chat answered, the key sent to the named endpoint |
| -- | the predicate's table (incl. `127.0.0.1.nip.io`, `localhost.evil.test`, IPv4-mapped IPv6); a remote `http://` endpoint gets no connection at all; a probe is not redirected |

`tests/e2e/test_web_llm_transport_postgres.py` -- the workspace and services on PostgreSQL:

| # | Proven |
|---|---|
| 1 | a remote `http://` EXTERNAL connection, pasted key, `custom` and an overridden preset, en and zh-TW: 409 with the explanation; the credential directory is never written; no row |
| 2 | an environment variable, an existing stored reference, no credential and the service API's every mode: refused the same; raw SQL is refused by `012i` |
| 3 | the Ollama form (loopback `http://`), a declared Docker host (`http://host.docker.internal`), and a loopback EXTERNAL stand-in still work |
| 4 | a historical row (written around `012i`): fetch, health, probe, rotation and re-enabling refused before any request; it can be disabled and retired; in an ACTIVE runtime, readiness blocks it, `load_active_runtime` refuses, a research request answers 409 -- and nothing was opened to the host |
| 5-7 | a provider that redirects, through every service path: the research run stops at `hypotheses FAILED ProviderError: PROTOCOL_ERROR: HTTP 307: ...`; discovery 409; health `PROTOCOL_ERROR`; probes fail -- the target receives nothing, and no key, redirect body or target address is in any table |
| 10 | unchanged: every existing LLM routing, egress, authority, credential and Ollama test |

Mutation battery: nine entries, one per check -- the predicate, the backstop, the redirect
handler, the redirect's words, creation, use, re-enabling, readiness, the active runtime. The
locality tests and their six entries are in §6.

## 5. Verification

Code: `c3e7181`. CI run `37203562579`: commit hygiene, spec conformance, lint/types/full suite
and the PostgreSQL backend profile, all green; the TLS transport tests ran there (Linux, `openssl`
present -- in CI a missing `openssl` fails them rather than skipping).

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| backend-free `pytest` | 2470 collected: 1664 passed, **2 failed**, 804 skipped (backend-gated). The two failures were the status-freshness tests, run before `update_status.py` regenerated `IMPLEMENTATION_STATUS.md` for `012i`; this record first omitted them (corrected in §6). After regeneration a bare run executes 1666 of the 2470 -- as the status file states -- and CI's Linux job ran 1663 passed, 807 skipped |
| fresh PostgreSQL database (56 migrations), whole suite | 2468 passed, 2 skipped (Lumerical, network), 0 failed; requirement coverage current |
| the new tests, repeated | unit 9/9 x 10 runs, unit + e2e 15/15 x 3 runs |
| `update_status.py --check`, obligation inventory `--check`, spec tests | current; 206 passed |
| evidence, debate and root-cause benchmark reports `--check` | current (offline reports; the Lumi Agent benchmark was not run) |
| mutation battery, the nine transport entries (fresh database) | 9/9 killed |
| mutation battery, all entries (fresh database, PostgreSQL profile) | 334/334 killed, no anchor missing (41 min) |

**Deployed** (`docker compose -p lab-brain-workspace up --build -d` from `c3e7181`): `init` applied
`012i`; the constraint is present and NOT VALID; the existing rows (the `ollama` LOCAL connection and
two DISABLED loopback-gateway stand-ins) were untouched. Through the deployed form, with cookies and
CSRF as a browser: an external service at `http://models.example.org/v1` with a throwaway dummy key
answered 409 with 「An external service must use https://…」, repeated no key, wrote no file to the
credentials volume (still the same two) and added no row; 本機模型（Ollama） → 取得可用模型 answered
303 and recorded `REACHABLE`, 4 models -- plain `http://` to the Docker host is this machine.

## 6. Locality follow-up: the Docker host only where declared

**The P1.** The rule above said the Docker host is this machine only where the deployment declares
it, but three boundaries did not ask: `plaintext_refusal` defaulted its declaration to
`{host.docker.internal}`, `OpenAICompatibleClient` called it without one, and `load_active_runtime`
was not given the workspace's declaration. A historical ACTIVE runtime on
`http://host.docker.internal:...` therefore passed the research runtime and the client backstop in
a deployment that never declared that host.

**The fix** (smallest coherent: no new module, no schema change):

- `plaintext_refusal(url, local_hosts)` has no default; `endpoint_refusal(url, reach, local_hosts)`
  adds the LOCAL-is-this-machine check at use.
- `OpenAICompatibleClient(..., local_hosts=())`: the declaration is explicit; built without one,
  a client trusts loopback only (and bypasses proxies for loopback only).
- `LLMSettings` builds every client with its own declaration (`_declared_client`); an injected
  factory is still the caller's.
- `load_active_runtime(connection, secrets, *, local_hosts)` -- required, keyword-only; it judges
  every route with `endpoint_refusal` under that declaration before reading a credential, and
  builds each route's client with it.
- `readiness.evaluate(..., transport_problem=...)` -- required; the settings service passes its own.
- The workspace loads the active runtime from one helper, `_load_runtime`, which passes
  `local_hosts=self._local_hosts`; its local-model checks build their clients with it too.
- The database constraints are unchanged and described above as coarse.

| # | Proven (`tests/unit/test_llm_transport.py`, `tests/e2e/test_web_llm_transport_postgres.py`) |
|---|---|
| 1 | `host.docker.internal` without a declaration: refused for plaintext, and as LOCAL even over `https://`; with the declaration, this machine; look-alikes (`host.docker.internal.evil.test`) never |
| 2 | a client constructed directly, with no declaration, refuses `http://host.docker.internal:<port>` before opening a connection -- though the endpoint there answers; given the declaration, the same client reaches it |
| 3 | one database, two deployments: in the undeclared one, the ACTIVE runtime routed through the Docker host is refused by `load_active_runtime` and by a research request (409) before any credential is resolved (a recording `SecretStore.resolve` saw no call) and before any connection is opened; settings steps refuse with `local_remote` / `url.plaintext`; readiness blocks it |
| 4 | the declared workspace carries its declaration to research: the same rows reason research through the Docker host (303, the model answered), and `load_active_runtime` with the declaration returns the runtime again |
| 5 | in the declared deployment, 本機模型（Ollama） at `http://host.docker.internal:<port>/v1` is added from the form and its 3 models fetched |
| 6 | loopback `http://` needs no declaration, for LOCAL and for the accepted EXTERNAL local-gateway case |
| 7 | every remote-`http://`, redirect and TLS test of §4 unchanged and passing |

In the tests `host.docker.internal` is made to resolve to 127.0.0.1 (as Docker makes it resolve to
the host); that is name resolution only -- whether anything may be sent there is decided by the
declaration, which is what the tests vary.

Mutation battery: six entries -- a client trusting the Docker host by name, the LOCAL row not
re-checked at use, the active runtime trusting it by name, the workspace dropping the declaration,
the settings client dropping it, the local-model check dropping it -- and the two transport entries
re-anchored on the refactored checks.

### Verification

Recorded in the follow-up commit, once CI and the full mutation battery have run.
