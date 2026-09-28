"""The researcher's pages: home, research data, research history, new research, system status.

ORGANISED AROUND WHAT A RESEARCHER DOES, not around backend objects:

    add research data -> see it processed -> choose it -> confirm -> start research -> read it

Each page answers one question (the navigation's hints) and every incomplete state says what to do
next. Values are shown in the researcher's language; the canonical ones -- states, identifiers,
trust classes, labels -- stay one click away under Technical details. Nothing here decides: every
list is what the server read, every state is `derive_state`'s, every button is a form the server
re-checks.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from lab_brain.interfaces.web.i18n import Messages
from lab_brain.interfaces.web.pages import (
    Chrome,
    EpisodeRow,
    Html,
    ProjectRow,
    cat,
    h,
    page,
    when,
    when_text,
)
from lab_brain.research.data import MATERIAL_KINDS, DataItem, UsableData

Messages.extend(
    {
        # -- shared vocabulary -----------------------------------------------------------------
        "kind.measurement": ("Measurement report or lab record", "量測報告或實驗紀錄"),
        "kind.measurement.hint": (
            "Data the lab measured: test reports, measurement logs.",
            "實驗室量測得到的資料，例如測試報告、量測紀錄。",
        ),
        "kind.run_record": ("Simulation or computation record", "模擬或運算紀錄"),
        "kind.run_record.hint": (
            "What a simulation, calculation or script run recorded.",
            "模擬、計算或程式執行留下的紀錄。",
        ),
        "kind.note": ("Notes, ideas or literature excerpts", "筆記、想法或文獻摘錄"),
        "kind.note.hint": (
            "Experience, meeting notes, key points from papers. Treated as expert judgement, not "
            "as a measurement.",
            "經驗判斷、會議筆記、文獻重點。系統會把它當作經驗性的說法，而不是量測結果。",
        ),
        "kind.none": ("not given", "未指定"),
        "sens.PUBLIC": ("Public", "公開"),
        "sens.PUBLIC.hint": (
            "Already public, or may be made public.",
            "已公開或可以公開的內容。",
        ),
        "sens.INTERNAL": ("Lab internal", "實驗室內部"),
        "sens.INTERNAL.hint": (
            "Circulates inside the lab only.",
            "只在實驗室內部流通的內容。",
        ),
        "sens.CONFIDENTIAL_LAB": ("Lab confidential", "實驗室機密"),
        "sens.CONFIDENTIAL_LAB.hint": (
            "Unpublished results; handled on this machine unless a project explicitly allows "
            "otherwise.",
            "尚未公開的研究成果；除非研究專案明確允許，否則只在這台電腦上處理。",
        ),
        "sens.RESTRICTED_NDA": ("Under NDA", "保密協議（NDA）"),
        "sens.RESTRICTED_NDA.hint": (
            "Bound by a non-disclosure agreement; never sent to an external AI API.",
            "受保密協議約束；永遠不會送往外部 AI API。",
        ),
        "sens.not_cleared": (
            "your access in this project does not include this level",
            "你在這個研究專案的閱讀權限不含此分級",
        ),
        "item.READY": ("Ready for research", "可用於研究"),
        "item.READY.next": (
            "Nothing to do: pick it in New research.",
            "不需要處理：可以在「新增研究」直接選用。",
        ),
        "item.PARTIAL": ("Partly usable", "部分可用"),
        "item.PARTIAL.next": (
            "Part of the file could not be read; the readable part can still be used. If the "
            "missing part matters, fix the file and import it again.",
            "檔案有一部分無法讀取，可讀取的部分仍可選用。如果缺少的部分很重要，請修正檔案後重新匯入。",
        ),
        "item.PROCESSING": ("Processing", "處理中"),
        "item.PROCESSING.next": (
            "Still being processed. Reload this page in a moment.",
            "系統仍在處理，請稍後重新整理這個頁面。",
        ),
        "item.NEEDS_REVIEW": ("Needs a person's check", "需要人工確認"),
        "item.NEEDS_REVIEW.next": (
            "Part of it waits for a person's decision (for example a possible conflict with "
            "earlier data). It becomes usable once that is decided; ask the project's reviewer.",
            "有內容需要人工確認（例如可能與既有資料互相矛盾），確認後才會變成可用。請聯絡研究專案的審查者。",
        ),
        "item.DUPLICATE": ("Same content as an earlier file", "與既有檔案內容相同"),
        "item.DUPLICATE.next": (
            "Identical to “{name}”, so nothing was added twice. Use that one; it keeps its own "
            "classification ({label}).",
            "內容和「{name}」完全相同，因此沒有重複加入。請直接選用原本那一份；分級沿用原檔（{label}）。",
        ),
        "item.DUPLICATE.relabel": (
            "You declared {declared} this time, but content identity keeps the classification "
            "the project already holds ({label}). If it should be stricter, ask the deployment's "
            "operator.",
            "你這次選的分級是「{declared}」，但相同內容會沿用研究專案中既有的分級（{label}）。"
            "如果應該更嚴格，請聯絡部署管理者。",
        ),
        "item.BLOCKED": ("Stopped by a safety rule", "已被安全規則擋下"),
        "item.BLOCKED.next": (
            "Stopped before it was stored -- for example because it seems to contain a password "
            "or private key. Remove that content and import the file again.",
            "檔案在儲存前就被擋下，例如疑似含有密碼或私鑰。請移除敏感內容後重新匯入。",
        ),
        "item.FAILED": ("Could not be processed", "處理失敗"),
        "item.FAILED.next": (
            "The file could not be read. Check the reason below, fix the file (a .md, .txt, .csv "
            "or .json text file) and import it again.",
            "系統無法讀取這個檔案。請看下方原因，修正檔案（.md、.txt、.csv 或 .json 文字檔）"
            "後重新匯入。",
        ),
        "item.unreadable": (
            "Classified above your access in this project: listed, but you cannot use it.",
            "分級高於你在這個研究專案的閱讀權限：會列出，但你無法使用。",
        ),
        "ep.EVIDENCE_GATHERING": ("In progress", "進行中"),
        "ep.SUSPENDED": ("Waiting -- can be continued", "等待中，可以繼續"),
        "ep.COMPLETED": ("Finished", "已完成"),
        "ep.ABANDONED": ("Stopped", "已中止"),
        "tech": ("Technical details", "技術細節"),
        # Why an item failed, by the M1 catalog's reason code: the catalog's own English sentence
        # (shown as the catalog renders it) and its Traditional Chinese, for the codes an import
        # can end with. An unknown code shows the catalog's sentence as it is.
        "reason.GENERIC": ("This item could not be processed.", "這個項目無法處理。"),
        "reason.SEC003_SUSPECTED_CREDENTIAL": (
            "This file was quarantined because it appears to contain a credential.",
            "檔案看起來含有憑證（例如密碼、金鑰或私鑰），已被隔離，沒有保存。",
        ),
        "reason.UX004_ALREADY_DURABLE": (
            "This stage was skipped because the file was already stored.",
            "檔案已經保存過，所以跳過這個步驟。",
        ),
        "reason.PARSE_TEXT_FAILED": (
            "Some text could not be extracted from this document.",
            "無法從這份文件擷取文字（可能不是文字檔，或編碼無法辨識）。",
        ),
        "reason.SEGMENT_FAILED": (
            "The document was stored but could not be divided into citable passages.",
            "文件已保存，但無法切成可引用的段落。",
        ),
        "reason.OPS004_DB_COMMIT_FAILED": (
            "This upload could not be recorded and left nothing behind.",
            "這次上傳無法記錄，也沒有留下任何資料。",
        ),
        "reason.OPS004_PROMOTE_FAILED_COMPENSATED": (
            "This upload was rolled back and left no partial record.",
            "這次上傳已復原，沒有留下不完整的紀錄。",
        ),
        "reason.UNREADABLE_UPLOAD": ("This file could not be read.", "無法讀取這個檔案。"),
        "reason.RETRY_LIMIT_REACHED": (
            "This step failed after all its retries.",
            "這個步驟重試多次後仍然失敗。",
        ),
        "reason.EXTERNAL_SERVICE_UNAVAILABLE": (
            "An external service did not respond.",
            "外部服務沒有回應。",
        ),
        "reason.BUDGET_EXHAUSTED": (
            "This step was stopped because the project's budget is spent.",
            "研究專案的預算已用完，因此停止這個步驟。",
        ),
        "reason.READ_NOT_PERMITTED": (
            "You do not have access to the source of this record.",
            "你沒有這份資料來源的閱讀權限。",
        ),
        # -- home -------------------------------------------------------------------------------
        "home.title": ("Research workspace", "研究工作台"),
        "home.lede": (
            "Start here: import your lab's data, then start research on a question. Each panel "
            "says what to do next.",
            "從這裡開始：先把實驗室的資料匯入，再針對一個問題開始研究。每個區塊都會告訴你下一步。",
        ),
        "home.add_data": ("＋ Import research data", "＋ 匯入研究資料"),
        "home.add_data.hint": (
            "Measurement reports, simulation records, notes -- the files the research reads.",
            "量測報告、模擬紀錄、筆記：研究會讀取的檔案都從這裡放進來。",
        ),
        "home.start": ("＋ Start new research", "＋ 開始新研究"),
        "home.start.hint": (
            "Ask a question, choose the data it should use, confirm, start.",
            "提出問題、選擇要用的資料、確認後開始。",
        ),
        "home.data": ("Research data", "研究資料"),
        "home.data.counts": (
            "{ready} ready for research · {processing} processing · {attention} need attention",
            "可用 {ready} 份 · 處理中 {processing} 份 · 需要處理 {attention} 份",
        ),
        "home.data.none": (
            "No research data yet. Use “＋ Import research data” to add your first file.",
            "還沒有任何研究資料。按「＋ 匯入研究資料」加入第一份檔案。",
        ),
        "home.data.all": ("All research data", "查看全部研究資料"),
        "home.research": ("Research", "研究"),
        "home.research.waiting": (
            "{n} research task(s) waiting -- they can be continued.",
            "有 {n} 項研究任務在等待中，可以繼續。",
        ),
        "home.research.none": (
            "No research yet. Once some data is ready for research, use “＋ Start new research”.",
            "還沒有任何研究。資料可用之後，按「＋ 開始新研究」。",
        ),
        "home.research.all": ("Research history", "查看研究紀錄"),
        "home.ai": ("AI models", "AI 模型"),
        "home.sim": ("Simulation", "模擬"),
        "home.sim.none": (
            "No simulator is connected to this deployment. This is a known limit, not a fault: "
            "every other research step runs, a check that needs simulation is listed as waiting, "
            "and the same research can be continued once a simulator is available.",
            "這個部署沒有連接模擬器。這是已知的限制，不是故障：研究的其他步驟照常進行，需要模擬的驗證會列為"
            "「等待模擬」，等模擬器可用時可以繼續同一項研究。",
        ),
        "home.sim.all": (
            "Every simulation capability can run here.",
            "所有模擬功能都可以在這裡執行。",
        ),
        "home.sim.more": ("System status", "查看系統狀態"),
        "home.projects": ("Your research projects", "你的研究專案"),
        "home.next": ("Next:", "下一步："),
        "home.next.no_data": (
            "import research data into a project.",
            "把研究資料匯入研究專案。",
        ),
        "home.next.processing": (
            "wait for your data to finish processing, or check the items that need attention.",
            "等待資料處理完成，或查看需要處理的資料。",
        ),
        "home.next.start": (
            "start research on the data that is ready.",
            "用已可用的資料開始研究。",
        ),
        "home.next.continue": (
            "continue the research that is waiting, or start new research.",
            "繼續等待中的研究，或開始新的研究。",
        ),
        # -- AI status (home and system status) ------------------------------------------------
        "ai.none": (
            "No AI model configuration is applied: research uses the local rule-based reasoner "
            "and no AI model is called.",
            "目前沒有套用 AI 模型配置：研究使用本機的規則式推理，不會呼叫任何 AI 模型。",
        ),
        "ai.active": (
            "New research uses the AI model configuration “{name}”.",
            "新的研究會使用 AI 模型配置「{name}」。",
        ),
        "ai.unusable": (
            "The applied configuration “{name}” cannot be used right now, so new research will "
            "not start: {reason}",
            "已套用的配置「{name}」目前無法使用，所以新的研究不會開始：{reason}",
        ),
        "ai.next.admin": (
            "open AI model settings and follow the steps, or keep the local reasoner.",
            "到「AI 模型設定」照步驟建立並套用配置；或繼續使用本機規則式推理。",
        ),
        "ai.next.fix": (
            "open AI model settings and fix what is listed there.",
            "到「AI 模型設定」依照「尚待處理」清單修正。",
        ),
        "ai.next.ok": (
            "nothing: new research uses it automatically.",
            "不需要做什麼：新的研究會自動使用它。",
        ),
        "ai.next.member": (
            "nothing on your side: AI models are set up by the deployment's AI model "
            "administrator.",
            "你不需要處理：AI 模型由部署的 AI 模型管理者設定。",
        ),
        "ai.open": ("AI model settings", "前往 AI 模型設定"),
        "ai.detail": ("Current model configuration", "查看目前的模型配置"),
        # -- research data ----------------------------------------------------------------------
        "data.title": ("Research data", "研究資料"),
        "data.lede": (
            "Everything Lab Brain reads comes in here. Import measurement reports, simulation "
            "records or notes into a research project: each file is checked for secrets, stored "
            "and split into citable passages. Once it shows “Ready for research”, pick it in New "
            "research -- no need to upload it again.",
            "要交給 Lab Brain 的資料，都從這裡匯入。把量測報告、模擬紀錄或筆記匯入研究專案："
            "系統會先做安全"
            "檢查、保存檔案，並切成可引用的段落。狀態顯示「可用於研究」後，就能在「新增研究」直接選用，不必"
            "重新上傳。",
        ),
        "data.project": ("Research project", "研究專案"),
        "data.switch": ("Show", "切換"),
        "data.add": ("＋ Import research data", "＋ 匯入研究資料"),
        "data.add.into": ("into {project}", "匯入到「{project}」"),
        "data.files": ("Choose files", "選擇檔案"),
        "data.files.hint": (
            "one or more text files: .md, .txt, .csv or .json",
            "可一次選多個文字檔：.md、.txt、.csv 或 .json",
        ),
        "data.kind": ("What kind of material is it?", "這是哪一類資料？"),
        "data.kind.hint": (
            "Required. The system does not guess it; it decides how much weight the statements "
            "carry in research.",
            "必填。系統不會自己判斷；這會決定這些內容在研究中的份量。",
        ),
        "data.sensitivity": ("How sensitive is it?", "資料分級"),
        "data.sensitivity.hint": (
            "Required, no default. It decides who may read it, and whether it may ever be sent "
            "to an external AI API.",
            "必填，沒有預設值。這會決定誰能讀取，以及能不能送往外部 AI API。",
        ),
        "data.submit": ("Import", "匯入"),
        "data.added": (
            "{n} file(s) imported. How each was processed:",
            "已匯入 {n} 個檔案，處理結果如下：",
        ),
        "data.list": ("Data in this project", "這個研究專案的研究資料"),
        "data.none": (
            "This project has no research data yet. Import the first file above.",
            "這個研究專案還沒有研究資料。請用上方的表單匯入第一份檔案。",
        ),
        "data.col.file": ("File", "檔案"),
        "data.col.kind": ("Kind", "資料類型"),
        "data.col.sensitivity": ("Classification", "分級"),
        "data.col.state": ("Status and next step", "狀態與下一步"),
        "data.col.added": ("Imported", "匯入時間"),
        "data.col.origin": ("Imported from", "來源"),
        "data.origin.RESEARCH_DATA": ("Research data page", "研究資料頁"),
        "data.origin.RESEARCH_RUN": ("Uploaded with research", "隨研究上傳"),
        "data.origin.OTHER": ("Other", "其他"),
        "data.why": ("Why:", "原因："),
        "data.need.files": ("Choose at least one file.", "請至少選擇一個檔案。"),
        "data.need.kind": (
            "Choose what kind of material the files are.",
            "請選擇資料類型。",
        ),
        "data.need.sensitivity": (
            "Choose how sensitive the files are.",
            "請選擇資料分級。",
        ),
        "data.not_cleared": (
            "Not imported: your access in this project does not include “{label}”, so you "
            "could not read the file back or use it. Choose a level you hold, or ask the "
            "deployment's operator to extend your access. Nothing was stored.",
            "沒有匯入：你在這個研究專案的閱讀權限不含「{label}」，匯入後你自己也無法讀取或使用它。"
            "請選擇你有權限的分級，或請部署管理者調整權限。系統沒有儲存任何內容。",
        ),
        "data.passages": ("{n} passage(s)", "{n} 個段落"),
        "data.legend": ("What the statuses mean", "狀態說明"),
        # -- research history -------------------------------------------------------------------
        "eps.title": ("Research history", "研究紀錄"),
        "eps.lede": (
            "Research you started, in projects you are a member of. Waiting research can be "
            "continued; finished research can be read.",
            "你開始的研究（限你目前所屬的研究專案）。等待中的研究可以繼續；已完成的研究可以查看報告。",
        ),
        "eps.none": ("You have not started any research yet.", "你還沒有開始任何研究。"),
        "eps.col.question": ("Question", "研究問題"),
        "eps.col.project": ("Research project", "研究專案"),
        "eps.col.state": ("Status", "狀態"),
        "eps.col.runs": ("Runs", "執行次數"),
        "eps.col.started": ("Started", "開始時間"),
        # -- new research -----------------------------------------------------------------------
        "new.title": ("New research", "新增研究"),
        "new.lede": (
            "Describe the question, choose the data it should use, and confirm everything before "
            "the research starts. Data already in the project is used as it is -- nothing is "
            "uploaded twice.",
            "描述研究問題、選擇要使用的資料，開始前會先讓你確認全部輸入。研究專案裡已有的資料會直接使用，"
            "不會重複上傳。",
        ),
        "new.step.1": ("Question", "研究問題"),
        "new.step.2": ("Project", "研究專案"),
        "new.step.3": ("Existing data", "選擇既有資料"),
        "new.step.4": ("New files (optional)", "加入新檔案（選填）"),
        "new.step.5": ("External sources (optional)", "外部資料來源（選填）"),
        "new.step.6": ("Confirm", "確認輸入"),
        "new.step.7": ("Start", "開始研究"),
        "new.project": ("Research project", "研究專案"),
        "new.switch": ("Switch project", "切換研究專案"),
        "new.switch.hint": (
            "Switching keeps what you typed; files you chose must be chosen again.",
            "切換時會保留已輸入的文字；已選的檔案需要重新選擇。",
        ),
        "new.goal": ("What do you want to find out?", "想釐清的研究問題"),
        "new.goal.hint": ("In your own words.", "用你自己的話描述即可。"),
        "new.goal.sensitivity": (
            "How sensitive is the question itself?",
            "研究問題本身的分級",
        ),
        "new.goal.sensitivity.hint": (
            "Required, no default: the question travels with the research.",
            "必填，沒有預設值：研究問題會隨研究一起處理。",
        ),
        "new.framing": (
            "Add background (optional): symptom, expected and observed behaviour",
            "補充問題背景（選填）：症狀、預期行為、觀察到的行為",
        ),
        "new.symptom": ("Symptom", "症狀"),
        "new.expected": ("Expected behaviour", "預期行為"),
        "new.observed": ("Observed behaviour", "觀察到的行為"),
        "new.data.hint": (
            "Only this project's data that is ready for research is listed. Tick what this "
            "research should use; each item is used as it was processed, not uploaded again.",
            "只列出這個研究專案中「可用於研究」的資料。勾選這次研究要用的；每份資料會直接使用已處理好的內容，"
            "不會重新上傳。",
        ),
        "new.data.none": (
            "This project has no data ready for research yet. Add files in the next step, or "
            "import them on the Research data page first.",
            "這個研究專案還沒有可用的資料。可以在下一步直接加入新檔案，或先到「研究資料」頁匯入。",
        ),
        "new.data.use": ("Use", "使用"),
        "new.data.kind": ("Use it as", "作為"),
        "new.data.pick_kind": ("choose…", "請選擇…"),
        "new.files.hint": (
            "New files are first imported into the project's research data -- with the same "
            "checks as the Research data page -- and then used in this research.",
            "新檔案會先匯入研究專案的研究資料（與「研究資料」頁相同的檢查），再用於這次研究。",
        ),
        "new.files": ("Files", "檔案"),
        "new.sources.hint": (
            "Only what you give here is searched or read. A literature search sends only the "
            "query you confirm may be public -- nothing else about this research.",
            "只會使用你在這裡提供的內容。文獻搜尋只會送出你確認可以公開的查詢，這次研究的其他內容都不會送出。",
        ),
        "new.corpus": ("Literature file (local)", "文獻資料檔（本機）"),
        "new.corpus.hint": (
            "a JSON file with a “papers” list; searched only with the query below",
            "含有「papers」清單的 JSON 檔；只會用下方的查詢搜尋",
        ),
        "new.query": ("Literature search query", "文獻查詢"),
        "new.query.public": (
            "I confirm this query may be made public",
            "我確認這段查詢可以公開",
        ),
        "new.verification": ("Verification input (optional)", "驗證輸入（選填）"),
        "new.verification.hint": (
            "The domain's input for planning checks, e.g. a device project JSON. Without it, "
            "no verification is planned.",
            "用來規劃驗證的輸入，例如元件專案 JSON。沒有提供時，不會規劃驗證。",
        ),
        "new.next": ("Next: confirm the inputs", "下一步：確認輸入"),
        "new.next.hint": (
            "Nothing is reasoned yet: the next page shows exactly what the research will use.",
            "還不會開始推理：下一頁會列出這次研究將使用的全部內容。",
        ),
        "new.need.kind": (
            "Choose a kind for “{name}”, or untick it.",
            "請為「{name}」選擇資料類型，或取消勾選。",
        ),
        "new.need.goal_sensitivity": (
            "Choose how sensitive the question is.",
            "請選擇研究問題的分級。",
        ),
        "new.need.files_kind": (
            "Choose what kind of material the new files are.",
            "請選擇新檔案的資料類型。",
        ),
        "new.need.files_sensitivity": (
            "Choose how sensitive the new files are.",
            "請選擇新檔案的分級。",
        ),
        "new.not_usable": (
            "“{name}” is not data this research may use in this project.",
            "「{name}」不是這個研究專案中可以使用的資料。",
        ),
        # -- confirm ------------------------------------------------------------------------------
        "rv.title": ("Confirm the inputs", "確認研究輸入"),
        "rv.lede": (
            "This is exactly what the research will use. Nothing has been reasoned yet: start it "
            "when this is right, or go back to change it.",
            "以下就是這次研究會使用的全部內容。系統還沒開始推理：確認無誤就開始，或返回修改。",
        ),
        "rv.added": (
            "{n} new file(s) were imported into the project's research data:",
            "已將 {n} 個新檔案匯入研究專案的研究資料：",
        ),
        "rv.same_as": (
            "your new file “{name}” has the same content, so this one -- already in the project "
            "-- is used, once",
            "你新加入的「{name}」內容與這份相同，因此直接使用研究專案中原本這一份（不會重複）",
        ),
        "rv.excluded": (
            "Not usable, so not included:",
            "以下檔案無法使用，因此不會納入：",
        ),
        "rv.will_use": ("This research will use", "這次研究將使用"),
        "rv.question": ("Question", "研究問題"),
        "rv.question_label": ("Question classification", "問題分級"),
        "rv.project": ("Research project", "研究專案"),
        "rv.data": ("Research data ({n})", "研究資料（{n} 份）"),
        "rv.data.none": (
            "No research data. Without evidence there is nothing to debate: the research will stop "
            "after the evidence step. Go back and choose data, or start anyway.",
            "沒有選用任何資料。沒有證據就無法辯論，研究會在證據步驟之後停止。可以返回選擇資料，或仍然開始。",
        ),
        "rv.new": ("new", "新加入"),
        "rv.background": ("Background", "問題背景"),
        "rv.sources": ("External sources", "外部資料來源"),
        "rv.sources.none": (
            "None: no external source is contacted.",
            "無：不會連線任何外部資料來源。",
        ),
        "rv.literature": (
            "Literature file “{name}”, searched with the public query “{query}”",
            "文獻資料檔「{name}」，以可公開的查詢「{query}」搜尋",
        ),
        "rv.verification": ("Verification input", "驗證輸入"),
        "rv.verification.none": (
            "None: no verification will be planned.",
            "無：不會規劃驗證。",
        ),
        "rv.ai": ("AI model", "AI 模型"),
        "rv.sim": ("Simulation", "模擬"),
        "rv.start": ("Start research", "開始研究"),
        "rv.back": ("Go back and change", "返回修改"),
        "rv.bytes": ("{n} bytes", "{n} 位元組"),
        # -- system status -----------------------------------------------------------------------
        "st.title": ("System status", "系統狀態"),
        "st.lede": (
            "What the system can do right now, what is missing, and what to do about it.",
            "系統現在能做什麼、還缺什麼，以及該怎麼補。",
        ),
        "st.ok": ("Working", "正常"),
        "st.problem": ("Problem", "有問題"),
        "st.missing": ("Not set up", "尚未設定"),
        "st.limit": ("Known limit", "已知限制"),
        "st.col.part": ("Part", "項目"),
        "st.col.state": ("Status", "狀態"),
        "st.col.detail": ("What it means / what to do", "說明與下一步"),
        "st.db": ("Database", "資料庫"),
        "st.db.ok": (
            "Answers; {n} schema migration(s) applied.",
            "連線正常；已套用 {n} 個資料庫版本更新。",
        ),
        "st.storage": ("File storage", "檔案儲存"),
        "st.storage.ok": (
            "Imported files are kept here; {free} free.",
            "匯入的檔案保存在這裡；剩餘空間 {free}。",
        ),
        "st.storage.problem": (
            "The file store cannot be written: new files cannot be imported. Ask the operator.",
            "檔案儲存區無法寫入：無法匯入新檔案。請聯絡部署管理者。",
        ),
        "st.data": ("Research data import", "研究資料匯入"),
        "st.data.row": (
            "{project}: {ready} ready · {processing} processing · {attention} need attention",
            "{project}：可用 {ready} 份 · 處理中 {processing} 份 · 需要處理 {attention} 份",
        ),
        "st.data.attention": (
            "Some files need attention: open Research data to see why.",
            "有檔案需要處理：到「研究資料」查看原因。",
        ),
        "st.ai": ("AI model configuration", "AI 模型配置"),
        "st.local": ("Local models (Ollama)", "本機模型（Ollama）"),
        "st.local.none": (
            "No local model connection is set up. Optional: add “Local model (Ollama)” in AI "
            "model settings.",
            "尚未設定本機模型連線。這是選用的：可以在「AI 模型設定」新增「本機模型（Ollama）」。",
        ),
        "st.local.row": (
            "{name}: {outcome} (checked {at})",
            "{name}：{outcome}（檢查於 {at}）",
        ),
        "st.local.never": ("{name}: never checked", "{name}：尚未檢查"),
        "st.external": ("External AI APIs", "外部 AI API"),
        "st.external.none": (
            "No external AI API connection is set up. Optional: nothing leaves this machine.",
            "尚未設定外部 AI API 連線。這是選用的：沒有任何內容會離開這台電腦。",
        ),
        "st.recheck": ("Check the connections now", "立即檢查模型連線"),
        "st.recheck.hint": (
            "Asks each enabled model connection whether it answers, and records the result.",
            "向每個使用中的模型連線確認是否有回應，並記錄結果。",
        ),
        "st.sim": ("Simulation (Lumerical)", "模擬（Lumerical）"),
        "st.sim.cannot": (
            "Not available here: {why}. This is a known limit, not a fault -- research runs "
            "without it and lists each check that needs simulation as waiting; the same "
            "research can be continued once a simulator is available.",
            "這裡無法執行：{why}。這是已知的限制，不是故障：研究照常進行，需要模擬的驗證會列為等待中，"
            "模擬器可用時可以繼續同一項研究。",
        ),
        "st.sim.why": (
            "no licensed simulator is installed or wired into this deployment",
            "此部署沒有安裝或接上具授權的模擬軟體",
        ),
        "st.sim.can": (
            "Every simulation capability can run here.",
            "所有模擬功能都可以在這裡執行。",
        ),
        "st.checks": ("Local checks without a simulator", "不需模擬器的本機檢查"),
        "st.checks.ok": (
            "{n} check(s) (design-file readers) run automatically when a verification plan "
            "chooses them.",
            "{n} 項檢查（讀取設計檔）在驗證計畫選到時會自動執行。",
        ),
        "st.blocked": ("Unavailable capabilities", "無法使用的功能"),
        "st.blocked.lede": (
            "What research cannot do in this deployment, and why:",
            "這個部署中研究無法執行的功能，以及原因：",
        ),
        "st.blocked.sim": (
            "{n} simulation capability(ies): no licensed simulator is wired into this deployment.",
            "{n} 項模擬功能：這個部署沒有接上具授權的模擬軟體。",
        ),
        "st.blocked.sim.needs": (
            "Needs a Lumerical installation with a licence seat and its provider module. Until "
            "then, research lists these checks as waiting and can be continued later.",
            "需要安裝 Lumerical 並具備授權，以及對應的模擬模組。在那之前，研究會把這些檢查列為等待"
            "中，"
            "之後可以繼續。",
        ),
        "st.blocked.other": (
            "{n} capability(ies) of type {kind} are unavailable here (see the technical details).",
            "{n} 項 {kind} 類型的功能在這裡無法使用（原因見技術細節）。",
        ),
        "st.egress": ("External transfer, per project", "各研究專案的外部傳輸"),
    }
)


# -- small helpers ------------------------------------------------------------------------------


def _tech(m: Messages, rows: Sequence[tuple[str, object]]) -> Html:
    return h(
        '<details class="tech"><summary>{}</summary><table>{}</table></details>',
        m("tech"),
        cat(h("<tr><th>{}</th><td><code>{}</code></td></tr>", k, v) for k, v in rows),
    )


def reason(code: str, summary: str, m: Messages) -> str:
    """Why an import failed: the catalog's sentence, or its translation where there is one."""
    if m.locale == "en":
        return summary
    try:
        return m(f"reason.{code}") or summary
    except KeyError:
        return summary


def item_state(state: str, m: Messages) -> Html:
    """A derived ingestion state in the researcher's words; the canonical one is its tooltip."""
    return h('<span class="state state-{}" title="{}">{}</span>', state, state, m(f"item.{state}"))


def episode_state(state: str, m: Messages) -> Html:
    key = f"ep.{state}"
    try:
        text = m(key)
    except KeyError:
        text = state
    return h('<span class="state state-{}" title="{}">{}</span>', state, state, text)


def kind_name(kind: str | None, m: Messages) -> str:
    """A trust class the researcher declared, in their words."""
    for key, trust in MATERIAL_KINDS.items():
        if trust.value == kind:
            return m(f"kind.{key}")
    return m("kind.none")


def kind_key(kind: str | None) -> str | None:
    return next((k for k, t in MATERIAL_KINDS.items() if t.value == kind), None)


def sensitivity_name(label: str | None, m: Messages) -> str:
    return m(f"sens.{label}") if label else "-"


def _choices(
    name: str,
    options: Sequence[tuple[str, str, str]],
    *,
    required: bool,
    chosen: str = "",
    disabled: frozenset[str] = frozenset(),
    disabled_hint: str = "",
) -> Html:
    """Radio buttons, NONE pre-selected unless the researcher chose one already: the researcher
    declares, the page does not guess. A disabled option says why."""
    return cat(
        h(
            '<label class="choice{}"><input type="radio" name="{}" value="{}"{}{}{}> {}'
            '<span class="hint">{}</span></label>',
            Html(" off" if value in disabled else ""),
            name,
            value,
            Html(" required" if required else ""),
            Html(" checked" if value == chosen and value not in disabled else ""),
            Html(" disabled" if value in disabled else ""),
            text,
            f"{hint} ({disabled_hint})" if value in disabled and disabled_hint else hint,
        )
        for value, text, hint in options
    )


def kind_choices(m: Messages, name: str = "kind", *, required: bool = True) -> Html:
    return _choices(
        name,
        [(k, m(f"kind.{k}"), m(f"kind.{k}.hint")) for k in MATERIAL_KINDS],
        required=required,
    )


def sensitivity_choices(
    m: Messages,
    sensitivities: Sequence[str],
    name: str,
    *,
    required: bool = True,
    chosen: str = "",
    cleared: frozenset[str] | None = None,
) -> Html:
    """`cleared`, when given: the labels this actor holds; the others are shown, disabled, with
    the reason -- so nobody is pushed to pick a lower label without knowing why."""
    return _choices(
        name,
        [(s, m(f"sens.{s}"), m(f"sens.{s}.hint")) for s in sensitivities],
        required=required,
        chosen=chosen,
        disabled=frozenset(s for s in sensitivities if cleared is not None and s not in cleared),
        disabled_hint=m("sens.not_cleared"),
    )


def _project_picker(
    m: Messages, action: str, projects: Sequence[ProjectRow], chosen: str | None, button: str
) -> Html:
    return h(
        '<form method="get" action="{}" class="picker"><label for="pp">{}</label>'
        '<select id="pp" name="project">{}</select> <button class="small" type="submit">{}'
        "</button></form>",
        action,
        m("data.project"),
        _project_options(projects, chosen),
        button,
    )


def _project_options(projects: Sequence[ProjectRow], chosen: str | None) -> Html:
    return cat(
        h(
            '<option value="{}"{}>{}</option>',
            p.project_id,
            Html(" selected" if p.project_id == chosen else ""),
            p.name,
        )
        for p in projects
    )


def _no_projects(chrome: Chrome, title_key: str) -> bytes:
    m = chrome.m
    body = h(
        '<h1>{}</h1><p class="box notice">{}</p>',
        m(title_key),
        m("home.no_projects", actor=chrome.actor_id),
    )
    return page(m(title_key), body, chrome=chrome)


@dataclass(frozen=True)
class DataCounts:
    ready: int = 0
    processing: int = 0
    attention: int = 0

    @classmethod
    def of(cls, items: Sequence[DataItem]) -> DataCounts:
        ready = sum(1 for i in items if i.state.value in ("READY", "PARTIAL"))
        processing = sum(1 for i in items if i.state.value == "PROCESSING")
        attention = sum(1 for i in items if i.state.value in ("NEEDS_REVIEW", "BLOCKED", "FAILED"))
        return cls(ready, processing, attention)


@dataclass(frozen=True)
class AiStatus:
    """What reasons new research now, in the researcher's words, and what to do about it."""

    sentence: str
    next_step: str
    admin: bool
    problem: bool = False
    configured: bool = False


@dataclass(frozen=True)
class Capabilities:
    domain: str
    backends: Mapping[str, str]
    #: (capability id, action type, why not, what it needs)
    blocked: Sequence[tuple[str, str, str, str]]


def _ai_links(ai: AiStatus, m: Messages) -> Html:
    links = [h('<a href="/runtime">{}</a>', m("ai.detail"))]
    if ai.admin:
        links.insert(0, h('<a href="/settings/llm">{}</a>', m("ai.open")))
    return cat(links, " · ")


def _next(m: Messages, text: str) -> Html:
    return h('<div class="next"><strong>{}</strong> {}</div>', m("home.next"), text)


# -- home ---------------------------------------------------------------------------------------


def home_page(
    chrome: Chrome,
    *,
    projects: Sequence[ProjectRow],
    recent: Sequence[tuple[ProjectRow, DataItem]],
    counts: DataCounts,
    episodes: Sequence[EpisodeRow],
    ai: AiStatus,
    capabilities: Capabilities,
) -> bytes:
    m = chrome.m
    if not projects:
        return _no_projects(chrome, "home.title")
    waiting = [ep for ep in episodes if ep.state == "SUSPENDED"]
    if not recent:
        next_step = m("home.next.no_data")
    elif waiting:
        next_step = m("home.next.continue")
    elif counts.ready:
        next_step = m("home.next.start")
    else:
        next_step = m("home.next.processing")
    data_card = h(
        '<div class="card"><h2>{}</h2>{}{}<p><a href="/data">{}</a></p></div>',
        m("home.data"),
        h("<p>{}</p>", m("home.data.counts", **vars(counts))) if recent else Html(""),
        h(
            "<ul>{}</ul>",
            cat(
                h(
                    '<li>{} <span class="muted">{}</span> {}</li>',
                    item.name,
                    project.name,
                    item_state(item.state.value, m),
                )
                for project, item in recent[:6]
            ),
        )
        if recent
        else h('<p class="muted">{}</p>', m("home.data.none")),
        m("home.data.all"),
    )
    research_card = h(
        '<div class="card"><h2>{}</h2>{}{}<p><a href="/episodes">{}</a></p></div>',
        m("home.research"),
        h('<p class="box warn">{}</p>', m("home.research.waiting", n=len(waiting)))
        if waiting
        else Html(""),
        h(
            "<ul>{}</ul>",
            cat(
                h(
                    '<li><a href="/episodes/{}">{}</a> {}</li>',
                    ep.episode_id,
                    ep.goal,
                    episode_state(ep.state, m),
                )
                for ep in (*waiting, *(x for x in episodes if x.state != "SUSPENDED"))[:6]
            ),
        )
        if episodes
        else h('<p class="muted">{}</p>', m("home.research.none")),
        m("home.research.all"),
    )
    ai_card = h(
        '<div class="card"><h2>{}</h2><p{}>{}</p>{}<p>{}</p></div>',
        m("home.ai"),
        Html(' class="box warn"' if ai.problem else ""),
        ai.sentence,
        _next(m, ai.next_step),
        _ai_links(ai, m),
    )
    sim_card = h(
        '<div class="card"><h2>{}</h2><p class="box info">{}</p><p><a href="/status">{}</a></p>'
        "</div>",
        m("home.sim"),
        m("home.sim.none") if capabilities.blocked else m("home.sim.all"),
        m("home.sim.more"),
    )
    body = h(
        '<h1>{}</h1><p class="lede">{}</p>'
        '<div class="cta"><div><a class="button" href="/data">{}</a>'
        '<span class="hint">{}</span></div>'
        '<div><a class="button secondary" href="/runs/new">{}</a><span class="hint">{}</span>'
        "</div></div>{}"
        '<div class="grid">{}{}{}{}</div><h2>{}</h2><ul>{}</ul>',
        m("home.title"),
        m("home.lede"),
        m("home.add_data"),
        m("home.add_data.hint"),
        m("home.start"),
        m("home.start.hint"),
        _next(m, next_step),
        data_card,
        research_card,
        ai_card,
        sim_card,
        m("home.projects"),
        cat(
            h('<li><a href="/data?project={}">{}</a></li>', p.project_id, p.name) for p in projects
        ),
    )
    return page(m("home.title"), body, chrome=chrome)


# -- research data ------------------------------------------------------------------------------


def _next_for(item: DataItem, names: Mapping[str, str], m: Messages) -> Html:
    """What the researcher should know and do about one item, in their words."""
    state_ = item.state.value
    if state_ == "DUPLICATE":
        label = sensitivity_name(item.sensitivity, m)
        text = h(
            "{}",
            m("item.DUPLICATE.next", name=names.get(item.duplicate_of or "", "-"), label=label),
        )
        if item.declared_label and item.sensitivity and item.declared_label != item.sensitivity:
            text = h(
                '{}<div class="warn-line">{}</div>',
                text,
                m(
                    "item.DUPLICATE.relabel",
                    declared=sensitivity_name(item.declared_label, m),
                    label=label,
                ),
            )
        return text
    if state_ in ("READY", "PARTIAL") and item.artifact_id and not item.readable:
        return h("{}", m("item.unreadable"))
    return h("{}", m(f"item.{state_}.next"))


def data_page(
    chrome: Chrome,
    *,
    projects: Sequence[ProjectRow],
    project: ProjectRow | None,
    items: Sequence[DataItem],
    reasons: Mapping[str, Sequence[str]],
    sensitivities: Sequence[str],
    cleared: frozenset[str],
    added: Sequence[str] = (),
    error: str | None = None,
) -> bytes:
    """`added`: the item ids the previous import produced, to report how each came out."""
    m = chrome.m
    if project is None:
        return _no_projects(chrome, "data.title")
    names = {i.item_id: i.name for i in items}
    by_id = {i.item_id: i for i in items}
    just_added = [by_id[x] for x in added if x in by_id]
    result = (
        h(
            '<div class="box notice" id="result"><p><strong>{}</strong></p><ul>{}</ul></div>',
            m("data.added", n=len(just_added)),
            cat(
                h(
                    "<li>{} {} -- {}</li>",
                    i.name,
                    item_state(i.state.value, m),
                    _next_for(i, names, m),
                )
                for i in just_added
            ),
        )
        if just_added
        else Html("")
    )
    form = h(
        '<form method="post" action="/data" enctype="multipart/form-data" class="card intake"'
        ' id="import"><input type="hidden" name="csrf" value="{}">'
        '<input type="hidden" name="project" value="{}">'
        "<h2>{} <small>{}</small></h2>"
        '<fieldset><legend><span class="step">1</span>{}</legend>'
        '<input type="file" name="files" multiple required> '
        '<span class="hint">{}</span></fieldset>'
        '<fieldset><legend><span class="step">2</span>{}</legend>'
        '<p class="hint">{}</p>{}</fieldset>'
        '<fieldset><legend><span class="step">3</span>{}</legend>'
        '<p class="hint">{}</p>{}</fieldset>'
        '<button type="submit" class="primary">{}</button></form>',
        chrome.csrf or "",
        project.project_id,
        m("data.add"),
        m("data.add.into", project=project.name),
        m("data.files"),
        m("data.files.hint"),
        m("data.kind"),
        m("data.kind.hint"),
        kind_choices(m),
        m("data.sensitivity"),
        m("data.sensitivity.hint"),
        sensitivity_choices(m, sensitivities, "sensitivity", cleared=cleared),
        m("data.submit"),
    )
    rows = []
    for item in items:
        why = reasons.get(item.item_id, ())
        rows.append(
            h(
                '<tr id="{}"><td>{}<div class="purpose">{}</div></td><td>{}</td><td>{}</td>'
                '<td>{}<div class="purpose">{}</div>{}</td><td>{}</td><td>{}</td></tr>',
                item.item_id,
                item.name,
                m("data.passages", n=item.evidence_units) if item.evidence_units else "",
                kind_name(item.declared_kind.value if item.declared_kind else None, m),
                sensitivity_name(item.sensitivity, m),
                item_state(item.state.value, m),
                _next_for(item, names, m),
                h(
                    '<div class="purpose"><strong>{}</strong> {}</div>',
                    m("data.why"),
                    " ".join(why),
                )
                if why
                else Html(""),
                when(item.submitted_at),
                h(
                    "{}{}",
                    m(f"data.origin.{item.origin}"),
                    h(' <a href="/episodes/{}">↗</a>', item.episode_id) if item.episode_id else "",
                ),
            )
        )
    table = (
        h(
            '<div class="scroll"><table><thead><tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th>'
            "<th>{}</th><th>{}</th></tr></thead><tbody>{}</tbody></table></div>{}",
            m("data.col.file"),
            m("data.col.kind"),
            m("data.col.sensitivity"),
            m("data.col.state"),
            m("data.col.added"),
            m("data.col.origin"),
            cat(rows),
            _tech(
                m,
                [
                    (
                        i.name,
                        f"item={i.item_id} artifact={i.artifact_id or '-'} "
                        f"state={i.state.value} "
                        f"kind={i.declared_kind.value if i.declared_kind else '-'} "
                        f"label={i.sensitivity or '-'} "
                        f"declared_label={i.declared_label or '-'} units={i.evidence_units}"
                        + (f" errors={','.join(i.error_ids)}" if i.error_ids else ""),
                    )
                    for i in items
                ],
            ),
        )
        if items
        else h('<p class="muted">{}</p>', m("data.none"))
    )
    legend = h(
        '<details class="legend"><summary>{}</summary><dl>{}</dl></details>',
        m("data.legend"),
        cat(
            h("<dt>{}</dt><dd>{}</dd>", item_state(s, m), m(f"item.{s}.next", name="…", label="…"))
            for s in (
                "READY",
                "PARTIAL",
                "PROCESSING",
                "NEEDS_REVIEW",
                "DUPLICATE",
                "BLOCKED",
                "FAILED",
            )
        ),
    )
    body = h(
        '<h1>{}</h1><p class="lede">{}</p>{}{}{}{}<h2>{}</h2>{}{}',
        m("data.title"),
        m("data.lede"),
        _project_picker(m, "/data", projects, project.project_id, m("data.switch"))
        if len(projects) > 1
        else Html(""),
        h('<p class="box error">{}</p>', error) if error else Html(""),
        result,
        form,
        m("data.list"),
        table,
        legend,
    )
    return page(m("data.title"), body, chrome=chrome)


# -- research history ---------------------------------------------------------------------------


def episodes_page(
    chrome: Chrome, *, episodes: Sequence[EpisodeRow], projects: Mapping[str, str]
) -> bytes:
    m = chrome.m
    if episodes:
        listing = h(
            '<div class="scroll"><table><thead><tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th>'
            "<th>{}</th></tr></thead><tbody>{}</tbody></table></div>{}",
            m("eps.col.question"),
            m("eps.col.project"),
            m("eps.col.state"),
            m("eps.col.runs"),
            m("eps.col.started"),
            cat(
                h(
                    '<tr><td><a href="/episodes/{}">{}</a></td><td>{}</td><td>{}</td><td>{}</td>'
                    "<td>{}</td></tr>",
                    ep.episode_id,
                    ep.goal,
                    projects.get(ep.project_id, ep.project_id),
                    episode_state(ep.state, m),
                    ep.runs,
                    when(ep.start_time),
                )
                for ep in episodes
            ),
            _tech(
                m,
                [
                    (
                        ep.goal[:60],
                        f"{ep.episode_id} project={ep.project_id} state={ep.state} "
                        f"outcome={ep.outcome_status or '-'} reason={ep.suspend_reason or '-'}",
                    )
                    for ep in episodes
                ],
            ),
        )
    else:
        listing = h(
            '<p class="muted">{}</p><p><a class="button" href="/runs/new">{}</a></p>',
            m("eps.none"),
            m("home.start"),
        )
    body = h('<h1>{}</h1><p class="lede">{}</p>{}', m("eps.title"), m("eps.lede"), listing)
    return page(m("eps.title"), body, chrome=chrome)


# -- new research: question, project, data, new files, sources -> confirm -> start ---------------


@dataclass(frozen=True)
class Draft:
    """What the researcher has entered so far -- kept across a project switch and a refusal, so
    nothing typed is lost. Files cannot be kept by a browser form; they are chosen again."""

    goal: str = ""
    sensitivity: str = ""
    symptom: str = ""
    expected: str = ""
    observed: str = ""
    #: artifact id -> material kind key, as ticked
    chosen: Mapping[str, str] = field(default_factory=dict)
    literature_query: str = ""
    literature_public: bool = False


def _steps(m: Messages, current: int) -> Html:
    return h(
        '<ol class="steps">{}</ol>',
        cat(
            h(
                "<li{}>{}. {}</li>",
                Html(' class="done"' if n < current else (' class="here"' if n == current else "")),
                n,
                m(f"new.step.{n}"),
            )
            for n in range(1, 8)
        ),
    )


def _data_table(m: Messages, usable: Sequence[UsableData], chosen: Mapping[str, str]) -> Html:
    return h(
        '<p class="hint">{}</p><div class="scroll"><table><thead><tr><th>{}</th><th>{}</th>'
        "<th>{}</th><th>{}</th><th>{}</th></tr></thead><tbody>{}</tbody></table></div>{}",
        m("new.data.hint"),
        m("new.data.use"),
        m("data.col.file"),
        m("new.data.kind"),
        m("data.col.sensitivity"),
        m("eps.col.state"),
        cat(
            h(
                '<tr><td><input type="checkbox" name="use" value="{}" id="use-{}"{}></td>'
                '<td><label class="inline" for="use-{}">{}</label>'
                '<div class="purpose">{}</div></td>'
                '<td><select name="kind:{}" aria-label="{}">{}{}</select></td>'
                "<td>{}</td><td>{}</td></tr>",
                u.artifact_id,
                u.item_id,
                Html(" checked" if u.artifact_id in chosen else ""),
                u.item_id,
                u.name,
                m("data.passages", n=u.evidence_units),
                u.artifact_id,
                m("new.data.kind"),
                h('<option value="">{}</option>', m("new.data.pick_kind"))
                if u.declared_kind is None and u.artifact_id not in chosen
                else Html(""),
                cat(
                    h(
                        '<option value="{}"{}>{}</option>',
                        key,
                        Html(
                            " selected"
                            if chosen.get(u.artifact_id, "") == key
                            or (u.artifact_id not in chosen and u.declared_kind == trust)
                            else ""
                        ),
                        m(f"kind.{key}"),
                    )
                    for key, trust in MATERIAL_KINDS.items()
                ),
                sensitivity_name(u.sensitivity, m),
                item_state(u.state.value, m),
            )
            for u in usable
        ),
        _tech(m, [(u.name, f"{u.artifact_id} ({u.item_id})") for u in usable]),
    )


def new_research_page(
    chrome: Chrome,
    *,
    projects: Sequence[ProjectRow],
    project: ProjectRow | None,
    usable: Sequence[UsableData],
    sensitivities: Sequence[str],
    cleared: frozenset[str],
    reasoner: Html,
    draft: Draft | None = None,
    error: str | None = None,
) -> bytes:
    m = chrome.m
    if project is None:
        return _no_projects(chrome, "new.title")
    draft = draft or Draft()
    data = (
        _data_table(m, usable, draft.chosen)
        if usable
        else h('<p class="box notice">{}</p>', m("new.data.none"))
    )
    switch = (
        h(
            '<select name="switch_to" aria-label="{}">{}</select> '
            '<button class="small" type="submit" formaction="/runs/new" formnovalidate>{}</button>'
            '<div class="hint">{}</div>',
            m("new.project"),
            _project_options(projects, project.project_id),
            m("new.switch"),
            m("new.switch.hint"),
        )
        if len(projects) > 1
        else Html("")
    )
    body = h(
        '<h1>{}</h1><p class="lede">{}</p>{}{}'
        '<form method="post" action="/runs/review" enctype="multipart/form-data">'
        '<input type="hidden" name="csrf" value="{}">'
        '<input type="hidden" name="project" value="{}">'
        # 1. the question
        '<fieldset><legend><span class="step">1</span>{}</legend>'
        '<label for="goal">{} <span class="hint">{}</span></label>'
        '<textarea id="goal" name="goal" required>{}</textarea>'
        '<p><strong>{}</strong> <span class="hint">{}</span></p>{}'
        "<details{}><summary>{}</summary>"
        '<label for="symptom">{}</label><input type="text" id="symptom" name="symptom" value="{}">'
        '<label for="expected">{}</label>'
        '<input type="text" id="expected" name="expected" value="{}">'
        '<label for="observed">{}</label>'
        '<input type="text" id="observed" name="observed" value="{}">'
        "</details></fieldset>"
        # 2. the project
        '<fieldset><legend><span class="step">2</span>{}</legend>'
        "<p><strong>{}</strong></p>{}</fieldset>"
        # 3. existing data
        '<fieldset><legend><span class="step">3</span>{}</legend>{}</fieldset>'
        # 4. new files
        '<fieldset><legend><span class="step">4</span>{}</legend><p class="hint">{}</p>'
        '<label for="files">{}</label><input type="file" id="files" name="files" multiple>'
        "<p><strong>{}</strong></p>{}<p><strong>{}</strong></p>{}</fieldset>"
        # 5. external sources
        '<fieldset><legend><span class="step">5</span>{}</legend><p class="hint">{}</p>'
        '<label for="corpus">{} <span class="hint">{}</span></label>'
        '<input type="file" id="corpus" name="literature_corpus">'
        '<label for="query">{}</label>'
        '<input type="text" id="query" name="literature_query" value="{}">'
        '<label class="check"><input type="checkbox" name="literature_query_public" value="yes"{}>'
        " {}</label>"
        '<label for="verification">{} <span class="hint">{}</span></label>'
        '<input type="file" id="verification" name="verification_input"></fieldset>'
        '<div class="box">{}</div>'
        '<p><button type="submit" class="primary">{}</button> <span class="hint">{}</span></p>'
        "</form>",
        m("new.title"),
        m("new.lede"),
        _steps(m, 1),
        h('<p class="box error">{}</p>', error) if error else Html(""),
        chrome.csrf or "",
        project.project_id,
        m("new.step.1"),
        m("new.goal"),
        m("new.goal.hint"),
        draft.goal,
        m("new.goal.sensitivity"),
        m("new.goal.sensitivity.hint"),
        sensitivity_choices(m, sensitivities, "sensitivity", chosen=draft.sensitivity),
        Html(" open" if draft.symptom or draft.expected or draft.observed else ""),
        m("new.framing"),
        m("new.symptom"),
        draft.symptom,
        m("new.expected"),
        draft.expected,
        m("new.observed"),
        draft.observed,
        m("new.step.2"),
        project.name,
        switch,
        m("new.step.3"),
        data,
        m("new.step.4"),
        m("new.files.hint"),
        m("new.files"),
        m("data.kind"),
        _choices(
            "files_kind",
            [(k, m(f"kind.{k}"), m(f"kind.{k}.hint")) for k in MATERIAL_KINDS],
            required=False,
        ),
        m("data.sensitivity"),
        sensitivity_choices(m, sensitivities, "files_sensitivity", required=False, cleared=cleared),
        m("new.step.5"),
        m("new.sources.hint"),
        m("new.corpus"),
        m("new.corpus.hint"),
        m("new.query"),
        draft.literature_query,
        Html(" checked" if draft.literature_public else ""),
        m("new.query.public"),
        m("new.verification"),
        m("new.verification.hint"),
        reasoner,
        m("new.next"),
        m("new.next.hint"),
    )
    return page(m("new.title"), body, chrome=chrome)


@dataclass(frozen=True)
class Selected:
    """One item the research will use, as the confirmation page states it."""

    artifact_id: str
    name: str
    kind: str
    sensitivity: str | None
    state: str
    new: bool
    #: For a new upload that turned out to be the same content as data already in the project.
    same_as: str | None = None


@dataclass(frozen=True)
class Carried:
    """A file the confirmation carries to the start, as the bytes the researcher sent."""

    name: str
    size: int
    encoded: str


def review_page(
    chrome: Chrome,
    *,
    project: ProjectRow,
    draft: Draft,
    selected: Sequence[Selected],
    added: Sequence[DataItem],
    excluded: Sequence[DataItem],
    literature: Carried | None,
    verification: Carried | None,
    reasoner: Html,
    egress: Html,
    simulation: str,
) -> bytes:
    m = chrome.m
    names = {i.item_id: i.name for i in added}
    notices = Html("")
    if added:
        notices = h(
            '<div class="box notice"><p>{}</p><ul>{}</ul></div>',
            m("rv.added", n=len(added)),
            cat(h("<li>{} {}</li>", i.name, item_state(i.state.value, m)) for i in added),
        )
    if excluded:
        notices = h(
            '{}<div class="box warn"><p>{}</p><ul>{}</ul></div>',
            notices,
            m("rv.excluded"),
            cat(
                h(
                    "<li>{} {} -- {}</li>",
                    i.name,
                    item_state(i.state.value, m),
                    _next_for(i, names, m),
                )
                for i in excluded
            ),
        )
    data = (
        h(
            "<ul>{}</ul>",
            cat(
                h(
                    "<li><strong>{}</strong>{} -- {}, {} {}{}</li>",
                    s.name,
                    h(' <span class="state state-READY">{}</span>', m("rv.new")) if s.new else "",
                    m(f"kind.{s.kind}"),
                    sensitivity_name(s.sensitivity, m),
                    item_state(s.state, m),
                    h('<div class="purpose">{}</div>', m("rv.same_as", name=s.same_as))
                    if s.same_as
                    else "",
                )
                for s in selected
            ),
        )
        if selected
        else h('<p class="box warn">{}</p>', m("rv.data.none"))
    )
    hidden = cat(
        (
            h('<input type="hidden" name="csrf" value="{}">', chrome.csrf or ""),
            h('<input type="hidden" name="project" value="{}">', project.project_id),
            h('<input type="hidden" name="goal" value="{}">', draft.goal),
            h('<input type="hidden" name="sensitivity" value="{}">', draft.sensitivity),
            *(
                h('<input type="hidden" name="{}" value="{}">', k, v)
                for k, v in (
                    ("symptom", draft.symptom),
                    ("expected", draft.expected),
                    ("observed", draft.observed),
                )
                if v
            ),
            *(
                h(
                    '<input type="hidden" name="use" value="{}">'
                    '<input type="hidden" name="kind:{}" value="{}">',
                    s.artifact_id,
                    s.artifact_id,
                    s.kind,
                )
                for s in selected
            ),
            *(
                (
                    h(
                        '<input type="hidden" name="literature_corpus_name" value="{}">',
                        literature.name,
                    ),
                    h(
                        '<input type="hidden" name="literature_corpus_b64" value="{}">',
                        literature.encoded,
                    ),
                    h(
                        '<input type="hidden" name="literature_query" value="{}">',
                        draft.literature_query,
                    ),
                    h('<input type="hidden" name="literature_query_public" value="yes">'),
                )
                if literature is not None
                else ()
            ),
            *(
                (
                    h(
                        '<input type="hidden" name="verification_name" value="{}">',
                        verification.name,
                    ),
                    h(
                        '<input type="hidden" name="verification_b64" value="{}">',
                        verification.encoded,
                    ),
                )
                if verification is not None
                else ()
            ),
        )
    )
    background = (
        h(
            "<tr><th>{}</th><td>{}</td></tr>",
            m("rv.background"),
            cat(
                h("<div>{}: {}</div>", m(f"new.{k}"), v)
                for k, v in (
                    ("symptom", draft.symptom),
                    ("expected", draft.expected),
                    ("observed", draft.observed),
                )
                if v
            ),
        )
        if draft.symptom or draft.expected or draft.observed
        else Html("")
    )
    sources = (
        h(
            "{}",
            m("rv.literature", name=literature.name, query=draft.literature_query),
        )
        if literature is not None
        else h("{}", m("rv.sources.none"))
    )
    verification_line = (
        h("{} ({})", verification.name, m("rv.bytes", n=verification.size))
        if verification is not None
        else h("{}", m("rv.verification.none"))
    )
    summary = h(
        '<div class="card"><h2>{}</h2><table class="summary"><tbody>'
        "<tr><th>{}</th><td><strong>{}</strong></td></tr><tr><th>{}</th><td>{}</td></tr>"
        "<tr><th>{}</th><td>{}</td></tr><tr><th>{}</th><td>{}</td></tr>{}"
        "<tr><th>{}</th><td>{}</td></tr><tr><th>{}</th><td>{}</td></tr>"
        '<tr><th>{}</th><td>{}<div class="purpose">{}</div></td></tr>'
        "<tr><th>{}</th><td>{}</td></tr></tbody></table>{}</div>",
        m("rv.will_use"),
        m("rv.question"),
        draft.goal,
        m("rv.question_label"),
        sensitivity_name(draft.sensitivity, m),
        m("rv.project"),
        project.name,
        m("rv.data", n=len(selected)),
        data,
        background,
        m("rv.sources"),
        sources,
        m("rv.verification"),
        verification_line,
        m("rv.ai"),
        reasoner,
        egress,
        m("rv.sim"),
        simulation,
        _tech(
            m,
            [("project", project.project_id), ("sensitivity", draft.sensitivity)]
            + [(s.name, f"{s.artifact_id} as {s.kind}") for s in selected],
        ),
    )
    back = f"/runs/new?project={project.project_id}"
    body = h(
        '<h1>{}</h1><p class="lede">{}</p>{}{}{}'
        '<form method="post" action="/runs" enctype="multipart/form-data">{}'
        '<p class="actions"><button type="submit" class="primary">{}</button> '
        '<a href="{}">{}</a></p></form>',
        m("rv.title"),
        m("rv.lede"),
        _steps(m, 6),
        notices,
        summary,
        hidden,
        m("rv.start"),
        back,
        m("rv.back"),
    )
    return page(m("rv.title"), body, chrome=chrome)


# -- system status ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    """One row of the system status: what, its state (ok | problem | missing | limit), and what
    it means for the researcher -- the raw facts in the technical details."""

    name: str
    state: str
    detail: Html
    technical: str = ""


def status_page(
    chrome: Chrome,
    *,
    parts: Sequence[Part],
    capabilities: Capabilities,
    egress: Sequence[tuple[str, str, str]],
    admin: bool,
) -> bytes:
    m = chrome.m
    badge = {"ok": "READY", "problem": "FAILED", "missing": "UNBOUND", "limit": "WAITING"}
    rows = cat(
        h(
            '<tr><td><strong>{}</strong></td><td><span class="state state-{}">{}</span></td>'
            "<td>{}</td></tr>",
            p.name,
            badge[p.state],
            m(f"st.{p.state}"),
            p.detail,
        )
        for p in parts
    )
    recheck = (
        h(
            '<form method="post" action="/status/check" class="inline">'
            '<input type="hidden" name="csrf" value="{}"><button class="small" type="submit">{}'
            '</button></form> <span class="hint">{}</span>',
            chrome.csrf or "",
            m("st.recheck"),
            m("st.recheck.hint"),
        )
        if admin
        else Html("")
    )
    kinds: dict[str, list[str]] = {}
    for cap, kind, _why, _needs in capabilities.blocked:
        kinds.setdefault(kind, []).append(cap)
    blocked = (
        h(
            '<div class="card"><h2>{}</h2><p>{}</p><ul>{}</ul>{}</div>',
            m("st.blocked"),
            m("st.blocked.lede"),
            cat(
                h(
                    '<li>{}<div class="purpose">{}</div></li>',
                    m("st.blocked.sim", n=len(caps))
                    if kind == "SIMULATION"
                    else m("st.blocked.other", n=len(caps), kind=kind),
                    m("st.blocked.sim.needs") if kind == "SIMULATION" else "",
                )
                for kind, caps in sorted(kinds.items())
            ),
            _tech(
                m,
                [(k, v) for k, v in sorted(capabilities.backends.items())]
                + [
                    (cap, f"{kind} UNAVAILABLE: {why} -- needs: {needs}")
                    for cap, kind, why, needs in capabilities.blocked
                ],
            ),
        )
        if capabilities.blocked
        else Html("")
    )
    egress_card = h(
        '<div class="card"><h2>{}</h2><ul>{}</ul></div>',
        m("st.egress"),
        cat(
            h(
                '<li>{}: {} <a href="/projects/{}/egress">{}</a></li>',
                name,
                status,
                project_id,
                m("eg.link"),
            )
            for project_id, name, status in egress
        ),
    )
    body = h(
        '<h1>{}</h1><p class="lede">{}</p><div class="scroll"><table class="status"><thead><tr>'
        "<th>{}</th><th>{}</th><th>{}</th></tr></thead><tbody>{}</tbody></table></div><p>{}</p>"
        "{}{}{}",
        m("st.title"),
        m("st.lede"),
        m("st.col.part"),
        m("st.col.state"),
        m("st.col.detail"),
        rows,
        recheck,
        blocked,
        egress_card,
        _tech(m, [(p.name, p.technical) for p in parts if p.technical]),
    )
    return page(m("st.title"), body, chrome=chrome)


def status_when(value: dt.datetime | None) -> str:
    return when_text(value) if value is not None else "-"


__all__ = [
    "AiStatus",
    "Capabilities",
    "Carried",
    "DataCounts",
    "Draft",
    "Part",
    "Selected",
    "data_page",
    "episode_state",
    "episodes_page",
    "home_page",
    "item_state",
    "kind_key",
    "kind_name",
    "new_research_page",
    "review_page",
    "sensitivity_name",
    "status_page",
    "status_when",
]
