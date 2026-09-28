"""HTML for the LLM settings and runtime pages: presentation of the `012e` rows and readiness.

The workflow is Connection -> Fetch/declare model -> Capability test -> Lock -> Slot binding ->
Readiness -> Activate. Every value shown is a stored row or the server's readiness evaluation;
every button is a form the server re-checks. Credentials are never rendered: a connection shows
its reference (`env:NAME` / `wincred:...`) and fingerprint (`****abcd`), and the credential field of
every form is a password input that is never filled back in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.web import (
    egress_pages,  # noqa: F401 - the eg.* messages used below
    labels,
)
from lab_brain.interfaces.web.i18n import RESEARCH_OUTPUT_LANGUAGE, Messages
from lab_brain.interfaces.web.pages import Chrome, Html, cat, e, h, page, state
from lab_brain.llm_runtime.capabilities import (
    BINDABLE_SLOTS,
    SLOT_REQUIREMENTS,
    Capability,
    critic_fallback,
    role_routes,
)
from lab_brain.llm_runtime.readiness import Readiness, SlotReadiness
from lab_brain.llm_runtime.registry import (
    ConnectionRow,
    HealthRow,
    ModelRow,
    ProbeRow,
    RuntimeRow,
)

Messages.extend(
    {
        "llm.title": ("LLM settings", "LLM 設定"),
        "llm.intro": (
            "Language-model routes for the research service. A role never names a model: each "
            "cognitive role goes to a logical slot (fixed in code, shown below), and you choose "
            "which locked model serves each slot. With no runtime active, the local rule-based "
            "catalog reasoner serves every slot.",
            "研究服務使用的語言模型路由。角色從不直接指定模型：每個認知角色對應到一個邏輯 slot"
            "（寫在程式中，列於下方），由你選擇每個 slot 由哪個已鎖定的模型負責。沒有啟用任何執行"
            "環境時，所有 slot 由本機規則式機制目錄推理器負責。",
        ),
        "llm.steps": ("Workflow", "流程"),
        "llm.step.connection": ("Connection", "連線"),
        "llm.step.model": ("Fetch/declare model", "取得／宣告模型"),
        "llm.step.test": ("Capability test", "能力測試"),
        "llm.step.lock": ("Lock", "鎖定"),
        "llm.step.bind": ("Slot binding", "Slot 綁定"),
        "llm.step.ready": ("Runtime readiness", "執行環境就緒"),
        "llm.step.activate": ("Activate", "啟用"),
        "llm.connections": ("Connections", "連線"),
        "llm.models": ("Models", "模型"),
        "llm.runtimes": ("Runtimes", "執行環境"),
        "llm.roles": ("Roles and slots (read-only)", "角色與 slot（唯讀）"),
        "llm.roles.intro": (
            "CognitiveRole -> LogicalSlot is the router's own table. It is not configurable here.",
            "CognitiveRole -> LogicalSlot 是路由器本身的對照表，此處不可設定。",
        ),
        "llm.critic_fallback": (
            "When REASONING_ADVERSARIAL is not bound, the Adversarial Critic falls back to {slot}: "
            "no model-route independence.",
            "REASONING_ADVERSARIAL 未綁定時，Adversarial Critic 會退回 {slot}："
            "沒有模型路由獨立性。",
        ),
        "llm.requirements": (
            "What each slot's model must have proven",
            "各 slot 的模型必須通過的能力",
        ),
        "llm.output_language": (
            "Interface language and research-output language are separate: research reports are "
            "written in {lang}, whatever the interface language.",
            "介面語言與研究輸出語言是分開的：不論介面語言為何，研究報告以 {lang} 撰寫。",
        ),
        "col.slot": ("Slot", "Slot"),
        "col.roles": ("Roles", "角色"),
        "col.requires": ("Requires", "需要"),
        "col.endpoint": ("Endpoint", "端點"),
        "col.reach": ("Reach", "範圍"),
        "col.credential": ("Credential", "憑證"),
        "col.config": ("Configuration", "設定狀態"),
        "col.health": ("Latest health", "最新健康狀態"),
        "col.models": ("Models", "模型"),
        "col.model": ("Model", "模型"),
        "col.connection": ("Connection", "連線"),
        "col.source": ("Source", "來源"),
        "col.lifecycle": ("Lifecycle", "生命週期"),
        "col.verified": ("Proven capabilities", "已證實能力"),
        "col.locked": ("Locked capabilities", "鎖定能力"),
        "col.route": ("Route", "路由"),
        "col.labels": ("External evidence", "外部可攜證據"),
        "col.bindings": ("Bindings", "綁定"),
        "col.activated": ("Activated", "啟用"),
        "col.capability": ("Capability", "能力"),
        "col.latency": ("Latency (ms)", "延遲（毫秒）"),
        "col.when": ("When", "時間"),
        "col.needed_by": ("Needed by", "需要此能力的 slot"),
        "llm.none": ("None yet.", "目前沒有。"),
        "llm.no_credential": ("none", "無"),
        "llm.add_connection": ("Add a connection", "新增連線"),
        "llm.name": ("Name", "名稱"),
        "llm.name.hint": (
            "lower case, e.g. openrouter or local-ollama",
            "小寫，例如 openrouter 或 local-ollama",
        ),
        "llm.base_url": ("Base URL", "Base URL"),
        "llm.base_url.hint": (
            "an OpenAI-compatible endpoint, e.g. https://api.openai.com/v1 or http://127.0.0.1:11434/v1",
            "OpenAI 相容端點，例如 https://api.openai.com/v1 或 http://127.0.0.1:11434/v1",
        ),
        "llm.reach": ("Reach", "範圍"),
        "llm.reach.hint": (
            "LOCAL only for a model on this machine; anything else is EXTERNAL and passes the "
            "egress gate",
            "只有本機上的模型能宣告為 LOCAL；其他一律為 EXTERNAL，並受外送閘門管制",
        ),
        "llm.credential": ("Credential", "憑證"),
        "llm.credential.none": (
            "none (a local endpoint without a key)",
            "無（不需金鑰的本機端點）",
        ),
        "llm.credential.env": (
            "an environment variable of this workspace:",
            "本工作區的環境變數：",
        ),
        "llm.credential.store": ("type it in, kept in {store}:", "直接輸入，保存在 {store}："),
        "llm.credential.nostore": (
            "No secure credential store is available on this machine: a typed-in credential would "
            "be refused. Set an environment variable for the workspace and reference it.",
            "本機沒有可用的安全憑證儲存區：直接輸入的憑證會被拒絕。請為工作區設定環境變數並引用它。",
        ),
        "llm.credential.note": (
            "The credential is never stored by the workspace or shown again: only its reference "
            "and a fingerprint are kept.",
            "工作區絕不保存或再次顯示憑證：只保留其參照與指紋。",
        ),
        "llm.save": ("Save", "儲存"),
        "llm.check_health": ("Check health", "檢查健康狀態"),
        "llm.fetch": ("Fetch models", "取得模型清單"),
        "llm.declare": ("Declare a model", "宣告模型"),
        "llm.declare.button": ("Declare", "宣告"),
        "llm.enable": ("Enable", "啟用"),
        "llm.disable": ("Disable", "停用"),
        "llm.retire": ("Retire", "淘汰"),
        "llm.replace_credential": ("Replace the credential", "更換憑證"),
        "llm.health_history": ("Health checks", "健康檢查紀錄"),
        "llm.health_note": (
            "Health is what the endpoint answered when checked. It never changes the configuration "
            "state.",
            "健康狀態是檢查當下端點的回應，不會改變設定狀態。",
        ),
        "llm.test": ("Run capability test", "執行能力測試"),
        "llm.test.note": (
            "Probes send only fixed, synthetic payloads -- no project data. Each answer is "
            "judged by "
            "code; the role probes use the real typed role parsers.",
            "探測只送出固定的合成內容，不含任何專案資料。每個回答由程式判定；角色探測使用真正的型別"
            "化角色解析器。",
        ),
        "llm.lock": ("Lock", "鎖定"),
        "llm.unlock": ("Unlock", "解除鎖定"),
        "llm.lock.note": (
            "A lock freezes exactly the capabilities whose latest probe passed, and a route "
            "fingerprint that inference provenance records as the model version.",
            "鎖定會凍結最新探測通過的能力，以及推論溯源記錄為模型版本的路由指紋。",
        ),
        "llm.serves": ("Slots this model can serve", "此模型可負責的 slot"),
        "llm.probe_history": ("Probe history", "探測紀錄"),
        "llm.new_runtime": ("New runtime (draft)", "新執行環境（草稿）"),
        "llm.runtime.labels": (
            "Evidence an EXTERNAL route may carry",
            "EXTERNAL 路由可攜帶的證據分級",
        ),
        "llm.runtime.labels.note": (
            "RESTRICTED_NDA never leaves this machine. The researcher's own clearance still "
            "applies.",
            "RESTRICTED_NDA 絕不離開本機。研究者本身的權限仍然適用。",
        ),
        "llm.create": ("Create", "建立"),
        "llm.runtime.title": ("Runtime", "執行環境"),
        "llm.bind": ("Bind", "綁定"),
        "llm.unbind": ("Unbind", "解除綁定"),
        "llm.no_eligible": (
            "No locked model has proven what this slot needs.",
            "沒有已鎖定的模型通過此 slot 需要的能力。",
        ),
        "llm.ineligible": ("Not eligible:", "不符合："),
        "llm.critic": ("Adversarial review route", "反方審查的模型路由"),
        "llm.egress": ("Egress", "外送"),
        "llm.blockers": ("Blockers", "阻擋項目"),
        "llm.warnings": ("Warnings", "警告"),
        "llm.ready": ("Ready to activate.", "可以啟用。"),
        "llm.not_ready": ("Not ready.", "尚未就緒。"),
        "llm.check": ("Check readiness now", "立即檢查就緒狀態"),
        "llm.check.note": (
            "Checks the health of every connection this runtime binds, then evaluates again.",
            "檢查此執行環境綁定的每個連線健康狀態，然後重新評估。",
        ),
        "llm.activate": ("Activate", "啟用"),
        "llm.activate.note": (
            "Activation checks readiness live and fails closed. New research runs then use this "
            "runtime; the previous active runtime is retired.",
            "啟用時會即時檢查就緒狀態，未就緒即拒絕。之後的新研究會使用此執行環境；原本啟用的執行環境會被淘汰。",
        ),
        "llm.deactivate": ("Deactivate", "停用"),
        "llm.deactivate.note": (
            "New research runs then use the local catalog reasoner (the explicit fallback).",
            "之後的新研究會使用本機機制目錄推理器（明示的備援）。",
        ),
        "llm.discard": ("Discard draft", "捨棄草稿"),
        "rt.title": ("Runtime readiness", "執行環境就緒狀態"),
        "rt.none": (
            "No LLM runtime is active. New research runs use the local rule-based catalog "
            "reasoner on every slot (the explicit fallback): no language model is called.",
            "目前沒有啟用的 LLM 執行環境。新研究在所有 slot 使用本機規則式機制目錄推理器（明示的"
            "備援）：不會呼叫任何語言模型。",
        ),
        "rt.active": ("Active runtime", "已啟用的執行環境"),
        "rt.unusable": (
            "It cannot be used right now, so research runs are refused rather than re-routed: "
            "{reason}",
            "目前無法使用，因此研究會被拒絕而不是改走其他路由：{reason}",
        ),
        "rt.open": ("Open the runtime", "開啟執行環境"),
    }
)

STEPS = (
    "llm.step.connection",
    "llm.step.model",
    "llm.step.test",
    "llm.step.lock",
    "llm.step.bind",
    "llm.step.ready",
    "llm.step.activate",
)


@dataclass(frozen=True)
class Overview:
    connections: Sequence[ConnectionRow]
    health: Mapping[str, HealthRow | None]
    models: Sequence[ModelRow]
    verified: Mapping[str, frozenset[Capability]]
    runtimes: Sequence[RuntimeRow]
    bindings: Mapping[str, Mapping[LogicalSlot, str]]
    secure_store: str | None
    progress: Sequence[bool]


def _csrf(chrome: Chrome) -> Html:
    return h('<input type="hidden" name="csrf" value="{}">', chrome.csrf or "")


def _button(chrome: Chrome, action: str, label: str, css: str = "small") -> Html:
    return h(
        '<form class="inline" method="post" action="{}">{}<button class="{}" type="submit">{}'
        "</button></form>",
        action,
        _csrf(chrome),
        css,
        label,
    )


def _table(head: Sequence[str], rows: Sequence[Sequence[object]], m: Messages) -> Html:
    if not rows:
        return h('<p class="muted">{}</p>', m("llm.none"))
    return h(
        '<div class="scroll"><table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></div>',
        cat(h("<th>{}</th>", c) for c in head),
        cat(h("<tr>{}</tr>", cat(h("<td>{}</td>", c) for c in row)) for row in rows),
    )


def _credential(c: ConnectionRow, m: Messages) -> Html:
    if c.secret_ref is None:
        return e(m("llm.no_credential"))
    return h("<code>{}</code> {}", c.secret_ref, c.secret_fingerprint or "")


def _health(row: HealthRow | None) -> Html:
    if row is None:
        return Html("-")
    return h(
        '{} <span class="muted">{}</span>', state(row.outcome), f"{row.checked_at:%Y-%m-%d %H:%M}"
    )


def _secret_fields(chrome: Chrome, secure_store: str | None, prefix: str = "") -> Html:
    m = chrome.m
    store = (
        h(
            '<label class="check"><input type="radio" name="secret_mode" value="store"> {}</label>'
            '<input type="password" name="secret_value" autocomplete="off">',
            m("llm.credential.store", store=secure_store),
        )
        if secure_store
        else h('<p class="muted">{}</p>', m("llm.credential.nostore"))
    )
    return h(
        "<label>{}</label>"
        '<label class="check"><input type="radio" name="secret_mode" value="none" checked> {}'
        "</label>"
        '<label class="check"><input type="radio" name="secret_mode" value="env"> {}</label>'
        '<input type="text" name="env_name" placeholder="OPENAI_API_KEY" autocomplete="off">'
        '{}<p class="muted">{}</p>',
        prefix or m("llm.credential"),
        m("llm.credential.none"),
        m("llm.credential.env"),
        store,
        m("llm.credential.note"),
    )


def _error(chrome: Chrome, error: str | None) -> Html:
    if not error:
        return Html("")
    return h(
        '<div class="box error">{}{}</div>',
        labels.humanize(error, chrome.m.locale),
        labels.technical(chrome.m.locale, [], [error]),
    )


def overview_page(chrome: Chrome, data: Overview, *, error: str | None = None) -> bytes:
    m = chrome.m
    names = {c.connection_id: c.name for c in data.connections}
    steps = h(
        '<ol class="steps">{}</ol>',
        cat(
            h("<li{}>{}. {}</li>", Html(' class="done"' if done else ""), n, m(key))
            for n, (key, done) in enumerate(zip(STEPS, data.progress, strict=True), start=1)
        ),
    )
    connections = _table(
        (
            m("col.name"),
            m("col.endpoint"),
            m("col.reach"),
            m("col.credential"),
            m("col.config"),
            m("col.health"),
            m("col.models"),
        ),
        [
            (
                h('<a href="/settings/llm/connections/{}">{}</a>', c.connection_id, c.name),
                h("<code>{}</code>", c.base_url),
                state(c.reach),
                _credential(c, m),
                state(c.lifecycle),
                _health(data.health.get(c.connection_id)),
                sum(1 for x in data.models if x.connection_id == c.connection_id),
            )
            for c in data.connections
        ],
        m,
    )
    models = _table(
        (
            m("col.model"),
            m("col.connection"),
            m("col.source"),
            m("col.lifecycle"),
            m("col.verified"),
            m("col.route"),
        ),
        [
            (
                h(
                    '<a href="/settings/llm/models/{}"><code>{}</code></a>',
                    x.model_profile_id,
                    x.model_name,
                ),
                names.get(x.connection_id, x.connection_id),
                x.source,
                state(x.lifecycle),
                labels.listing(
                    (
                        labels.capability(c.value, m.locale)
                        for c in sorted(data.verified.get(x.model_profile_id, ()))
                    ),
                    m.locale,
                ),
                h("<code>{}</code>", x.lock_fingerprint) if x.lock_fingerprint else "-",
            )
            for x in data.models
        ],
        m,
    )
    runtimes = _table(
        (m("col.name"), m("col.state"), m("col.labels"), m("col.bindings"), m("col.activated")),
        [
            (
                h('<a href="/settings/llm/runtimes/{}">{}</a>', r.runtime_id, r.name),
                state(r.state),
                ", ".join(r.external_labels),
                labels.listing(
                    (
                        h("{}: <code>{}</code>", labels.slot(slot_, m.locale), model_)
                        for slot_, model_ in sorted(data.bindings[r.runtime_id].items())
                    ),
                    m.locale,
                ),
                f"{r.activated_at:%Y-%m-%d %H:%M} ({r.activated_by})" if r.activated_at else "-",
            )
            for r in data.runtimes
        ],
        m,
    )
    add_connection = h(
        '<form method="post" action="/settings/llm/connections" class="box">{}'
        '<h3>{}</h3><label for="c_name">{} <span class="hint">{}</span></label>'
        '<input type="text" id="c_name" name="name" required>'
        '<label for="c_url">{} <span class="hint">{}</span></label>'
        '<input type="text" id="c_url" name="base_url" required>'
        '<label for="c_reach">{} <span class="hint">{}</span></label>'
        '<select id="c_reach" name="reach"><option value="EXTERNAL">EXTERNAL</option>'
        '<option value="LOCAL">LOCAL</option></select>{}<button type="submit">{}</button></form>',
        _csrf(chrome),
        m("llm.add_connection"),
        m("llm.name"),
        m("llm.name.hint"),
        m("llm.base_url"),
        m("llm.base_url.hint"),
        m("llm.reach"),
        m("llm.reach.hint"),
        _secret_fields(chrome, data.secure_store),
        m("llm.save"),
    )
    label_boxes = cat(
        h(
            '<label class="check"><input type="checkbox" name="external_labels" value="{}"{}> {}'
            "</label>",
            label,
            Html(" checked" if label == "PUBLIC" else ""),
            label,
        )
        for label in ("PUBLIC", "INTERNAL", "CONFIDENTIAL_LAB")
    )
    new_runtime = h(
        '<form method="post" action="/settings/llm/runtimes" class="box">{}<h3>{}</h3>'
        '<label for="r_name">{}</label><input type="text" id="r_name" name="name" required>'
        '<label>{}</label>{}<p class="muted">{}</p><button type="submit">{}</button></form>',
        _csrf(chrome),
        m("llm.new_runtime"),
        m("llm.name"),
        m("llm.runtime.labels"),
        label_boxes,
        m("llm.runtime.labels.note"),
        m("llm.create"),
    )
    routes = role_routes()
    roles = h(
        "{}{}",
        _table(
            (m("col.role"), m("col.slot")),
            [
                (labels.role(role.value, m.locale), labels.slot(slot, m.locale))
                for role, slot in routes.items()
            ],
            m,
        ),
        labels.technical(m.locale, [(role.value, slot.value) for role, slot in routes.items()]),
    )
    requirements = h(
        "{}{}",
        _table(
            (m("col.slot"), m("col.requires")),
            [
                (
                    labels.slot(s, m.locale),
                    labels.listing(
                        (
                            labels.capability(c.value, m.locale)
                            for c in sorted(SLOT_REQUIREMENTS[s])
                        ),
                        m.locale,
                    ),
                )
                for s in BINDABLE_SLOTS
            ]
            + [(labels.slot(LogicalSlot.EMBEDDING, m.locale), m("lbl.builtin_model"))],
            m,
        ),
        labels.technical(
            m.locale,
            [
                (s.value, ",".join(sorted(c.value for c in SLOT_REQUIREMENTS[s])))
                for s in BINDABLE_SLOTS
            ]
            + [("EMBEDDING", "built-in local embedder")],
        ),
    )
    body = h(
        '<h1>{}</h1>{}<p class="muted">{}</p><h2>{}</h2>{}'
        "<h2>{}</h2>{}{}<h2>{}</h2>{}<h2>{}</h2>{}{}"
        '<h2>{}</h2><p class="muted">{}</p>{}<p>{}</p><h3>{}</h3>{}<p class="muted">{}</p>',
        m("llm.title"),
        _error(chrome, error),
        m("llm.intro"),
        m("llm.steps"),
        steps,
        m("llm.connections"),
        connections,
        add_connection,
        m("llm.models"),
        models,
        m("llm.runtimes"),
        runtimes,
        new_runtime,
        m("llm.roles"),
        m("llm.roles.intro"),
        roles,
        m("llm.critic_fallback", slot=critic_fallback().value),
        m("llm.requirements"),
        requirements,
        m("llm.output_language", lang=RESEARCH_OUTPUT_LANGUAGE),
    )
    return page(m("llm.title"), body, chrome=chrome)


def connection_page(
    chrome: Chrome,
    connection: ConnectionRow,
    health: Sequence[HealthRow],
    models: Sequence[ModelRow],
    *,
    secure_store: str | None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    base = f"/settings/llm/connections/{connection.connection_id}"
    actions = [
        _button(chrome, f"{base}/health", m("llm.check_health")),
        _button(chrome, f"{base}/fetch", m("llm.fetch")),
    ]
    for target, key in (
        ("ENABLED", "llm.enable"),
        ("DISABLED", "llm.disable"),
        ("RETIRED", "llm.retire"),
    ):
        if connection.lifecycle != target and connection.lifecycle != "RETIRED":
            actions.append(
                h(
                    '<form class="inline" method="post" action="{}/lifecycle">{}'
                    '<input type="hidden" name="lifecycle" value="{}">'
                    '<button class="small{}" type="submit">{}</button></form>',
                    base,
                    _csrf(chrome),
                    target,
                    Html(" danger" if target == "RETIRED" else ""),
                    m(key),
                )
            )
    declare = h(
        '<form method="post" action="{}/declare" class="box">{}<label for="d_model">{}</label>'
        '<input type="text" id="d_model" name="model_name" required>'
        '<button type="submit">{}</button></form>',
        base,
        _csrf(chrome),
        m("llm.declare"),
        m("llm.declare.button"),
    )
    replace = h(
        '<form method="post" action="{}/secret" class="box"><h3>{}</h3>{}{}'
        '<button type="submit">{}</button></form>',
        base,
        m("llm.replace_credential"),
        _csrf(chrome),
        _secret_fields(chrome, secure_store, prefix=m("llm.credential")),
        m("llm.save"),
    )
    body = h(
        "<h1>{} <code>{}</code></h1>{}"
        '<div class="box"><div>{}: <code>{}</code> | {}: {} | {}: {} | {}: {}</div>'
        '<div class="muted">{}</div></div><p>{}</p>'
        "<h2>{}</h2>{}{}<h2>{}</h2>{}{}",
        m("col.connection"),
        connection.name,
        _error(chrome, error),
        m("col.endpoint"),
        connection.base_url,
        m("col.reach"),
        state(connection.reach),
        m("col.credential"),
        _credential(connection, m),
        m("col.config"),
        state(connection.lifecycle),
        m("llm.health_note"),
        cat(actions, " "),
        m("llm.models"),
        _table(
            (m("col.model"), m("col.source"), m("col.lifecycle"), m("col.route")),
            [
                (
                    h(
                        '<a href="/settings/llm/models/{}"><code>{}</code></a>',
                        x.model_profile_id,
                        x.model_name,
                    ),
                    x.source,
                    state(x.lifecycle),
                    h("<code>{}</code>", x.lock_fingerprint) if x.lock_fingerprint else "-",
                )
                for x in models
            ],
            m,
        ),
        declare if connection.lifecycle == "ENABLED" else Html(""),
        m("llm.health_history"),
        _table(
            (m("col.outcome"), m("col.latency"), m("col.detail"), m("col.when")),
            [
                (
                    state(x.outcome),
                    x.latency_ms if x.latency_ms is not None else "-",
                    x.detail,
                    f"{x.checked_at:%Y-%m-%d %H:%M:%S}",
                )
                for x in health
            ],
            m,
        ),
        replace if connection.lifecycle != "RETIRED" else Html(""),
    )
    return page(connection.name, body, chrome=chrome)


def model_page(
    chrome: Chrome,
    model: ModelRow,
    connection: ConnectionRow,
    latest: Mapping[Capability, ProbeRow],
    history: Sequence[ProbeRow],
    *,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    base = f"/settings/llm/models/{model.model_profile_id}"
    needed = {c: [s.value for s in BINDABLE_SLOTS if c in SLOT_REQUIREMENTS[s]] for c in Capability}
    capabilities = _table(
        (
            m("col.capability"),
            m("col.outcome"),
            m("col.detail"),
            m("col.latency"),
            m("col.when"),
            m("col.needed_by"),
        ),
        [
            (
                labels.capability(c.value, m.locale),
                state(latest[c].outcome) if c in latest else "-",
                latest[c].detail if c in latest else "",
                latest[c].latency_ms if c in latest and latest[c].latency_ms is not None else "-",
                f"{latest[c].probed_at:%Y-%m-%d %H:%M:%S}" if c in latest else "-",
                labels.listing(
                    (labels.slot(LogicalSlot(x), m.locale) for x in needed[c]), m.locale
                ),
            )
            for c in Capability
        ],
        m,
    )
    actions: list[Html] = []
    if model.lifecycle in ("DISCOVERED", "TESTED"):
        boxes = cat(
            h(
                '<label class="check"><input type="checkbox" name="capabilities" value="{}" '
                "checked> {}</label>",
                c.value,
                labels.capability(c.value, m.locale),
            )
            for c in Capability
        )
        actions.append(
            h(
                '<form method="post" action="{}/test" class="box">{}<h3>{}</h3>{}'
                '<p class="muted">{}</p><button type="submit">{}</button></form>',
                base,
                _csrf(chrome),
                m("llm.test"),
                boxes,
                m("llm.test.note"),
                m("llm.test"),
            )
        )
    buttons: list[Html] = []
    if model.lifecycle == "TESTED":
        buttons.append(_button(chrome, f"{base}/lock", m("llm.lock")))
    if model.lifecycle == "LOCKED":
        buttons.append(_button(chrome, f"{base}/unlock", m("llm.unlock")))
    if model.lifecycle != "RETIRED":
        buttons.append(_button(chrome, f"{base}/retire", m("llm.retire"), "small danger"))
    serves = [
        s
        for s in BINDABLE_SLOTS
        if {c.value for c in SLOT_REQUIREMENTS[s]} <= set(model.locked_capabilities or ())
        and (s is not LogicalSlot.PRIVATE_LOCAL or connection.reach == "LOCAL")
    ]
    body = h(
        "<h1>{} <code>{}</code></h1>{}"
        '<div class="box"><div>{}: <a href="/settings/llm/connections/{}">{}</a> ({}) | {}: {}'
        " | {}: {}</div><div>{}: {}</div><div>{}: {}</div>"
        '<div class="muted">{}</div></div><h2>{}</h2>{}{}<p>{}</p><h2>{}</h2>{}<h2>{}</h2>{}',
        m("col.model"),
        model.model_name,
        _error(chrome, error),
        m("col.connection"),
        connection.connection_id,
        connection.name,
        state(connection.reach),
        m("col.source"),
        model.source,
        m("col.lifecycle"),
        state(model.lifecycle),
        m("col.locked"),
        labels.listing(
            (labels.capability(c, m.locale) for c in model.locked_capabilities or ()), m.locale
        ),
        m("col.route"),
        h("<code>{}</code>", model.lock_fingerprint) if model.lock_fingerprint else "-",
        m("llm.lock.note"),
        m("col.verified"),
        capabilities,
        cat(actions),
        cat(buttons, " "),
        m("llm.serves"),
        h(
            "<p>{}</p>{}",
            labels.listing((labels.slot(x, m.locale) for x in serves), m.locale),
            labels.technical(
                m.locale,
                [
                    (m("col.locked"), ",".join(model.locked_capabilities or ()) or "-"),
                    (m("llm.serves"), ",".join(x.value for x in serves) or "-"),
                ],
            ),
        ),
        m("llm.probe_history"),
        _table(
            (m("col.capability"), m("col.outcome"), m("col.detail"), m("col.when")),
            [
                (x.capability, state(x.outcome), x.detail, f"{x.probed_at:%Y-%m-%d %H:%M:%S}")
                for x in history
            ],
            m,
        ),
    )
    return page(model.model_name, body, chrome=chrome)


def _slot_row(s: SlotReadiness, loc: str, m: Messages) -> tuple[object, ...]:
    """One slot, three cells: what it is for (and its status), which model, who relies on it."""
    use = h(
        '<strong>{}</strong><span class="purpose">{}</span><div>{}</div>',
        labels.slot(s.slot, loc),
        labels.slot_purpose(s.slot, loc),
        labels.state(s.state, loc),
    )
    if s.state == "BUILTIN":
        model: Html = e(m("lbl.builtin_model"))
    elif s.model:
        model = h(
            '<code>{}</code><span class="purpose">{}</span>',
            s.model,
            m("lbl.via", connection=s.connection or "-", reach=labels.reach(s.reach, loc)),
        )
    else:
        model = Html("-")
    who = (
        labels.listing((labels.role(r, loc) for r in s.roles), loc)
        if s.roles
        else e(m("lbl.nobody"))
    )
    needs = labels.listing((labels.capability(c, loc) for c in s.requires), loc)
    # Only what a researcher needs here, in their language; the raw notes are in the details.
    if s.state == "BUILTIN":
        note: Html = e(m("lbl.builtin_note"))
    elif s.state == "BLOCKED":
        note = cat((h("<div>{}</div>", labels.humanize(n, loc)) for n in s.notes), "")
    elif not s.model and any(n.startswith("no locked model has proven") for n in s.notes):
        note = e(m("llm.no_eligible"))
    else:
        note = Html("")
    return (
        use,
        model,
        h(
            '<div>{}</div><div class="purpose">{}: {}</div>{}',
            who,
            m("lbl.col.needs"),
            needs if s.requires else Html("-"),
            h('<div class="purpose">{}</div>', note) if note else Html(""),
        ),
    )


def _critic_sentence(readiness: Readiness, m: Messages) -> str:
    by_slot = {s.slot: s for s in readiness.slots}
    primary = by_slot.get(LogicalSlot.REASONING_PRIMARY)
    critic = by_slot.get(LogicalSlot.REASONING_ADVERSARIAL)
    primary_model = (primary.model if primary is not None else None) or "-"
    if critic is None or critic.model is None:
        return m("lbl.critic.fallback", model=primary_model)
    if not readiness.critic_independent:
        return m("lbl.critic.same", model=primary_model)
    return m("lbl.critic.own", model=critic.model)


def _egress_sentence(readiness: Readiness, m: Messages) -> str:
    external = sorted(
        {s.connection for s in readiness.slots if s.reach == "EXTERNAL" and s.connection}
    )
    if not external:
        return m("lbl.egress.local")
    return m(
        "lbl.egress.external",
        names=", ".join(external),
        labels=", ".join(readiness.runtime.external_labels),
    )


def readiness_block(chrome: Chrome, readiness: Readiness) -> Html:
    """What an activated runtime would do, in the researcher's terms; the routing identifiers and
    the server's own rule text one click away."""
    m = chrome.m
    loc = m.locale
    rows = [_slot_row(s, loc, m) for s in readiness.slots]
    table = h(
        '<div class="scroll"><table class="readable"><thead><tr>{}</tr></thead><tbody>{}</tbody>'
        "</table></div>",
        cat(h("<th>{}</th>", m(k)) for k in ("lbl.col.use", "lbl.col.model", "lbl.col.who")),
        cat(h("<tr>{}</tr>", cat(h("<td>{}</td>", c) for c in row)) for row in rows),
    )
    verdict = (
        h('<p class="box">{}</p>', m("llm.ready"))
        if readiness.ready
        else h(
            '<div class="box error"><strong>{}</strong><ul>{}</ul></div>',
            m("llm.not_ready"),
            cat(h("<li>{}</li>", labels.humanize(b, loc)) for b in readiness.blockers),
        )
    )
    warnings = (
        h(
            '<div class="box warn"><strong>{}</strong><ul>{}</ul></div>',
            m("llm.warnings"),
            cat(h("<li>{}</li>", labels.humanize(w, loc)) for w in readiness.warnings),
        )
        if readiness.warnings
        else Html("")
    )
    details = labels.technical(
        loc,
        [
            (
                labels.SLOT_NAMES[s.slot][0 if loc == "en" else 1],
                f"{s.slot.value} | state={s.state} | roles={','.join(s.roles) or '-'} | "
                f"requires={','.join(s.requires) or '-'} | route={s.route or '-'}",
            )
            for s in readiness.slots
        ],
        [
            readiness.critic,
            readiness.egress,
            *readiness.blockers,
            *readiness.warnings,
            *(n for s in readiness.slots for n in s.notes),
        ],
    )
    return h(
        '{}{}<h3>{}</h3><p class="box{}">{}</p><h3>{}</h3><p>{}</p>{}{}',
        table,
        verdict,
        m("llm.critic"),
        Html("" if readiness.critic_independent else " warn"),
        _critic_sentence(readiness, m),
        m("llm.egress"),
        _egress_sentence(readiness, m),
        warnings,
        details,
    )


def runtime_page(
    chrome: Chrome,
    runtime: RuntimeRow,
    readiness: Readiness,
    eligible: Mapping[LogicalSlot, Sequence[tuple[ModelRow, str]]],
    ineligible: Mapping[LogicalSlot, Sequence[tuple[ModelRow, str]]],
    *,
    error: str | None = None,
    notice: str | None = None,
) -> bytes:
    m = chrome.m
    base = f"/settings/llm/runtimes/{runtime.runtime_id}"
    binding = Html("")
    if runtime.state == "DRAFT":
        forms = []
        for slot in BINDABLE_SLOTS:
            options = eligible.get(slot, ())
            refusals = ineligible.get(slot, ())
            select = (
                h(
                    '<form class="inline" method="post" action="{}/bind">{}'
                    '<input type="hidden" name="slot" value="{}"><select name="model">{}</select> '
                    '<button class="small" type="submit">{}</button></form>',
                    base,
                    _csrf(chrome),
                    slot.value,
                    cat(
                        h(
                            '<option value="{}">{} ({})</option>',
                            x.model_profile_id,
                            x.model_name,
                            conn,
                        )
                        for x, conn in options
                    ),
                    m("llm.bind"),
                )
                if options
                else h('<span class="muted">{}</span>', m("llm.no_eligible"))
            )
            unbind = h(
                '<form class="inline" method="post" action="{}/unbind">{}'
                '<input type="hidden" name="slot" value="{}">'
                '<button class="small" type="submit">{}</button></form>',
                base,
                _csrf(chrome),
                slot.value,
                m("llm.unbind"),
            )
            raw = [f"{x.model_name} ({reason})" for x, reason in refusals]
            why_not = (
                h(
                    '<div class="muted">{} {}</div>{}',
                    m("llm.ineligible"),
                    cat((labels.humanize(r, m.locale) for r in raw), "; "),
                    labels.technical(m.locale, [(slot.value, slot.value)], raw),
                )
                if refusals
                else Html("")
            )
            forms.append(
                h(
                    '<tr><td><strong>{}</strong><span class="purpose">{}</span></td>'
                    "<td>{} {}{}</td></tr>",
                    labels.slot(slot, m.locale),
                    labels.slot_purpose(slot, m.locale),
                    select,
                    unbind,
                    why_not,
                )
            )
        binding = h(
            '<div class="scroll"><table><thead><tr><th>{}</th><th>{}</th></tr></thead>'
            "<tbody>{}</tbody></table></div>",
            m("col.slot"),
            m("col.model"),
            cat(forms),
        )
    buttons: list[Html] = [
        h(
            '<form class="inline" method="post" action="{}/check">{}<button class="small" '
            'type="submit">{}</button></form> <span class="muted">{}</span>',
            base,
            _csrf(chrome),
            m("llm.check"),
            m("llm.check.note"),
        )
    ]
    if runtime.state == "DRAFT":
        buttons.append(
            h(
                '<div class="box">{} <span class="muted">{}</span></div>',
                _button(chrome, f"{base}/activate", m("llm.activate"), "small"),
                m("llm.activate.note"),
            )
        )
        buttons.append(_button(chrome, f"{base}/retire", m("llm.discard"), "small danger"))
    elif runtime.state == "ACTIVE":
        buttons.append(
            h(
                '<div class="box">{} <span class="muted">{}</span></div>',
                _button(chrome, f"{base}/retire", m("llm.deactivate"), "small danger"),
                m("llm.deactivate.note"),
            )
        )
    body = h(
        '<h1>{} {}</h1>{}{}<div class="box">{}: {} | {}: {}</div>{}<h2>{}</h2>{}{}',
        m("llm.runtime.title"),
        runtime.name,
        _error(chrome, error),
        h('<p class="box notice">{}</p>', notice) if notice else Html(""),
        m("col.state"),
        state(runtime.state),
        m("col.labels"),
        ", ".join(runtime.external_labels),
        binding,
        m("llm.step.ready"),
        readiness_block(chrome, readiness),
        cat(buttons),
    )
    return page(runtime.name, body, chrome=chrome)


def active_runtime_page(
    chrome: Chrome,
    readiness: Readiness | None,
    *,
    unusable: str | None = None,
    admin: bool = False,
    projects: Sequence[tuple[str, str, str]] = (),
) -> bytes:
    """`projects`: (id, name, egress summary) of every project this actor may act in -- whether
    each one's evidence may use the runtime's external routes is that project's own policy."""
    m = chrome.m
    egress = (
        h(
            "<h2>{}</h2><ul>{}</ul>",
            m("eg.status"),
            cat(
                h(
                    '<li><code>{}</code> {}: {} <a href="/projects/{}/egress">{}</a></li>',
                    project_id,
                    name,
                    status,
                    project_id,
                    m("eg.link"),
                )
                for project_id, name, status in projects
            ),
        )
        if projects
        else Html("")
    )
    if readiness is None:
        body = h('<h1>{}</h1><p class="box">{}</p>{}', m("rt.title"), m("rt.none"), egress)
    else:
        runtime = readiness.runtime
        name = (
            h('<a href="/settings/llm/runtimes/{}">{}</a>', runtime.runtime_id, runtime.name)
            if admin
            else e(runtime.name)
        )
        body = h(
            '<h1>{}</h1><div class="box">{}: {} {}</div>{}{}{}',
            m("rt.title"),
            m("rt.active"),
            name,
            state(runtime.state),
            h('<p class="box error">{}</p>', m("rt.unusable", reason=unusable))
            if unusable
            else Html(""),
            egress,
            readiness_block(chrome, readiness),
        )
    return page(m("rt.title"), body, chrome=chrome)


__all__ = [
    "Overview",
    "active_runtime_page",
    "connection_page",
    "model_page",
    "overview_page",
    "readiness_block",
    "runtime_page",
]
