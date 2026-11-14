BEGIN READ ONLY;
\echo '== source artifacts behind every bundle member of the later episode, and behind the wrong episode'
SELECT e.episode_id, t.source_artifact_id, count(*) AS members
FROM research_episodes e
JOIN evidence_bundles b ON b.retrieval_trace_id = e.trace_id
JOIN evidence_bundle_members m ON m.bundle_id = b.bundle_id
JOIN attestations t ON t.attestation_id = m.attestation_id
WHERE e.episode_id IN ('epi:12265cfd-ab34-4ba0-a329-cadc3d8894e6', 'epi:7b56877f-9287-4075-a3c6-9980abab8eef')
GROUP BY 1, 2 ORDER BY 1, 2;
ROLLBACK;
