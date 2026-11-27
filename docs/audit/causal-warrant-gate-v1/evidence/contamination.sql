-- Read-only: where CONFIRMED conclusions exist, who authored the support that produced them, and
-- what later research read them (precedents, heuristic candidates, review items).
BEGIN READ ONLY;
\echo '== every CONFIRMED FailureAnalysis'
SELECT f.failure_analysis_id, f.project_id, f.episode_id, f.failure_class, f.confirmed_root_cause,
       f.root_cause_evidence_ids, f.created_at
FROM failure_analyses f WHERE f.resolution_status = 'CONFIRMED' ORDER BY f.created_at;
\echo '== the SUPPORTS relations behind each CONFIRMED cause, with the author of the prediction'
SELECT f.failure_analysis_id, r.relation_id, r.relation_type, r.attributes->>'prediction_id' AS prediction_id,
       r.attributes->>'capability_id' AS capability, r.attributes->>'run_id' AS run_id,
       i.provider, i.model_id, i.model_version
FROM failure_analyses f
JOIN relation_judgments r ON r.to_entity_id = f.confirmed_root_cause AND r.relation_type = 'SUPPORTS'
LEFT JOIN predictions p ON p.prediction_id = r.attributes->>'prediction_id'
LEFT JOIN inference_provenance i ON i.inference_id = p.inference_provenance_id
WHERE f.resolution_status = 'CONFIRMED' ORDER BY f.created_at, r.relation_id;
\echo '== verification plans whose rationale cites a CONFIRMED analysis as a precedent'
SELECT v.plan_id, v.project_id, v.episode_id, v.created_at, v.rationale->'precedents' AS precedents
FROM verification_plans v
WHERE jsonb_array_length(COALESCE(v.rationale->'precedents', '[]'::jsonb)) > 0
ORDER BY v.created_at;
\echo '== heuristic candidates, review items, review resolutions'
SELECT (SELECT count(*) FROM candidate_heuristics) AS candidate_heuristics,
       (SELECT count(*) FROM review_items) AS review_items,
       (SELECT count(*) FROM review_resolutions) AS review_resolutions;
ROLLBACK;
