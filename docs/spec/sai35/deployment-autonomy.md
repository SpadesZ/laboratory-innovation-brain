# SAI 3.5 — Appendix G: Deployment architecture and production autonomy without external coding agents

Version: `3.5.0-master-candidate.3`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-AUTO-001–003 of [SAI 3.5](../SAI_3.5.md) and restates SAI 3.4
ASM-001 and G9 for discovery without weakening them. Nothing here has been tested.

## 1. Deployment topology

| Unit | Runs | Network | Notes |
|---|---|---|---|
| Web and API | ResearcherWorkspace, authenticated API | researchers (TB-1) | no developer tools |
| Control services | CampaignOrchestrator, GovernancePlane, CostGovernance, RegistrationRegistry, ReportGenerator | internal only | one service identity per component |
| Discovery services | ProblemDiscovery, HypothesisBrain, MechanismExplorer, ResearchReframing, NoveltyAuditor | model runtime and authorized source providers through the egress gate (TB-2) | read feedback records only |
| Validation services | VerificationPlanner, ValidationLoop, NumericalValidation, PhysicalValidation, ModelQualification, CausalWarrantGate | internal only | separate identities from the Discovery services |
| Model runtime | ScientificLLM and ModelRouter routes: local model servers declared free by the Owner, or approved external providers under budget | provider endpoints on the egress allowlist | typed proposals only; no shell, SDK passthrough or code execution |
| Simulator workers | PhysicalModelBuilder lowering, licensed Lumerical products | only the allowlisted license endpoint (TB-3) | per-job isolation (ASM-005) |
| PostgreSQL and artifact store | canonical records, artifacts | internal only | database rules hold the permission matrix (TB-5) |
| Evaluation plane | evaluator tools, sealed vault, hidden-world generator, scorer | separate host or account; outputs in, nothing out (TB-4) | not operated by the implementer |

The initial single-site deployment may co-locate the control, Discovery and Validation services in
one host, with separate identities, as long as the database rules hold; workers needing a license
are separate (SAI 3.4 architecture §1). Scaling decisions follow measured load (SAI 3.3 P20).

## 2. Development plane versus production

| Development plane | Production |
|---|---|
| developers, coding agents (Codex, Claude Code and similar), CI, test databases, fake SDKs | the units of §1 only |
| writes code, migrations, DomainPack payloads, operation catalogs, policies — through review and release | runs released images; cannot modify its code, catalogs or policies at run time |
| may call development endpoints | no route, credential or binary for any coding agent; development endpoints denied by the egress allowlist |

A new typed operation, model family, validator or policy reaches production only as a reviewed
release (S35-MOD-002). A production campaign that needs one stops with a ReviewItem (S35-AUTO-003);
it never waits for, or calls, a developer or a coding agent.

## 3. What production autonomy means

The complete production research workflow of [Appendix A](lifecycle.md) — problem discovery,
literature, idea generation, admission, selection, registration, model construction, licensed
execution, validation, admission, confirmation hand-over, feedback, reframing and reporting — runs
inside the deployment. Human involvement is limited to the recorded decisions SAI 3.3 §23.4, the
Owner gates and the Causal Warrant Gate's signed review require, each a ReviewItem resolution. A
model call is allowed through ScientificLLM and ModelRouter under egress, sensitivity and budget
gates; it returns typed proposals only.

## 4. Acceptance check (T-S35-AUTO-001, T-S35-AUTO-002, T-S35-AUTO-003)

### 4.1 Static deployment audit (T-S35-AUTO-002, deterministic, every release)

1. Build the release image set and the egress allowlist exactly as deployed.
2. Scan every image filesystem and package list against the maintained coding-agent denylist:
   executables, packages, configuration and session directories, credentials and environment
   variables of Codex, Claude Code and other coding agents named on the list.
3. Check the egress allowlist: no endpoint on the denylist; development endpoints absent.
4. Check write permissions: no research service identity can write the code, the operation
   catalog, policies or configuration.
5. Attach the audit report (image digests, denylist version, findings) to the release. Any finding
   fails the release.

### 4.2 Dynamic workflow check (T-S35-AUTO-001, empirical)

1. Environment: a deployment-equivalent installation of the release from §4.1 with coding-agent
   executables absent, their network endpoints blocked at the network layer, and process, network
   and repository audit logging on.
2. Cases: the frozen in-envelope case set (before licensing: without licensed simulation, each
   needed simulation reported as NOT_PERFORMED; under G9: with licensed simulation on qualified
   workers). Cases and expected envelopes are frozen before the run.
3. Start from a blank workspace per case; the only inputs are the case brief, the envelope and the
   authorized sources.
4. Run each campaign to a closed state.
5. Pass when: every campaign closes with a report in both languages; process, network and
   repository logs show zero coding-agent invocations; every attempt to reach a blocked endpoint is
   refused and logged; no file in the code or configuration changed; every human intervention is a
   recorded ReviewItem resolution with actor and time.
6. A campaign that needed a developer, a hand-written model, a manual database or manifest edit, or a
   prebuilt vendor project fails the check (as SAI 3.4 G9 states).

### 4.3 Out-of-envelope stop (T-S35-AUTO-003, deterministic)

Fixtures: an unknown model family, an unqualified product, a bound exceeded, a request needing a
new typed operation. Each must stop with a ReviewItem naming the exact gap and at most two options,
with no outbound connection to a development endpoint and no change to any envelope or catalog.

## 5. Status

S35-AUTO-001 and S35-AUTO-002 are **untested**: the product was not designed around coding agents,
but no audit or deployment-equivalent run exists. S35-AUTO-003 is proposed. The SAI 3.4 G9 gate and
these checks may share evidence; each issues its own result.
