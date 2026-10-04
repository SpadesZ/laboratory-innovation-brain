# Where a model-provider call may go: https, and no redirects

Date: 2026-10-04
Scope: a transport-security follow-up to [model-credentials.md](model-credentials.md), closing two
P1s of its review. **Not a milestone.** No Requirement or Test ID was added and no milestone status
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
the same list the `LOCAL` reach already uses: loopback (`127.0.0.0/8`, `localhost`, `[::1]`), and
the Docker host (`host.docker.internal`) where the container deployment declares it. Therefore:

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

The rule is one function, `llm_runtime.provider.plaintext_refusal(url, local_hosts)`, applied at
every boundary a call or a row passes:

| Boundary | What happens to a refused endpoint |
|---|---|
| `LLMSettings.add_connection` | refused (`url.plaintext`) BEFORE the credential is stored, resolved or parsed -- for every credential mode |
| database, `012i` | `CHECK` on `llm_connections`: an ENABLED row is `https://` or this machine. `NOT VALID`: an older row does not stop the migration, and is refused where it is used (below). Still enforced on every later INSERT/UPDATE, so such a row can be disabled or retired, never (re-)enabled |
| fetch models, health check, capability test, key rotation, enabling | refused (`url.plaintext`) before the key is read; nothing is recorded or sent |
| readiness | a blocker on the slot: the runtime cannot be activated |
| `load_active_runtime` | `RuntimeUnavailable` before the key is read: research is refused, never reasoned elsewhere |
| `OpenAICompatibleClient._request` | the backstop for any caller: refused before a request is built or a connection opened |
| `OpenAICompatibleClient` opener | `_NoRedirects`: every 3xx refused, for discovery, health, probes and inference alike |

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
handler, the redirect's words, creation, use, re-enabling, readiness, the active runtime.

## 5. Verification

Code: `c3e7181`. CI run `37203562579`: commit hygiene, spec conformance, lint/types/full suite
and the PostgreSQL backend profile, all green; the TLS transport tests ran there (Linux, `openssl`
present -- in CI a missing `openssl` fails them rather than skipping).

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| backend-free `pytest` | 1664 passed, 804 skipped (PostgreSQL / Lumerical / network) |
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
