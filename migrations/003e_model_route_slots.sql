-- 003e_model_route_slots.sql
--
-- M3 / §7.3 / §17.14. The slot vocabulary `003d` accepted could not record §7.3's own slots.
--
-- THE CONTRADICTION THIS REMOVES. §17.14's `InferenceProvenance.logical_slot` is the field §7.3's
-- routing table is recorded in, and §7.3 names six LLM slots and one embedding slot:
-- REASONING_PRIMARY, REASONING_ADVERSARIAL, FAST_UTILITY, CODE, PRIVATE_LOCAL, VISION, EMBEDDING.
-- `003d` constrained the column to seven values chosen before routing existed -- HYPOTHESIS,
-- CRITIQUE, EXTRACTION, PLANNING, SUMMARISATION, RELATION, EMBEDDING -- which name the FUNCTION a
-- call served rather than the ROUTE it was sent down. M3's scope is "PRIMARY/FAST/EMBEDDING minimum
-- routing", and under `003d` a call routed to REASONING_PRIMARY was unrecordable: the write that
-- makes an inference durable (LLM-001) would have been refused for using the spec's own word.
--
-- ADDITIVE, AND DELIBERATELY SO. M1's rows keep their values and stay readable; the M1 code that
-- wrote them is unchanged. Narrowing the vocabulary to §7.3 only would rewrite history that is
-- already durable, and M1 is hard-locked. Both vocabularies are accepted; M3's roles write §7.3's.
--
-- NUMBERING. Extends `003`, next to `003d` whose constraint it replaces. Forward-only: `003d` is
-- applied and checksummed, so it is not edited.

ALTER TABLE inference_provenance
    DROP CONSTRAINT IF EXISTS inference_provenance_logical_slot_check;

ALTER TABLE inference_provenance
    ADD CONSTRAINT inference_provenance_logical_slot_check CHECK (
        logical_slot IN (
            -- `003d`'s values, unchanged.
            'HYPOTHESIS', 'CRITIQUE', 'EXTRACTION', 'PLANNING',
            'SUMMARISATION', 'RELATION', 'EMBEDDING',
            -- §7.3's slots.
            'REASONING_PRIMARY', 'REASONING_ADVERSARIAL', 'FAST_UTILITY',
            'CODE', 'PRIVATE_LOCAL', 'VISION'
        )
    );
