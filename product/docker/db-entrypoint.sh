#!/bin/sh
set -eu
# Read the host-private secret while the stock image entrypoint still runs as root.
# It becomes available to init scripts after the image drops to postgres UID.
export RLT_APP_PASSWORD="$(cat /run/secrets/app_db_password)"
exec /usr/local/bin/docker-entrypoint.sh "$@"
