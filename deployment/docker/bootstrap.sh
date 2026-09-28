#!/bin/sh
# Every start: migrations, then the operator's bootstrap of the researcher this workspace acts as.
#
# The bootstrap is the deployment operator's decision, made explicit (`lab-brain admin`, idempotent):
#   - the researcher, a person (HUMAN);
#   - their first project, created PRIVATE -- no evidence of it may leave this machine until its
#     privacy mode is changed by the operator and the project declares an egress policy;
#   - their membership: exactly the clearance in LAB_BRAIN_CLEARANCE, and the LLM_EGRESS approval
#     scope, i.e. the authority to DECLARE (not an actual approval of) their project's egress;
#   - administration of this deployment's language-model routes.
# Their membership of the bootstrap project is what the configuration says, each start.
set -eu
python /app/scripts/migrate.py
lab-brain admin actor "$LAB_BRAIN_ACTOR" --name "$LAB_BRAIN_ACTOR_NAME"
lab-brain admin project "$LAB_BRAIN_PROJECT" --name "$LAB_BRAIN_PROJECT_NAME"
lab-brain admin member "$LAB_BRAIN_PROJECT" "$LAB_BRAIN_ACTOR" \
    --clearance "$LAB_BRAIN_CLEARANCE" --scope LLM_EGRESS
lab-brain admin llm-admin "$LAB_BRAIN_ACTOR"
