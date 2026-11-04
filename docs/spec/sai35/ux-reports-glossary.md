# SAI 3.5 — Appendix F: Researcher experience, reports and bilingual glossary

Version: `3.5.0-master-candidate.2`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative for report content (§2), workspace content (§1) and terms (§3). Refines
S35-RPT-001–004 of [SAI 3.5](../SAI_3.5.md). Inherited: SAI 3.4 ASM-016 (bilingual scientific
content, canonical records never overwritten), SAI 3.3 UX-001–007 (MessageCatalog, error classes,
derived system health).

## 1. Researcher workspace

All views exist in zh-TW and en with the same identifiers, numbers, units and states.

| View | Shows | Actions (each a recorded ReviewItem resolution) |
|---|---|---|
| Campaign list | campaigns with state, stage, autonomy level, envelope, budget used versus ceiling, open anomalies | open; Owner stop |
| Campaign detail | lifecycle stages with checkpoints and skip reasons; every hypothesis and claim with its epistemic stage and claim state, every other record with its own state; distinguishability verdicts and certified diversity bounds with experiment-set version; the three termination dimensions; registrations; FeedbackRecords; reframings with failed hypotheses | accept a problem (outside an envelope); request a report |
| Authorization inbox | registrations awaiting a signed authorization; Owner-gate requests; ReviewItems with the exact gap and at most two options | sign or refuse with rationale |
| Envelope page | active envelopes, bounds, autonomy level, consumption against ceilings, expiry | Owner revoke; propose a new envelope (needs an Owner decision) |
| Anomaly registry | every anomaly with state history and evidence | flag a new anomaly |
| Report view | the report of §2 and its bundle | export (every provided format, both languages) |

Display rules: nothing not passed is shown as verified or in a success style; `UNKNOWN`,
`NOT_PERFORMED`, `INSUFFICIENT_VALIDATION`, `STOPPED`, `ACCOMMODATED` and
`PROVISIONALLY_EXPLAINED` are shown as such; no uncalibrated probability is shown; state names and
identifiers are never translated; error text comes from the versioned MessageCatalog with one of the
five SAI 3.3 error classes (S35-RPT-004).

## 2. Report structure

Each campaign report has the same sections in both languages. Section content is derived from
canonical records; a translation is a derived presentation bound to the canonical record hash
(ASM-016).

| § | Section | Content | Requirement |
|---|---|---|---|
| 1 | Summary | outcome state of the campaign, strongest claim and its stage, what was not established | S35-RPT-001 |
| 2 | Problem | the ResearchProblem, its origin and provenance, valuation | S35-PROB-001, S35-PROB-002 |
| 3 | Hypotheses | every hypothesis and idea with epistemic stage, claim state, mechanism, predictions and falsifier | S35-HYP-001–003 |
| 4 | Mechanism distinguishability | experiment-set version, threshold, every pair verdict, aliases, `UNRESOLVED` pairs, certified diversity lower and upper bounds, adequacy results, never-considered families | S35-MECH-001, S35-MECH-002 |
| 5 | Experiments | selections with their rationale, registrations (envelope or signed), sweeps, Runs | S35-SEL-001, S35-REG-001 |
| 6 | Observations | admitted observations with conditions; simulated outputs labelled as model outputs | S35-EVI-001, S35-VAL-001 |
| 7 | Interpretations | relation judgments, kept separate from observations | ASM-016 |
| 8 | Uncertainty | per source: numerical, input parameters, measurement or reference, model form, extraction, mapping | S35-VAL-003 |
| 9 | Conclusions and outcomes | stage-3 claims only as conclusions, with their Causal Warrant Gate decision; stage-2 outcomes (CONTRADICTED, INCONCLUSIVE) as test results | S35-CWG-001 |
| 10 | Novelty | novelty class with prior-art coverage scope and model cutoffs | S35-NOV-001, S35-NOV-002 |
| 11 | Anomalies | every anomaly and its state | S35-PROB-003 |
| 12 | Reframing and failures | every reframing with trigger and kind, every failed hypothesis with its last state | S35-REF-002 |
| 13 | Limitations | limitations, NOT_PERFORMED steps with reason and what is needed, contamination findings | ASM-016, G0-P |
| 14 | Cost | realized consumption against budgets and ceilings | S35-COST-001 |
| 15 | Stop reasons | StopRecord, if any | S35-LOOP-003 |
| 16 | Bundle | machine-verifiable bundle reference and environment manifest | S35-RPT-002 |

## 3. Bilingual glossary

Each English term has exactly one canonical zh-TW term (S35-RPT-003). State names, identifiers and
component names in code font stay in English in both languages.

| English term | zh-TW term | Meaning in this specification |
|---|---|---|
| autonomous AI scientist | 自主 AI 科學家 | the product target of §2 of SAI 3.5 |
| research campaign | 研究活動 | the unit of autonomous research on one problem ([Appendix A](lifecycle.md)) |
| research problem | 研究問題 | a ResearchProblem record with origin and provenance |
| anomaly | 異常 | an admitted observation no live hypothesis predicts |
| contradiction | 矛盾 | a typed Conflict between admitted evidence or with an admitted prediction |
| knowledge gap | 知識缺口 | a recorded absence that blocks a decision |
| exploratory idea | 探索性想法 | epistemic stage 1 |
| testable hypothesis | 可檢驗假說 | epistemic stage 2 |
| evidence-supported conclusion | 有證據支持的結論 | epistemic stage 3, only through the Causal Warrant Gate |
| hypothesis | 假說 | as SAI 3.3 §8.1 |
| prediction | 預測 | a typed Prediction bound to an OutcomeSpace |
| observation | 觀察 | admitted evidence, never inference |
| interpretation | 解釋 | a relation judgment about observations |
| uncertainty | 不確定度 | per-source uncertainty |
| conclusion | 結論 | a stage-3 claim |
| limitation | 限制 | what the result does not cover |
| export | 匯出 | a provided output format of a report |
| mechanism | 機制 | the physical or measurement-chain cause a hypothesis names |
| mechanism class | 機制類別 | hypotheses no available experiment can tell apart |
| distinguishable | 可區分的 | separated by an available experiment beyond the threshold |
| experiment set | 實驗集合 | the versioned set of experiments available to a campaign |
| effective search space | 有效搜尋空間 | the mechanism families actually considered |
| falsifiable | 可否證的 | has a typed CONTRADICTS prediction over a measurable observable |
| falsifier | 否證條件 | the observation that would contradict the hypothesis |
| Research Reframing | 研究重新框定 | a typed, append-only change of the research framing after failure |
| failure history | 失敗紀錄 | every failed hypothesis, assumption, observable and model, kept |
| competing explanations | 競爭解釋 | live hypotheses for the same observation |
| rival closure | 對手閉包 | registering and testing every declared rival of no greater complexity |
| discriminating experiment | 鑑別性實驗 | an experiment that converts a surviving pair to DISTINGUISHABLE |
| mechanism identity | 機制身分 | the content hash of a canonical forward-model declaration, never its name |
| alias | 別名 | a hypothesis whose mechanism identity equals one already held |
| certified distinguishable | 經認證可區分 | pair verdict DISTINGUISHABLE: separated for every parameter choice under E |
| unresolved pair | 未判定配對 | pair verdict UNRESOLVED: neither verdict can be certified |
| certified diversity | 經認證多樣性 | the largest number of held mechanisms pairwise certified distinguishable |
| catalog adequacy | 目錄充分性 | whether any held mechanism fits the admitted data under the pre-registered criterion |
| realized-cost checkpoint | 實際成本檢查點 | a frozen cumulative-cost level at which every arm's held answer is scored |
| operational termination | 作業性終止 | how a campaign ended (VALID or INVALID), not what it achieved |
| experimental completion | 實驗完成度 | NOT_PERFORMED, PARTIAL or COMPLETED |
| scientific acceptance | 科學接受 | NONE, PENDING_CAUSAL_WARRANT_GATE or ACCEPTED_DISCOVERY |
| prospective registration | 前瞻登記 | a registration made before the test's data exists |
| research envelope | 研究授權範圍 | an Owner-approved ResearchEnvelope with machine-checkable bounds |
| autonomy level | 自主等級 | AL0–AL4 of [Appendix E](governance-security.md) |
| Owner gate | Owner 關卡 | a recorded Owner authorization before money, license, physical experiment or publication |
| Causal Warrant Gate | 因果依據關卡 | the exclusive confirmation authority (V1.1) |
| confirmation | 確認 | a Causal Warrant Gate decision to CONFIRMED |
| signed review | 簽章審查 | a reviewer's signed answer under an enrolled key |
| physical model | 物理模型 | a model built from a PhysicalModelSpec |
| typed operation | 型別化操作 | an operation from the closed catalog of the model builder |
| model qualification | 模型資格化 | qualifying a model family before its outputs may discriminate |
| simulator worker | 模擬器工作節點 | an internal qualified worker running a licensed product |
| parameter sweep | 參數掃描 | a registered sweep, one Run per point |
| convergence study | 收斂研究 | the ASM-008 study per observable |
| uncertainty analysis | 不確定度分析 | per-source uncertainty with combination rules |
| model refinement | 模型細化 | bounded refinement under ASM-011 |
| independent physical validation | 獨立物理驗證 | validation on independent reference data |
| evidence admission | 證據准入 | the Artifact, Observation and Attestation admission path |
| provenance | 溯源紀錄 | inputs, producer, model call and policy behind a record |
| prior-art coverage | 先前技術覆蓋範圍 | the sources actually searched for a novelty statement |
| novelty class | 新穎性類別 | one of the classes of [Appendix D](provenance-novelty-independence.md) §3 |
| known-mechanism rediscovery | 已知機制再發現 | `KNOWN_MECHANISM_REDISCOVERY` |
| engineering optimization | 工程最佳化 | `ENGINEERING_OPTIMIZATION` |
| model correction | 模型修正 | `MODEL_CORRECTION` |
| new physical knowledge | 新物理知識 | `NEW_PHYSICAL_KNOWLEDGE` |
| contamination | 污染 | exposure of sealed answers or memorized material |
| independent evaluator | 獨立評估者 | the Owner-assigned evaluator who issues G-D verdicts |
| hidden world | 隱藏世界 | an evaluator-generated synthetic case with sealed truth |
| realized consumption | 實際消耗 | resources actually used, including failures and retries |
| true-cause discovery | 真因發現 | metric 1 of the comparison protocol |
| effective mechanism diversity | 有效機制多樣性 | metric 2 |
| discriminating-experiment efficiency | 鑑別實驗效率 | metric 3 |
| false discovery | 錯誤發現 | metric 4 |
| independent reproducibility | 獨立可重現性 | metric 5 |
| engineering validity | 工程有效性 | evidence that a rule is enforced in software |
| scientific validity | 科學有效性 | independent evidence that findings are true and hold up |
| external coding agent | 外部程式代理 | Codex, Claude Code or any similar development agent; never part of production |
