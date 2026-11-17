#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo 'ERROR: Docker is not installed'; exit 1; }
docker compose version >/dev/null 2>&1 || { echo 'ERROR: Docker Compose v2 plugin is missing'; exit 1; }
command -v python3 >/dev/null || { echo 'ERROR: python3 is required to generate a password'; exit 1; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  password="$(openssl rand -hex 20 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(20))')"
  sed -i "s/REPLACE_WITH_STRONG_UNIQUE_PASSWORD/$password/" .env
  echo 'Created .env with a randomly generated password.'
fi

append_env_if_missing() {
  local key="$1"
  local value="$2"
  if ! grep -q "^${key}=" .env; then
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}
append_env_if_missing CONSOLE_UID "$(id -u)"
append_env_if_missing CONSOLE_GID "$(id -g)"
chmod 600 .env
mkdir -p data/runs

password_value="$(sed -n 's/^MUJOCO_CONSOLE_PASSWORD=//p' .env | tail -1)"
if [[ -z "$password_value" || "$password_value" == 'REPLACE_WITH_STRONG_UNIQUE_PASSWORD' ]]; then
  echo 'ERROR: Set a non-empty MUJOCO_CONSOLE_PASSWORD in .env.' >&2
  exit 1
fi

port="$(sed -n 's/^CONSOLE_PORT=//p' .env | tail -1)"
port="${port:-8000}"
if ! [[ "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  echo 'ERROR: CONSOLE_PORT must be an integer between 1 and 65535.' >&2
  exit 1
fi

docker compose config --quiet
docker compose up -d --build

echo 'Waiting for the console health check...'
health=''
for _ in {1..60}; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' mujoco-console 2>/dev/null || true)"
  if [[ "$health" == 'healthy' ]]; then
    break
  fi
  if [[ "$health" == 'unhealthy' || "$health" == 'exited' ]]; then
    break
  fi
  sleep 2
done

if [[ "$health" != 'healthy' ]]; then
  echo "ERROR: Console did not become healthy (state: ${health:-unknown})." >&2
  docker compose logs --tail=120 console || true
  exit 1
fi

echo "Service URL: http://<UBUNTU-LAN-IP>:${port}"
echo 'LAN IPv4 addresses:'
hostname -I || true
echo "Login password is stored in $(pwd)/.env (keep it private)."
echo 'Useful commands: docker compose ps; docker compose logs -f console'
