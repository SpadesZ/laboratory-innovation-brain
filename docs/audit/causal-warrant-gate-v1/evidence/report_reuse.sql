-- Read-only: did anything recorded after the wrong confirmation (12:20:37 UTC) reach later research?
BEGIN READ ONLY;
\echo '== artifacts ingested into prj:bench-gemini at or after the wrong confirmation'
SELECT o.artifact_id, a.media_type, a.source_origin, o.ingested_at
FROM artifact_occurrences o JOIN artifacts a USING (artifact_id)
WHERE o.project_id = 'prj:bench-gemini' AND o.ingested_at >= '2026-10-13 12:20:37+00' ORDER BY o.ingested_at;
\echo '== bundles of the later episode epi:12265cfd: members and how many came from executed runs'
SELECT b.bundle_id, count(*) AS members,
       count(*) FILTER (WHERE t.run_id IS NOT NULL OR t.observation_id IS NOT NULL) AS from_runs
FROM evidence_bundles b
JOIN research_episodes e ON e.trace_id = b.retrieval_trace_id
JOIN evidence_bundle_members m ON m.bundle_id = b.bundle_id
JOIN attestations t ON t.attestation_id = m.attestation_id
WHERE e.episode_id = 'epi:12265cfd-ab34-4ba0-a329-cadc3d8894e6'
GROUP BY b.bundle_id ORDER BY b.bundle_id;
ROLLBACK;
