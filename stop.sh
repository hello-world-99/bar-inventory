#!/bin/sh
# Stops Bar Inventory. Data stays; ./start.sh starts it again.
set -eu
cd "$(dirname "$0")"
docker compose stop
