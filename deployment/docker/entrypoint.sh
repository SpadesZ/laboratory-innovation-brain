#!/bin/sh
# The database URL is assembled here, inside the container, from the password file the `secrets`
# service generated. The password is never in the image, the compose file or the host's environment.
set -eu
if [ -n "${LAB_BRAIN_DATABASE_PASSWORD_FILE:-}" ]; then
    if [ ! -r "$LAB_BRAIN_DATABASE_PASSWORD_FILE" ]; then
        echo "lab-brain: the database password file is not readable" >&2
        exit 2
    fi
    password="$(cat "$LAB_BRAIN_DATABASE_PASSWORD_FILE")"
    export LAB_BRAIN_DATABASE_URL="postgresql://lab_brain:${password}@${LAB_BRAIN_DATABASE_HOST:-db}:5432/lab_brain"
    unset password
fi
exec "$@"
