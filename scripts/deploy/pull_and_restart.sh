#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/trading-platform}"
SOURCE_DIR="${SOURCE_DIR:-${DEPLOY_ROOT}/src}"
BRANCH="${BRANCH:-main}"
ENV_FILE="${ENV_FILE:-${DEPLOY_ROOT}/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-${DEPLOY_ROOT}/docker-compose.yml}"

if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
  echo "Missing git checkout in ${SOURCE_DIR}. Run deploy_backend.sh first."
  exit 1
fi

git -C "${SOURCE_DIR}" fetch --all --prune
git -C "${SOURCE_DIR}" checkout "${BRANCH}"
git -C "${SOURCE_DIR}" pull --ff-only origin "${BRANCH}"

cp "${SOURCE_DIR}/deploy/oracle/docker-compose.yml" "${COMPOSE_FILE}"
cp "${SOURCE_DIR}/deploy/oracle/caddy/Caddyfile" "${DEPLOY_ROOT}/caddy/Caddyfile"
cp "${SOURCE_DIR}/deploy/oracle/redis/redis.conf" "${DEPLOY_ROOT}/redis/redis.conf"
cp "${SOURCE_DIR}/deploy/oracle/prometheus/prometheus.yml" "${DEPLOY_ROOT}/prometheus/prometheus.yml"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --remove-orphans

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
