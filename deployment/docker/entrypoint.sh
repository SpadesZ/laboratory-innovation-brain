#!/bin/sh
# The database URL is assembled here, inside the container, from the password file the `secrets`
# service generated. The password is never in the image, the compose file or the host's environment.
# LAB_BRAIN_DATABASE_USER names the role: the migrator (`lab_brain`, the default) for `init`, the
# services' role (`lab_brain_app`) for `web` and `local-models` -- each with its own password file.
set -eu
if [ -n "${LAB_BRAIN_DATABASE_PASSWORD_FILE:-}" ]; then
    if [ ! -r "$LAB_BRAIN_DATABASE_PASSWORD_FILE" ]; then
        echo "lab-brain: the database password file is not readable" >&2
        exit 2
    fi
    user="${LAB_BRAIN_DATABASE_USER:-lab_brain}"
    case "$user" in
        "" | *[!a-z0-9_]*)
            echo "lab-brain: LAB_BRAIN_DATABASE_USER is a plain lower-case role name" >&2
            exit 2
            ;;
    esac
    password="$(cat "$LAB_BRAIN_DATABASE_PASSWORD_FILE")"
    export LAB_BRAIN_DATABASE_URL="postgresql://${user}:${password}@${LAB_BRAIN_DATABASE_HOST:-db}:5432/lab_brain"
    unset password user
fi
exec "$@"
