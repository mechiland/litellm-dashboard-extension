#!/bin/sh
set -eu
python /opt/litellm-ui-overrides/prepare_gateway.py
exec /app/docker/prod_entrypoint.sh "$@"
