-- 009a_retrieval_representations.sql
--
-- EVI-010 / §17.25 / ADR-0011. What an index holds about a canonical evidence unit.
--
-- WHY THIS IS A SEPARATE MIGRATION from 003a. Not tidiness -- the separation is the requirement.
-- ADR-0011 states that deleting and rebuilding an index must not change scientific evidence
-- identity, and the schema-level form of that guarantee is that
--
--     DELETE FROM retrieval_representations WHERE index_id = '...'
--
-- is expressible and touches no row of `evidence_units`. Put the two in one table with a nullable
-- embedding column and that operation becomes an UPDATE on scientific data.
--
-- The FK points from here to there, never the reverse: an evidence unit does not know which
-- indexes hold it, and must not, or dropping an index would require rewriting evidence rows.
--
-- 009 is Appendix A's `vectors.sql` slot. This is the 'a' extension of it: EVI-007's dense index
-- lands in the same slot later and adds columns here rather than anywhere near 003a.

CREATE TABLE IF NOT EXISTS retrieval_representations (
    representation_id       TEXT PRIMARY KEY,
    -- ON DELETE CASCADE, and the direction matters. Removing a unit removes what indexes said
    -- about it, because a representation of nothing is a candidate that resolves to nothing --
    -- which the resolver would drop silently. The reverse cascade does not and must not exist.
    evidence_unit_id        TEXT NOT NULL
                            REFERENCES evidence_units(evidence_unit_id) ON DELETE CASCADE,
    project_id              TEXT NOT NULL REFERENCES projects(project_id),

    index_id                TEXT NOT NULL,
    index_kind              TEXT NOT NULL,

    -- EVI-007's compatibility keys. NULL on a LEXICAL index is not a missing value: a BM25 index
    -- has no embedding space to be incompatible with. The CHECK below makes that literal, so a
    -- lexical row can never carry a model name a later cosine comparison might trust.
    embedding_model         TEXT,
    embedding_version       TEXT,
    dimensions              INTEGER,

    -- Digest of the text AS INDEXED. Present so divergence from the canonical body is
    -- detectable, NOT so it can be trusted -- §17.25 fixes the canonical body as authoritative
    -- on disagreement. A stale index is an operational problem, not an evidence problem.
    payload_digest          TEXT NOT NULL,
    built_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT retrieval_representation_kind_is_known
        CHECK (index_kind IN ('LEXICAL', 'DENSE', 'HYBRID')),
    CONSTRAINT retrieval_representation_digest_is_wellformed
        CHECK (payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT retrieval_representation_dimensions_are_positive
        CHECK (dimensions IS NULL OR dimensions > 0),

    -- EVI-007, in both directions.
    --
    -- A DENSE/HYBRID row that does not name its embedding space cannot be filtered by
    -- compatibility, so mixing spaces becomes possible and §6.13's "混合不同 embedding space 的
    -- cosine 距離是靜默垃圾" is exactly what happens -- silently.
    --
    -- A LEXICAL row that DOES name one is the subtler error: nothing was embedded, so the name
    -- describes no space, and a later migration that filtered on `embedding_model` would treat
    -- these rows as members of a space they are not in.
    CONSTRAINT retrieval_representation_embedding_space_is_complete
        CHECK (
            (index_kind = 'LEXICAL'
             AND embedding_model IS NULL AND embedding_version IS NULL AND dimensions IS NULL)
         OR (index_kind <> 'LEXICAL'
             AND embedding_model IS NOT NULL AND embedding_version IS NOT NULL)
        )
);

-- One representation per unit per index. Two rows would mean a rebuild appended rather than
-- replaced, and a search would rank the same unit twice.
CREATE UNIQUE INDEX IF NOT EXISTS retrieval_representations_unit_index_key
    ON retrieval_representations (evidence_unit_id, index_id);

-- The drop-an-index operation this table exists to keep cheap and non-destructive.
CREATE INDEX IF NOT EXISTS retrieval_representations_index_idx
    ON retrieval_representations (index_id);

-- Retrieval filters by project before scoring (SEC-002), so a cross-project unit is never
-- ranked, never scored and never leaks through a result count.
CREATE INDEX IF NOT EXISTS retrieval_representations_project_idx
    ON retrieval_representations (project_id, index_id);

-- EVI-007's compatibility filter, for when the dense index lands.
CREATE INDEX IF NOT EXISTS retrieval_representations_embedding_space_idx
    ON retrieval_representations (embedding_model, embedding_version)
    WHERE embedding_model IS NOT NULL;

-- A representation must belong to the same project as the unit it represents.
--
-- This cannot be a CHECK: it reads another table. Without it a representation could be written
-- into project B naming a unit in project A, and the resolver's project comparison -- which is
-- defence in depth, not the primary gate -- would be the only thing standing between that row
-- and an R-7 leak through a different door. Enforced here so the row cannot exist.
CREATE OR REPLACE FUNCTION retrieval_representation_project_matches_unit()
RETURNS TRIGGER AS $$
DECLARE
    unit_project TEXT;
BEGIN
    SELECT project_id INTO unit_project
      FROM evidence_units
     WHERE evidence_unit_id = NEW.evidence_unit_id;

    IF unit_project IS NULL THEN
        RAISE EXCEPTION
            'retrieval representation % names evidence unit %, which does not exist',
            NEW.representation_id, NEW.evidence_unit_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF unit_project <> NEW.project_id THEN
        RAISE EXCEPTION
            'retrieval representation % is in project % but evidence unit % belongs to %; '
            'presence in one project grants nothing in another (SEC-002, R-7)',
            NEW.representation_id, NEW.project_id, NEW.evidence_unit_id, unit_project
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS retrieval_representation_project_matches
    ON retrieval_representations;
CREATE TRIGGER retrieval_representation_project_matches
    BEFORE INSERT OR UPDATE ON retrieval_representations
    FOR EACH ROW EXECUTE FUNCTION retrieval_representation_project_matches_unit();
