# SPEC-ISSUE-017: whether a local model endpoint is free is a fact no client can observe

Severity: GATE
Status: OPEN
Blocks gate: M4
Raised: 2026-11-01
Raised by: G0 reliability closure (`g0-reliability-authenticity-closure`), audit residual "unmetered local proxy" (Owner decision A3)
Affected: `COST-001`, §14 (cost governance), migrations `011r`, `011t`, `011v`, `llm_runtime.spend`

## The gap

`COST-001` asks for a monetary ceiling on model use. A request to an endpoint on this machine may
still cost money: a LiteLLM-style proxy on localhost forwards to a paid provider, and the client
sees only `127.0.0.1`. Until `011v` a deployment with no ceiling sent such requests unmetered.

`011v` closes the path in the client (this machine is metered like any endpoint; with no guard a
request is refused unsent) and narrows the one exemption (an exact model per Owner declaration; a
declared-free endpoint that answers with a paid provider's billing signs loses the exemption). It
cannot decide the underlying fact: a proxy that strips every billing sign is indistinguishable from
a model server. The specification does not say who is allowed to assert "this endpoint is free",
how that assertion is reviewed or expires, or whether a free local model may be used at all
without a ceiling.

## Competing readings

- Reading A: a local endpoint is free by nature; `COST-001` governs remote providers only.
- Reading B: no endpoint is free unless the Owner says so, per model, and the Owner's declaration
  is the cost trust root (what `011v` implements).
- Reading C: as B, and a declaration also expires (for example 90 days) and must name the model
  digest the server reports, so a swapped model behind the same name is metered again.

## Provisional implementation

Reading B. `011v`: no wildcard declarations (and old `*` rows count for nothing), paid-proxy
evidence withdraws a declaration until the Owner renews it, the retired
`LAB_BRAIN_LLM_SPEND_METER_LOCAL` switch is not read. The Owner's declaration is the trust root.

## What needs an Owner / maintainer decision

1. Accept Reading B (or C) as the cost-governance rule for local endpoints.
2. Whether declarations expire, and whether they must bind the served model digest.
3. Who may declare (today: members of `lab_brain_spend_admin`).
