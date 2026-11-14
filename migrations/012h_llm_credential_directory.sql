-- A third place a model-provider credential may live: this deployment's credential directory.
--
-- `012e` admits two references: `env:NAME` (an environment variable the operator sets) and
-- `wincred:lab-brain/llm/<uuid>` (Windows Credential Manager). A container has neither an operating-
-- system credential store nor a way for a researcher to set an environment variable from the page,
-- so the container deployment keeps a key a researcher pastes in a dedicated directory on its own
-- volume (`llm_runtime.secrets.DirectoryCredentialStore`), one file per key, named by an opaque id.
--
-- What this row holds is unchanged: a REFERENCE and a fingerprint, never the key. The reference
-- names the key's file by that id and nothing else -- no connection name, no provider, no part of
-- the key. The key's bytes are in the directory only; nothing here can read them.

ALTER TABLE llm_connections DROP CONSTRAINT llm_connections_secret_ref_check;
ALTER TABLE llm_connections ADD CONSTRAINT llm_connections_secret_ref_check CHECK (
    secret_ref IS NULL
    OR secret_ref ~ '^(env:[A-Za-z_][A-Za-z0-9_]{0,127}|(wincred|file):lab-brain/llm/[0-9a-f-]{36})$'
);

COMMENT ON COLUMN llm_connections.secret_ref IS
    'Where the credential lives, never the credential: env:NAME, wincred:lab-brain/llm/<uuid> '
    '(Windows Credential Manager) or file:lab-brain/llm/<uuid> (this deployment''s credential '
    'directory, llm_runtime.secrets.DirectoryCredentialStore).';
