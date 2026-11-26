#!/bin/sh
# Loads the example data (a week of POS days, the owner's day, products running low) into a FRESH install.
# The app must be running (./start.sh). Nothing is needed on this computer besides Docker.
set -eu
cd "$(dirname "$0")"

if [ -z "${BAR_ADMIN_PASSWORD:-}" ]; then
  BAR_ADMIN_PASSWORD=$(sed -n 's/^INITIAL_ADMIN_PASSWORD=\(..*\)$/\1/p' .env 2>/dev/null | head -n 1)
fi
if [ -z "${BAR_ADMIN_PASSWORD:-}" ]; then
  printf "Password of the user 'admin': "
  stty -echo 2>/dev/null || true
  read -r BAR_ADMIN_PASSWORD
  stty echo 2>/dev/null || true
  echo
fi
export BAR_ADMIN_PASSWORD

# Git Bash on Windows: Docker needs C:/... rather than /c/..., and MSYS must not rewrite /examples/... into a Windows
# path. Both are no-ops on Linux and macOS.
here=$(pwd -W 2>/dev/null || pwd)
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
docker compose run --rm --no-deps -e BAR_ADMIN_PASSWORD -v "$here/examples:/examples:ro" \
  backend python /examples/load_examples.py http://web
