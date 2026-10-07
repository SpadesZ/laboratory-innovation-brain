"""The workspace's own words, in English and Traditional Chinese.

ONLY THE INTERFACE IS TRANSLATED. Headings, labels, buttons, hints and the workspace's own notices
come from this catalog. Nothing the research service, a document or a provider produced is: a
report's statements, evidence excerpts, stage details, conclusions, the service's refusals, every
identifier (episode, hypothesis, attestation, capability, run, route) and every enum value (states,
slots, capabilities, outcomes) are shown exactly as stored, in whatever locale is chosen.

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
    "acting_as": ("signed in as", "目前身分"),
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
}


class Messages:
    """The interface's words in one locale. `m(key, **values)`."""

    def __init__(self, locale: str) -> None:
        self.locale = locale if locale in LOCALES else DEFAULT_LOCALE
        self._index = LOCALES.index(self.locale)

    def __call__(self, key: str, **values: object) -> str:
        text = _M[key][self._index]
        return text.format(**values) if values else text

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
