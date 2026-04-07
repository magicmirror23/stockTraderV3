# Oracle Cloud Always Free ARM Deployment (FastAPI Microservices)

This guide deploys the backend stack on OCI Ubuntu ARM (VM.Standard.A1.Flex) using Docker Compose.

## 1. Minimum Viable Production Stack (Phase 1)

Mandatory:
- `reverse-proxy` (Caddy)
- `api-gateway`
- `market-data`
- `prediction` (inference-only)
- `trading`
- `portfolio-risk`
- `admin-backtest`
- `postgres`
- `redis`

Optional (Phase 2 profiles):
- `rabbitmq` (`--profile queue`)
- `prometheus` + `grafana` (`--profile monitoring`)

## 2. OCI Provisioning Checklist

1. Create instance:
   - Shape: `VM.Standard.A1.Flex` (ARM64)
   - OS: Ubuntu LTS
   - Public subnet with internet route
2. Attach/assign public IP (ephemeral or reserved).
3. Update OCI ingress rules (Security List or NSG):
   - Allow TCP `22` from your admin IP only
   - Allow TCP `80` from `0.0.0.0/0`
   - Allow TCP `443` from `0.0.0.0/0`
   - Do **not** open `5432`, `6379`, `5672`, `15672`, `8000+`
4. SSH in:
   ```bash
   ssh ubuntu@<PUBLIC_IP>
   ```

## 3. Server Bootstrap (Ubuntu ARM)

Run as root once:
```bash
sudo -i
cd /tmp
git clone <YOUR_REPO_URL> trading-platform
cd trading-platform
bash scripts/server/bootstrap_oracle_ubuntu.sh
```

What this does:
- OS updates + essentials
- creates deploy user
- SSH hardening basics
- swap setup
- Docker Engine + Compose plugin
- UFW rules (`22`, `80`, `443`)
- creates `/opt/trading-platform/*` layout

## 4. Deployment Directory Layout

```text
/opt/trading-platform/
  docker-compose.yml
  .env.production
  src/                      # git checkout
  caddy/Caddyfile
  redis/redis.conf
  prometheus/prometheus.yml
  scripts/
  models/                   # model_v001/... artifacts
  data/storage/
  backups/
```

## 5. First Deploy

As deploy user:
```bash
sudo su - deploy
git clone <YOUR_REPO_URL> ~/trading-platform-bootstrap
cd ~/trading-platform-bootstrap
export REPO_URL=<YOUR_REPO_URL>
export BRANCH=main
bash scripts/deploy/deploy_backend.sh
```

If this is the first run, it creates `/opt/trading-platform/.env.production` from `.env.production.example` and exits.

Edit env file, then rerun deploy:
```bash
nano /opt/trading-platform/.env.production
bash /opt/trading-platform/src/scripts/deploy/deploy_backend.sh
```

## 6. Systemd Auto-start on Reboot

Install service:
```bash
sudo cp /opt/trading-platform/src/deploy/oracle/systemd/trading-backend.service /etc/systemd/system/trading-backend.service
sudo systemctl daemon-reload
sudo systemctl enable trading-backend.service
sudo systemctl start trading-backend.service
sudo systemctl status trading-backend.service
```

## 7. TLS and Domain

### HTTP bootstrap (no domain yet)
- Set in `.env.production`:
  - `CADDY_SITE_ADDRESS=:80`
- Access using `http://<PUBLIC_IP>/api/v1/health`

### Enable HTTPS later
1. Point DNS A record to OCI public IP.
2. Set:
   - `CADDY_SITE_ADDRESS=api.yourdomain.com`
   - `TLS_EMAIL=you@example.com`
3. Redeploy:
   ```bash
   bash /opt/trading-platform/scripts/pull_and_restart.sh
   ```
Caddy will automatically provision and renew certificates.

## 8. Model Artifact Deployment (Inference-Only)

Copy trained bundles to:
```text
/opt/trading-platform/models/model_v001/
  model.pkl
  scaler.pkl
  feature_columns.json
  metadata.json
  metrics.json
```

Set:
- `INFERENCE_ONLY=true`
- `ALLOW_PROD_RETRAIN=false`
- `MODEL_REGISTRY_DIR=/opt/models`

Prediction service model endpoints:
- `GET /api/v1/model/status`
- `GET /api/v1/model/metadata`
- `POST /api/v1/model/reload`
- `POST /api/v1/model/activate-version`

## 9. Verification Checklist

Run:
```bash
docker compose --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml ps
curl -fsS http://127.0.0.1/api/v1/health
```

Verify:
- reverse proxy reachable on public IP/domain
- gateway `/api/v1/health` returns healthy/degraded JSON
- `postgres` is healthy
- `redis` is healthy
- prediction model status endpoint works
- reboot test:
  ```bash
  sudo reboot
  # after reconnect
  systemctl status trading-backend.service
  docker compose --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml ps
  ```
- internal services are **not** exposed (`ss -tulpen` should show only 22/80/443 publicly)

## 10. Logs and Basic Observability

```bash
docker compose --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml logs -f api-gateway
docker compose --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml logs -f prediction
```

Optional:
- Queue profile:
  ```bash
  docker compose --profile queue --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml up -d
  ```
- Monitoring profile:
  ```bash
  docker compose --profile monitoring --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml up -d
  ```
  Access through SSH tunnel for safety:
  - Grafana `127.0.0.1:3000`
  - Prometheus `127.0.0.1:9090`

## 11. Backup and Restore

Backup:
```bash
bash /opt/trading-platform/scripts/backup_postgres.sh
```

Restore example:
```bash
gunzip -c /opt/trading-platform/backups/postgres/postgres_stocktrader_<STAMP>.sql.gz | \
docker compose --env-file /opt/trading-platform/.env.production -f /opt/trading-platform/docker-compose.yml exec -T postgres \
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

## 12. Rollback Instructions

1. Go to source checkout:
   ```bash
   cd /opt/trading-platform/src
   ```
2. Checkout previous known-good commit/tag:
   ```bash
   git checkout <GOOD_COMMIT_OR_TAG>
   ```
3. Redeploy:
   ```bash
   bash /opt/trading-platform/scripts/pull_and_restart.sh
   ```
4. Verify health endpoint + compose status.

## 13. ARM64 Notes

- Base images used are multi-arch ARM64 compatible (`python:3.12-slim`, `postgres:16-alpine`, `redis:7-alpine`, `caddy:2.8-alpine`).
- Keep worker counts low (defaults = 1) to avoid memory pressure.
- Use inference-only in production to avoid heavy training dependencies/CPU spikes.
- Do not run all optional profiles unless you have confirmed memory headroom.
