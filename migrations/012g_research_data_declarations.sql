-- Research data intake. What the researcher DECLARED about a file they added to a project outside a
-- research run -- the kind of material it is, and its label -- bound to the ingestion item it became.
--
-- The file itself goes through the one authoritative path, unchanged: Artifact and
-- ArtifactOccurrence (the project's sensitivity label, declared at upload), ingestion, EvidenceUnits,
-- the secret scan, content identity (the same bytes arriving again are the SAME artifact, and the
-- later item is derived DUPLICATE). Nothing here stores bytes, units or evidence. What had no place
-- to live was the trust class the researcher declares (§6.5: declared, never inferred) -- a research
-- run carries it per document for its own admission; data added before any run needs it recorded, so
-- a later run can use the item as declared. The label declared for the upload is kept beside it:
-- for a DUPLICATE the occurrence keeps its first label, and what the researcher said this time would
-- otherwise be lost. One row per item, append-only.

CREATE TABLE IF NOT EXISTS research_data_declarations (
    item_id        TEXT PRIMARY KEY REFERENCES ingestion_items (item_id),
    project_id     TEXT NOT NULL REFERENCES projects (project_id),
    actor_id       TEXT NOT NULL REFERENCES actors (actor_id),
    -- The trust class the researcher declared: a measurement record, a simulation/run record, or
    -- notes. The same three a research run's uploads may be declared as.
    declared_kind  TEXT NOT NULL CHECK (
        declared_kind IN ('INTERNAL_MEASUREMENT', 'INTERNAL_RUN', 'EXPERT_HEURISTIC')
    ),
    -- The label the researcher declared for THIS upload. For a new artifact it is the label its
    -- occurrence was stored under; for a DUPLICATE the occurrence keeps its first arrival's label
    -- (content identity), and this records what was declared, so a page can show both.
    declared_label TEXT NOT NULL CHECK (
        declared_label IN ('RESTRICTED_NDA', 'CONFIDENTIAL_LAB', 'INTERNAL', 'PUBLIC')
    ),
    -- The file name as the researcher chose it, for display; the item's own display name is the
    -- upload URI the ingestion recorded.
    file_name      TEXT NOT NULL CHECK (btrim(file_name) <> '' AND length(file_name) <= 255),
    declared_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS research_data_declarations_project_idx
    ON research_data_declarations (project_id, declared_at DESC);

CREATE FUNCTION research_data_declarations_guard() RETURNS TRIGGER AS $$
DECLARE
    v_item ingestion_items%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a research data declaration is append-only: it is what was declared';
    END IF;
    SELECT * INTO v_item FROM ingestion_items WHERE item_id = NEW.item_id;
    IF v_item.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'ingestion item % belongs to project %, not %', NEW.item_id,
            v_item.project_id, NEW.project_id;
    END IF;
    IF v_item.actor_id <> NEW.actor_id THEN
        RAISE EXCEPTION 'ingestion item % was submitted by %; only its submitter declares it',
            NEW.item_id, v_item.actor_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER research_data_declarations_guard_trg
    BEFORE INSERT OR UPDATE OR DELETE ON research_data_declarations
    FOR EACH ROW EXECUTE FUNCTION research_data_declarations_guard();

COMMENT ON TABLE research_data_declarations IS
    'The material kind (trust class) a researcher declared for a file added as research data, '
    'bound to its ingestion item. The file, its artifact and its evidence live where every '
    'ingestion puts them; this row stores none of it.';
