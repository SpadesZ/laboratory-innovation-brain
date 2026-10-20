-- A provider that was reached but did not answer within the call's deadline: TIMEOUT.
--
-- `012e` knew one outcome for every failure to get an answer, UNREACHABLE. A local model that is
-- slower than the deployment's inference deadline is reachable -- it accepted the connection and
-- the request -- and calling it unreachable sends the operator to the network instead of to the
-- deadline (`lab-brain web --inference-deadline`). `llm_runtime.provider` now tells them apart: a
-- connection that cannot be made is UNREACHABLE; an answer that does not arrive in time is TIMEOUT.

ALTER TABLE llm_connection_health DROP CONSTRAINT llm_connection_health_outcome_check;
ALTER TABLE llm_connection_health ADD CONSTRAINT llm_connection_health_outcome_check CHECK (
    outcome IN (
        'REACHABLE', 'AUTH_FAILED', 'UNREACHABLE', 'TIMEOUT', 'PROTOCOL_ERROR', 'SECRET_UNAVAILABLE'
    )
);
