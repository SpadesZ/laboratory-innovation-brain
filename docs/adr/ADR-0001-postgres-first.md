# ADR-0001: PostgreSQL + JSONB + pgvector as the single v1 store

Status: Accepted
Date: 2026-09-12
Affected Requirements: SYS-001, EVI-005, EVI-007
Human Approval Required: No (records a decision already fixed by SAI 3.3 §6.6)

## Context

The system needs entity storage, relation traversal, versioned conditions and vector
retrieval. The tempting v1 shape is a polyglot stack: Postgres for entities, a graph
database for relations, a vector database for embeddings. Each additional store
multiplies migration, backup, consistency and provenance surface before a single
research episode has run end to end.

## Constraints

- P20 Scale by evidence: architecture upgrades are triggered by measured load, not by
  projected node counts.
- §6.6 fixes PostgreSQL + JSONB + pgvector as the single source of truth for v1 and
  explicitly refuses a fixed node-count threshold for migrating to a graph database.
- Cognition and retrieval may only depend on the `GraphRepository` contract (§17.12).

## Options Considered

1. **Postgres only** — one store, one transaction boundary, one backup story.
   Multi-hop traversal is recursive SQL, which is more verbose than Cypher.
2. **Postgres + graph DB from day one** — better traversal ergonomics, at the cost of
   two-store consistency and dual provenance paths before any workload justifies it.
3. **Postgres + vector DB** — same objection; pgvector already covers v1 recall needs.

## Decision

Option 1. PostgreSQL is the only store. Relations live in relation tables; traversal is
recursive SQL behind `GraphRepository`. Embeddings use pgvector.

Migration to a graph backend is gated on a **measured traversal workload**, not a node
count. Any future backend must first pass relation-semantics, provenance-trace,
transaction-consistency and regression tests (§17.12) before cutover.

The abstraction lowers replacement cost. It does not make replacement free, and this ADR
does not claim it does.

## Consequences

- Positive: one transaction boundary, so `RelationJudgment` and `BeliefRevisionEvent`
  commit atomically — which is what makes event replay trustworthy.
- Positive: `as_of` historical replay is a plain timestamp predicate.
- Negative: deep traversal is recursive CTEs. Mitigated by the bounded-traversal rule —
  every `GraphRepository` method takes a limit, so no query is unbounded by construction.
- `retrieval/graph_paths` stays unimplemented in Phase 1 (§18.1).

## Migration / Rollback

Rollback means replacing the `storage/postgres` implementation of `GraphRepository`.
Because no caller imports psycopg or writes SQL outside `storage/`, the blast radius is
that package plus its conformance tests.

## Tests / Evidence

- `T-SYS-001` rejects any cognition-layer bypass to state mutation.
- `GraphRepository` conformance tests run against both the in-memory fake and Postgres,
  so the contract — not one backend's behaviour — is what callers rely on.
