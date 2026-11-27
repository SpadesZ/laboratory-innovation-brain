#!/bin/sh
# Phase C, step 7: freeze the blind run's output BEFORE anything of the target is read.
#
#     sh benchmarks/lumi_agent/freeze.sh <episode id>
#
# Run from the repository root while the deployment is up. Writes benchmarks/lumi_agent/frozen/:
# the report as the workspace exports it, the report as the research service returned and the
# workspace recorded it, the inference provenance of the episode (which model, route and provider
# produced each hypothesis, position and critique), and MANIFEST with the SHA-256 of each. Commit
# `frozen/` -- that commit is the freeze -- and only then begin Phase D.
set -eu
EPISODE="${1:?usage: freeze.sh <episode id>}"
case "$EPISODE" in
    epi:*) ;;
    *) echo "not an episode id: $EPISODE" >&2; exit 2 ;;
esac
if ! printf '%s' "$EPISODE" | grep -Eq '^epi:[0-9a-f-]{36}$'; then
    echo "not an episode id: $EPISODE" >&2
    exit 2
fi
OUT="benchmarks/lumi_agent/frozen"
mkdir -p "$OUT"
PORT="${LAB_BRAIN_PORT:-8765}"
SQL() { docker compose exec -T db psql -U lab_brain -d lab_brain -At -c "$1"; }

curl -fsS -H "Host: 127.0.0.1:$PORT" \
    "http://127.0.0.1:$PORT/episodes/$EPISODE/runs/1/report.md" -o "$OUT/report.md"
SQL "SELECT r.report::text FROM research_run_reports r JOIN research_runs x USING (research_run_id)
     WHERE x.episode_id = '$EPISODE' AND x.ordinal = 1" > "$OUT/report.json"
SQL "SELECT row_to_json(p)::text FROM (
       SELECT inference_id, role, logical_slot, provider, model_id, model_version, prompt_id,
              prompt_version, evidence_bundle_hash, created_at
         FROM inference_provenance
        WHERE trace_id = (SELECT trace_id FROM research_episodes WHERE episode_id = '$EPISODE')
        ORDER BY created_at, inference_id) p" > "$OUT/provenance.jsonl"
SQL "SELECT row_to_json(e)::text FROM (
       SELECT episode_id, project_id, state, outcome_status, start_time, end_time
         FROM research_episodes WHERE episode_id = '$EPISODE') e" > "$OUT/episode.json"
SQL "SELECT row_to_json(r)::text FROM (
       SELECT runtime_id, name, state, activated_by, activated_at FROM llm_runtimes
        WHERE state = 'ACTIVE') r" > "$OUT/runtime.json"

[ -s "$OUT/report.json" ] || { echo "no recorded report for $EPISODE" >&2; exit 1; }
{
    echo "episode $EPISODE"
    echo "frozen_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    for f in report.md report.json provenance.jsonl episode.json runtime.json; do
        echo "sha256 $(sha256sum "$OUT/$f" | cut -d' ' -f1)  $f"
    done
} > "$OUT/MANIFEST"
cat "$OUT/MANIFEST"
echo "Commit benchmarks/lumi_agent/frozen/ now; Phase D starts only after that commit."
