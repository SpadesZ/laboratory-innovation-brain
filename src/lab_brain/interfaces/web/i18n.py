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
    "brand": ("Research workspace", "研究工作區"),
    "nav.episodes": ("Episodes", "研究 Episode"),
    "nav.new": ("New research run", "新研究"),
    "nav.llm": ("LLM settings", "LLM 設定"),
    "nav.runtime": ("Runtime", "執行環境"),
    "acting_as": ("acting as", "目前身分"),
    "language": ("Language", "語言"),
    "back": ("Back", "返回"),
    "page_suffix": ("Lab Brain research workspace", "Lab Brain 研究工作區"),
    # -- home -------------------------------------------------------------------------------------
    "home.title": ("Research workspace", "研究工作區"),
    "home.intro": (
        "Research episodes you opened, in projects you are an active member of. A SUSPENDED "
        "episode can be continued; a COMPLETED one is read-only.",
        "你開啟的研究 episode（僅限你目前為有效成員的 project）。SUSPENDED 的 episode 可以續跑；"
        "COMPLETED 的 episode 為唯讀。",
    ),
    "home.start": ("Start a new research run", "開始新的研究"),
    "home.episodes": ("Your episodes", "你的 episode"),
    "home.projects": ("Your projects", "你的 project"),
    "home.no_episodes": (
        "You have not opened a research episode yet.",
        "你尚未開啟任何研究 episode。",
    ),
    "home.no_projects": (
        "{actor} is not an active member of any project, so there is nothing to research here.",
        "{actor} 目前不是任何 project 的有效成員，因此沒有可研究的內容。",
    ),
    "col.episode": ("Episode", "Episode"),
    "col.project": ("Project", "Project"),
    "col.goal": ("Goal", "目標"),
    "col.state": ("State", "狀態"),
    "col.reason": ("Reason / outcome", "原因／結果"),
    "col.runs": ("Runs", "Run 數"),
    "col.opened": ("Opened", "開啟時間"),
    "col.name": ("Name", "名稱"),
    # -- new run ----------------------------------------------------------------------------------
    "new.title": ("New research run", "新研究"),
    "new.no_projects": (
        "{actor} is not an active member of any project.",
        "{actor} 目前不是任何 project 的有效成員。",
    ),
    "new.intro": (
        "Opens a new research episode: your files are stored and read, competing hypotheses are "
        "debated, the verification this deployment can run is run, and one report comes back. "
        "Simulations this deployment cannot run are reported as blocked, never run or emulated.",
        "開啟一個新的研究 episode：你的檔案會被保存與讀取、競爭假說會被辯論、執行本部署可執行的"
        "驗證，最後回傳一份報告。本部署無法執行的模擬只會列為 blocked，絕不執行也不模擬。",
    ),
    "new.reasoner": ("Reasoner for this run", "本次研究的推理來源"),
    "new.reasoner.catalog": (
        "No LLM runtime is active: the local rule-based catalog reasoner serves every model slot "
        "(the explicit fallback).",
        "目前沒有啟用的 LLM 執行環境：由本機規則式機制目錄推理器負責所有模型 slot（明示的備援）。",
    ),
    "new.reasoner.runtime": (
        "The active LLM runtime {name} serves the model slots; see Runtime for its routes.",
        "由已啟用的 LLM 執行環境 {name} 負責模型 slot；路由詳見「執行環境」。",
    ),
    "new.reasoner.unusable": (
        "The active LLM runtime cannot be used, so research runs are refused: {reason}",
        "已啟用的 LLM 執行環境目前無法使用，因此研究會被拒絕：{reason}",
    ),
    "new.project": ("Project", "Project"),
    "new.goal": ("Research goal", "研究目標"),
    "new.goal.hint": ("the question, in your own words", "用你自己的話描述問題"),
    "new.measurement": ("Measurement records", "量測紀錄"),
    "new.measurement.hint": (
        "statements are used as INTERNAL_MEASUREMENT evidence",
        "其中的陳述以 INTERNAL_MEASUREMENT 證據使用",
    ),
    "new.run_record": ("Run records", "Run 紀錄"),
    "new.run_record.hint": (
        "earlier simulations or runs (INTERNAL_RUN)",
        "先前的模擬或 run（INTERNAL_RUN）",
    ),
    "new.note": ("Notes", "筆記"),
    "new.note.hint": (
        "notes or expert heuristics (EXPERT_HEURISTIC)",
        "筆記或專家經驗（EXPERT_HEURISTIC）",
    ),
    "new.verification": ("Verification input", "驗證輸入"),
    "new.verification.hint": (
        "optional; the domain's input, e.g. a device project JSON. Without it nothing is verified.",
        "選填；領域的輸入，例如元件專案 JSON。沒有它就不會進行任何驗證。",
    ),
    "new.corpus": ("Literature corpus", "文獻語料"),
    "new.corpus.hint": (
        "optional; a local corpus file, searched only with the query below",
        "選填；本機語料檔，只會以下方的查詢搜尋",
    ),
    "new.query": ("Literature query", "文獻查詢"),
    "new.query.hint": ("sent to the literature provider", "會送給文獻提供者"),
    "new.query.public": (
        "I declare this query PUBLIC: it may leave this workspace",
        "我聲明此查詢為 PUBLIC：它可以離開本工作區",
    ),
    "new.symptom": ("Symptom", "症狀"),
    "new.expected": ("Expected behaviour", "預期行為"),
    "new.observed": ("Observed behaviour", "觀察到的行為"),
    "optional": ("optional", "選填"),
    "new.sensitivity": ("Classification of the goal and files", "目標與檔案的機密分級"),
    "new.submit": ("Run research", "開始研究"),
    # -- episode ----------------------------------------------------------------------------------
    "ep.title": ("Research episode", "研究 episode"),
    "ep.goal": ("Goal:", "目標："),
    "ep.state_now": ("Episode state now:", "目前 episode 狀態："),
    "ep.project": ("Project", "Project"),
    "ep.trace": ("trace", "trace"),
    "ep.opened": ("opened", "開啟於"),
    "ep.closed": ("closed", "結束於"),
    "ep.continue.text": (
        "Continue this episode: the same episode, resumed through its lifecycle, over its own "
        "hypotheses and inputs. Checks already executed are not run again.",
        "續跑此 episode：同一個 episode，經由其生命週期恢復，沿用自己的假說與輸入；已執行過的檢查"
        "不會再執行。",
    ),
    "ep.continue.button": ("Continue episode", "續跑 episode"),
    "ep.readonly": (
        "This episode is {state}: it is read-only and receives no new research run.",
        "此 episode 為 {state}：唯讀，不再接受新的研究 run。",
    ),
    "ep.runs": ("Runs of this episode", "此 episode 的 run"),
    "col.run": ("Run", "Run"),
    "col.research_run": ("Research run", "Research run"),
    "col.actor": ("Actor", "執行者"),
    "col.started": ("Started", "開始"),
    "col.finished": ("Finished", "結束"),
    "col.outcome": ("Outcome", "結果"),
    "col.report": ("Report", "報告"),
    "ep.report_link": ("report", "報告"),
    "ep.not_recorded": (
        "not recorded in the workspace (run elsewhere)",
        "未記錄於工作區（於他處執行）",
    ),
    "ep.running": ("running", "執行中"),
    "ep.no_report": (
        "No report of this episode was recorded in the workspace.",
        "工作區中沒有此 episode 的報告紀錄。",
    ),
    "ep.report_of": ("Report of run {n}", "Run {n} 的報告"),
    "ep.not_found.title": ("No such episode", "沒有此 episode"),
    "ep.not_found": ("No episode {episode} for {actor}.", "{actor} 沒有 episode {episode}。"),
    "ep.not_continued": ("Not continued", "未續跑"),
    # -- report (headings only; the report's own text is never translated) ------------------------
    "r.episode": ("Episode", "Episode"),
    "r.state_end": ("Episode state at the end of this run:", "本次 run 結束時的 episode 狀態："),
    "r.actor": ("actor", "執行者"),
    "r.domain": ("domain", "領域"),
    "r.started": ("Started", "開始"),
    "r.finished": ("finished", "結束"),
    "r.continuation": ("Continuation: run {n} of this episode", "續跑：此 episode 的第 {n} 個 run"),
    "r.resumed_from": ("Resumed from", "恢復自"),
    "r.reasoning": ("Reasoning:", "推理："),
    "r.earlier_runs": ("Earlier runs", "先前的 run"),
    "r.earlier_checks": (
        "Checks executed by earlier runs (not executed again)",
        "先前 run 已執行的檢查（不再執行）",
    ),
    "r.result": ("Result", "結果"),
    "r.ruled_out": ("Ruled out by executed checks:", "已執行檢查排除："),
    "r.still_competing": ("Still competing:", "仍在競爭："),
    "r.trace": ("Confirmation trace:", "確認追溯："),
    "r.confirmed": ("Confirmed hypothesis:", "已確認的假說："),
    "r.pending_simulation": ("Pending simulation:", "待執行的模擬："),
    "r.pending_sentence": (
        "is the best next verification action and cannot run here --",
        "是下一步最佳的驗證動作，但無法在此執行 --",
    ),
    "r.stages": ("Stages", "階段"),
    "col.stage": ("Stage", "階段"),
    "col.status": ("Status", "狀態"),
    "col.detail": ("Detail", "細節"),
    "r.inputs": ("Inputs and ingestion", "輸入與匯入"),
    "col.file": ("File", "檔案"),
    "col.role": ("Role", "角色"),
    "col.declared": ("Declared as", "宣告為"),
    "col.artifact": ("Artifact", "Artifact"),
    "col.job": ("Job", "Job"),
    "col.units": ("Units", "單元"),
    "col.statements": ("Statements", "陳述"),
    "r.verification_input": ("Verification input:", "驗證輸入："),
    "r.evidence": ("Evidence and sources", "證據與來源"),
    "r.evidence.continuation": (
        "This run admitted no statement. The statements the hypotheses were debated over were "
        "admitted by run 1 of this episode and stand unchanged.",
        "本次 run 沒有納入新陳述。假說辯論所依據的陳述由此 episode 的第 1 個 run 納入，維持不變。",
    ),
    "r.evidence.none": ("No statement was admitted as evidence.", "沒有陳述被納入為證據。"),
    "r.literature": ("External literature --", "外部文獻 --"),
    "r.literature.source": ("Source:", "來源："),
    "r.literature.query": ("Query (declared public by the actor):", "查詢（執行者聲明為公開）："),
    "r.literature.policy": ("Egress policy for this run:", "本次 run 的外送政策："),
    "r.literature.discovered": ("Passages discovered:", "找到的段落："),
    "r.refused": ("refused:", "拒絕："),
    "r.hypotheses": ("Competing hypotheses", "競爭假說"),
    "r.falsifier": ("Falsifier:", "否證條件："),
    "r.cheapest": ("Cheapest test:", "最低成本檢驗："),
    "r.predictions": ("Predictions:", "預測："),
    "r.critique": ("Critique:", "批判："),
    "r.no_hypotheses": ("No hypothesis was admitted.", "沒有假說被納入。"),
    "r.debate": ("Debate and critique", "辯論與批判"),
    "r.debate.none": ("The debate did not run.", "辯論未執行。"),
    "r.debate.head": ("Debate", "辯論"),
    "r.debate.reasoner": ("reasoner", "推理者"),
    "r.debate.rounds": ("round(s)", "輪"),
    "r.debate.stopped": ("stopped:", "停止："),
    "r.position": ("Position:", "立場："),
    "r.critic_examined": (
        "Critic cross-examined {n} evidence item(s); its inverted retrieval found {m}.",
        "批判者交叉檢視了 {n} 項證據；反向檢索找到 {m} 項。",
    ),
    "r.alternatives": ("Critic named alternatives:", "批判者提出的替代機制："),
    "r.surviving": ("Surviving after critique:", "批判後存續："),
    "r.contradicted": ("Contradicted by critique:", "被批判反駁："),
    "r.gate": ("Debate gate:", "辯論閘門："),
    "none": ("none", "無"),
    "r.belief": ("Belief state", "信念狀態"),
    "col.hypothesis": ("Hypothesis", "假說"),
    "col.mechanism": ("Mechanism", "機制"),
    "col.moves": ("Governed moves", "受治理的轉移"),
    "r.plans": ("Verification plans", "驗證計畫"),
    "r.plans.none": ("No verification plan was made.", "沒有擬定驗證計畫。"),
    "r.completed": ("Completed actions", "已完成的動作"),
    "r.by": ("by", "由"),
    "r.output": ("output:", "輸出："),
    "r.completed.none": ("No verification action was executed.", "沒有執行任何驗證動作。"),
    "r.human": ("Actions awaiting a person", "等待人員執行的動作"),
    "r.human.none": ("None.", "無。"),
    "r.blocked": ("Blocked simulation actions", "被阻擋的模擬動作"),
    "r.best_next": ("best next action", "下一步最佳動作"),
    "r.also_sufficient": ("also sufficient", "亦足夠"),
    "r.would_decide": ("would decide:", "可判定："),
    "r.estimated_cost": ("estimated cost:", "估計成本："),
    "r.requires": ("requires:", "需要："),
    "r.blocked.none": (
        "None: no simulation is needed for the next step, or none would change a decision.",
        "無：下一步不需要模擬，或沒有模擬能改變任何決策。",
    ),
    "r.next": ("Next steps", "下一步"),
    "r.provenance": ("Provenance", "溯源"),
    "r.failure": ("Failure analysis:", "失效分析："),
    "r.heuristic": ("Heuristic candidate (pending review):", "經驗法則候選（待審）："),
    "r.ran": ("What ran, and what did not", "執行了什麼、沒執行什麼"),
    "r.not_performed": ("Not performed:", "未執行："),
    "r.note": ("Note:", "備註："),
    # -- form and request messages ----------------------------------------------------------------
    "msg.refused": ("The request was refused", "請求被拒絕"),
    "msg.not_found": ("Not found", "找不到"),
    "msg.no_page": ("There is no such page.", "沒有這個頁面。"),
    "msg.no_research": ("No research", "無法研究"),
    "msg.not_llm_admin.title": ("LLM administration only", "僅限 LLM 管理者"),
    "msg.not_llm_admin": (
        "{actor} is not an LLM administrator of this deployment. The language-model routes are "
        "deployment configuration, granted by the deployment's operator (lab-brain admin "
        "llm-admin {actor}); membership of a project does not grant it. Whether a project's "
        "evidence may use an external model is that project's own egress policy (Runtime page).",
        "{actor} 不是此部署的 LLM 管理者。語言模型路由屬於部署層級的設定，由部署的管理者授予"
        "（lab-brain admin llm-admin {actor}）；專案成員資格不會給予此權限。專案的證據能否送往"
        "外部模型，由該專案自己的外送政策決定（見「執行環境」頁面）。",
    ),
    "msg.no_research_text": (
        "No research for {actor} in {project}.",
        "{actor} 無法在 {project} 進行研究。",
    ),
    "msg.no_recorded_run": ("That run has no recorded report.", "該 run 沒有報告紀錄。"),
    "msg.choose_project": ("Choose a project.", "請選擇 project。"),
    "msg.needs_goal": ("A research run needs a goal.", "研究需要一個目標。"),
    "msg.literature_together": (
        "A literature corpus and a literature query go together: a provider is only searched with "
        "a query you declare public.",
        "文獻語料與文獻查詢必須一起提供：只會以你聲明為公開的查詢搜尋提供者。",
    ),
    "msg.literature_public": (
        "Declare the literature query PUBLIC to send it to the provider, or leave the literature "
        "fields empty.",
        "請聲明文獻查詢為 PUBLIC 才能送給提供者，或將文獻欄位留空。",
    ),
    "msg.unknown_classification": ("Unknown classification {value}.", "未知的機密分級 {value}。"),
    "msg.not_corpus": (
        "{name} is not a literature corpus (a JSON object with 'papers').",
        "{name} 不是文獻語料（需為含有 'papers' 的 JSON 物件）。",
    ),
    "msg.runtime_unusable.title": ("LLM runtime unavailable", "LLM 執行環境無法使用"),
    "msg.settings_refused": ("Not done", "未完成"),
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
