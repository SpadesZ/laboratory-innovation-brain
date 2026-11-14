-- Plaintext http:// to a model provider only on this machine.
--
-- A model-provider call carries the credential (`Authorization: Bearer ...`) and, for a research
-- step, the prompt with the evidence it digests. Over plaintext http:// both cross every network
-- between the workspace and the endpoint. `012e` admitted http:// for any connection; from here an
-- ENABLED connection uses http:// only to this machine -- the hosts
-- `llm_connections_local_is_this_machine` (`012f`) already names -- and https:// everywhere else,
-- whatever its reach and wherever its credential lives.
--
-- ENABLED only: a connection the rule refuses can always be disabled or retired, never enabled.
--
-- NOT VALID: a row written before this migration is not rejected HERE -- a migration that failed on
-- it would stop the deployment from starting. Postgres still enforces the constraint on every later
-- INSERT and UPDATE, and such a row is refused wherever it would be USED: every settings step that
-- would contact it, readiness (it cannot be activated), the active runtime (research is refused
-- before its credential is read), and the transport itself (`llm_runtime.provider`), which sends
-- nothing to it.

ALTER TABLE llm_connections ADD CONSTRAINT llm_connections_plaintext_only_on_this_machine CHECK (
    lifecycle <> 'ENABLED'
    OR base_url ~ '^https://'
    OR base_url ~ '^http://(127\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|localhost|\[::1\]|host\.docker\.internal)(:[0-9]{1,5})?(/|$)'
) NOT VALID;
