#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo 'ERROR: Docker not installed'; exit 1; }
docker compose version >/dev/null || { echo 'ERROR: Docker Compose plugin missing'; exit 1; }
if [[ ! -f .env ]]; then
  cp .env.example .env
  pass="$( (openssl rand -hex 20 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(20))') )"
  sed -i "s/REPLACE_WITH_STRONG_UNIQUE_PASSWORD/$pass/" .env
  chmod 600 .env
  echo 'Created .env with a randomly generated password.'
fi
if ! grep -q '^CONSOLE_UID=' .env; then printf '\nCONSOLE_UID=%s\nCONSOLE_GID=%s\n' "$(id -u)" "$(id -g)" >> .env; fi
mkdir -p data/runs
if grep -q 'REPLACE_WITH_STRONG_UNIQUE_PASSWORD' .env; then
  echo 'ERROR: Configure MUJOCO_CONSOLE_PASSWORD in .env first.'; exit 1
fi
docker compose up -d --build
port="$(grep -E '^CONSOLE_PORT=' .env | tail -1 | cut -d= -f2)"; port="${port:-8000}"
echo "Service URL: http://<UBUNTU-LAN-IP>:${port}"
echo 'LAN IPv4 addresses:'
hostname -I || true
echo "Login password is in $(pwd)/.env (keep it private)."
echo 'Use docker compose logs -f console to inspect startup errors.'
