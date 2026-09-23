-- 012b_technical_details.sql
--
-- UX-003 / §17.24. The row `error_records.technical_detail_ref` points AT.
--
-- WHY THIS IS A SEPARATE TABLE AND NOT COLUMNS ON `error_records`.
--
-- §17.24 splits disclosure into two tiers, and the split is an authorization boundary rather
-- than a rendering preference:
--
--     tier one   the catalog message, the reference a human quotes, the trace refs
--     tier two   component, message, stack, source path, prompt fragment -- which may contain
--                NDA filenames, private repository paths and restricted prompt content
--
-- `DiagnosticsService.default_payload` is built FROM the error record. Putting the detail on
-- that row would mean the default payload was constructed from an object that already held the
-- restricted material -- so the service would be redacting something it had loaded, and any
-- future field added to the payload would leak it by default. The pointer makes tier two a
-- second read that only happens after the scope check passes.
--
-- SENSITIVITY IS ON THE DETAIL, NOT ON THE ERROR. §17.24 redacts detail against the requesting
-- Actor's `sensitivity_clearance`, so the label has to describe the detail. Two failures of the
-- same class in the same project can carry very differently classified detail -- a parse failure
-- naming a public preprint and one naming an NDA datasheet -- and a label on the error record
-- would have to be the more restrictive of the two for every reader.
--
-- PROJECT SCOPE IS STORED AND ENFORCED. The column is here because §17.24 scopes error lookup by
-- project membership, and a detail row reachable from another project's error record would be a
-- way to reach it anyway. A deferred constraint trigger checks the pair, rather than a composite
-- foreign key: the error record and its detail are written from the same failure and either
-- order is legitimate inside one transaction -- the same reasoning `012`'s stage/error trigger
-- records.
--
-- NO `resolved_at`, NO LIFECYCLE. This is an immutable description of what went wrong. The
-- ErrorRecord owns the lifecycle; a detail row that could be edited would let the explanation of
-- a past incident be changed after the fact.

CREATE TABLE technical_details (
    detail_ref      TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects (project_id),

    -- §14.1's vocabulary. Redaction compares this against the actor's clearance as an EXACT set
    -- membership -- the labels are categories of handling rather than a ladder, and
    -- `ProjectMembership.clears` is the one predicate that knows it.
    sensitivity     TEXT NOT NULL CHECK (
        sensitivity IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL_LAB', 'RESTRICTED_NDA')
    ),

    -- Survives redaction: it names a subsystem, not content. "FigureParser" tells a support
    -- engineer where to look and nothing about the document.
    component       TEXT NOT NULL,
    message         TEXT NOT NULL,

    stack_ref       TEXT,
    source_path     TEXT,
    prompt_fragment TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX technical_details_project_idx ON technical_details (project_id);

COMMENT ON TABLE technical_details IS
    'UX-003 / §17.24 tier two. Pointed at by `error_records.technical_detail_ref`, never inlined '
    'there: the default payload is built from the error record, so a detail column would put '
    'restricted material into the object the untrusted tier is rendered from.';

-- `error_records.technical_detail_ref` resolves, and to a detail in the same project.
--
-- Deferred, because the ErrorRecord and its detail are projected from one failure and a writer
-- may legitimately insert either first inside one transaction.
CREATE FUNCTION error_detail_must_resolve_in_project() RETURNS TRIGGER AS $$
DECLARE
    v_project TEXT;
BEGIN
    IF NEW.technical_detail_ref IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT project_id INTO v_project FROM technical_details
     WHERE detail_ref = NEW.technical_detail_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'error % names technical detail % which does not exist; §17.24 makes expansion an '
            'authorization decision, and a reference that resolves to nothing turns a granted '
            'expansion into a silent empty answer',
            NEW.error_id, NEW.technical_detail_ref;
    END IF;
    IF v_project IS DISTINCT FROM NEW.project_id THEN
        RAISE EXCEPTION
            'error % is in project % but its technical detail % is in %; §17.24 scopes error '
            'lookup by project membership, and a cross-project detail reference is a way to '
            'reach one anyway',
            NEW.error_id, NEW.project_id, NEW.technical_detail_ref, v_project;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER error_detail_must_resolve_in_project_trg
    AFTER INSERT OR UPDATE ON error_records
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION error_detail_must_resolve_in_project();
