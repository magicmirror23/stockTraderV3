#!/usr/bin/env bash
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/trading-platform}"
SOURCE_DIR="${SOURCE_DIR:-${DEPLOY_ROOT}/src}"
BRANCH="${BRANCH:-main}"
REPO_URL="${REPO_URL:-}"
ENV_FILE="${ENV_FILE:-${DEPLOY_ROOT}/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-${DEPLOY_ROOT}/docker-compose.yml}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Install Docker first."
  exit 1
fi

mkdir -p "${DEPLOY_ROOT}" "${SOURCE_DIR}"

if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
  if [[ -z "${REPO_URL}" ]]; then
    echo "REPO_URL is required for first-time deploy."
    exit 1
  fi
  git clone --branch "${BRANCH}" "${REPO_URL}" "${SOURCE_DIR}"
else
  git -C "${SOURCE_DIR}" fetch --all --prune
  git -C "${SOURCE_DIR}" checkout "${BRANCH}"
  git -C "${SOURCE_DIR}" pull --ff-only origin "${BRANCH}"
fi

mkdir -p \
  "${DEPLOY_ROOT}/caddy" \
  "${DEPLOY_ROOT}/redis" \
  "${DEPLOY_ROOT}/prometheus" \
  "${DEPLOY_ROOT}/models" \
  "${DEPLOY_ROOT}/data/storage" \
  "${DEPLOY_ROOT}/backups" \
  "${DEPLOY_ROOT}/scripts"

cp "${SOURCE_DIR}/deploy/oracle/docker-compose.yml" "${COMPOSE_FILE}"
cp "${SOURCE_DIR}/deploy/oracle/caddy/Caddyfile" "${DEPLOY_ROOT}/caddy/Caddyfile"
cp "${SOURCE_DIR}/deploy/oracle/redis/redis.conf" "${DEPLOY_ROOT}/redis/redis.conf"
cp "${SOURCE_DIR}/deploy/oracle/prometheus/prometheus.yml" "${DEPLOY_ROOT}/prometheus/prometheus.yml"
cp "${SOURCE_DIR}/scripts/deploy/pull_and_restart.sh" "${DEPLOY_ROOT}/scripts/pull_and_restart.sh"
cp "${SOURCE_DIR}/scripts/deploy/backup_postgres.sh" "${DEPLOY_ROOT}/scripts/backup_postgres.sh"
chmod +x "${DEPLOY_ROOT}/scripts/pull_and_restart.sh" "${DEPLOY_ROOT}/scripts/backup_postgres.sh"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${SOURCE_DIR}/.env.production.example" "${ENV_FILE}"
  echo "Created ${ENV_FILE}. Fill secrets and rerun."
  exit 1
fi

if [[ "${RUN_MIGRATIONS:-false}" == "true" ]] && [[ -n "${MIGRATION_CMD:-}" ]]; then
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" run --rm api-gateway bash -lc "${MIGRATION_CMD}"
fi

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull --ignore-pull-failures
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --remove-orphans

echo
echo "Service status:"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps

echo
echo "Gateway health check:"
curl -fsS http://127.0.0.1/api/v1/health || {
  echo "Gateway health check failed."
  exit 1
}

echo
echo "Deployment complete."
