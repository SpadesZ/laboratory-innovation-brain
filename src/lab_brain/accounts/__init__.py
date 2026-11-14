"""Laboratory accounts: sign-in, two system roles, account states, and project ownership (`012u`).

An account is a person's way into the workspace, bound to the HUMAN actor every research record
already names. Authorization stays where it was: project memberships and their clearance decide
what a person may read and do inside a project. Accounts add who is signed in, in which state,
and the laboratory-wide role:

    ADMIN    the laboratory's administrators: approve registrations, manage accounts and project
             membership, the deployment's model settings, and see every project for oversight
             (each such view recorded); no authority over scientific evidence or history
    MEMBER   creates projects, which they own, and works in the projects they own or were
             assigned to

Pending, active and suspended are account STATES, not roles. A person registers (PENDING),
verifies their email, and an administrator approves them (ACTIVE). Only established mechanisms
are used: scrypt from the standard library for passwords, `secrets` for tokens, SHA-256 of a
token for what is stored, SMTP with TLS for mail -- and mail fails closed until it is configured.
"""
