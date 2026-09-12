-- 008a_condition_payload_validation.sql
--
-- EVI-005 at the payload level, not just the reference level.
--
-- Migration 003 gives `conditions_schema_version` a foreign key to condition_schemas, which
-- proves the declared version is *registered*. It says nothing about whether the `conditions`
-- JSONB actually conforms to that schema. So direct SQL could insert
-- `conditions = '{"levle": 1}'` against a valid version and the row would be accepted -- and a
-- misspelled key that survives into storage produces a record that looks fully specified and is
-- not, which is precisely what makes condition-aware retrieval treat incomparable data as
-- comparable.
--
-- A CHECK constraint cannot do this: it may not reference another table. Hence a trigger.
--
-- SCOPE: deliberately the same subset the Python registry enforces -- `required` keys must be
-- present, keys absent from `properties` are rejected. No type checking, no nested schemas, no
-- `$ref`. Full JSON Schema semantics are not implemented here and must not be inferred from this
-- file; a domain needing richer validation registers a comparator that performs it (§6.19).
--
-- NUMBERING: 008a, not 009. Appendix A reserves 001-012 for named canonical migrations and 009 is
-- `009_vectors.sql`. The `a` suffix marks this as an amendment to 008 rather than a new canonical
-- migration. It must nevertheless apply *after* 003, since that is where the target tables are
-- created -- see APPLY_ORDER in scripts/migrate.py.

CREATE FUNCTION lab_brain_validate_conditions() RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    declared_schema  JSONB;
    required_keys    TEXT[];
    declared_keys    TEXT[];
    supplied_keys    TEXT[];
    missing_keys     TEXT[];
    undeclared_keys  TEXT[];
BEGIN
    SELECT json_schema INTO declared_schema
    FROM condition_schemas
    WHERE schema_ref = NEW.conditions_schema_version;

    IF declared_schema IS NULL THEN
        -- Unreachable while the foreign key stands. Raised rather than skipped so that dropping
        -- the FK later cannot silently turn this trigger into a no-op.
        RAISE EXCEPTION
            'condition schema % is not registered (EVI-005)', NEW.conditions_schema_version
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    SELECT coalesce(array_agg(value), '{}')
      INTO required_keys
      FROM jsonb_array_elements_text(coalesce(declared_schema -> 'required', '[]'::jsonb)) AS value;

    SELECT coalesce(array_agg(key), '{}')
      INTO declared_keys
      FROM jsonb_object_keys(coalesce(declared_schema -> 'properties', '{}'::jsonb)) AS key;

    SELECT coalesce(array_agg(key), '{}')
      INTO supplied_keys
      FROM jsonb_object_keys(coalesce(NEW.conditions, '{}'::jsonb)) AS key;

    SELECT coalesce(array_agg(key ORDER BY key), '{}')
      INTO missing_keys
      FROM unnest(required_keys) AS key
     WHERE key <> ALL (supplied_keys);

    IF cardinality(missing_keys) > 0 THEN
        RAISE EXCEPTION
            'conditions are missing required fields % declared by % (EVI-005)',
            missing_keys, NEW.conditions_schema_version
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT coalesce(array_agg(key ORDER BY key), '{}')
      INTO undeclared_keys
      FROM unnest(supplied_keys) AS key
     WHERE key <> ALL (declared_keys);

    IF cardinality(undeclared_keys) > 0 THEN
        RAISE EXCEPTION
            'conditions carry fields % not declared by % (EVI-005); declared fields are %',
            undeclared_keys, NEW.conditions_schema_version, declared_keys
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION lab_brain_validate_conditions() IS
    'EVI-005 payload validation: required keys present, undeclared keys rejected. '
    'Deliberately the same subset as lab_brain.evidence.ConditionSchemaRegistry.validate; '
    'not full JSON Schema semantics.';

CREATE TRIGGER observations_validate_conditions
    BEFORE INSERT OR UPDATE OF conditions, conditions_schema_version ON observations
    FOR EACH ROW EXECUTE FUNCTION lab_brain_validate_conditions();

CREATE TRIGGER attestations_validate_conditions
    BEFORE INSERT OR UPDATE OF conditions, conditions_schema_version ON attestations
    FOR EACH ROW EXECUTE FUNCTION lab_brain_validate_conditions();
