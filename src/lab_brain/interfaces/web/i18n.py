"""The workspace's own words, in English and Traditional Chinese.

THE INTERFACE IS TRANSLATED; THE RECORD IS NOT. Headings, labels, buttons, hints, the
workspace's own notices and the words for stored status values (`bs.`, `cs.`, `ws.`, `td.`, `ss.`
-- the value stays the tooltip) come from this catalog. Nothing the research service, a document or
a provider produced is rewritten: a report's statements, evidence excerpts, stage details,
conclusions, the service's refusals and every identifier are shown as stored. A pack's declared
words have curated renderings of their own (`pages.Terms`); anything else is shown as written.

The interface language is a per-browser preference (a cookie). It is not the research-output
language: the research service writes its report in English, and changing the interface language
changes neither what is stored nor how a run is written (`RESEARCH_OUTPUT_LANGUAGE`).
"""

from __future__ import annotations

LOCALES: tuple[str, ...] = ("en", "zh-TW")
DEFAULT_LOCALE = "en"
LOCALE_NAMES = {"en": "English", "zh-TW": "繁體中文"}

#: The language research output is written in. Independent of the interface language.
RESEARCH_OUTPUT_LANGUAGE = "en"

_M: dict[str, tuple[str, str]] = {
    # -- chrome -----------------------------------------------------------------------------------
    "brand": ("Lab Brain", "實驗室研究大腦"),
    "nav.label": ("Main sections", "主要區塊"),
    # The main entries, in the order a researcher works; each `.hint` is the question it answers.
    "nav.home": ("Home", "首頁"),
    "nav.home.hint": ("What should I do next?", "現在該做什麼？"),
    "nav.data": ("Research data", "研究資料"),
    "nav.data.hint": (
        "Where I give Lab Brain my data, and what it has",
        "要把資料交給 Lab Brain，就是來這裡",
    ),
    "nav.new": ("New research", "新增研究"),
    "nav.new.hint": ("What do I want to investigate?", "我想研究什麼問題？"),
    "nav.episodes": ("Research history", "研究紀錄"),
    "nav.episodes.hint": (
        "What has been investigated, and where does each stand?",
        "做過哪些研究？各自進行到哪裡？",
    ),
    "nav.projects": ("Projects", "研究專案"),
    "nav.projects.hint": (
        "Which projects am I in, and who works there?",
        "我參與哪些專案？誰在專案裡？",
    ),
    "nav.inbox": ("Decisions", "待我決定"),
    "nav.inbox.hint": ("What is waiting for me to decide or do?", "有哪些事等我決定或處理？"),
    "nav.admin": ("Laboratory", "實驗室管理"),
    "nav.admin.hint": (
        "Everyone, every project, and who is waiting for approval",
        "所有成員、所有專案，以及等待核准的人",
    ),
    "nav.llm": ("AI models", "AI 模型設定"),
    "nav.llm.hint": (
        "Which AI model handles which kind of work?",
        "哪個 AI 模型負責哪一類工作？",
    ),
    "nav.status": ("System status", "系統狀態"),
    "nav.status.hint": (
        "What can the system do now, and what is missing?",
        "系統現在能做什麼？還缺什麼？",
    ),
    "acting_as": ("Working as", "目前身分"),
    "language": ("Language", "語言"),
    "back": ("Back", "返回"),
    "tech.details": ("Technical details", "技術細節"),
    "page_suffix": ("Lab Brain", "實驗室研究大腦"),
    "home.no_projects": (
        "{actor} is not an active member of any research project yet. Ask the deployment's "
        "operator to add you to one (lab-brain admin member <project> {actor} ...).",
        "{actor} 目前還不是任何研究專案的成員。請部署管理者把你加入研究專案"
        "（lab-brain admin member <研究專案> {actor} ...）。",
    ),
    "home.no_projects.accounts": (
        "You are not in any research project yet. Create one, or ask a project's owner to add you.",
        "您尚未參與任何研究專案。可以自行建立，或請專案擁有者把您加入。",
    ),
    "col.episode": ("Research task", "研究任務"),
    "col.project": ("Research project", "研究專案"),
    "col.goal": ("Question", "研究問題"),
    "col.state": ("Status", "狀態"),
    "col.reason": ("Reason / outcome", "原因／結果"),
    "col.runs": ("Runs", "執行次數"),
    "col.opened": ("Started", "開始時間"),
    "col.name": ("Name", "名稱"),
    # -- the reasoner line (new research, confirmation) -------------------------------------------
    "new.reasoner.catalog": (
        "No AI model configuration is applied: the local rule-based reasoner does the reasoning; "
        "no AI model is called.",
        "目前沒有套用 AI 模型配置：由本機的規則式推理負責，不會呼叫任何 AI 模型。",
    ),
    "new.reasoner.runtime": (
        "The AI model configuration “{name}” does the reasoning.",
        "由 AI 模型配置「{name}」負責推理。",
    ),
    "new.reasoner.unusable": (
        "The applied AI model configuration cannot be used right now, so research will not "
        "start: {reason}",
        "已套用的 AI 模型配置目前無法使用，所以研究不會開始：{reason}",
    ),
    "optional": ("optional", "選填"),
    # -- a research task (episode) ----------------------------------------------------------------
    "ep.title": ("Research task", "研究任務"),
    "ep.goal": ("Question:", "研究問題："),
    "ep.state_now": ("Status now:", "目前狀態："),
    "ep.project": ("Research project", "研究專案"),
    "ep.trace": ("trace", "追溯碼"),
    "ep.opened": ("started", "開始於"),
    "ep.closed": ("closed", "結束於"),
    "ep.run_count": ("{n} run(s)", "共執行 {n} 次"),
    "ep.run_n": ("Run {n}", "第 {n} 次"),
    "ep.waiting.simulator": (
        "waiting for a simulation that cannot run here ({capability})",
        "正在等待這裡無法執行的模擬（{capability}）",
    ),
    "ep.continue.text": (
        "Continue this research: the same research task picks up where it stopped, with its own "
        "hypotheses and inputs. Checks already executed are not run again.",
        "繼續這項研究：同一個研究任務會從停下的地方接著做，沿用原本的假說與輸入；已執行過的檢查不會重做。",
    ),
    "ep.continue.button": ("Continue research", "繼續研究"),
    "ep.readonly": (
        "This research has ended ({state}): it can be read, and it takes no further run.",
        "這項研究已結束（{state}）：可以查看，但不會再執行。",
    ),
    "ep.runs": ("Runs of this research", "執行紀錄"),
    "col.run": ("Run", "執行"),
    "col.research_run": ("Run ID", "執行識別碼"),
    "col.actor": ("By", "執行者"),
    "col.started": ("Started", "開始"),
    "col.finished": ("Finished", "結束"),
    "col.outcome": ("Outcome", "結果"),
    "col.report": ("Report", "報告"),
    "ep.report_link": ("report", "查看報告"),
    "ep.markdown": ("Markdown", "下載 Markdown"),
    "ep.not_recorded": (
        "not recorded in the workspace (run elsewhere)",
        "工作台沒有這次執行的報告（在其他地方執行）",
    ),
    "ep.running": ("running", "執行中"),
    "ep.continue.declare": (
        "How sensitive is this research question?",
        "這個研究問題的敏感度為何？",
    ),
    "ep.continue.declare.hint": (
        "This research was opened before its question's classification was recorded. "
        "Declare it to continue: it is recorded with this run and kept from then on.",
        "這項研究開始時還沒有記錄研究問題的分級。請宣告分級後再繼續；分級會隨這次執行記錄，"
        "之後一律沿用。",
    ),
    "ep.no_report": (
        "No report of this research was recorded in the workspace.",
        "工作台沒有這項研究的報告紀錄。",
    ),
    "ep.report_of": ("Research report -- run {n}", "研究報告（第 {n} 次執行）"),
    "ep.report_language": (
        "The report is kept as the research service wrote it; switching the interface language "
        "does not change its content.",
        "報告內容依研究服務產出的原文保存（英文）；切換介面語言不會改變報告內容。",
    ),
    "ep.not_found.title": ("No such research", "找不到這項研究"),
    "ep.not_found": (
        "No research {episode} for {actor}.",
        "{actor} 沒有研究任務 {episode}。",
    ),
    "ep.not_continued": ("Not continued", "沒有繼續"),
    "outcome.SUSPENDED": ("Paused, waiting", "暫停等待"),
    "outcome.COMPLETED": ("Finished", "已完成"),
    "outcome.CONFIRMED": ("Confirmed", "已確認原因"),
    "outcome.INCONCLUSIVE": ("Inconclusive", "無法判定"),
    "outcome.NOT_REACHED": ("Not reached", "未能完成"),
    "outcome.FAILED": ("Failed", "執行失敗"),
    "outcome.status.PROVISIONAL": ("provisional conclusion", "初步結論"),
    "outcome.status.INCONCLUSIVE": ("inconclusive so far", "目前無法判定"),
    # -- report (headings only; the report's own text is never translated) ------------------------
    "r.episode": ("Research task", "研究任務"),
    "r.state_end": ("Status at the end of this run:", "這次執行結束時的狀態："),
    "r.actor": ("by", "執行者"),
    "r.domain": ("domain", "領域"),
    "r.started": ("Started", "開始"),
    "r.finished": ("finished", "結束"),
    "r.continuation": (
        "Continuation: run {n} of this research",
        "繼續研究：這項研究的第 {n} 次執行",
    ),
    "r.resumed_from": ("Resumed from", "從這裡接續"),
    "r.reasoning": ("Reasoning:", "推理："),
    "r.earlier_runs": ("Earlier runs", "先前的執行"),
    "r.earlier_checks": (
        "Checks executed by earlier runs (not executed again)",
        "先前執行過的檢查（不會重做）",
    ),
    "r.result": ("Result", "結果"),
    "r.ruled_out": ("Ruled out by executed checks:", "已被檢查排除："),
    "r.still_competing": ("Still competing:", "仍在比較中："),
    "r.trace": ("Confirmation trace:", "確認依據："),
    "r.confirmed": ("Confirmed hypothesis:", "已確認的假說："),
    "r.pending_simulation": ("Waiting for simulation:", "等待模擬："),
    "r.pending_sentence": (
        "is the best next check and cannot run here --",
        "是下一步最值得做的檢查，但這裡無法執行：",
    ),
    "r.stages": ("Steps", "研究步驟"),
    "col.stage": ("Step", "步驟"),
    "col.status": ("Status", "狀態"),
    "col.detail": ("Detail", "說明"),
    "r.inputs": ("Inputs and import", "輸入與匯入"),
    "col.file": ("File", "檔案"),
    "col.role": ("Used as", "用途"),
    "col.declared": ("Kind", "資料類型"),
    "col.artifact": ("File ID", "檔案識別碼"),
    "col.job": ("Job", "工作識別碼"),
    "col.units": ("Passages", "段落"),
    "col.statements": ("Statements", "陳述"),
    "r.verification_input": ("Verification input:", "驗證輸入："),
    "r.evidence": ("Evidence and sources", "證據與來源"),
    "r.evidence.continuation": (
        "This run admitted no new statement. The hypotheses were debated over the statements run "
        "1 of this research admitted, unchanged.",
        "這次執行沒有納入新的陳述。假說辯論所依據的，是第 1 次執行納入的陳述，內容不變。",
    ),
    "r.evidence.none": ("No statement was admitted as evidence.", "沒有任何陳述被納入為證據。"),
    "r.literature": ("External literature --", "外部文獻："),
    "r.literature.source": ("Source:", "來源："),
    "r.literature.query": ("Query (confirmed public):", "查詢（已確認可公開）："),
    "r.literature.policy": ("External transfer rule for this run:", "這次執行的外部傳輸規則："),
    "r.literature.discovered": ("Passages found:", "找到的段落："),
    "r.refused": ("refused:", "被拒絕："),
    "r.hypotheses": ("Competing hypotheses", "互相競爭的假說"),
    "r.falsifier": (
        "Model's explanation (prose falsifier, not adjudicated):",
        "模型的說明（文字否證條件，不作判定）：",
    ),
    "r.falsifier_typed": (
        "Machine falsifier -- what verification adjudicates:",
        "機器否證條件（驗證據此判定）：",
    ),
    "r.cheapest": ("Cheapest check:", "最省成本的檢查："),
    "r.predictions": ("Predictions:", "預測："),
    "r.critique": ("Critique:", "反方意見："),
    "r.no_hypotheses": ("No hypothesis was admitted.", "沒有任何假說被納入。"),
    "r.debate": ("Debate and critique", "辯論與反方審查"),
    "r.debate.none": ("The debate did not run.", "沒有進行辯論。"),
    "r.debate.head": ("Debate", "辯論"),
    "r.debate.reasoner": ("reasoner", "推理來源"),
    "r.debate.rounds": ("round(s)", "輪"),
    "r.debate.stopped": ("stopped:", "結束原因："),
    "r.position": ("Position:", "立場："),
    "r.critic_examined": (
        "The critic cross-examined {n} evidence item(s); its separate search found {m}.",
        "反方審查交叉檢視了 {n} 項證據；它另外的反向搜尋找到 {m} 項。",
    ),
    "r.alternatives": ("Alternatives the critic named:", "反方提出的其他可能機制："),
    "r.surviving": ("Still standing after critique:", "經過反方審查仍成立："),
    "r.contradicted": ("Contradicted by critique:", "被反方審查推翻："),
    "r.gate": ("Debate check:", "辯論把關："),
    "none": ("none", "無"),
    "r.belief": ("Where each hypothesis stands", "各假說目前的狀態"),
    "col.hypothesis": ("Hypothesis", "假說"),
    "col.mechanism": ("Mechanism", "機制"),
    "col.moves": ("Recorded changes", "狀態變更紀錄"),
    "r.plans": ("Verification plans", "驗證計畫"),
    "r.plans.none": ("No verification plan was made.", "沒有擬定驗證計畫。"),
    "r.completed": ("Checks completed", "已完成的檢查"),
    "r.by": ("by", "執行方式："),
    "r.output": ("output:", "產出："),
    "r.completed.none": ("No check was executed.", "沒有執行任何檢查。"),
    "r.human": ("Actions awaiting a person", "等待人員處理的事項"),
    "r.human.none": ("None.", "無。"),
    "r.blocked": ("Simulations waiting", "等待中的模擬"),
    "r.best_next": ("best next check", "下一步最值得做"),
    "r.also_sufficient": ("also sufficient", "也可以判定"),
    "r.would_decide": ("would decide:", "可以判定："),
    "r.estimated_cost": ("estimated cost:", "估計成本："),
    "r.requires": ("requires:", "需要："),
    "r.blocked.none": (
        "None: the next step needs no simulation, or no simulation would change a decision.",
        "無：下一步不需要模擬，或任何模擬都不會改變判斷。",
    ),
    "r.next": ("Next steps", "下一步"),
    "r.provenance": ("Where this came from", "來源追溯"),
    "r.failure": ("Failure analysis:", "失效分析："),
    "r.heuristic": ("Rule-of-thumb candidate (pending review):", "經驗法則候選（待審查）："),
    "r.ran": ("What ran, and what did not", "執行了什麼、沒執行什麼"),
    "r.not_performed": ("Not performed:", "未執行："),
    "r.note": ("Note:", "備註："),
    # -- form and request messages ----------------------------------------------------------------
    "msg.refused": ("The request was refused", "請求被拒絕"),
    "msg.not_found": ("Not found", "找不到"),
    "msg.no_page": ("There is no such page.", "沒有這個頁面。"),
    "msg.no_research": ("No research", "無法進行研究"),
    "msg.not_llm_admin.title": (
        "For the AI model administrator only",
        "只有 AI 模型管理者可以使用",
    ),
    "msg.not_llm_admin": (
        "{actor} is not an AI model administrator of this deployment. AI model settings are "
        "deployment configuration, granted by the deployment's operator (lab-brain admin "
        "llm-admin {actor}); membership of a project does not grant it. Whether a project's "
        "evidence may use an external AI API is that project's own external transfer setting "
        "(System status).",
        "{actor} 不是這個部署的 AI 模型管理者。AI 模型設定屬於部署層級的設定，由部署管理者授權"
        "（lab-brain admin llm-admin {actor}）；研究專案成員資格不包含這項權限。"
        "研究專案的證據能否送往"
        "外部 AI API，由該研究專案自己的外部傳輸設定決定（見「系統狀態」）。",
    ),
    "msg.no_research_text": (
        "No research for {actor} in {project}.",
        "{actor} 無法在研究專案 {project} 進行研究。",
    ),
    "msg.no_recorded_run": ("That run has no recorded report.", "這次執行沒有報告紀錄。"),
    "msg.choose_project": ("Choose a research project.", "請選擇研究專案。"),
    "msg.needs_goal": ("Describe the research question.", "請描述研究問題。"),
    "msg.literature_together": (
        "A literature file and a search query go together: the file is only searched with a "
        "query you confirm may be public.",
        "文獻資料檔和文獻查詢必須一起提供：只會用你確認可以公開的查詢來搜尋。",
    ),
    "msg.literature_public": (
        "Confirm that the literature query may be made public, or leave the literature fields "
        "empty.",
        "請勾選「我確認這段查詢可以公開」，或把文獻欄位留白。",
    ),
    "msg.unknown_classification": ("Unknown classification {value}.", "未知的分級 {value}。"),
    "msg.not_corpus": (
        "{name} is not a literature file (a JSON object with a 'papers' list).",
        "{name} 不是文獻資料檔（需為含有「papers」清單的 JSON 物件）。",
    ),
    "msg.runtime_unusable.title": (
        "The AI model configuration cannot be used",
        "AI 模型配置目前無法使用",
    ),
    "msg.settings_refused": ("Not done", "沒有完成"),
    # -- the episode page: what was asked, found, tested and learned (three disclosure layers) ---
    "v.result": ("Current conclusion", "目前結論"),
    "v.hypotheses": (
        "Competing hypotheses and where each stands",
        "互相競爭的假說與各自的證據狀態",
    ),
    "v.tested": ("What was tested and observed", "實際做了哪些檢查、觀察到什麼"),
    "v.support": ("What supports or challenges each hypothesis", "支持或挑戰各假說的證據"),
    "v.why": ("Why the system can or cannot conclude", "為什麼能（或不能）下結論"),
    "v.next": ("What to do next", "下一步該做什麼"),
    "v.reasoning": ("Evidence and reasoning", "證據與推理"),
    "v.audit": ("Audit and provenance", "稽核與來源紀錄"),
    "v.run_shown": ("Showing run {n} of {total}.", "顯示第 {n} 次執行（共 {total} 次）。"),
    "v.other_runs": ("Other runs:", "其他執行："),
    "v.continued": (
        "Run {n} continued this research from where it stopped; it did not start over.",
        "第 {n} 次執行是從上次停下的地方繼續，不是重新開始。",
    ),
    "v.conclusion.CONFIRMED": ("Root cause: {mechanism}", "根本原因：{mechanism}"),
    "v.conclusion.PROVISIONAL": ("The question is still open.", "問題仍待解答。"),
    "v.conclusion.INCONCLUSIVE": (
        "No hypothesis remains in contention.",
        "已沒有任何假說仍在競爭。",
    ),
    "v.conclusion.NOT_REACHED": (
        "The research stopped before verification.",
        "研究在驗證之前就停止了。",
    ),
    "v.no_root_cause": ("No root cause has been confirmed.", "尚未確認任何根本原因。"),
    "v.no_hypothesis": ("No hypothesis was admitted.", "沒有任何假說被接受。"),
    "v.no_verification_input": (
        "No verification input was given, so no check could be planned. This research cannot "
        "be continued: start new research and give a device project as its verification "
        "input.",
        "這次沒有提供驗證輸入，所以無法規劃任何檢查。這項研究不能繼續；請新增研究，並提供裝置專案作為"
        "驗證輸入。",
    ),
    "v.source_status": ("source status: {status}", "來源狀態：{status}"),
    "v.stopped_at": (
        "It stopped at the {stage} step ({status}).",
        "停在「{stage}」步驟（{status}）。",
    ),
    "v.falsifier_recorded": (
        "Machine falsifier, as the run recorded it:",
        "這次執行記錄的機器否證條件：",
    ),
    "v.falsifier_none": (
        "No machine falsifier is recorded for this hypothesis.",
        "此假說沒有記錄機器否證條件。",
    ),
    "v.falsifier_prose": (
        "The proposer's own wording of the falsifier (not used to decide):",
        "提出者自己的文字否證說明（不作判定）：",
    ),
    "v.supported": ("Supported:", "已獲支持："),
    "v.still_competing": (
        "Still open (neither supported nor ruled out):",
        "尚未判定（未獲支持，也未排除）：",
    ),
    "v.ruled_out": ("Ruled out:", "已排除："),
    "v.executed": ("Executed in this run", "這次執行的檢查"),
    "v.observed": ("{observable} = {outcome}", "{observable} = {outcome}"),
    "v.check_kind": ("{check} ({kind})", "{check}（{kind}）"),
    "v.no_observation": ("no observed outcome is recorded for it", "沒有記錄任何觀察結果"),
    "v.nothing_executed": ("No check was executed in this run.", "這次沒有執行任何檢查。"),
    "v.run_unrecorded": (
        "No report of this run is recorded, so what it tested and learned is not known here.",
        "這次執行沒有記錄報告，因此這裡無從得知它檢查了什麼、學到了什麼。",
    ),
    "v.earlier": (
        "Executed in earlier runs, not repeated",
        "先前已執行、這次不再重複的檢查",
    ),
    "v.needs_person": ("Planned, needs a person", "已規劃、需要人員執行"),
    "v.unavailable": ("Cannot run here", "這個環境無法執行"),
    "v.matched": (
        "{observable} = {outcome} matched the prediction {mechanism} declared in advance (if "
        "{expected}, it {effect} the hypothesis){designated}.",
        "{observable} = {outcome} 符合「{mechanism}」事先宣告的預測"
        "（若為 {expected}，則{effect}此假說）{designated}。",
    ),
    "v.designated": (", its machine falsifier", "（即它的機器否證條件）"),
    "v.not_comparable": (
        " -- declared in another outcome space or version, so not comparable",
        "——宣告於不同的結果空間或版本，無法比較",
    ),
    "v.space_unrecorded": (
        " -- the observation does not record its outcome space, so not comparable",
        "——此觀察沒有記錄其結果空間，無法比較",
    ),
    "v.moved": (
        "{mechanism}: {from_state} -> {to_state}, a governed belief change (decision: {decision}).",
        "「{mechanism}」：{from_state} → {to_state}，經治理程序的信念改變（決定：{decision}）。",
    ),
    "v.decided": (
        "{mechanism}: its transition policy decided \u201c{result}\u201d; its state did not "
        "change.",
        "「{mechanism}」：轉移政策的決定是「{result}」；狀態沒有改變。",
    ),
    "v.no_decision": (
        "{mechanism}: no governed transition is recorded for this relation.",
        "「{mechanism}」：這個關係沒有任何經治理程序的狀態轉移紀錄。",
    ),
    "v.matched_unrecorded": (
        "{observable} = {outcome} is comparable to {mechanism}'s declared prediction, but no "
        "relation is recorded for it.",
        "{observable} = {outcome} 與「{mechanism}」宣告的預測相符，但沒有記錄任何關係。",
    ),
    "v.no_match": (
        "{observable} = {outcome} matched no declared prediction, so it neither supports nor "
        "contradicts any hypothesis, and no belief could move.",
        "{observable} = {outcome} 不符合任何事先宣告的預測，所以既不支持也不反駁任何假說，"
        "任何信念都不會改變。",
    ),
    "v.declared_over": ("Declared about {observable}:", "對 {observable} 事先宣告的預測："),
    "v.declared_item": (
        "{mechanism}: if {expected}, {effect}{designated}",
        "「{mechanism}」：若為 {expected}，則{effect}{designated}",
    ),
    "v.no_prediction": (
        "No hypothesis declared a prediction about {observable}; the result is on record and "
        "moves nothing.",
        "沒有任何假說對 {observable} 做過預測；結果已記錄，但不會改變任何信念。",
    ),
    "v.not_recorded": (
        "The stored records do not say what this result meant for the hypotheses.",
        "儲存的紀錄沒有說明這個結果對各假說代表什麼。",
    ),
    "v.summary_none": (
        "No governed belief change happened in this run.",
        "這次執行沒有發生任何經治理程序的信念改變。",
    ),
    "v.summary_moves": (
        "{n} governed belief change(s) happened in this run.",
        "這次執行發生了 {n} 項經治理程序的信念改變。",
    ),
    "v.no_checks_learned": (
        "Nothing was tested in this run, so no belief could move.",
        "這次沒有做任何檢查，所以任何信念都不會改變。",
    ),
    "v.critique_note": (
        "The critic raised {n} objection(s). Objections are critique, not belief changes; they "
        "are under Evidence and reasoning.",
        "反方審查提出了 {n} 項質疑。質疑屬於審查意見，不是信念改變；詳見「證據與推理」。",
    ),
    "v.best_next": (
        "Best next check: {check} ({kind}).",
        "最佳的下一項檢查：{check}（{kind}）。",
    ),
    "v.blocked_because": (
        "It cannot run here: {reason}. It needs: {requires}.",
        "這裡無法執行：{reason}。需要：{requires}。",
    ),
    "v.also_blocked": (
        "Also cannot run here: {check} ({kind}).",
        "同樣無法在這裡執行：{check}（{kind}）。",
    ),
    "v.would_decide": ("Its result would decide:", "它的結果可以判定："),
    "v.person": (
        "A person can act now: {check} ({kind}).",
        "現在可由人員執行：{check}（{kind}）。",
    ),
    "v.nothing_next": ("No further check is planned.", "沒有規劃其他檢查。"),
    "v.l2.conclusion": ("The research service's conclusion, as recorded", "研究服務記錄的結論"),
    "v.l2.observed": ("Results of executed checks", "已執行檢查的結果"),
    "v.l2.observed_item": (
        "{check}: {observable} = {outcome} ({epistemic})",
        "{check}：{observable} = {outcome}（{epistemic}）",
    ),
    "v.l2.declared": ("Declared predictions", "事先宣告的預測"),
    "v.l2.declared_item": (
        "{observable} = {expected} -> {effect}{designated} -- {status}",
        "{observable} = {expected} -> {effect}{designated}——{status}",
    ),
    "v.l2.observed_now": ("observed", "已觀察到"),
    "v.l2.pending": (
        "not observed yet: no check observed this",
        "尚未觀察到：沒有檢查觀察過這一項",
    ),
    "v.l2.observed_other": (
        "not what was observed: the check observed {outcome}",
        "與觀察結果不同：檢查觀察到的是 {outcome}",
    ),
    "v.l2.not_comparable": (
        "not comparable: declared in {declared}, observed in {observed}; nothing is inferred",
        "無法比較：宣告於 {declared}，觀察於 {observed}；不作任何推論",
    ),
    "v.l2.space_unrecorded": (
        "an outcome space the record does not name",
        "紀錄未載明的結果空間",
    ),
    "v.l2.interpretations": (
        "Reasoning and critique (positions, not evidence)",
        "推理與審查的立場（不是證據）",
    ),
    "v.l2.objection": ("{mechanism}: {objection}", "{mechanism}：{objection}"),
    "v.l2.critique_stage": (
        "These are critique-stage judgments, not governed belief changes.",
        "以上是審查階段的判斷，不是經治理程序的信念改變。",
    ),
    "v.l2.candidates": ("Verification candidates", "驗證候選方案"),
    "v.l2.evidence": ("Evidence excerpts", "證據摘錄"),
    "v.l2.unavailable": ("Not performed or unavailable", "未執行或無法取得"),
    "v.l2.recorded_next": ("Next steps, as the run recorded them", "這次執行記錄的下一步"),
    "v.l3.records": (
        "Records behind each executed check",
        "每項已執行檢查背後的紀錄",
    ),
    "v.conclusions": ("Recorded conclusions", "已記錄的結論"),
    "v.conclusion.flagged": (
        "This conclusion is flagged {kind}. It stays on record as written:",
        "這個結論已被標註為 {kind}，紀錄保持原樣：",
    ),
    "v.conclusion.not_relied": (
        "Not used as a precedent or for heuristics: {why}",
        "不作為先例或歸納來源：{why}",
    ),
    "v.conclusion.relied": (
        "Its warrants verify; case memory may cite it as a precedent.",
        "其依據均可驗證；可作為案例記憶中的先例。",
    ),
    "v.conclusion.not_relied_l1": (
        "-- recorded as confirmed, but not used as a precedent or for heuristics; the records "
        "say why.",
        "——紀錄為已確認，但不作為先例或歸納來源；原因見紀錄層。",
    ),
    "v.l3.conclusions": (
        "Recorded conclusions, their warrants and flags",
        "已記錄的結論、其依據與標註",
    ),
    # -- the episode page, read as a researcher asks (pages: L1) -------------------------------
    "v.sep": (", ", "、"),
    "v.tag.hyp": ("Hypothesis", "假說"),
    "v.tag.pred": ("Prediction", "預測"),
    "v.tag.obs": ("Observation", "觀察"),
    "v.tag.interp": ("Interpretation", "解讀"),
    "v.tag.finding": ("Confirmed finding", "已確認的發現"),
    "col.standing": ("Where it stands", "目前狀態"),
    "col.evidence_status": ("Evidence so far", "目前的證據"),
    "v.observation": (
        "{check}: observed {observable} = {outcome}",
        "{check}：觀察到 {observable} = {outcome}",
    ),
    "v.ev.effect": ("-- this {effect} it.", "——{effect}此假說。"),
    "v.ev.unrecorded": (
        "-- comparable to its declared prediction, but no relation is recorded.",
        "——與它事先宣告的預測可比較，但沒有記錄任何關係。",
    ),
    "v.ev.no_bearing": (
        "-- it matched none of its declared predictions, so it neither supports nor refutes it.",
        "——不符合它事先宣告的任何預測，既不支持也不否證此假說。",
    ),
    "v.ev.untested": (
        "Not tested yet. The check that tests it: {check} ({kind}) -- {where}.",
        "尚未檢驗。能檢驗它的是{check}（{kind}）——{where}。",
    ),
    "v.ev.untested_unknown": (
        "Not tested yet; no check that tests it is recorded.",
        "尚未檢驗；紀錄中沒有能檢驗它的檢查。",
    ),
    "v.ev.blocked": (
        "it did not run here, so its result is unknown (unverified)",
        "沒有在這裡執行，結果未知（未驗證）",
    ),
    "v.ev.person": (
        "a person must perform it; there is no result yet",
        "需由人員執行，目前沒有結果",
    ),
    "v.ev.ran_no_observation": (
        "it ran, but recorded no outcome about this hypothesis",
        "已執行，但沒有記錄與此假說相關的結果",
    ),
    "v.ev.unplanned": ("this run did not plan it", "這次執行沒有規劃"),
    "v.not_run_unknown": (
        "-- not run; its result is unknown and nothing is assumed about it.",
        "——未執行；結果未知，也不作任何假設。",
    ),
    "v.predicted": ("What it predicts (declared before any check)", "它事先宣告的預測"),
    "v.pred.item": (
        "if {observable} = {expected}: {effect} it{designated} -- {status}",
        "若 {observable} = {expected}：{effect}此假說{designated}——{status}",
    ),
    "v.pred.observed": ("observed", "已觀察到"),
    "v.pred.other": (
        "not what was observed ({outcome} was)",
        "與觀察不同（觀察到的是 {outcome}）",
    ),
    "v.pred.not_comparable": (
        "not comparable with what was observed (another outcome space)",
        "無法與觀察比較（結果空間不同）",
    ),
    "v.pred.pending": ("not observed yet", "尚未觀察"),
    "v.supporting": ("Observations that support it", "支持它的觀察"),
    "v.challenging": ("Observations that challenge it", "挑戰它的觀察"),
    "v.objections": (
        "The critic raised {n} objection(s) to it -- critique, not evidence; see Evidence and "
        "reasoning.",
        "反方審查對它提出 {n} 項質疑——屬於審查意見，不是證據；詳見「證據與推理」。",
    ),
    "v.would.item": (
        "if {observable} = {outcome}: {effect} {mechanism}",
        "若 {observable} = {outcome}：{effect}「{mechanism}」",
    ),
    "v.why.can": ("The system can conclude:", "系統可以下結論："),
    "v.why.cannot": ("The system cannot conclude yet:", "系統目前還不能下結論："),
    "v.why.others_ruled_out": (
        "rivals ruled out by an observation: {names}",
        "已被觀察排除的對立假說：{names}",
    ),
    "v.why.open_rivals": (
        "a limitation -- rivals tested but not ruled out: {names}",
        "限制：已檢驗但尚未被排除的對立假說：{names}",
    ),
    "v.why.supported_unconfirmed": (
        "{mechanism} is supported and no rival remains open, but the governed path has not "
        "confirmed it",
        "「{mechanism}」獲得支持，且沒有其他假說仍待判定，但治理程序沒有確認它",
    ),
    "v.why.waiting": ("what it waits for: {reason}", "目前等待：{reason}"),
    "v.why.held": (
        "{n} observation(s) bearing on a hypothesis wait for a person's review: the transition "
        "policy decided a person must look first, so no belief changed",
        "有 {n} 項與假說相關的觀察等待人員審查：轉移政策決定須先由人員判斷，因此信念沒有改變",
    ),
    "v.why.stopped": (
        "the research stopped at the {stage} step ({status}); the reason it recorded is in the "
        "step table under Evidence and reasoning",
        "研究停在「{stage}」步驟（{status}）；紀錄的原因見「證據與推理」中的步驟表",
    ),
    "v.why.challenged": (
        "{mechanism} is challenged: a result contradicts it, but it has not been ruled out",
        "「{mechanism}」受到挑戰：有牴觸它的結果，但它尚未被排除",
    ),
    "v.why.failed": (
        "ran and failed, so no result from them is used: {checks}",
        "以下檢查執行失敗，不使用其任何結果：{checks}",
    ),
    "v.failed_no_result": (
        "-- it ran and failed; no result from it is used.",
        "——執行失敗，不使用它的任何結果。",
    ),
    "v.ev.failed": ("it ran and failed, so there is no result", "執行失敗，沒有結果"),
    "v.set_aside": ("Revised or superseded:", "已修正或被取代："),
    "v.unknown_cause": ("a hypothesis this report does not list", "本報告未列出的假說"),
    "v.next.warrant": (
        "A person who may answer it must answer the diagnostic warrant review (under Decisions): "
        "does the observed outcome bear on the hypothesis's mechanism as the hypothesis claims? "
        "Then continue this research.",
        "需要有權回覆的人回覆診斷依據審查（在「待我決定」）：觀察到的結果是否如假說所述反映該機制？"
        "回覆後再繼續這項研究。",
    ),
    "ep.waiting.warrant": (
        "waiting for a person's answer on a diagnostic warrant",
        "等待人員回覆診斷依據（diagnostic warrant）審查",
    ),
    "ep.waiting.undiscriminated": (
        "waiting for evidence that tells the supported mechanism from a rival",
        "等待能把獲得支持的機制與對立假說區分開來的證據",
    ),
    "ep.waiting.competing": (
        "waiting for a person: two mechanisms are supported",
        "等待人員判斷：有兩個機制同時獲得支持",
    ),
    "tr.curated_note": (
        "The Chinese terms on this page are curated translations ({note}); each original is under "
        "Audit and provenance.",
        "本頁的中文術語為策展翻譯（{note}）；原文見「稽核與來源紀錄」。",
    ),
    "v.why.warranted": (
        "the confirmation rests on {n} recorded diagnostic warrant(s), and they verify",
        "此確認依據 {n} 項已記錄的診斷依據（diagnostic warrant），且已通過驗證",
    ),
    "v.why.untested_rivals": (
        "a limitation -- rivals never tested in this research: {names}",
        "限制：本研究從未檢驗的對立假說：{names}",
    ),
    "v.why.basis": ("the supporting observation: {observation}", "支持的觀察：{observation}"),
    "v.why.not_relied": (
        "the confirmation is on record, but case memory does not rely on it; the records say why",
        "此確認已記錄，但案例記憶不以它為依據；原因見紀錄層",
    ),
    "v.why.open": (
        "{n} hypothesis(es) still open -- neither supported nor ruled out: {names}",
        "仍有 {n} 個假說尚未判定（未獲支持，也未排除）：{names}",
    ),
    "v.why.supported_not_confirmed": (
        "{mechanism} is supported, but support is not confirmation while rivals remain open",
        "「{mechanism}」獲得支持；但只要仍有對立假說未被排除，支持就不等於確認",
    ),
    "v.why.competing": (
        "{n} rival hypotheses are supported at once: {names} -- the evidence does not single out "
        "one cause",
        "{n} 個對立假說同時獲得支持：{names}——證據無法指出單一原因",
    ),
    "v.why.inconclusive": (
        "no hypothesis remains in contention: each was ruled out or set aside, so none explains "
        "the observations",
        "已沒有任何假說仍在競爭：每一個都已被排除或擱置，因此沒有一個能解釋觀察結果",
    ),
    "v.why.conflicting": (
        "the evidence about {mechanism} conflicts: it is both supported and challenged",
        "關於「{mechanism}」的證據互相矛盾：同時有支持與挑戰它的結果",
    ),
    "v.why.no_input": (
        "no verification input was given, so nothing could be checked",
        "沒有提供驗證輸入，因此無法做任何檢查",
    ),
    "v.why.unperformed": (
        "not performed, so their results are unknown and unverified -- nothing is assumed in "
        "their place: {checks}",
        "以下檢查沒有執行，結果未知、未經驗證，也沒有以任何假設值代替：{checks}",
    ),
    "v.why.person": ("waiting for a person to perform: {checks}", "等待人員執行：{checks}"),
    "v.why.rules": (
        "The hypotheses and the critique came from the local rule-based catalog reasoner, not a "
        "language model.",
        "假說與反方審查來自本機的規則式目錄推理器，沒有使用語言模型。",
    ),
    "v.why.models": (
        "The hypotheses and the critique came from language models, as their inference "
        "provenance records: {models}.",
        "假說與反方審查由語言模型產生（依推論來源紀錄）：{models}。",
    ),
    "v.why.model_item": ("{role}: {model}", "{role}：{model}"),
    "v.why.reasoner": ("Reasoner, as recorded: {reasoner}", "推理來源（依紀錄）：{reasoner}"),
    "v.why.no_debate": ("No debate is recorded for this run.", "這次執行沒有辯論紀錄。"),
    "v.why.rule": (
        "A belief changes only when an observation matches a prediction declared in advance and "
        "the governed transition allows it; the system never declares a confirmation the evidence "
        "does not support.",
        "只有當觀察結果符合事先宣告的預測、且經治理程序核准時，信念才會改變；"
        "證據不足時，系統不會宣告確認。",
    ),
    "v.l3.originals": ("Translations beside their originals", "翻譯與原文對照"),
    "tr.untranslated": (" (untranslated)", "（未翻譯，顯示英文原文）"),
    "tr.notice": (
        "{n} passage(s) on this page have no curated translation and are shown in English, marked.",
        "本頁有 {n} 段文字沒有經策展的中文翻譯，以英文原文顯示並加註標示。",
    ),
    "tr.as_written": (
        "Research is recorded in English and shown here as written.",
        "研究紀錄以英文撰寫，此處依原文顯示。",
    ),
    "tr.provenance": (
        "Translations: {ref}. The record keeps its original text; each translation is shown "
        "beside it.",
        "翻譯來源：{ref}。紀錄保留原文；每段翻譯都與原文並列。",
    ),
    "tr.none": ("(no translation)", "（無翻譯）"),
    "tr.curated": ("curated translation", "策展翻譯"),
    "tr.missing": ("no curated translation: shown in English", "無策展翻譯：以英文原文顯示"),
    "col.shown": ("Shown", "頁面顯示"),
    "col.original": ("Original, as recorded", "原文（紀錄）"),
    "col.rendering": ("Source", "來源"),
    "col.item": ("Item", "項目"),
    "col.value": ("Value", "內容"),
    "ep.summary_export": ("summary in this language", "本語言的研究摘要"),
    "sum.title": ("Research summary (derived document)", "研究摘要（衍生文件）"),
    "sum.provenance": ("Where this summary comes from", "本摘要的來源"),
    "sum.derived": ("What this is", "文件性質"),
    "sum.derived_text": (
        "Derived for reading from run {n}'s recorded report. The record is that report itself, "
        "unchanged (report.md).",
        "由第 {n} 次執行所記錄的報告衍生，供閱讀之用；"
        "正式紀錄是該報告本身（report.md），未經更動。",
    ),
    "sum.source": (
        "SHA-256 of the record's export (report.md) when this was made",
        "製作時正式紀錄匯出檔（report.md）的 SHA-256",
    ),
    "sum.renderings": ("Translations used", "使用的翻譯"),
    "sum.untranslated": (
        "Passages shown in English (no curated translation)",
        "以英文原文顯示的段落數（無策展翻譯）",
    ),
    "sum.reasoner": ("Who reasoned", "推理來源"),
    "sum.exported": ("Made at", "製作時間"),
    "sum.episode": ("Research task", "研究任務"),
    # -- stored values, in words (the value itself stays the tooltip) ---------------------------
    "bs.DRAFT": ("Draft", "草稿"),
    "bs.ADMITTED": ("Admitted, not yet tested", "已受理、尚未檢驗"),
    "bs.ACTIVE": ("Open", "尚未判定"),
    "bs.SUPPORTED": ("Supported", "獲得支持"),
    "bs.CHALLENGED": ("Challenged", "受到挑戰"),
    "bs.CONTRADICTED": ("Refuted (ruled out)", "已被否證（排除）"),
    "bs.INCONCLUSIVE": ("Inconclusive", "無法判定"),
    "bs.EVOLVED": ("Revised into a new hypothesis", "已修正為新假說"),
    "bs.SUPERSEDED": ("Superseded", "已被取代"),
    "cs.CONFIRMED": ("Confirmed", "已確認"),
    "cs.PROVISIONAL": ("Not confirmed", "尚未確認"),
    "cs.INCONCLUSIVE": ("Inconclusive", "無法定論"),
    "cs.NOT_REACHED": ("Not reached", "未完成"),
    "ws.EXECUTED": ("executed", "已執行"),
    "ws.SUCCEEDED": ("succeeded", "已完成"),
    "ws.FAILED": ("failed", "執行失敗"),
    "ws.AWAITING_RESOURCE": ("waiting for a resource", "等待資源"),
    "ws.BUDGET_BLOCKED": ("refused by the budget", "超出預算而未執行"),
    "ws.BLOCKED": ("cannot run here", "無法在此執行"),
    "rt.SUPPORTS": ("supports", "支持"),
    "rt.CONTRADICTS": ("contradicts", "牴觸"),
    "rt.PREDICTS": ("is predicted by", "符合"),
    "td.ALLOW": ("allowed", "核准"),
    "td.DENY": ("denied", "否決"),
    "td.NEED_MORE_EVIDENCE": ("needs more evidence", "需要更多證據"),
    "td.NEED_HUMAN_REVIEW": ("needs a person's review", "需要人員審查"),
    "ss.DONE": ("done", "完成"),
    "ss.SKIPPED": ("skipped", "略過"),
    "ss.REFUSED": ("refused", "被拒絕"),
    "ss.FAILED": ("failed", "失敗"),
    "ss.PARTIAL": ("partly done", "部分完成"),
    "stage.ingestion": ("ingestion", "資料匯入"),
    "stage.evidence": ("evidence", "證據"),
    "stage.external evidence": ("external evidence", "外部證據"),
    "stage.hypotheses": ("hypotheses", "假說"),
    "stage.verification input": ("verification input", "驗證輸入"),
    "stage.verification": ("verification", "驗證"),
    "stage.pending simulation": ("pending simulation", "待執行的模擬"),
    "act.EXISTING_EVIDENCE_LOOKUP": ("existing-evidence lookup", "查詢既有證據"),
    "act.ANALYTICAL_RULE_CHECK": ("analytical check", "分析檢查"),
    "act.HISTORICAL_CASE_COMPARISON": ("historical case comparison", "歷史案例比對"),
    "act.NUMERICAL_SURROGATE": ("numerical surrogate", "數值代理模型"),
    "act.SIMULATION": ("simulation", "模擬"),
    "act.MEASUREMENT": ("measurement", "量測"),
    "act.FABRICATION": ("fabrication", "製作"),
    "act.HUMAN_EXPERT_REVIEW": ("expert review", "專家審查"),
    "act.unknown": ("kind not recorded", "未記錄類型"),
    "ep.waiting.debate": (
        "the debate did not produce admitted hypotheses; continuing retries it",
        "辯論沒有產生被接受的假說；繼續研究會重試",
    ),
}


class Messages:
    """The interface's words in one locale. `m(key, **values)`."""

    def __init__(self, locale: str) -> None:
        self.locale = locale if locale in LOCALES else DEFAULT_LOCALE
        self._index = LOCALES.index(self.locale)

    def __call__(self, key: str, **values: object) -> str:
        text = _M[key][self._index]
        return text.format(**values) if values else text

    def template(self, key: str) -> str:
        """The message unformatted, for a caller that fills it with markup (`pages.mh`)."""
        return _M[key][self._index]

    @staticmethod
    def extend(entries: dict[str, tuple[str, str]]) -> None:
        overlap = set(entries) & set(_M)
        if overlap:
            raise ValueError(f"message keys defined twice: {sorted(overlap)}")
        _M.update(entries)


def keys() -> frozenset[str]:
    return frozenset(_M)


def templates(key: str) -> tuple[str, ...]:
    """A message in every locale, in `LOCALES` order -- for checking that none is missing."""
    return tuple(_M[key])


__all__ = [
    "DEFAULT_LOCALE",
    "LOCALES",
    "LOCALE_NAMES",
    "RESEARCH_OUTPUT_LANGUAGE",
    "Messages",
    "keys",
    "templates",
]
