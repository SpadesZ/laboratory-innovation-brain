-- Read-only: every decision toward SUPPORTED, every SUPPORTS relation by the author of its prediction,
-- and every belief event into SUPPORTED or CONTRADICTED.
BEGIN READ ONLY;
\echo '== decisions'
SELECT d.decision_id, d.project_id, d.policy_id || '@' || d.policy_version AS policy, d.result,
       d.from_state || ' -> ' || d.to_state AS move, d.created_at
FROM belief_transition_decisions d ORDER BY d.created_at;
\echo '== SUPPORTS relations by prediction author'
SELECT r.project_id, COALESCE(i.provider, '(none)') AS provider, COALESCE(i.model_id, '(none)') AS model_id,
       count(*) AS supports_relations
FROM relation_judgments r
LEFT JOIN predictions p ON p.prediction_id = r.attributes->>'prediction_id'
LEFT JOIN inference_provenance i ON i.inference_id = p.inference_provenance_id
WHERE r.relation_type = 'SUPPORTS' GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
\echo '== belief events into SUPPORTED or CONTRADICTED, with the mechanism and the relation author'
SELECT e.event_id, e.project_id, e.to_state, e.policy_id || '@' || e.policy_version AS policy, h.mechanism,
       r.relation_type, r.attributes->>'outcome' AS outcome, p.observable_ref, i.model_id AS author, e.occurred_at
FROM belief_revision_events e
JOIN hypotheses h ON h.hypothesis_id = e.target_id
JOIN belief_transition_decisions d ON d.decision_id = e.authorization_decision_id
LEFT JOIN relation_judgments r ON r.relation_id = (d.decision_input_snapshot::jsonb -> 'admitted_relations' -> 0 ->> 'relation_id')
LEFT JOIN predictions p ON p.prediction_id = r.attributes->>'prediction_id'
LEFT JOIN inference_provenance i ON i.inference_id = p.inference_provenance_id
WHERE e.to_state IN ('SUPPORTED', 'CONTRADICTED') ORDER BY e.occurred_at;
ROLLBACK;
