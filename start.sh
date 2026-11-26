#!/bin/sh
# Starts Bar Inventory on this computer (Linux / macOS). On the first run creates .env with random secrets.
set -eu
cd "$(dirname "$0")"

secret() {  # $1 random bytes, URL-safe characters only
  head -c "$1" /dev/urandom | base64 | tr -d '\n+/='
}

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running (or not installed). Install Docker Engine + Compose (Linux) or Docker Desktop (macOS),"
  echo "start it, and run ./start.sh again. On Linux your user may need to be in the 'docker' group."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "The Docker Compose plugin is missing ('docker compose'). Install it and run ./start.sh again."
  exit 1
fi

if [ ! -f .env ]; then
  sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret 24)|" \
      -e "s|^JWT_SECRET=.*|JWT_SECRET=$(secret 48)|" \
      -e "s|^INITIAL_ADMIN_PASSWORD=.*|INITIAL_ADMIN_PASSWORD=$(secret 12)|" \
      .env.example > .env
  chmod 600 .env
  echo "Created .env with random secrets."
fi

# Compose prefers HTTP_PORT from the environment over .env: do the same.
port=${HTTP_PORT:-$(sed -n 's/^HTTP_PORT=\([0-9][0-9]*\).*/\1/p' .env | head -n 1)}
url="http://localhost:${port:-8080}"

echo "Starting the app (the first start builds it and takes a few minutes)..."
docker compose up -d --build

printf 'Waiting for %s ' "$url"
i=0
until curl -fsS "$url/api/health" >/dev/null 2>&1 || wget -q -O /dev/null "$url/api/health" 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 90 ]; then
    echo
    echo "The app did not answer at $url. See: docker compose logs backend"
    exit 1
  fi
  printf '.'
  sleep 2
done
echo

echo "Bar Inventory is running: $url"
pw=$(sed -n 's/^INITIAL_ADMIN_PASSWORD=\(..*\)$/\1/p' .env | head -n 1)
if [ -n "$pw" ]; then
  echo
  echo "First sign-in: user 'admin', password: $pw"
  echo "After signing in, change it ('Change password' at the bottom of the left menu),"
  echo "then delete the value after INITIAL_ADMIN_PASSWORD= in .env. This reminder disappears once it is deleted."
fi
