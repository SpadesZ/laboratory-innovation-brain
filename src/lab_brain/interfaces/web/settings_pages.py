"""HTML for the AI model settings: presentation of the `012e` rows, readiness and the guide.

The operator's path, as PC-MEF lays it out and over Laboratory Brain's own architecture:

    1. add a model connection        Provider, name, API key (or a local model), add
    2. get, test, confirm models     get available models -> choose -> capability test -> confirm
    3. assign models to research work    CognitiveRole -> LogicalSlot (fixed) -> Model (chosen)
    4. check and apply the configuration

Every stage says what to do next (`llm_guide`), and what is still missing is a "still to do / how"
checklist -- never the server's raw rule text as the main answer (it stays, verbatim, under the
technical details). Endpoint URLs, key references, timeouts, internal IDs and routing details live
under Advanced / Technical details. Credentials are never rendered: a connection shows its
reference (`env:NAME` / `wincred:...`) and fingerprint (`****abcd`) only in the details, and every
credential field is a password input that is never filled back in.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.web import (
    credential_forms,
    egress_pages,
    labels,
)
from lab_brain.interfaces.web.i18n import RESEARCH_OUTPUT_LANGUAGE, Messages
from lab_brain.interfaces.web.llm_guide import (
    MAIN_SLOTS,
    ConnectionLine,
    Guide,
    Todo,
    blocker_todo,
)
from lab_brain.interfaces.web.pages import Chrome, Html, cat, e, h, page, when
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
        "llm.title": ("AI model settings", "AI 模型設定"),
        "llm.intro": (
            "Choose which AI model does which kind of research work. Each research role goes to "
            "a use that is fixed in code; you assign a confirmed model to each use. Until a "
            "configuration is applied, research uses the local rule-based reasoner.",
            "設定哪個 AI 模型負責哪一類研究工作。每個研究角色對應到一種模型用途（寫在程式中），"
            "你只要替每種"
            "用途指派一個已確認的模型。套用配置之前，研究使用本機的規則式推理。",
        ),
        "llm.now.none": (
            "No configuration is applied: research uses the local rule-based reasoner.",
            "目前沒有套用任何模型配置：研究使用本機規則式推理。",
        ),
        "llm.now.active": (
            "Applied: “{name}”. New research uses it.",
            "套用中：「{name}」。新的研究會使用它。",
        ),
        "llm.now.draft": (
            "Being prepared: “{name}” (not applied yet).",
            "準備中：「{name}」（尚未套用）。",
        ),
        # -- the one next step -------------------------------------------------------------------
        "llm.next": ("Next:", "下一步："),
        "llm.next.add": ("add a model connection (step 1).", "新增模型連線（步驟 1）。"),
        "llm.next.fetch": (
            "get the available models of “{connection}”.",
            "取得「{connection}」的可用模型。",
        ),
        "llm.next.test": (
            "choose a model of “{connection}” and run the capability test.",
            "選一個「{connection}」的模型，執行模型能力測試。",
        ),
        "llm.next.lock": ("confirm the model “{model}”.", "確認「{model}」這個模型。"),
        "llm.next.failed": (
            "“{model}” passed no test: test another model.",
            "「{model}」沒有通過測試，請換一個模型測試。",
        ),
        "llm.next.disabled": (
            "enable the connection “{connection}” again.",
            "重新啟用模型連線「{connection}」。",
        ),
        "llm.next.credential": (
            "fix the API key of “{connection}”.",
            "修正「{connection}」的 API 金鑰。",
        ),
        "llm.next.unreachable": (
            "make “{connection}” reachable, then get its models again.",
            "讓「{connection}」可以連上，再重新取得可用模型。",
        ),
        "llm.next.assign": (
            "assign a model to {slot} (step 3).",
            "替「{slot}」指派模型（步驟 3）。",
        ),
        "llm.next.confirm_for": (
            "test and confirm a model that can do {slot} (step 2).",
            "測試並確認一個能勝任「{slot}」的模型（步驟 2）。",
        ),
        "llm.next.check": ("check the configuration (step 4).", "檢查配置（步驟 4）。"),
        "llm.next.apply": (
            "apply the configuration “{name}” (step 4).",
            "套用配置「{name}」（步驟 4）。",
        ),
        "llm.next.applied": (
            "nothing: “{name}” is applied and new research uses it.",
            "不需要處理：配置「{name}」已套用，新的研究會使用它。",
        ),
        "llm.next.fix_active": (
            "the applied configuration “{name}” cannot be used -- fix it first.",
            "已套用的配置「{name}」目前無法使用，請先修正。",
        ),
        "llm.next.todo": (
            "work through the list in step 4.",
            "依照步驟 4 的清單逐項完成。",
        ),
        # -- still to do / how -------------------------------------------------------------------
        "llm.todo.title": ("Still to do / how", "尚待處理 / 怎麼完成"),
        "llm.col.what": ("Still to do", "尚待處理"),
        "llm.col.how": ("How", "怎麼完成"),
        "llm.todo.none": ("Nothing left to do.", "沒有尚待處理的項目。"),
        "llm.todo.no_connection": ("No model connection yet", "尚未新增模型連線"),
        "llm.how.no_connection": (
            "In step 1 choose the provider, give a name and its API key (a local model needs "
            "none), then press “＋ Add”.",
            "在步驟 1 選擇模型服務，填入名稱與 API 金鑰（本機模型不需要金鑰），再按「＋ 新增」。",
        ),
        "llm.todo.fetch": ("“{connection}” has no models yet", "「{connection}」還沒有可用模型"),
        "llm.how.fetch": (
            "Press “Get available models” in step 2. If the list cannot be fetched, add a model "
            "by name on the connection's details page.",
            "在步驟 2 按「取得可用模型」。如果取不到清單，可以在連線詳細頁手動加入模型名稱。",
        ),
        "llm.todo.test": (
            "No model of “{connection}” is tested yet",
            "「{connection}」的模型還沒有測試",
        ),
        "llm.how.test": (
            "In step 2 choose a model and press “Run capability test”. The test sends fixed "
            "sample prompts only -- never research data.",
            "在步驟 2 選一個模型，按「執行模型能力測試」。測試只送出固定的測試內容，"
            "不含任何研究資料。",
        ),
        "llm.todo.lock": ("“{model}” is tested but not confirmed", "「{model}」已測試，還沒確認"),
        "llm.how.lock": (
            "Check its results and press “Confirm this model”; only confirmed models can be "
            "assigned.",
            "檢查測試結果後按「確認此模型」；只有已確認的模型才能指派。",
        ),
        "llm.todo.failed": ("“{model}” passed no basic test", "「{model}」沒有通過基本測試"),
        "llm.how.failed": (
            "Check that the model name and the service are right and test again, or test "
            "another model.",
            "確認模型名稱與服務正常後重新測試，或換一個模型測試。",
        ),
        "llm.todo.disabled": (
            "The connection “{connection}” is disabled",
            "模型連線「{connection}」已停用",
        ),
        "llm.how.disabled": (
            "Open its details and press “Enable”.",
            "到連線詳細頁按「啟用」。",
        ),
        "llm.todo.credential": (
            "The API key of “{connection}” cannot be read",
            "「{connection}」的 API 金鑰讀不到",
        ),
        "llm.how.credential": (
            "Replace the key on the connection's details page; if it comes from an environment "
            "variable, make sure the workspace runs with it set.",
            "到連線詳細頁更換金鑰；如果金鑰來自環境變數，確認工作台執行時有設定這個變數。",
        ),
        "llm.todo.unreachable": ("“{connection}” cannot be reached", "「{connection}」連不上"),
        "llm.how.unreachable": (
            "Make sure the service is running and its URL and key are right, then press “Get "
            "available models” again.",
            "確認服務正在執行、網址與金鑰正確，再按一次「取得可用模型」。",
        ),
        "llm.todo.no_candidate": (
            "No confirmed model can do {slot} yet",
            "還沒有能勝任「{slot}」的已確認模型",
        ),
        "llm.how.no_candidate": (
            "In step 2 test and confirm a model that passes what this use needs (listed in step "
            "3).",
            "在步驟 2 測試並確認一個能通過這項用途所需測試的模型（需要的測試列在步驟 3）。",
        ),
        "llm.todo.slot_empty": ("{slot} has no model yet", "「{slot}」還沒有模型"),
        "llm.how.slot_empty": (
            "In step 3 choose a confirmed model for {slot} and press “Assign”.",
            "在步驟 3 替「{slot}」選一個已確認的模型，按「指派」。",
        ),
        "llm.todo.stale_lock": (
            "“{model}”, assigned to {slot}, was confirmed under earlier test rules",
            "指派給「{slot}」的「{model}」是在舊版測試規則下確認的",
        ),
        "llm.how.stale_lock": (
            "Unlock it in step 2, run the capability test again and confirm it again (a model the "
            "applied configuration uses is released by retiring that configuration first). Its "
            "earlier confirmation stays on record.",
            "在步驟 2 解除確認、重新執行模型能力測試，通過後再確認（套用中的配置所使用的模型，"
            "需先停用該配置才能解除）。先前的確認紀錄會保留。",
        ),
        "llm.todo.role_fit": (
            "“{model}”, assigned to {slot}, demonstrated at least {shown} competing hypotheses; "
            "this deployment's research needs {required}",
            "指派給「{slot}」的「{model}」只證明能提出至少 {shown} 個競爭假說，"
            "這個部署的研究需要 {required} 個",
        ),
        "llm.how.role_fit": (
            "Test it again under the current requirement (unlock it first), or assign a model that "
            "demonstrated enough. Passing the general test is not enough for this research.",
            "解除確認後在目前的要求下重新測試，或改指派已證明足夠的模型。"
            "只通過一般能力測試，不代表能勝任這個部署的研究。",
        ),
        "llm.todo.too_slow": (
            "“{model}”, assigned to {slot}, needed {seconds} s for a test this use requires -- "
            "longer than this deployment allows one model call ({deadline} s)",
            "指派給「{slot}」的「{model}」完成這項用途必要的測試花了 {seconds} 秒，"
            "超過這個部署每次模型呼叫的時限（{deadline} 秒）",
        ),
        "llm.how.too_slow": (
            "Raise the deployment's inference deadline (LAB_BRAIN_INFERENCE_DEADLINE, or lab-brain "
            "web --inference-deadline) and restart it, or assign a faster model. The recorded "
            "test results stay as they are.",
            "提高部署的推理時限（LAB_BRAIN_INFERENCE_DEADLINE，或 lab-brain web "
            "--inference-deadline）後重新啟動，或改指派較快的模型。已記錄的測試結果不會改變。",
        ),
        "llm.todo.not_locked": (
            "The model “{model}” assigned to {slot} is no longer confirmed",
            "「{slot}」指派的「{model}」目前不是已確認狀態",
        ),
        "llm.how.not_locked": (
            "Confirm it again in step 2, or assign another model.",
            "在步驟 2 重新確認這個模型，或改指派其他模型。",
        ),
        "llm.todo.conn_off": (
            "The connection “{connection}” used for {slot} is not in use",
            "「{slot}」使用的模型連線「{connection}」沒有啟用",
        ),
        "llm.how.conn_off": (
            "Enable the connection again, or assign a model from another connection.",
            "重新啟用這個連線，或改指派其他連線的模型。",
        ),
        "llm.todo.never_checked": (
            "The connection “{connection}” used for {slot} was never checked",
            "「{slot}」使用的模型連線「{connection}」還沒檢查過",
        ),
        "llm.how.never_checked": (
            "Press “Check the configuration” in step 4.",
            "在步驟 4 按「檢查配置」。",
        ),
        "llm.todo.unhealthy": (
            "The last check of “{connection}” (used for {slot}) failed: {outcome}",
            "「{slot}」使用的模型連線「{connection}」最近一次檢查失敗：{outcome}",
        ),
        "llm.how.unhealthy": (
            "Make sure the service is running and its URL and key are right, then press “Check "
            "the configuration”.",
            "確認服務正在執行、網址與金鑰正確，再按「檢查配置」。",
        ),
        "llm.todo.critic": (
            "Independent critique has no model, and the Primary reasoning model did not pass the "
            "critique test",
            "「獨立批判」沒有指派模型，而「主要推理」的模型沒有通過反方批判測試",
        ),
        "llm.how.critic": (
            "Assign a confirmed model to Independent critique, or test the Primary reasoning "
            "model again until it passes the critique test.",
            "替「獨立批判」指派一個已確認的模型，或重新測試主要推理的模型直到通過反方批判測試。",
        ),
        "llm.todo.active_unusable": (
            "The applied configuration “{name}” cannot be used: {reason}",
            "已套用的配置「{name}」目前無法使用：{reason}",
        ),
        "llm.how.active_unusable": (
            "Fix what the reason names (usually an API key or a connection), then check the "
            "configuration again.",
            "依照原因修正（通常是 API 金鑰或模型連線），再重新檢查配置。",
        ),
        "llm.todo.raw": ("{text}", "{text}"),
        "llm.how.raw": (
            "The rule's own words are under the technical details below.",
            "系統規則的原文在下方的技術細節中。",
        ),
        "llm.warnings": ("Notes", "注意事項"),
        "llm.warn.critic_fallback": (
            "Independent critique has no model: adversarial review runs on the Primary reasoning "
            "model, which is not an independent model.",
            "「獨立批判」沒有指派模型：反方審查會改由「主要推理」的模型處理，這不是獨立的模型。",
        ),
        "llm.how.critic_fallback": (
            "For a truly independent review, assign a different confirmed model to Independent "
            "critique.",
            "若要真正獨立的反方審查，請替「獨立批判」指派另一個已確認的模型。",
        ),
        "llm.warn.raw": ("{text}", "{text}"),
        # -- step 1: add a model connection -------------------------------------------------------
        "llm.s1": ("1. Add a model connection", "1. 新增模型連線"),
        "llm.s1.lede": (
            "Where the models come from: a local model on this machine, or an external API with "
            "its key.",
            "模型從哪裡來：這台電腦上的本機模型，或是需要 API 金鑰的外部 API。",
        ),
        "llm.provider": ("Provider", "模型服務（Provider）"),
        "llm.name": ("Name", "名稱"),
        "llm.name.hint": (
            "optional: lower-case letters, digits and '-', e.g. openai-main; left empty, one is "
            "chosen",
            "選填：英文小寫、數字或 -，例如 openai-main；留空會自動命名",
        ),
        "llm.key": ("API key", "API 金鑰"),
        "llm.key.hint": (
            "kept in {store}; never shown again -- only a fingerprint of its last characters. "
            "Leave empty for a local model.",
            "保存在 {store}；之後不會再顯示，只顯示最後幾碼的指紋。本機模型請留空。",
        ),
        "llm.key.env": ("API key environment variable", "API 金鑰環境變數名稱"),
        "llm.key.env.hint": (
            "This machine has no secure key store, so a typed key would be refused. Put the key "
            "in deployment/docker/llm-keys.env (Docker) or the workspace's environment and enter "
            "the variable's name here, e.g. OPENAI_API_KEY. Leave empty for a local model.",
            "這台機器沒有安全的金鑰儲存區，直接輸入金鑰會被拒絕。請把金鑰放在 deployment/docker/llm"
            "-keys.env"
            "（Docker）或工作台的環境變數中，並在這裡填變數名稱，例如 OPENAI_API_KEY。"
            "本機模型請留空。",
        ),
        "llm.add": ("＋ Add", "＋ 新增"),
        "llm.bad_provider": ("Choose a provider.", "請選擇模型服務。"),
        "llm.need_url": (
            "Enter the service URL under Advanced for “other service”.",
            "選擇「其他服務」時，請在進階設定填入服務網址。",
        ),
        "llm.need_key": (
            "Enter the API key (or, under Advanced, the environment variable that holds it).",
            "請填入 API 金鑰（或在進階設定填入存放金鑰的環境變數名稱）。",
        ),
        "llm.advanced": (
            "Advanced: custom service URL, key from an environment variable",
            "進階設定：自訂服務網址、以環境變數提供金鑰",
        ),
        "llm.base_url": ("Service URL", "服務網址"),
        "llm.base_url.hint": (
            "only for “other service”, or to override a provider's usual address; an "
            "OpenAI-compatible endpoint, https:// unless it runs on this machine, e.g. "
            "https://api.example.com/v1",
            "只有「其他服務」或要改用其他位址時才需要填；需為 OpenAI 相容端點，"
            "除了這台電腦上的服務以外都必須是 https://，例如 https://api.example.com/v1",
        ),
        "llm.reach": ("Type", "類型"),
        "llm.reach.hint": (
            "A local model only for one on this machine; anything else is an external API and "
            "passes the external transfer rules.",
            "只有這台電腦上的模型能設為本機模型；其他一律是外部 API，並受外部傳輸規則管制。",
        ),
        "llm.reach.LOCAL": ("Local model", "本機模型"),
        "llm.reach.EXTERNAL": ("External API", "外部 API"),
        "llm.env_name": ("Key from environment variable", "改用環境變數提供金鑰"),
        "llm.env_name.hint": (
            "instead of typing the key: the variable's name, e.g. OPENAI_API_KEY",
            "不直接輸入金鑰時使用：填變數名稱，例如 OPENAI_API_KEY",
        ),
        "llm.p.ollama": ("Local model (Ollama)", "本機模型（Ollama）"),
        "llm.p.openai": ("OpenAI", "OpenAI"),
        "llm.p.openrouter": ("OpenRouter", "OpenRouter"),
        "llm.p.gemini": ("Google Gemini", "Google Gemini"),
        "llm.p.deepseek": ("DeepSeek", "DeepSeek"),
        "llm.p.mistral": ("Mistral", "Mistral"),
        "llm.p.xai": ("xAI (Grok)", "xAI（Grok）"),
        "llm.p.custom": (
            "Other OpenAI-compatible service (URL under Advanced)",
            "其他 OpenAI 相容服務（在進階設定填網址）",
        ),
        # -- step 2: get, test, confirm ----------------------------------------------------------
        "llm.s2": ("2. Get, test and confirm models", "2. 取得、測試並確認模型"),
        "llm.s2.lede": (
            "Each connection, left to right: get the available models → choose one → run the "
            "capability test → confirm it. Only confirmed models can be assigned in step 3.",
            "每個模型連線依序完成：取得可用模型 → 選一個模型 → 執行模型能力測試 → 確認此模型。"
            "只有已確認的模型才能在步驟 3 指派。",
        ),
        "llm.s2.none": (
            "No model connection yet: add one in step 1.",
            "還沒有模型連線：請先完成步驟 1。",
        ),
        "llm.fetch": ("Get available models", "取得可用模型"),
        "llm.pick": ("Model to test", "要測試的模型"),
        "llm.test": ("Run capability test", "執行模型能力測試"),
        "llm.test.note": (
            "The test sends only fixed sample prompts -- never project data. Each answer is "
            "judged by code; the role tests use the real research parsers.",
            "測試只送出固定的測試內容，不含任何研究資料。每個回答都由程式判定；研究角色的測試使用實際的研究解析器。",
        ),
        "llm.lock": ("Confirm this model", "確認此模型"),
        "llm.lock.stale": (
            "This confirmation was made under earlier test rules (a test, role prompt or answer "
            "format has changed since): the model cannot be used until it is unlocked, tested "
            "again and confirmed again. The earlier confirmation stays on record.",
            "這個確認是在舊版測試規則下完成的（測試內容、角色提示或回答格式已變更）：解除確認、"
            "重新測試並再次確認之前，這個模型無法使用。先前的確認紀錄會保留。",
        ),
        "llm.probe.minimum": (" (asked for at least {n} hypotheses)", "（要求至少 {n} 個假說）"),
        "llm.details": ("Details", "詳細"),
        "llm.cstep.done": (
            "Ready: {n} confirmed model(s) here can be assigned in step 3.",
            "已就緒：這個連線有 {n} 個已確認的模型，可以在步驟 3 指派。",
        ),
        "llm.cstep.retired": ("Removed.", "已移除。"),
        "llm.models.count": ("{n} model(s)", "{n} 個模型"),
        "llm.passed": ("passed:", "通過："),
        "llm.passed.none": ("passed nothing yet", "尚未通過任何測試"),
        "llm.mstate.DISCOVERED": ("not tested", "未測試"),
        "llm.mstate.TESTED": ("tested, not confirmed", "已測試，未確認"),
        "llm.mstate.LOCKED": ("confirmed", "已確認"),
        "llm.mstate.RETIRED": ("retired", "已停用"),
        "llm.cstate.ENABLED": ("in use", "使用中"),
        "llm.cstate.DISABLED": ("disabled", "已停用"),
        "llm.cstate.RETIRED": ("removed", "已移除"),
        "llm.h.REACHABLE": ("answers", "連線正常"),
        "llm.h.AUTH_FAILED": ("key refused", "金鑰被拒絕"),
        "llm.h.UNREACHABLE": ("unreachable", "連不上"),
        "llm.h.TIMEOUT": ("no answer in time", "回應逾時"),
        "llm.h.PROTOCOL_ERROR": ("unexpected answer", "回應格式不符"),
        "llm.h.SECRET_UNAVAILABLE": ("key unreadable", "讀不到金鑰"),
        "llm.h.none": ("not checked yet", "尚未檢查"),
        "llm.probe.PASSED": ("passed", "通過"),
        "llm.probe.FAILED": ("failed", "未通過"),
        "llm.probe.ERROR": ("error", "錯誤"),
        # -- step 3: assign ----------------------------------------------------------------------
        "llm.s3": ("3. Assign models to research work", "3. 指派模型給研究工作"),
        "llm.s3.lede": (
            "Each kind of research work (a use) is served by one confirmed model. Which research "
            "roles go to which use is fixed in code; you choose the model.",
            "每一種研究工作（模型用途）由一個已確認的模型負責。哪些研究角色屬於哪種用途寫在程式中，你只需要選模型。",
        ),
        "llm.s3.active": (
            "The applied configuration cannot be changed in place: assigning a model starts a "
            "new configuration from it, and the applied one stays in use until you apply the "
            "new one.",
            "已套用的配置不能直接修改：指派模型時會以它為起點建立新的配置；新的配置套用之前，原本的配置會繼續使用。",
        ),
        "llm.col.use": ("Use", "模型用途"),
        "llm.col.roles": ("Research roles", "負責的研究角色"),
        "llm.col.model": ("Model", "指派的模型"),
        "llm.required": ("required", "必要"),
        "llm.recommended": ("recommended", "建議"),
        "llm.optional": ("optional", "選用"),
        "llm.assign": ("Assign", "指派"),
        "llm.unassign": ("Remove", "移除"),
        "llm.no_option": (
            "No confirmed model has passed what this use needs yet.",
            "還沒有已確認的模型通過這項用途需要的測試。",
        ),
        "llm.needs": ("needs:", "需要通過："),
        "llm.s3.more": (
            "Other uses (no research step uses them in this version)",
            "其他用途（這個版本沒有研究步驟使用）",
        ),
        # -- step 4: check and apply -------------------------------------------------------------
        "llm.s4": ("4. Check and apply the configuration", "4. 檢查並套用配置"),
        "llm.check": ("Check the configuration", "檢查配置"),
        "llm.check.note": (
            "Asks each connection the configuration uses whether it answers, then checks again.",
            "向配置使用的每個模型連線確認是否有回應，然後重新檢查。",
        ),
        "llm.apply": ("Apply configuration", "套用配置"),
        "llm.apply.note": (
            "New research then uses this configuration and the one applied before is retired. "
            "Applying checks everything once more and refuses if anything is missing.",
            "套用後，新的研究會使用這個配置，原本套用的配置會停用。套用時會再檢查一次，有缺漏就不會套用。",
        ),
        "llm.apply.later": (
            "“Apply configuration” becomes available once the list above is done.",
            "上方清單完成後，就可以按「套用配置」。",
        ),
        "llm.nothing_to_apply": (
            "No configuration is being prepared: assign a model in step 3 to start one.",
            "目前沒有準備中的配置：在步驟 3 指派模型時會自動建立。",
        ),
        "llm.deactivate": ("Stop using the applied configuration", "停用目前的配置"),
        "llm.deactivate.note": (
            "New research then uses the local rule-based reasoner.",
            "之後新的研究會使用本機規則式推理。",
        ),
        "llm.discard": ("Discard this draft", "捨棄這個準備中的配置"),
        # -- advanced ----------------------------------------------------------------------------
        "llm.adv": ("Advanced and technical details", "進階設定與技術細節"),
        "llm.new_runtime": ("New configuration", "建立新的模型配置"),
        "llm.runtime.labels": (
            "Highest classification an external API may receive",
            "外部 API 最多可以收到的分級",
        ),
        "llm.runtime.labels.note": (
            "NDA material never leaves this machine. Each project's own external transfer "
            "setting and each researcher's access still apply.",
            "保密協議（NDA）的資料永遠不會離開這台電腦。各研究專案自己的外部傳輸設定與研究者的閱讀權限仍然適用。",
        ),
        "llm.draft.labels": (
            "The configuration being prepared lets an external API receive at most: {labels}.",
            "準備中的配置允許外部 API 最多收到：{labels}。",
        ),
        "llm.create": ("Create", "建立"),
        "llm.configs": ("All configurations", "所有模型配置"),
        "llm.rstate.DRAFT": ("being prepared", "準備中"),
        "llm.rstate.ACTIVE": ("applied", "套用中"),
        "llm.rstate.RETIRED": ("retired", "已停用"),
        "llm.roles": (
            "Research roles and uses (fixed in code, read-only)",
            "研究角色與模型用途的對應（寫在程式中，唯讀）",
        ),
        "llm.critic_fallback": (
            "When Independent critique has no model, adversarial review falls back to {slot}: "
            "no independent model.",
            "「獨立批判」沒有指派模型時，反方審查會改由「{slot}」處理：沒有獨立的模型。",
        ),
        "llm.requirements": (
            "What each use's model must pass",
            "各用途的模型必須通過的測試",
        ),
        "llm.output_language": (
            "Research reports are written in {lang}, whatever the interface language.",
            "不論介面語言為何，研究報告都以{lang}撰寫。",
        ),
        "llm.lang.en": ("English", "英文"),
        "col.slot": ("Use", "模型用途"),
        "col.roles": ("Research roles", "研究角色"),
        "col.requires": ("Needs", "需要通過"),
        "col.endpoint": ("Service URL", "服務網址"),
        "col.reach": ("Type", "類型"),
        "col.credential": ("API key", "API 金鑰"),
        "col.config": ("Status", "狀態"),
        "col.health": ("Latest check", "最近一次檢查"),
        "col.models": ("Models", "模型"),
        "col.model": ("Model", "模型"),
        "col.connection": ("Model connection", "模型連線"),
        "col.source": ("Source", "來源"),
        "col.lifecycle": ("Status", "狀態"),
        "col.verified": ("Latest test result", "最近一次測試結果"),
        "col.locked": ("Confirmed capabilities", "確認時通過的能力"),
        "col.route": ("Model fingerprint", "模型指紋"),
        "col.labels": ("External upper limit", "外部 API 分級上限"),
        "col.bindings": ("Assignments", "指派"),
        "col.activated": ("Applied", "套用時間"),
        "col.capability": ("Capability", "能力"),
        "col.latency": ("Time (ms)", "耗時（毫秒）"),
        "col.when": ("When", "時間"),
        "col.needed_by": ("Needed by", "哪些用途需要"),
        "llm.source.FETCHED": ("from the model list", "取得清單"),
        "llm.source.DECLARED": ("added by name", "手動加入"),
        "llm.none": ("None yet.", "目前沒有。"),
        "llm.no_credential": ("none", "無"),
        # -- the connection's details ------------------------------------------------------------
        "llm.back": ("Back to AI model settings", "回到 AI 模型設定"),
        "llm.credential": ("API key", "API 金鑰"),
        "llm.credential.none": (
            "none (a local model without a key)",
            "無（不需金鑰的本機模型）",
        ),
        "llm.credential.env": (
            "an environment variable of this workspace:",
            "工作台的環境變數：",
        ),
        "llm.credential.store": ("type it in, kept in {store}:", "直接輸入，保存在 {store}："),
        "llm.credential.nostore": (
            "No secure key store is available on this machine: a typed-in key would be refused. "
            "Set an environment variable for the workspace and reference it.",
            "這台機器沒有安全的金鑰儲存區：直接輸入的金鑰會被拒絕。請替工作台設定環境變數，並在這裡填變數名稱。",
        ),
        "llm.credential.note": (
            "The key is never stored by the workspace or shown again: only its reference and a "
            "fingerprint are kept.",
            "工作台不會儲存或再次顯示金鑰：只保留它的來源與指紋。",
        ),
        "llm.save": ("Save", "儲存"),
        "llm.check_health": ("Check connection", "檢查連線"),
        "llm.declare": ("Add a model by name", "手動加入模型名稱"),
        "llm.declare.button": ("Add", "加入"),
        "llm.enable": ("Enable", "啟用"),
        "llm.disable": ("Disable", "停用"),
        "llm.retire": ("Remove", "移除"),
        "llm.replace_credential": ("Replace the API key", "更換 API 金鑰"),
        "llm.health_history": ("Connection checks", "連線檢查紀錄"),
        "llm.health_note": (
            "A check records what the service answered at that moment; it never changes the "
            "settings.",
            "連線檢查只記錄當時服務的回應，不會改變設定。",
        ),
        # -- the model's details -----------------------------------------------------------------
        "llm.unlock": ("Undo confirmation", "取消確認"),
        "llm.lock.note": (
            "Confirming freezes exactly the capabilities whose latest test passed, and a "
            "fingerprint recorded with every inference as the model version.",
            "確認時會凍結最近一次測試通過的能力，以及每次推論都會記錄的模型指紋（作為模型版本）。",
        ),
        "llm.serves": ("Uses this model can serve", "這個模型可以負責的用途"),
        "llm.probe_history": ("Test history", "測試紀錄"),
        "llm.retire_model": ("Retire this model", "停用這個模型"),
        # -- a configuration's details -----------------------------------------------------------
        "llm.runtime.title": ("Model configuration", "模型配置"),
        "llm.bind": ("Assign", "指派"),
        "llm.unbind": ("Remove", "移除"),
        "llm.no_eligible": (
            "No confirmed model has passed what this use needs.",
            "沒有已確認的模型通過這項用途需要的測試。",
        ),
        "llm.ineligible": ("Not eligible:", "不符合："),
        "llm.critic": ("Adversarial review", "反方審查"),
        "llm.egress": ("External transfer", "外部傳輸"),
        "llm.blockers": ("Still to do", "尚待處理"),
        "llm.ready": ("Ready to apply.", "可以套用。"),
        "llm.ready.active": ("Complete: nothing is missing.", "配置完整：沒有缺漏。"),
        "llm.not_ready": ("Not ready yet -- still to do:", "尚未完成，還需要處理："),
        "rt.title": ("Current model configuration", "目前的模型配置"),
        "rt.none": (
            "No AI model configuration is applied. New research uses the local rule-based "
            "reasoner for every use: no AI model is called.",
            "目前沒有套用 AI 模型配置。新的研究在所有用途都使用本機規則式推理，不會呼叫任何 AI "
            "模型。",
        ),
        "rt.active": ("Applied configuration", "套用中的配置"),
        "rt.unusable": (
            "It cannot be used right now, so new research is refused rather than sent to another "
            "model: {reason}",
            "目前無法使用，因此新的研究會被拒絕，而不會改用其他模型：{reason}",
        ),
        "rt.open": ("Open the configuration", "開啟配置"),
        "llm.open": ("AI model settings", "前往 AI 模型設定"),
    }
)

#: The providers the connection form offers: (message key, usual base URL, reach). Every one is an
#: OpenAI-compatible endpoint -- the only kind `012e` knows -- so a preset is only a convenience
#: for the URL and the reach; nothing here is provider-specific logic. `None`: the local model's
#: address, which depends on where the workspace runs.
PROVIDERS: Mapping[str, tuple[str | None, str]] = {
    "ollama": (None, "LOCAL"),
    "openai": ("https://api.openai.com/v1", "EXTERNAL"),
    "openrouter": ("https://openrouter.ai/api/v1", "EXTERNAL"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "EXTERNAL"),
    "deepseek": ("https://api.deepseek.com/v1", "EXTERNAL"),
    "mistral": ("https://api.mistral.ai/v1", "EXTERNAL"),
    "xai": ("https://api.x.ai/v1", "EXTERNAL"),
    "custom": (None, "EXTERNAL"),
}


def provider_of(connection: ConnectionRow) -> str:
    """The preset a connection's URL matches, for display ("custom" otherwise)."""
    for key, (url, _reach) in PROVIDERS.items():
        if url is not None and connection.base_url.rstrip("/") == url:
            return key
    if connection.reach == "LOCAL" and urlsplit(connection.base_url).port == 11434:
        return "ollama"
    return "custom"


@dataclass(frozen=True)
class Overview:
    guide: Guide
    runtimes: Sequence[RuntimeRow]
    bindings: Mapping[str, Mapping[LogicalSlot, str]]
    secure_store: str | None
    #: What protects a pasted key here ("os", "filesystem") -- or None: no store.
    store_protection: str | None
    ollama: credential_forms.OllamaState


def _csrf(chrome: Chrome) -> Html:
    return h('<input type="hidden" name="csrf" value="{}">', chrome.csrf or "")


def _back_field() -> Html:
    return Html('<input type="hidden" name="next" value="/settings/llm">')


def _button(
    chrome: Chrome, action: str, label: str, css: str = "small", *, back: bool = False
) -> Html:
    return h(
        '<form class="inline" method="post" action="{}">{}{}<button class="{}" type="submit">{}'
        "</button></form>",
        action,
        _csrf(chrome),
        _back_field() if back else Html(""),
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


def _named(prefix: str, value: str, m: Messages, css: str | None = None) -> Html:
    """A stored enum value by its name (the value in the tooltip)."""
    try:
        text = m(f"{prefix}.{value}")
    except KeyError:
        text = value
    return h('<span class="state state-{}" title="{}">{}</span>', css or value, value, text)


def _credential(c: ConnectionRow, m: Messages) -> Html:
    """Where the key is, in words, and its fingerprint: never the key, and the reference itself
    only in the technical details."""
    if c.secret_ref is None:
        return e(m("llm.no_credential"))
    scheme, _, name = c.secret_ref.partition(":")
    if scheme == "env":
        return h("{} <code>{}</code>", m("cred.where.env", name=name), c.secret_fingerprint or "")
    return h("{} <code>{}</code>", m("cred.where.stored"), c.secret_fingerprint or "")


def _health(row: HealthRow | None, m: Messages) -> Html:
    if row is None:
        return e(m("llm.h.none"))
    return h(
        '{} <span class="muted">{}</span>',
        _named("llm.h", row.outcome, m),
        when(row.checked_at),
    )


def _slot_text(value: str, m: Messages) -> str:
    try:
        return labels.SLOT_NAMES[LogicalSlot(value)][0 if m.locale == "en" else 1]
    except (ValueError, KeyError):
        return value


def _values(todo: Todo, m: Messages) -> dict[str, str]:
    values = dict(todo.values)
    if "slot" in values:
        values["slot"] = _slot_text(values["slot"], m)
    if "outcome" in values:
        with suppress(KeyError):
            values["outcome"] = m(f"llm.h.{values['outcome']}")
    return values


def todo_text(todo: Todo, m: Messages) -> tuple[str, str]:
    values = _values(todo, m)
    return m(todo.what, **values), (m(todo.how, **values) if todo.how else "")


def checklist(todos: Sequence[Todo], m: Messages, *, empty: bool = True) -> Html:
    """The "still to do / how" table; the server's own rule text of each line one click away."""
    if not todos:
        return h('<p class="box">{}</p>', m("llm.todo.none")) if empty else Html("")
    rows = []
    for todo in todos:
        what, how = todo_text(todo, m)
        rows.append(
            h(
                "<tr><td>{}</td><td>{}</td></tr>",
                labels.humanize(what, m.locale) if todo.what.endswith(".raw") else what,
                how,
            )
        )
    raw = [t.raw for t in todos if t.raw]
    return h(
        '<div class="scroll"><table class="checklist"><thead><tr><th>{}</th><th>{}</th></tr>'
        "</thead><tbody>{}</tbody></table></div>{}",
        m("llm.col.what"),
        m("llm.col.how"),
        cat(rows),
        labels.technical(m.locale, [], raw) if raw else Html(""),
    )


def _warnings(todos: Sequence[Todo], m: Messages) -> Html:
    if not todos:
        return Html("")
    return h(
        '<div class="box warn"><strong>{}</strong><ul>{}</ul></div>',
        m("llm.warnings"),
        cat(
            h(
                "<li>{}{}</li>",
                labels.humanize(todo_text(t, m)[0], m.locale),
                h(' <span class="purpose">{}</span>', todo_text(t, m)[1]) if t.how else Html(""),
            )
            for t in todos
        ),
    )


def _error(chrome: Chrome, error: object) -> Html:
    return credential_forms.problem(chrome, error)


def _next_box(m: Messages, guide: Guide) -> Html:
    values = dict(guide.next_values)
    if "slot" in values:
        values["slot"] = _slot_text(values["slot"], m)
    return h(
        '<div class="next"><strong>{}</strong> {}</div>',
        m("llm.next"),
        m(guide.next_step, **values),
    )


def _caps(values: Iterable[str], m: Messages) -> Html:
    return labels.listing((labels.capability(c, m.locale) for c in sorted(values)), m.locale)


# -- step 2 ---------------------------------------------------------------------------------------


def _connection_card(chrome: Chrome, line: ConnectionLine) -> Html:
    m = chrome.m
    c = line.connection
    base = f"/settings/llm/connections/{c.connection_id}"
    usable = c.lifecycle == "ENABLED" and not line.credential_problem
    untested = [x for x in line.models if x.model.lifecycle in ("DISCOVERED", "TESTED")]
    fetch = h(
        '<form method="post" action="{}/fetch">{}{}<button class="small" type="submit"{}>{}'
        "</button></form>",
        base,
        _csrf(chrome),
        _back_field(),
        Html("" if usable else " disabled"),
        m("llm.fetch"),
    )
    test = (
        h(
            '<form method="post" action="{}/test">{}{}<select name="model_profile_id"'
            ' aria-label="{}">{}</select><button class="small" type="submit"{}>{}</button></form>',
            base,
            _csrf(chrome),
            _back_field(),
            m("llm.pick"),
            cat(
                h(
                    '<option value="{}"{}>{} ({})</option>',
                    x.model.model_profile_id,
                    Html(
                        " selected"
                        if line.focus is not None
                        and x.model.model_profile_id == line.focus.model_profile_id
                        else ""
                    ),
                    x.model.model_name,
                    m(f"llm.mstate.{x.model.lifecycle}"),
                )
                for x in untested
            ),
            Html("" if usable else " disabled"),
            m("llm.test"),
        )
        if untested
        else Html("")
    )
    lock = (
        h(
            '<form method="post" action="/settings/llm/models/{}/lock">{}{}'
            '<button class="small" type="submit">{}: {}</button></form>',
            line.focus.model_profile_id,
            _csrf(chrome),
            _back_field(),
            m("llm.lock"),
            line.focus.model_name,
        )
        if line.step == "llm.cstep.lock" and line.focus is not None
        else Html("")
    )
    confirmed = [x for x in line.models if x.model.lifecycle == "LOCKED"]
    if line.step == "llm.cstep.done":
        step = h('<span class="badge state-READY">{}</span>', m("llm.cstep.done", n=len(confirmed)))
    else:
        key = f"llm.next.{line.step.rsplit('.', 1)[1]}"
        step = h(
            '<span class="next-step"><strong>{}</strong> {}</span>',
            m("llm.next"),
            m(
                key,
                connection=c.name,
                model=line.focus.model_name if line.focus is not None else "",
            ),
        )
    shown = [x for x in line.models if x.model.lifecycle in ("TESTED", "LOCKED")]
    tested = (
        h(
            "<ul>{}</ul>",
            cat(
                h(
                    "<li><code>{}</code> {} -- {}</li>",
                    x.model.model_name,
                    _named("llm.mstate", x.model.lifecycle, m),
                    h("{} {}", m("llm.passed"), _caps(x.passed, m))
                    if x.passed
                    else e(m("llm.passed.none")),
                )
                for x in shown
            ),
        )
        if shown
        else Html("")
    )
    return h(
        '<div class="conn" id="c-{}"><div class="row"><strong>{}</strong>'
        ' <span class="badge">{}</span> {} {} <span class="muted">{}</span>'
        ' <a href="{}">{}</a></div>'
        '<div class="row">{}{}{}</div><div>{}</div>{}</div>',
        c.connection_id,
        c.name,
        m(f"llm.p.{provider_of(c)}"),
        _named("llm.reach", c.reach, m),
        _health(line.health, m),
        m("llm.models.count", n=len(line.models)),
        base,
        m("llm.details"),
        fetch,
        test,
        lock,
        step,
        tested,
    )


# -- step 3 ---------------------------------------------------------------------------------------


def _assign_rows(chrome: Chrome, guide: Guide, slots: Sequence[LogicalSlot]) -> Html:
    m = chrome.m
    rows = []
    for line in guide.slots:
        if line.slot not in slots:
            continue
        need = (
            "llm.required"
            if line.required
            else (
                "llm.recommended"
                if line.slot is LogicalSlot.REASONING_ADVERSARIAL
                else "llm.optional"
            )
        )
        current = (
            h(
                "<div><code>{}</code> {}</div>",
                line.bound.model_name,
                h(
                    '<form class="inline" method="post" action="/settings/llm/assign">{}'
                    '<input type="hidden" name="slot" value="{}">'
                    '<input type="hidden" name="action" value="unassign">'
                    '<button class="small" type="submit">{}</button></form>',
                    _csrf(chrome),
                    line.slot.value,
                    m("llm.unassign"),
                )
                if guide.draft is not None
                else Html(""),
            )
            if line.bound is not None
            else Html("")
        )
        choose = (
            h(
                '<form method="post" action="/settings/llm/assign" class="inline">{}'
                '<input type="hidden" name="slot" value="{}"><select name="model" aria-label="{}">'
                '{}</select> <button class="small" type="submit">{}</button></form>',
                _csrf(chrome),
                line.slot.value,
                labels.SLOT_NAMES[line.slot][0 if m.locale == "en" else 1],
                cat(
                    h(
                        '<option value="{}"{}>{} ({})</option>',
                        model.model_profile_id,
                        Html(
                            " selected"
                            if line.bound is not None
                            and line.bound.model_profile_id == model.model_profile_id
                            else ""
                        ),
                        model.model_name,
                        conn,
                    )
                    for model, conn in line.options
                ),
                m("llm.assign"),
            )
            if line.options
            else h('<span class="muted">{}</span>', m("llm.no_option"))
        )
        rows.append(
            h(
                '<tr><td><strong>{}</strong> <span class="badge">{}</span>'
                '<span class="purpose">{}</span><span class="purpose">{}</span></td>'
                "<td>{}</td><td>{}{}</td></tr>",
                labels.slot(line.slot, m.locale),
                m(need),
                labels.slot_purpose(line.slot, m.locale),
                h(
                    "{} {}",
                    m("llm.needs"),
                    _caps({c.value for c in SLOT_REQUIREMENTS[line.slot]}, m),
                ),
                labels.listing((labels.role(r, m.locale) for r in line.roles), m.locale)
                if line.roles
                else e(m("lbl.nobody")),
                current,
                choose,
            )
        )
    return h(
        '<div class="scroll"><table class="readable"><thead><tr><th>{}</th><th>{}</th><th>{}</th>'
        "</tr></thead><tbody>{}</tbody></table></div>",
        m("llm.col.use"),
        m("llm.col.roles"),
        m("llm.col.model"),
        cat(rows),
    )


# -- the page -------------------------------------------------------------------------------------


def overview_page(chrome: Chrome, data: Overview, *, error: object = None) -> bytes:
    m = chrome.m
    guide = data.guide
    now = [
        m("llm.now.active", name=guide.active.name)
        if guide.active is not None
        else m("llm.now.none")
    ]
    if guide.draft is not None:
        now.append(m("llm.now.draft", name=guide.draft.name))
    status = h(
        '<div class="box">{}</div>{}',
        cat((h("<div>{}</div>", x) for x in now), ""),
        _next_box(m, guide),
    )
    connections = (
        cat(_connection_card(chrome, line) for line in guide.connections)
        if guide.connections
        else h('<p class="muted">{}</p>', m("llm.s2.none"))
    )
    step2 = h(
        '<section class="card" id="models"><h2>{}</h2><p class="lede">{}</p>{}'
        '<p class="muted">{}</p></section>',
        m("llm.s2"),
        m("llm.s2.lede"),
        connections,
        m("llm.test.note"),
    )
    step3 = h(
        '<section class="card" id="assign"><h2>{}</h2><p class="lede">{}</p>{}{}'
        '<details class="advanced"><summary>{}</summary>{}</details></section>',
        m("llm.s3"),
        m("llm.s3.lede"),
        h('<p class="box info">{}</p>', m("llm.s3.active"))
        if guide.active is not None and guide.draft is None
        else Html(""),
        _assign_rows(chrome, guide, MAIN_SLOTS),
        m("llm.s3.more"),
        _assign_rows(chrome, guide, [s for s in BINDABLE_SLOTS if s not in MAIN_SLOTS]),
    )
    if guide.draft is not None:
        base = f"/settings/llm/runtimes/{guide.draft.runtime_id}"
        apply = (
            h(
                '<div class="box">{} <span class="muted">{}</span></div>',
                _button(chrome, f"{base}/activate", m("llm.apply"), "primary", back=True),
                m("llm.apply.note"),
            )
            if guide.ready_to_apply
            else h('<p class="muted">{}</p>', m("llm.apply.later"))
        )
        actions = h(
            '<p>{} <span class="muted">{}</span></p>{}<p>{}</p>',
            _button(chrome, f"{base}/check", m("llm.check"), back=True),
            m("llm.check.note"),
            apply,
            _button(chrome, f"{base}/retire", m("llm.discard"), "small danger", back=True),
        )
    elif guide.active is not None:
        base = f"/settings/llm/runtimes/{guide.active.runtime_id}"
        actions = h(
            '<p>{} <span class="muted">{}</span></p><p>{} <span class="muted">{}</span></p>',
            _button(chrome, f"{base}/check", m("llm.check"), back=True),
            m("llm.check.note"),
            _button(chrome, f"{base}/retire", m("llm.deactivate"), "small danger", back=True),
            m("llm.deactivate.note"),
        )
    else:
        actions = h('<p class="muted">{}</p>', m("llm.nothing_to_apply"))
    step4 = h(
        '<section class="card" id="apply"><h2>{}</h2><h3>{}</h3>{}{}{}</section>',
        m("llm.s4"),
        m("llm.todo.title"),
        checklist(guide.todos, m),
        _warnings(guide.warnings, m),
        actions,
    )
    body = h(
        '<h1>{}</h1>{}<p class="lede">{}</p>{}{}{}{}{}{}',
        m("llm.title"),
        _error(chrome, error),
        m("llm.intro"),
        status,
        credential_forms.add_connection_card(
            chrome,
            providers=tuple(k for k in PROVIDERS if k != "ollama"),
            protection=data.store_protection,
            store=data.secure_store,
            ollama=data.ollama,
        ),
        step2,
        step3,
        step4,
        _advanced(chrome, data),
    )
    return page(m("llm.title"), body, chrome=chrome)


def _advanced(chrome: Chrome, data: Overview) -> Html:
    m = chrome.m
    guide = data.guide
    label_boxes = cat(
        h(
            '<label class="check"><input type="checkbox" name="external_labels" value="{}"{}> {}'
            "</label>",
            label,
            Html(" checked" if label == "PUBLIC" else ""),
            egress_pages.label_names([label], m),
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
    runtimes = _table(
        (m("col.name"), m("col.state"), m("col.labels"), m("col.bindings"), m("col.activated")),
        [
            (
                h('<a href="/settings/llm/runtimes/{}">{}</a>', r.runtime_id, r.name),
                _named("llm.rstate", r.state, m),
                egress_pages.label_names(r.external_labels, m),
                labels.listing(
                    (
                        h("{}: <code>{}</code>", labels.slot(slot_, m.locale), model_)
                        for slot_, model_ in sorted(data.bindings.get(r.runtime_id, {}).items())
                    ),
                    m.locale,
                ),
                when(r.activated_at) if r.activated_at else "-",
            )
            for r in data.runtimes
        ],
        m,
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
                (labels.slot(s, m.locale), _caps({c.value for c in SLOT_REQUIREMENTS[s]}, m))
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
    connections = labels.technical(
        m.locale,
        [
            (
                line.connection.name,
                f"{line.connection.connection_id} {line.connection.reach} "
                f"{line.connection.base_url} lifecycle={line.connection.lifecycle} "
                f"credential={line.connection.secret_ref or '-'} "
                f"{line.connection.secret_fingerprint or ''}".strip(),
            )
            for line in guide.connections
        ]
        + [
            (
                x.model.model_name,
                f"{x.model.model_profile_id} {x.model.lifecycle} "
                f"passed={','.join(sorted(x.passed)) or '-'} "
                f"route={x.model.lock_fingerprint or '-'}",
            )
            for line in guide.connections
            for x in line.models
        ],
    )
    draft_labels = (
        h(
            "<p>{}</p>",
            m("llm.draft.labels", labels=egress_pages.label_names(guide.draft.external_labels, m)),
        )
        if guide.draft is not None
        else Html("")
    )
    return h(
        '<details class="advanced card"><summary>{}</summary>{}<h3>{}</h3>{}{}<h3>{}</h3>'
        '<p class="muted">{}</p>{}<p>{}</p><h3>{}</h3>{}{}<p class="muted">{}</p></details>',
        m("llm.adv"),
        draft_labels,
        m("llm.configs"),
        runtimes,
        new_runtime,
        m("llm.roles"),
        m("llm.s3.lede"),
        roles,
        m("llm.critic_fallback", slot=_slot_text(critic_fallback().value, m)),
        m("llm.requirements"),
        requirements,
        connections,
        m("llm.output_language", lang=m(f"llm.lang.{RESEARCH_OUTPUT_LANGUAGE}")),
    )


# -- a connection's details -----------------------------------------------------------------------


def connection_page(
    chrome: Chrome,
    connection: ConnectionRow,
    health: Sequence[HealthRow],
    models: Sequence[ModelRow],
    *,
    secure_store: str | None,
    store_protection: str | None = None,
    error: object = None,
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
    replace = credential_forms.replace_key_form(chrome, base, store_protection, secure_store)
    body = h(
        '<p><a href="/settings/llm">{}</a></p><p class="muted">{}</p><h1>{}</h1>{}'
        '<div class="box"><div>{} · {}: {} · {}: {}</div>'
        '<div class="muted">{}: <code>{}</code> · {}: {}</div></div><p class="muted">{}</p>'
        "<p>{}</p><h2>{}</h2>{}{}<h2>{}</h2>{}{}",
        m("llm.back"),
        m("col.connection"),
        connection.name,
        _error(chrome, error),
        m(f"llm.p.{provider_of(connection)}"),
        m("col.reach"),
        _named("llm.reach", connection.reach, m),
        m("col.config"),
        _named("llm.cstate", connection.lifecycle, m),
        m("col.endpoint"),
        connection.base_url,
        m("col.credential"),
        _credential(connection, m),
        m("llm.health_note"),
        cat(actions, " "),
        m("col.models"),
        _table(
            (m("col.model"), m("col.source"), m("col.lifecycle"), m("col.route")),
            [
                (
                    h(
                        '<a href="/settings/llm/models/{}"><code>{}</code></a>',
                        x.model_profile_id,
                        x.model_name,
                    ),
                    _named("llm.source", x.source, m),
                    _named("llm.mstate", x.lifecycle, m),
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
                    _named("llm.h", x.outcome, m),
                    x.latency_ms if x.latency_ms is not None else "-",
                    x.detail,
                    when(x.checked_at),
                )
                for x in health
            ],
            m,
        ),
        replace if connection.lifecycle != "RETIRED" else Html(""),
    )
    body = h(
        "{}{}",
        body,
        labels.technical(
            m.locale,
            [
                ("connection_id", connection.connection_id),
                ("secret_ref", connection.secret_ref or "-"),
                ("secret_fingerprint", connection.secret_fingerprint or "-"),
            ],
        ),
    )
    return page(connection.name, body, chrome=chrome)


# -- a model's details ----------------------------------------------------------------------------


def model_page(
    chrome: Chrome,
    model: ModelRow,
    connection: ConnectionRow,
    latest: Mapping[Capability, ProbeRow],
    history: Sequence[ProbeRow],
    *,
    error: object = None,
    stale: str | None = None,
) -> bytes:
    """`stale`: why the model's lock is not current under the qualification semantics in force
    (`SqlLLMRegistry.lock_problem`), or None."""
    m = chrome.m
    base = f"/settings/llm/models/{model.model_profile_id}"

    def probe_label(capability: str, parameters: Mapping[str, object]) -> Html:
        # What a parameterised probe demanded, beside the capability's name: passing at 2 and at
        # 5 are different evidence.
        label = labels.capability(capability, m.locale)
        shown = parameters.get("minimum_hypotheses")
        return h("{}{}", label, m("llm.probe.minimum", n=shown)) if shown else label

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
                probe_label(c.value, latest[c].parameters if c in latest else {}),
                _named("llm.probe", latest[c].outcome, m) if c in latest else "-",
                latest[c].detail if c in latest else "",
                latest[c].latency_ms if c in latest and latest[c].latency_ms is not None else "-",
                when(latest[c].probed_at) if c in latest else "-",
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
        buttons.append(_button(chrome, f"{base}/retire", m("llm.retire_model"), "small danger"))
    serves = [
        s
        for s in BINDABLE_SLOTS
        if {c.value for c in SLOT_REQUIREMENTS[s]} <= set(model.locked_capabilities or ())
        and (s is not LogicalSlot.PRIVATE_LOCAL or connection.reach == "LOCAL")
    ]
    body = h(
        '<p><a href="/settings/llm">{}</a></p><p class="muted">{}</p><h1><code>{}</code></h1>{}'
        '<div class="box"><div>{}: <a href="/settings/llm/connections/{}">{}</a> ({}) · {}: {}'
        " · {}: {}</div><div>{}: {}</div>"
        '<div class="muted">{}: {} -- {}</div></div><h2>{}</h2>{}{}<p>{}</p>'
        "<h2>{}</h2>{}<h2>{}</h2>{}",
        m("llm.back"),
        m("col.model"),
        model.model_name,
        cat(
            (
                _error(chrome, error),
                h('<div class="box warn">{}</div>', m("llm.lock.stale")) if stale else Html(""),
            )
        ),
        m("col.connection"),
        connection.connection_id,
        connection.name,
        _named("llm.reach", connection.reach, m),
        m("col.source"),
        _named("llm.source", model.source, m),
        m("col.lifecycle"),
        _named("llm.mstate", model.lifecycle, m),
        m("col.locked"),
        _caps(model.locked_capabilities or (), m),
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
                    ("model_profile_id", model.model_profile_id),
                ],
            ),
        ),
        m("llm.probe_history"),
        _table(
            (m("col.capability"), m("col.outcome"), m("col.detail"), m("col.when")),
            [
                (
                    probe_label(x.capability, x.parameters),
                    _named("llm.probe", x.outcome, m),
                    x.detail,
                    when(x.probed_at),
                )
                for x in history
            ],
            m,
        ),
    )
    return page(model.model_name, body, chrome=chrome)


# -- readiness, and a configuration's details -----------------------------------------------------


def _slot_row(s: SlotReadiness, loc: str, m: Messages) -> tuple[object, ...]:
    """One use, three cells: what it is for (and its status), which model, who relies on it."""
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
    if s.state == "BUILTIN":
        note: Html = e(m("lbl.builtin_note"))
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
        labels=egress_pages.label_names(readiness.runtime.external_labels, m),
    )


def readiness_block(chrome: Chrome, readiness: Readiness) -> Html:
    """What an applied configuration would do, in the researcher's terms; what is missing as a
    "still to do / how" list; the routing identifiers and the server's own rule text one click
    away."""
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
        h(
            '<p class="box">{}</p>',
            m("llm.ready.active" if readiness.runtime.state == "ACTIVE" else "llm.ready"),
        )
        if readiness.ready
        else h(
            '<div class="box error"><strong>{}</strong>{}</div>',
            m("llm.not_ready"),
            checklist([blocker_todo(b) for b in readiness.blockers], m),
        )
    )
    warnings = _warnings([Todo("llm.warn.raw", "", {"text": w}, w) for w in readiness.warnings], m)
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
    error: object = None,
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
                _button(chrome, f"{base}/activate", m("llm.apply"), "small"),
                m("llm.apply.note"),
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
        '<p><a href="/settings/llm">{}</a></p><p class="muted">{}</p><h1>{}</h1>{}{}'
        '<div class="box">{}: {} · {}: {}</div>{}<h2>{}</h2>{}{}',
        m("llm.back"),
        m("llm.runtime.title"),
        runtime.name,
        _error(chrome, error),
        h('<p class="box notice">{}</p>', notice) if notice else Html(""),
        m("col.state"),
        _named("llm.rstate", runtime.state, m),
        m("col.labels"),
        egress_pages.label_names(runtime.external_labels, m),
        binding,
        m("llm.check"),
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
    """`projects`: (id, name, external transfer summary) of every project this actor may act in
    -- whether each one's evidence may use the configuration's external APIs is that project's
    own setting."""
    m = chrome.m
    egress = (
        h(
            "<h2>{}</h2><ul>{}</ul>",
            m("eg.status"),
            cat(
                h(
                    '<li>{}: {} <a href="/projects/{}/egress">{}</a></li>',
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
    settings = h('<p><a href="/settings/llm">{}</a></p>', m("llm.open")) if admin else Html("")
    if readiness is None:
        body = h(
            '<h1>{}</h1><p class="box">{}</p>{}{}', m("rt.title"), m("rt.none"), settings, egress
        )
    else:
        runtime = readiness.runtime
        name = (
            h('<a href="/settings/llm/runtimes/{}">{}</a>', runtime.runtime_id, runtime.name)
            if admin
            else e(runtime.name)
        )
        body = h(
            '<h1>{}</h1><div class="box">{}: {} {}</div>{}{}{}{}',
            m("rt.title"),
            m("rt.active"),
            name,
            _named("llm.rstate", runtime.state, m),
            h('<p class="box error">{}</p>', m("rt.unusable", reason=unusable))
            if unusable
            else Html(""),
            settings,
            egress,
            readiness_block(chrome, readiness),
        )
    return page(m("rt.title"), body, chrome=chrome)


__all__ = [
    "PROVIDERS",
    "Overview",
    "active_runtime_page",
    "checklist",
    "connection_page",
    "model_page",
    "overview_page",
    "provider_of",
    "readiness_block",
    "runtime_page",
    "todo_text",
]
