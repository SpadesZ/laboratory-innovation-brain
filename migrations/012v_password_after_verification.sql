-- 012v: an account has a password only once its address is confirmed (verify first).
--
-- WHY. Under 012u a registration chose its password before anyone had shown they read the
-- address's mail. Someone who registered another person's address could wait for that person to
-- open the confirmation link -- and the confirmed account then signed in with the stranger's
-- password. Now the name and the password are chosen by whoever opens the link, in the step that
-- confirms the address. This constraint holds that for every writer: a password on an
-- unconfirmed account is refused, whoever writes it.
--
-- HISTORY. A password chosen before confirmation under 012u is exactly what this closes, so it is
-- removed (the account's holder sets one when they confirm the address). Nothing else changes: a
-- confirmed account keeps its password, and the first administrator (confirmed by the operator)
-- sets theirs by the operator's one-time link as before.

UPDATE accounts SET password_hash = NULL, password_changed_at = NULL
 WHERE email_verified_at IS NULL AND password_hash IS NOT NULL;

ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_password_after_verification;
ALTER TABLE accounts ADD CONSTRAINT accounts_password_after_verification
    CHECK (password_hash IS NULL OR email_verified_at IS NOT NULL);
