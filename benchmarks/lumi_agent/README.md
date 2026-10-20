# Lumi Agent blind benchmark (v1)

Can Laboratory Innovation Brain reason independently about a real research problem, rather than
reproduce a method it has already seen? The target is

> *Lumi Agent: Autonomous Lumerical FDTD Simulation for Photonic Waveguide Experiments*,
> GLSVLSI '26, pp. 253-258, DOI [10.1145/3787109.3816402](https://doi.org/10.1145/3787109.3816402)
> (published 2026-06-22, CC BY 4.0; authors per Crossref in `holdout.json`).

**Status: PREPARED.** Phase A and Phase B are done. Phase C (the blind run) has NOT been performed:
it needs the reasoning routes the researcher binds. Phase D (reveal and compare) has NOT been
performed. No result below is a benchmark result.

## Files

| File | What it is |
|---|---|
| `holdout.json` | the target, the holdout rule, the temporal cutoff (2026-03-23), the exclusion list, and the **preparer's exposure** -- what the preparing agent saw of the answer while identifying the target, and the mitigations |
| `problem_statement.md` | Phase A: the ONLY target-derived text the system receives -- problem, motivation, constraints, success criteria, and the question. No method, architecture, experiment or result |
| `bootstrap_corpus.py` | Phase B: the fixed queries (logged before any result was read) and the fixed selection rule |
| `search_log.json` | every query, its reason, URL, retrieval time, snapshot and SHA-256, what it selected and what it excluded and why |
| `snapshots/` | the raw provider responses (OpenAlex, GitHub) the corpus was built from, gzip-compressed; each SHA-256 in the log is of the uncompressed response |
| `v1/` | the superseded rule-v1 run, whole (see Phase B) |
| `freeze.sh` | Phase C step 7: freezes the run's report, recorded report and inference provenance with SHA-256 |
| `corpus.json` | the reasoning corpus in the product's literature-corpus format: each passage is a work's own abstract, with DOI, version, licence, peer-review status and retraction status |
| `technical_prior_art.json`, `technical_prior_art.md` | public repositories created before the cutoff -- TECHNICAL artefacts, never peer-reviewed evidence; the `.md` is the optional note upload |

## Phase A -- problem extraction (done)

Each sentence of `problem_statement.md` and its basis:

| Sentence (abridged) | Basis |
|---|---|
| waveguide experiments are designed and checked with FDTD in Lumerical | title; the abstract's problem framing |
| a researcher states the intent in natural language | the abstract's problem framing ("natural-language requests") |
| turning intent into an executable program and a physically meaningful setup is the step to solve | the abstract's problem framing |
| difficult for general-purpose language models | the abstract's problem framing |
| the scripting/Python interface is proprietary, little public data | the abstract's problem framing (the second clause is the operator's plain reading of "proprietary") |
| setup quality depends on judgment about geometry, materials, sources, monitors, mesh, outputs | the abstract's problem framing |
| licensed software; every run costs compute time | general domain knowledge of the benchmark operator, not the target |
| running is not sufficient; the setup must be physically meaningful | the abstract's problem framing |
| success: executes; physically meaningful; outputs interpreted correctly | the abstract's problem framing, restated as criteria |
| the question | the operator's restatement of the above |

Left out on purpose: every statement of how the target solves it, what it evaluates, and what it
found (see `holdout.json`, `preparer_exposure`, for what the preparer nonetheless saw).

## Phase B -- the corpus (done)

`python benchmarks/lumi_agent/bootstrap_corpus.py`. Peer-reviewed and preprint works from OpenAlex
published before 2026-03-23, selected by a fixed rule from queries derived from the problem statement
or deliberately searching for contrasting and contradicting approaches (optimisation-based inverse
design, learned surrogates, conventional scripted automation, evidence of unreliable generated code
and of failing multi-step model automation, verification of EM simulations). GitHub repositories are
kept apart as technical prior art.

**Result (rule v2): 54 works -- 43 peer-reviewed, 11 preprints -- 290 abstract passages, published
2005-08 to 2026-02; 2 repositories.** No work shares an author with the target; none is on or after
the cutoff. It holds genuine pre-cutoff prior art close to the problem (language-model benchmarks
and agents for photonic-circuit design, self-correcting language-model frameworks for physics and CFD
simulation, natural-language-to-simulation representations) and contrasting work (FDTD inverse
design, learned surrogates, hallucination in generated code, limits of model planning). Phase D must
weigh any "rediscovery" against what this corpus already said.

**Rule v1 was superseded, and kept** (`v1/`): full-text relevance alone returned mostly highly cited,
off-topic works and nothing from the language-model era. Rule v2 (title-and-abstract search, per-query
required terms and a 2021 lower bound for language-model queries, all fixed in the script before its
results were read) replaced it. Queries D01, D05 and D08 returned nothing under v2; the log records it.

Limitations, stated before any run:

- **Abstracts only.** The evidence text is each work's abstract; no full text was read or stored.
  Rights: the licence OpenAlex reports is recorded and the product's retention policy applies (an
  unknown licence keeps a bounded excerpt).
- **Selection is lexical and bounded**: the provider's relevance order, four works per query.
  Relevant work that no query surfaced is absent; the log makes every gap checkable.
- **Peer-review status is the provider's venue type**, not a verification of peer review.
- **Technical documentation is not in the corpus.** The product's literature connector locates
  passages by DOI; vendor documentation and repositories have none. Repositories enter only as an
  optional, clearly labelled note (the product classes an uploaded note EXPERT_HEURISTIC).
- **A run admits at most three passages** of the corpus: the product snapshots and admits the top
  three passages matching the query the researcher declares PUBLIC (`LiteratureRequest`,
  `max_passages=3`). The corpus is the pool; the product's own retrieval chooses. A connector check
  with the planned query (below) ranks first two passages of a natural-language-to-CFD-simulation
  preprint and one of an LLM-for-CAD preprint: the run's external evidence will be narrow. The query
  was not tuned after that check -- tuning it to what it retrieves would be the preparer choosing
  the evidence.
- Some works appear twice (a preprint and its published version, under two DOIs), and some
  off-topic works passed the fixed rule (notably under C07); both are left as the rule produced them.

## The finding that bears on validity -- read before Phase C

The only product vertical installed is the Silicon Photonics **series-resistance anomaly** diagnosis
vertical (`domains/silicon_photonics/product.py`). Its debate asks for at least as many competing
hypotheses as that pack's mechanism catalog holds (five), and every hypothesis must predict an
outcome in the pack's declared outcome spaces -- which describe Rs and its bias dependence. Its
verification plans need the pack's device-project input. The Lumi Agent problem (turning simulation
intent into working FDTD simulations) is outside that representation.

A dry run on a scratch database with the catalog reasoner and a generic phrasing of the problem (not
the target's text) confirmed what the code implies: the report is honest -- result `NOT_REACHED`,
verification SKIPPED for want of an input, and the debate refused with `CRITIQUE_ROUTE_UNCHANGED`
(with one short document and no distinct critic model, the Critic cannot be independent, §7.6). With
language models bound, the hypothesis engine would be asked to express FDTD-automation approaches as
predictions over Rs outcome spaces.

So a Phase C run through the existing workflow can test honesty and fail-closed behaviour on an
out-of-scope problem; it cannot fairly test whether the system can reason about this problem. Doing
that needs a product vertical whose hypothesis and outcome spaces can represent research-method and
software-workflow questions -- an architectural addition that was not made here (no expansion while
closing P0/P1, and designing it after seeing the target would itself risk contaminating the
benchmark). **The researcher should decide** between running as-is (documenting the limit) and first
commissioning such a vertical from someone who has not seen the target.

## Phase C -- the blind run (NOT performed; the researcher's steps)

Prepared in the running deployment: project `prj:lumi-blind` (RESEARCH mode), the researcher a
member with clearance PUBLIC and the `LLM_EGRESS` scope.

1. **LLM settings -> Add a connection**: your API provider, reach EXTERNAL, credential "an
   environment variable of this workspace" naming the variable you put in
   `deployment/docker/llm-keys.env` (then `docker compose up -d --force-recreate web`).
2. **Fetch models**; open each model you want -> **Test** -> **Lock**.
3. **Runtimes -> local-first** (the draft the deployment prepared): bind REASONING_PRIMARY to your
   reasoning model, and REASONING_ADVERSARIAL to a DIFFERENT model (otherwise the Critic falls back
   to the primary and the page says it is not independent). Bind FAST_UTILITY to one of the two
   local models that proved its requirements -- `qwen2.5:7b` or `qwen2.5-coder:7b` (nothing
   measured separates them, so the deployment did not choose).
4. **Check readiness now**; when it says ready, **Activate**.
5. **Runtime -> prj:lumi-blind -> External-model egress**: approve your connection for `PUBLIC`.
6. **New research run**: project `prj:lumi-blind`; goal = the Question of `problem_statement.md`;
   note = `problem_statement.md` (optionally also `technical_prior_art.md`); literature corpus =
   `corpus.json`; literature query = `language models generate executable physically meaningful
   FDTD simulation from natural language for photonic waveguides`, ticked as PUBLIC;
   classification PUBLIC; no verification input.
7. **Freeze before reading anything of the target**: save the report's Markdown export and the
   recorded report (`research_run_reports`) into `frozen/` with their SHA-256 and the episode, run
   and runtime ids; commit. Only then begin Phase D.

## Phase D -- reveal and compare (NOT performed)

Read the full target (CC BY 4.0) only after the freeze commit. Compare on explicit dimensions --
problem coverage, autonomy, scientific reasoning structure, FDTD workflow integration, verification
strategy, robustness and failure handling, reproducibility, provenance, human oversight,
extensibility, cost and operational complexity -- and sort every idea into: (1) independently
rediscovered, (2) materially different, (3) only in Lumi Agent, (4) only in Laboratory Brain.
Weigh (1) against the preparer's exposure and against what the corpus and the technical prior art
already contained. A conceptual or architectural advantage is labelled as such; nothing is claimed
experimentally superior without evidence that demonstrates it.
