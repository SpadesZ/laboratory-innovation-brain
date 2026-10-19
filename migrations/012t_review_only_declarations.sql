-- 012t_review_only_declarations.sql
--
-- A declared diagnostic link may be left to a person.
--
-- WHY. A DOMAIN warrant lets an observation move belief with no person in the loop, on the
-- strength of the DomainPack's declaration that the observed outcome diagnoses the class. The
-- science review of the silicon-photonics declarations (Causal Warrant Gate V1.1, review 04)
-- found links whose check cannot observe what the link claims: a drawn-layout reading cannot
-- refute a fabricated contact defect, a design-file solve cannot refute process compensation,
-- and a solver mesh property is not by itself the cause of a measured anomaly. Such a link is
-- still knowledge worth declaring -- it identifies the class and holds a conclusion back when it
-- is observed -- but it is not a warrant.
--
-- WHAT. A declaration may carry `review_only`: the link effects (SUPPORTS for the signature,
-- CONTRADICTS for every refutation) whose observation is never a DOMAIN warrant. A person's
-- warrant (REVIEW) still counts for them. Everything else the declarations decide -- which class a
-- hypothesis is of, which observed outcomes hold a conclusion back -- is unchanged. Mirrors
-- `DiagnosticDeclaration.review_only` and `core.warrant.domain_warrant`; the differential check
-- holds the two statements of the rule together.
--
-- HISTORY. Every set registered before this migration has no `review_only` and reads exactly as
-- before: an empty list. Registered rows are append-only and are not touched.

-- 012p's well-formedness rule, restated with `review_only`.
CREATE OR REPLACE FUNCTION diagnostic_declaration_sets_are_well_formed()
RETURNS TRIGGER AS $$
DECLARE
    v_bad TEXT;
BEGIN
    IF NEW.supersedes IS NOT NULL AND (
        NEW.supersedes = NEW.set_id || '@' || NEW.version
        OR NOT EXISTS (
            SELECT 1 FROM diagnostic_declaration_sets
             WHERE set_id || '@' || version = NEW.supersedes AND set_id = NEW.set_id
        )
    ) THEN
        RAISE EXCEPTION 'declaration set %@% supersedes %, which is not an earlier registered '
            'version of %', NEW.set_id, NEW.version, NEW.supersedes, NEW.set_id;
    END IF;
    SELECT d ->> 'class_id' INTO v_bad
      FROM jsonb_array_elements(NEW.declarations) d
     WHERE jsonb_typeof(d) <> 'object'
        OR coalesce(d ->> 'class_id', '') = '' OR coalesce(d ->> 'mechanism', '') = ''
        OR coalesce(d ->> 'observable_ref', '') = '' OR coalesce(d ->> 'outcome_space_id', '') = ''
        OR coalesce(d ->> 'outcome_space_version', '') = ''
        OR coalesce(d ->> 'supports_outcome', '') = ''
        OR jsonb_typeof(d -> 'refutes_outcomes') IS DISTINCT FROM 'array'
        OR jsonb_array_length(d -> 'refutes_outcomes') = 0
        OR (d -> 'refutes_outcomes') ? (d ->> 'supports_outcome')
        -- 012t: `review_only`, when present, names SUPPORTS and CONTRADICTS each at most once.
        OR (d ? 'review_only' AND (
               jsonb_typeof(d -> 'review_only') IS DISTINCT FROM 'array'
               OR EXISTS (SELECT 1 FROM jsonb_array_elements(d -> 'review_only') e
                           WHERE jsonb_typeof(e) <> 'string'
                              OR e #>> '{}' NOT IN ('SUPPORTS', 'CONTRADICTS'))
               OR (SELECT count(*) <> count(DISTINCT e)
                     FROM jsonb_array_elements(d -> 'review_only') e)))
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'declaration set %@% has a malformed declaration (%)', NEW.set_id,
            NEW.version, coalesce(v_bad, '?');
    END IF;
    -- The model's own rule: class ids, mechanisms and signatures are each unique in a set.
    IF (SELECT count(*) <> count(DISTINCT d ->> 'class_id')
                 OR count(*) <> count(DISTINCT d ->> 'mechanism')
                 OR count(*) <> count(DISTINCT jsonb_build_array(
                        d ->> 'observable_ref', d ->> 'outcome_space_id',
                        d ->> 'outcome_space_version', d ->> 'supports_outcome'))
          FROM jsonb_array_elements(NEW.declarations) d) THEN
        RAISE EXCEPTION 'declaration set %@% declares a class, mechanism or signature twice',
            NEW.set_id, NEW.version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 012p's view, with `review_only` appended (a view's existing columns cannot move).
CREATE OR REPLACE VIEW diagnostic_declarations AS
SELECT s.set_id,
       s.version,
       s.set_id || '@' || s.version                                   AS set_ref,
       d ->> 'class_id'                                               AS class_id,
       d ->> 'mechanism'                                              AS mechanism,
       d ->> 'statement'                                              AS statement,
       d ->> 'observable_ref'                                         AS observable_ref,
       d ->> 'outcome_space_id'                                       AS outcome_space_id,
       d ->> 'outcome_space_version'                                  AS outcome_space_version,
       d ->> 'supports_outcome'                                       AS supports_outcome,
       ARRAY(SELECT jsonb_array_elements_text(d -> 'refutes_outcomes')) AS refutes_outcomes,
       NOT EXISTS (
           SELECT 1 FROM diagnostic_declaration_sets x
            WHERE x.supersedes = s.set_id || '@' || s.version
       )                                                              AS active,
       -- 012t, appended: the link effects this declaration leaves to a person.
       ARRAY(SELECT jsonb_array_elements_text(coalesce(d -> 'review_only', '[]'::jsonb)))
                                                                      AS review_only
  FROM diagnostic_declaration_sets s
 CROSS JOIN LATERAL jsonb_array_elements(s.declarations) d;

-- 012p's `cwg_relation_warrant`, restated: only the DOMAIN condition changes.
CREATE OR REPLACE FUNCTION cwg_relation_warrant(
    p_relation relation_judgments,
    OUT warrant TEXT, OUT ref TEXT, OUT identifies TEXT
) AS $$
DECLARE
    v_link   RECORD;
    v_bound  RECORD;
    v_decl   RECORD;
    v_grant  diagnostic_warrant_grants%ROWTYPE;
    v_domain BOOLEAN := FALSE;
BEGIN
    IF p_relation.relation_type NOT IN ('SUPPORTS', 'CONTRADICTS')
       OR NOT cwg_relation_agrees(p_relation) THEN
        RETURN;
    END IF;
    SELECT * INTO v_link FROM cwg_observed_link(p_relation);
    SELECT * INTO v_bound FROM cwg_bound_class(p_relation.project_id, p_relation.to_entity_id);
    IF FOUND AND v_link.outcome IS NOT NULL THEN
        SELECT * INTO v_decl FROM diagnostic_declarations
         WHERE set_ref = v_bound.set_ref AND class_id = v_bound.class_id;
        v_domain := (v_link.observable, v_link.space_id, v_link.space_version)
                        = (v_decl.observable_ref, v_decl.outcome_space_id,
                           v_decl.outcome_space_version)
                    AND CASE
                        WHEN v_link.outcome = v_decl.supports_outcome THEN 'SUPPORTS'
                        WHEN v_link.outcome = ANY (v_decl.refutes_outcomes) THEN 'CONTRADICTS'
                    END IS NOT DISTINCT FROM p_relation.relation_type
                    -- 012t: a link the declaration leaves to a person is never a DOMAIN warrant.
                    AND NOT (p_relation.relation_type = ANY (v_decl.review_only));
    END IF;
    v_grant := cwg_counted_grant(p_relation);
    -- A person's refusal of this link outranks a declaration about the class.
    IF v_grant.grant_id IS NOT NULL AND v_grant.verdict = 'NOT_WARRANTED' THEN
        warrant := 'REFUSED';
        RETURN;
    END IF;
    IF v_domain THEN
        warrant := 'DOMAIN';
        ref := 'dds:' || v_bound.set_ref || '#' || v_bound.class_id;
        RETURN;
    END IF;
    IF v_grant.grant_id IS NOT NULL THEN
        warrant := 'REVIEW';
        ref := v_grant.grant_id;
        IF v_grant.identifies_class_ref IS NOT NULL AND v_link.outcome IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM diagnostic_declarations d
                WHERE 'dds:' || d.set_ref || '#' || d.class_id = v_grant.identifies_class_ref
                  AND (d.observable_ref, d.outcome_space_id, d.outcome_space_version,
                       d.supports_outcome)
                      = (v_link.observable, v_link.space_id, v_link.space_version, v_link.outcome)
           ) THEN
            identifies := v_grant.identifies_class_ref;
        END IF;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;
