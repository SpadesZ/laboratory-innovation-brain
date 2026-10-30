"""What the evaluator reads back from a finished episode: support provenance, as facts.

Scorer 2.0.0 decides whether a SUPPORTS relation to a hypothesis proposed after screening was
admissible. It does not take a verdict from the system under test -- a record saying
`"admissible": true` would be the generator grading itself. The collector instead reports, for every
SUPPORTS relation, the facts the 012y/011m/011o guard is defined on, read from the canonical rows.
A relation rests on its BASIS: its source and the observation behind every attestation it cites.
(012y/011m/011o/011p.)

    unobserved_basis            the source is not an observation, or a cited attestation attests no
                                observation (011o: only a prospective check can support)
    screened_observation        a basis observation is one the hypothesis was conditioned on
    observed_before_hypothesis  a basis observation was recorded before the hypothesis was
    repeats_screened_check      a basis observation's run is the screened check again: same
                                capability, inputs and parameters as a conditioned run (any backend)
    shares_screened_output      a basis observation's run emitted an output artifact a conditioned
                                run emitted -- the same content, since an artifact id is its hash
    retrospective_basis         a basis observation is not prospective in TIME or KIND (011p,
                                011s): it has no run; its run started before the hypothesis, reads
                                or emits data captured before it, reads the output of a run that
                                started before it, emits -- or reads as empirical data -- an
                                artifact recorded before it; or its DECLARED kind cannot produce
                                new evidence about what it read (an evidence lookup, a historical
                                case comparison, an expert review; a rule check or surrogate of a
                                design or of anything that existed before the hypothesis).
                                Recording time is not evidence time.
    unknown_capture_time        a basis run reads or emits EMPIRICAL data (not a declared design
                                specification it reads, nor a computed output of a computing
                                kind) whose capture time is NULL (011s)
    lineage_before_hypothesis   the lineage of a basis run's inputs or outputs (derived_from,
                                previous revision; transitively, at most 16 links) reaches an
                                output of a screened run or of a run started before the
                                hypothesis, empirical data captured or recorded before it or of
                                unknown capture time, an unrecorded artifact, a cycle, or more
                                than 16 links (011s)
    unclassified_capability     a basis observation has no run, or its run's capability has no
                                domain-pack declaration (`capability_declarations`) agreeing with
                                `capabilities` (011s)
    unauthorized_verification   a basis observation has no run, or its run's job is not bound to a
                                verification authorization of this hypothesis, for this
                                capability under the declaration in force, naming the relation's
                                prediction, made before the run started and -- for a measurement
                                -- before its data was captured (011s)

The 011s facts are read through the same SQL functions the guard calls (`prospective_*`), on the
rows as they are now -- so a guard switched off, or rows edited after the fact, are still reported.

For a hypothesis formed before any screening reading there is no conditioning record, so every fact
is false: its support is ordinary evidence, not a post-hoc reading. The SQL guard refuses the
inadmissible bases at write time; the collector reads them again so the score does not rest on the
guard having held.

Read-only, and only through the connection it is given.
"""

from __future__ import annotations

from typing import Any

_SUPPORTS = """
WITH rel AS (
    SELECT r.relation_id, r.from_entity_id, r.supporting_attestation_ids, h.created_at,
           c.screening_observation_ids AS screened, c AS conditioned,
           r.attributes ->> 'prediction_id' AS prediction_id
      FROM relation_judgments r
      JOIN hypotheses h ON h.project_id = r.project_id AND h.hypothesis_id = r.to_entity_id
      LEFT JOIN screening_conditioned_hypotheses c
             ON c.project_id = h.project_id AND c.hypothesis_id = h.hypothesis_id
     WHERE r.to_entity_id = %s AND r.relation_type = 'SUPPORTS'
), basis AS (
    SELECT rel.relation_id, o.observation_id, o.created_at AS observed, u AS run_row, u.*
      FROM rel
      JOIN observations o ON o.observation_id = rel.from_entity_id
                          OR o.observation_id IN (
                                 SELECT a.observation_id FROM attestations a
                                  WHERE a.attestation_id = ANY (rel.supporting_attestation_ids))
      LEFT JOIN runs u ON u.run_id = o.run_id
), screened_runs AS (
    SELECT rel.relation_id, sr.*, s.observation_ids AS screened_observations
      FROM rel
      JOIN screening_observations s ON s.screening_observation_id = ANY (rel.screened)
      JOIN runs sr ON sr.run_id = s.run_id
)
SELECT rel.relation_id,
       rel.screened IS NOT NULL AND (
           NOT EXISTS (SELECT 1 FROM observations WHERE observation_id = rel.from_entity_id)
           OR EXISTS (SELECT 1 FROM unnest(rel.supporting_attestation_ids) cited
                       LEFT JOIN attestations a ON a.attestation_id = cited
                      WHERE a.observation_id IS NULL)),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b JOIN screened_runs s ON s.relation_id = b.relation_id
            WHERE b.relation_id = rel.relation_id
              AND b.observation_id = ANY (s.screened_observations)),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b WHERE b.relation_id = rel.relation_id
              AND b.observed < rel.created_at),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b JOIN screened_runs s ON s.relation_id = b.relation_id
            WHERE b.relation_id = rel.relation_id
              AND s.capability_id = b.capability_id
              AND s.input_parameters = b.input_parameters
              AND (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(s.input_artifacts) x)
                = (SELECT coalesce(array_agg(x ORDER BY x), '{}')
                     FROM unnest(b.input_artifacts) x)),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b JOIN screened_runs s ON s.relation_id = b.relation_id
            WHERE b.relation_id = rel.relation_id
              AND s.output_artifacts && b.output_artifacts),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b
            WHERE b.relation_id = rel.relation_id
              AND (b.run_id IS NULL
                   OR b.start_time < rel.created_at
                   OR EXISTS (SELECT 1 FROM artifacts a
                               WHERE a.artifact_id = ANY (b.input_artifacts || b.output_artifacts)
                                 AND a.captured_at < rel.created_at)
                   OR EXISTS (SELECT 1 FROM runs earlier
                               WHERE earlier.project_id = b.project_id
                                 AND earlier.run_id <> b.run_id
                                 AND earlier.output_artifacts && b.input_artifacts
                                 AND earlier.start_time < rel.created_at)
                   OR prospective_kind_problem(b.run_row, rel.created_at) IS NOT NULL
                   OR prospective_existence_problem(b.run_row, rel.created_at) IS NOT NULL)),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b WHERE b.relation_id = rel.relation_id
              AND b.run_id IS NOT NULL
              AND prospective_capture_problem(b.run_row, rel.created_at) IS NOT NULL),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b WHERE b.relation_id = rel.relation_id
              AND b.run_id IS NOT NULL
              AND prospective_lineage_problem(rel.conditioned, b.run_row, rel.created_at)
                  IS NOT NULL),
       rel.screened IS NOT NULL AND EXISTS (
           SELECT 1 FROM basis b WHERE b.relation_id = rel.relation_id
              AND (b.run_id IS NULL
                   OR prospective_declaration_problem(b.run_row) IS NOT NULL)),
       rel.screened IS NOT NULL AND (
           NOT EXISTS (SELECT 1 FROM basis b WHERE b.relation_id = rel.relation_id)
           OR EXISTS (
               SELECT 1 FROM basis b WHERE b.relation_id = rel.relation_id
                  AND (b.run_id IS NULL
                       OR prospective_authorization_problem(
                              rel.conditioned, b.run_row, rel.prediction_id) IS NOT NULL)))
  FROM rel
 ORDER BY rel.relation_id
"""


def support_provenance(connection: Any, hypothesis_id: str) -> list[dict[str, Any]]:
    """Every SUPPORTS relation to `hypothesis_id`, with the facts scorer 2.2.0 judges it by."""
    return [
        {
            "relation_id": str(relation),
            "unobserved_basis": bool(unobserved),
            "screened_observation": bool(screened),
            "observed_before_hypothesis": bool(before),
            "repeats_screened_check": bool(repeat),
            "shares_screened_output": bool(same_bytes),
            "retrospective_basis": bool(retrospective),
            "unknown_capture_time": bool(unknown),
            "lineage_before_hypothesis": bool(lineage),
            "unclassified_capability": bool(unclassified),
            "unauthorized_verification": bool(unauthorized),
        }
        for (
            relation,
            unobserved,
            screened,
            before,
            repeat,
            same_bytes,
            retrospective,
            unknown,
            lineage,
            unclassified,
            unauthorized,
        ) in connection.execute(_SUPPORTS, (hypothesis_id,)).fetchall()
    ]


__all__ = ["support_provenance"]
