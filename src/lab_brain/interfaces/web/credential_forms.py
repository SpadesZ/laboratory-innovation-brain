"""How a model connection gets its credential, on the page: the forms and the refusals.

TWO KINDS OF CONNECTION, TWO FORMS. A local model (Ollama on this machine) needs no credential,
so its form HAS NO credential field -- not a hidden one, none -- and says whether Ollama answers
before anything is created; one button creates the connection and gets its models. An external
API's form is what a researcher expects: provider, name, API key, add. The key is pasted into a
password field that is never filled back in; an existing environment variable, an existing stored
reference and a custom service URL are under the advanced settings. Which form shows is chosen by
two radio buttons and CSS alone (the workspace allows no script); without `:has()` support both
forms simply show.

WHAT THE PAGE SAYS ABOUT A STORED KEY is what protects it, and nothing more (`llm_runtime.secrets`):
the operating system's store, or this deployment's credential directory -- filesystem isolation,
NOT encryption, and the page says "not encrypted" in so many words.

REFUSALS SPEAK THE RESEARCHER'S LANGUAGE. A settings refusal carries a code
(`SettingsRefused.code`, `SecretError.code`); the page says what happened and what to do next, and
the server's own rule text stays under the technical details. No refusal repeats a credential: the
services never put one in a message, and a provider's authentication refusal is never read.
"""

from __future__ import annotations

from dataclasses import dataclass

from lab_brain.interfaces.web import labels
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, h

Messages.extend(
    {
        # -- the kind of connection --------------------------------------------------------------
        "cred.kind": ("What kind of model?", "要新增哪一種模型？"),
        "cred.kind.ollama": ("Local model (Ollama)", "本機模型（Ollama）"),
        "cred.kind.external": (
            "External API (OpenAI, Gemini, OpenRouter, …)",
            "外部 API（OpenAI、Gemini、OpenRouter…）",
        ),
        # -- Ollama ------------------------------------------------------------------------------
        "cred.ollama.ready": (
            "✓ Local Ollama is answering ({n} model(s)).",
            "✓ 已連上本機 Ollama（{n} 個模型）。",
        ),
        "cred.ollama.down": (
            "✗ Local Ollama is not answering. Make sure Ollama is installed and running on this "
            "machine (ollama serve), then reload this page.",
            "✗ 目前連不上本機 Ollama。請確認這台電腦已安裝並啟動 Ollama（ollama serve），"
            "然後重新整理"
            "這個頁面。",
        ),
        "cred.ollama.added": (
            "Already added as “{name}”: “Get available models” refreshes its list.",
            "已新增為「{name}」：按「取得可用模型」可以更新模型清單。",
        ),
        "cred.ollama.none_needed": (
            "A local model needs no API key: nothing leaves this machine.",
            "本機模型不需要 API 金鑰：資料不會離開這台電腦。",
        ),
        "cred.ollama.go": ("Get available models", "取得可用模型"),
        "cred.ollama.url": ("Custom Ollama service URL", "自訂 Ollama 服務網址"),
        "cred.ollama.url.hint": (
            "only if Ollama listens elsewhere on this machine; default {url}",
            "只有 Ollama 在這台電腦的其他位址時才需要；預設為 {url}",
        ),
        # -- external API ------------------------------------------------------------------------
        "cred.key": ("API key", "API 金鑰"),
        "cred.key.filesystem": (
            "Pasted keys are kept in this deployment's own, unpublished credential storage -- "
            "protected by file permissions, not encrypted -- never in the database or on a page, "
            "and never shown again.",
            "金鑰會保存在此部署專用、未公開的憑證儲存空間中（以檔案權限保護，未加密），不會寫入資料庫或"
            "網頁，之後也不會再次顯示。",
        ),
        "cred.key.os": (
            "Pasted keys are kept in {store}, never in the database or on a page, and never "
            "shown again.",
            "金鑰會保存在 {store}，不會寫入資料庫或網頁，之後也不會再次顯示。",
        ),
        "cred.key.none": (
            "This deployment has no credential storage for a pasted key: use an existing "
            "environment variable under Advanced settings.",
            "這個部署沒有可以保存金鑰的憑證儲存空間：請在「進階設定」改用既有環境變數。",
        ),
        "cred.key.optional": (
            "Optional only for “other service” when it needs no key.",
            "只有「其他服務」且不需要金鑰時可以留白。",
        ),
        "cred.advanced": ("Advanced settings", "進階設定"),
        "cred.env": ("Use an existing environment variable", "改用既有環境變數"),
        "cred.env.hint": (
            "the variable's name, e.g. OPENAI_API_KEY (the workspace must be started with it set)",
            "填變數名稱，例如 OPENAI_API_KEY（工作台啟動時必須已設定）",
        ),
        "cred.ref": ("Use an existing credential reference", "改用既有憑證參照"),
        "cred.ref.hint": (
            "a reference such as env:NAME, or another connection's stored reference (in its "
            "technical details) -- never the key itself",
            "例如 env:名稱，或另一個連線已保存的憑證參照（見該連線的技術細節）；不是金鑰本身",
        ),
        "cred.url": ("Custom service URL", "自訂服務網址"),
        "cred.one_source": (
            "Fill in only one of: API key, environment variable, credential reference.",
            "API 金鑰、環境變數、憑證參照只能擇一填寫。",
        ),
        "cred.replace.key": ("New API key", "新的 API 金鑰"),
        "cred.where.stored": (
            "kept in the credential storage, fingerprint",
            "已保存在憑證儲存空間，指紋",
        ),
        "cred.where.env": (
            "from the environment variable {name}, fingerprint",
            "來自環境變數 {name}，指紋",
        ),
        "cred.replace.need": (
            "Paste the new API key (or, under Advanced settings, a variable or a reference).",
            "請貼上新的 API 金鑰（或在「進階設定」填環境變數或憑證參照）。",
        ),
        "cred.replace.note": (
            "The old key stops being used at once, and is deleted from the credential storage "
            "unless another connection uses it too.",
            "舊的金鑰會立刻停止使用；除非另一個連線也在使用，否則會從憑證儲存空間刪除。",
        ),
        # -- refusals, by code -------------------------------------------------------------------
        "err.secret.empty": (
            "The API key is empty. Paste the whole key. Nothing was saved.",
            "API 金鑰是空白的。請貼上完整的金鑰。沒有保存任何內容。",
        ),
        "err.secret.invalid": (
            "That is not a single API key (it has spaces, line breaks or other characters a key "
            "does not have, or is far too long). Paste just the key. Nothing was saved.",
            "這不是一把有效的 API 金鑰（含有空格、換行或金鑰不會有的字元，或長度過長）。"
            "請只貼上金鑰本身。"
            "沒有保存任何內容。",
        ),
        "err.secret.looks_like_key": (
            "What you pasted as a reference is a key itself. Paste the key into “API key”; the "
            "reference field takes references such as env:NAME. Nothing was saved.",
            "你在「既有憑證參照」貼上的是金鑰本身。請把金鑰貼到「API 金鑰」欄位；參照欄位只填像 "
            "env:名稱"
            " 這樣的參照。沒有保存任何內容。",
        ),
        "err.secret.ref_invalid": (
            "That credential reference is not in a known form: use env:VARIABLE_NAME, or a stored "
            "reference copied from another connection's technical details.",
            "憑證參照的格式不正確：請填 env:環境變數名稱，或從另一個連線的技術細節複製已保存的憑證"
            "參照。",
        ),
        "err.secret.store_unavailable": (
            "This deployment has no credential storage available, so a pasted key cannot be kept. "
            "Use an existing environment variable under Advanced settings, or ask the "
            "deployment's operator to enable the credential storage.",
            "這個部署目前沒有可用的憑證儲存空間，所以無法保存貼上的金鑰。請在「進階設定」改用既有環境變數，"
            "或請部署管理者啟用憑證儲存空間。",
        ),
        "err.secret.write_failed": (
            "The key could not be saved (the credential storage refused the write), and no "
            "connection was added. Try again; if it keeps happening, ask the deployment's "
            "operator to check the credential storage.",
            "金鑰沒有保存成功（憑證儲存空間無法寫入），也沒有新增連線。請再試一次；若持續發生，請部署管理者"
            "檢查憑證儲存空間。",
        ),
        "err.secret.missing": (
            "The API key this connection saved cannot be found (the credential storage may have "
            "been cleared or replaced). Paste it again with “Replace the API key” on the "
            "connection's details page.",
            "找不到這個連線保存的 API 金鑰（憑證儲存空間可能被清除或更換）。請到連線詳細頁按「更換 "
            "API "
            "金鑰」重新貼上。",
        ),
        "err.secret.env_unset": (
            "The environment variable is not set for this workspace, so the key cannot be read. "
            "Set it where the workspace starts (Docker: deployment/docker/llm-keys.env), or paste "
            "the API key directly instead.",
            "工作台讀不到這個環境變數，所以讀不到金鑰。請在工作台啟動的環境設定它（Docker："
            "deployment/docker/llm-keys.env），或改為直接貼上 API 金鑰。",
        ),
        "err.secret.one_source": (
            "Fill in only one of: API key, environment variable, credential reference.",
            "API 金鑰、環境變數、憑證參照只能擇一填寫。",
        ),
        "err.secret.needed": (
            "Paste the API key (or, under Advanced settings, a variable or a reference).",
            "請貼上 API 金鑰（或在「進階設定」填環境變數或憑證參照）。",
        ),
        "err.provider.auth_failed": (
            "The service refused this API key (authentication failed). Check that the key is "
            "right, still valid and allowed to list models, then use “Replace the API key” on the "
            "connection's details page.",
            "服務拒絕了這把 API 金鑰（驗證失敗）。請確認金鑰正確、仍然有效且有權限讀取模型清單，"
            "然後到連線"
            "詳細頁按「更換 API 金鑰」。",
        ),
        "err.provider.unreachable": (
            "The service cannot be reached. Check the service URL and the network; for a local "
            "model, make sure Ollama is running.",
            "連不上這個服務。請確認服務網址與網路；如果是本機模型，請確認 Ollama 已啟動。",
        ),
        "err.provider.protocol_error": (
            "The service did not answer as an OpenAI-compatible API. Check the service URL "
            "(usually ending in /v1).",
            "服務的回應不符合 OpenAI 相容介面。請確認服務網址（通常以 /v1 結尾）。",
        ),
        "err.provider.secret_unavailable": (
            "This connection's API key cannot be read. Use “Replace the API key” on the "
            "connection's details page.",
            "讀不到這個連線的 API 金鑰。請到連線詳細頁按「更換 API 金鑰」。",
        ),
        "err.ollama.unreachable": (
            "Local Ollama is not answering, so nothing was added. Make sure Ollama is installed "
            "and running on this machine (ollama serve), then try again.",
            "目前連不上本機 Ollama，所以沒有新增任何連線。請確認這台電腦已安裝並啟動 Ollama（ollama"
            " "
            "serve），然後再試一次。",
        ),
        "err.name_taken": (
            "A connection with that name already exists: choose another name, or leave it empty.",
            "已經有同名的模型連線：請換一個名稱，或留白讓系統自動命名。",
        ),
        "err.name_invalid": (
            "A connection name uses lower-case letters, digits, '.', '_' or '-' only; or leave it "
            "empty.",
            "連線名稱只能使用英文小寫、數字、「.」「_」「-」；也可以留白。",
        ),
        "err.url_invalid": (
            "The service URL must start with http:// or https:// and carry no key, query or "
            "fragment.",
            "服務網址必須以 http:// 或 https:// 開頭，且不能包含金鑰、查詢參數或片段。",
        ),
        "err.local_remote": (
            "A local model must be on this machine; a service on another host is an external API.",
            "本機模型必須在這台電腦上；其他主機上的服務請以外部 API 新增。",
        ),
        "err.rule": ("The server's rule text", "系統規則原文"),
    }
)


@dataclass(frozen=True)
class OllamaState:
    """What the page knows about this machine's Ollama: where it is expected, whether it answered
    just now (and with how many models), and the connection already made to it, if any."""

    url: str
    reachable: bool
    models: int = 0
    connection: str | None = None


def problem(chrome: Chrome, error: object) -> Html:
    """A refusal: what happened and what to do, in the researcher's words where its code is known;
    the server's own rule text under the technical details."""
    if not error:
        return Html("")
    m = chrome.m
    text = str(error)
    code = getattr(error, "code", None)
    if code:
        try:
            said = m(f"err.{code}")
        except KeyError:
            said = ""
        if said:
            return h(
                '<div class="box error">{}{}</div>',
                said,
                labels.technical(m.locale, [("code", code)], [text]),
            )
    return h(
        '<div class="box error">{}{}</div>',
        labels.humanize(text, m.locale),
        labels.technical(m.locale, [], [text]),
    )


def _csrf(chrome: Chrome) -> Html:
    return h('<input type="hidden" name="csrf" value="{}">', chrome.csrf or "")


def key_hint(m: Messages, protection: str | None, store: str | None) -> str:
    if protection == "filesystem":
        return m("cred.key.filesystem")
    if protection is not None:
        return m("cred.key.os", store=store or "")
    return m("cred.key.none")


def _key_field(m: Messages, protection: str | None, store: str | None, label: str) -> Html:
    if protection is None:
        return h('<div class="field"><p class="box warn">{}</p></div>', m("cred.key.none"))
    return h(
        '<div class="field"><label for="c_key">{}</label>'
        '<input type="password" id="c_key" name="secret_value" autocomplete="off"'
        ' placeholder="••••••••••••••••"><span class="hint">{}</span></div>',
        label,
        key_hint(m, protection, store),
    )


def _credential_advanced(m: Messages, *, with_url: bool) -> Html:
    return h(
        '<details class="advanced"><summary>{}</summary>'
        '<label for="c_env">{} <span class="hint">{}</span></label>'
        '<input type="text" id="c_env" name="env_name" autocomplete="off">'
        '<label for="c_ref">{} <span class="hint">{}</span></label>'
        '<input type="text" id="c_ref" name="secret_ref" autocomplete="off">{}'
        '<p class="muted">{}</p></details>',
        m("cred.advanced"),
        m("cred.env"),
        m("cred.env.hint"),
        m("cred.ref"),
        m("cred.ref.hint"),
        h(
            '<label for="c_url">{} <span class="hint">{}</span></label>'
            '<input type="text" id="c_url" name="base_url">'
            '<label for="c_reach">{} <span class="hint">{}</span></label>'
            '<select id="c_reach" name="reach"><option value="">-</option>'
            '<option value="EXTERNAL">{}</option><option value="LOCAL">{}</option></select>',
            m("cred.url"),
            m("llm.base_url.hint"),
            m("llm.reach"),
            m("llm.reach.hint"),
            m("llm.reach.EXTERNAL"),
            m("llm.reach.LOCAL"),
        )
        if with_url
        else Html(""),
        m("cred.one_source"),
    )


def add_connection_card(
    chrome: Chrome,
    *,
    providers: tuple[str, ...],
    protection: str | None,
    store: str | None,
    ollama: OllamaState,
) -> Html:
    """Step 1: the two forms and the choice between them."""
    m = chrome.m
    ollama_first = ollama.reachable and ollama.connection is None
    choice = h(
        '<fieldset class="kinds"><legend>{}</legend>'
        '<label class="choice"><input type="radio" name="kind" id="kind-ollama"{}> {}</label>'
        '<label class="choice"><input type="radio" name="kind" id="kind-external"{}> {}</label>'
        "</fieldset>",
        m("cred.kind"),
        Html(" checked" if ollama_first else ""),
        m("cred.kind.ollama"),
        Html("" if ollama_first else " checked"),
        m("cred.kind.external"),
    )
    status = (
        h('<p class="ready">{}</p>', m("cred.ollama.ready", n=ollama.models))
        if ollama.reachable
        else h('<p class="box warn">{}</p>', m("cred.ollama.down"))
    )
    local = h(
        '<form method="post" action="/settings/llm/ollama" id="f-ollama" class="kind-form">{}'
        '{}{}<p class="muted">{}</p>'
        '<button type="submit" class="primary">{}</button>'
        '<details class="advanced"><summary>{}</summary>'
        '<label for="o_url">{} <span class="hint">{}</span></label>'
        '<input type="text" id="o_url" name="base_url"></details></form>',
        _csrf(chrome),
        status,
        h("<p>{}</p>", m("cred.ollama.added", name=ollama.connection))
        if ollama.connection
        else Html(""),
        m("cred.ollama.none_needed"),
        m("cred.ollama.go"),
        m("cred.advanced"),
        m("cred.ollama.url"),
        m("cred.ollama.url.hint", url=ollama.url),
    )
    options = cat(h('<option value="{}">{}</option>', key, m(f"llm.p.{key}")) for key in providers)
    external = h(
        '<form method="post" action="/settings/llm/connections" id="f-external"'
        ' class="kind-form">{}<div class="grid">'
        '<div class="field"><label for="c_provider">{}</label>'
        '<select id="c_provider" name="provider">{}</select></div>'
        '<div class="field"><label for="c_name">{}</label>'
        '<input type="text" id="c_name" name="name"><span class="hint">{}</span></div>'
        "{}</div>{}"
        '<button type="submit" class="primary">{}</button></form>',
        _csrf(chrome),
        m("llm.provider"),
        options,
        m("llm.name"),
        m("llm.name.hint"),
        _key_field(m, protection, store, m("cred.key")),
        _credential_advanced(m, with_url=True),
        m("llm.add"),
    )
    return h(
        '<section class="card" id="add"><h2>{}</h2><p class="lede">{}</p>{}{}{}</section>',
        m("llm.s1"),
        m("llm.s1.lede"),
        choice,
        local,
        external,
    )


def replace_key_form(chrome: Chrome, base: str, protection: str | None, store: str | None) -> Html:
    """A connection's key, rotated: a new key pasted (or, under the advanced settings, a variable
    or a reference). The old key stops being used at once."""
    m = chrome.m
    return h(
        '<form method="post" action="{}/secret" class="box" id="replace-key"><h3>{}</h3>{}{}{}'
        '<p class="muted">{}</p><button type="submit">{}</button></form>',
        base,
        m("llm.replace_credential"),
        _csrf(chrome),
        _key_field(m, protection, store, m("cred.replace.key")),
        _credential_advanced(m, with_url=False),
        m("cred.replace.note"),
        m("llm.save"),
    )


def one_source(secret_value: str, env_name: str, secret_ref: str) -> str:
    """Which credential the researcher gave: "store" (a pasted key), "env", "ref" or "none".
    Raises `ValueError` when more than one was filled in -- the page never guesses which."""
    given = [
        mode
        for mode, value in (("store", secret_value), ("env", env_name), ("ref", secret_ref))
        if value.strip()
    ]
    if len(given) > 1:
        raise ValueError("more than one credential source")
    return given[0] if given else "none"


__all__ = [
    "OllamaState",
    "add_connection_card",
    "key_hint",
    "one_source",
    "problem",
    "replace_key_form",
]
