# Quick Start Guide - Dokploy

## 🚀 Deployment on Dokploy

### Prerequisites
- Dokploy installed and running.
- Ports `5432`, `8000`, `8501` available (or modified in `docker-compose.yml`).

### Deployment Steps

#### 1. Create a New Project in Dokploy
```bash
# If using Git, push the project to your repository
git add .
git commit -m "Initial commit - EU Border Risk Profiler"
git push origin main
```

#### 2. Configure Environment Variables in Dokploy

In the Dokploy interface, configure the following variables:

**Mandatory Variables:**
```
DB_USER=eubrp_user
DB_PASSWORD=CHANGE_ME_WITH_A_STRONG_PASSWORD
DB_NAME=eubrp_db
DB_HOST=db
```

**Optional Variables (with defaults):**
```
# Scheduler timezone (default Europe/Paris). The harvester runs daily at
# 02:00 and the predictor at 03:00 in this zone. Pick UTC if your VPS is
# UTC and you want predictable scheduling.
TZ=Europe/Paris

# Resilience knobs
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_SECONDS=2
EXIT_ON_FAILURE=true

# API authentication (recommended on a public VPS).
# Leave empty to keep the API open. When set, every protected endpoint
# requires the same value in the X-API-Key header. The bundled dashboard
# reads API_KEY automatically and forwards it.
# Generate a value with: python -c "import secrets; print(secrets.token_urlsafe(32))"
API_KEY=
```

> **Database port binding.** `docker-compose.yml` exposes Postgres on
> `127.0.0.1:5432`, i.e. only on the VPS loopback. Other Dokploy
> containers in the same project network reach it via `db:5432` regardless
> of this binding. Dokploy's reverse proxy (Traefik) handles HTTP routing
> for `api_service` (port 8000) and `dashboard` (port 8501) — you usually
> won't need to expose either of those directly either; map them to a
> domain in the Dokploy UI instead.

#### 3. Service Startup Order

Services automatically start in the following order thanks to `depends_on`:

1.  **db** (PostgreSQL) - starts first
2.  **data_harvester** - waits for DB to be healthy
3.  **risk_predictor** - waits for harvester to succeed
4.  **api_service** - waits for predictor to succeed
5.  **dashboard** - waits for API to be healthy

#### 4. Verify Functionality

Once deployed, verify the services:

**API Health Check:**
```bash
curl https://your-domain.com:8000/health
# Should return: {"status":"ok"}
```

`/health` stays public even when `API_KEY` is set. Protected endpoints
return `401` without the matching header:
```bash
curl -H "X-API-Key: $API_KEY" https://your-domain.com:8000/api/v1/risk/predict
```

**Swagger UI:**
Open `https://your-domain.com:8000/docs` in your browser.

**Streamlit Dashboard:**
Open `https://your-domain.com:8501` in your browser.

#### 5. Check Logs in Dokploy

If a service fails to start, check the logs:

1.  **db**: Should show `database system is ready to accept connections`
2.  **data_harvester**: Look for `Downloading Eurostat TSV bulk file...`,
    `Staging table asylum_data_staging prepared.`, then
    `Staging promoted to asylum_data atomically.` and finally
    `HARVEST COMPLETED SUCCESSFULLY`. The harvester writes
    `/tmp/harvester_health` after each successful cycle and the docker
    healthcheck verifies that file is younger than
    `HARVESTER_HEALTH_MAX_AGE_SECONDS` (default 25 h).
3.  **risk_predictor**: Look for `Trained and persisted model X for ...`
    or `Model X for ... reused (signature=...)`, then `Predictions saved
    for run ...`. Logs include `train_mae` and `test_mae` (honest hold-out
    error) when a model is retrained.
4.  **api_service**: Should show `Application startup complete`
5.  **dashboard**: Should show `You can now view your Streamlit app in your browser`

### 🔍 Troubleshooting Common Issues

#### Issue: Harvester does not start
**Symptom:** `data_harvester` container in restart loop
**Solutions:**
1.  Verify PostgreSQL is accessible: `docker logs eu_brp_db`
2.  Check DB credentials in environment variables
3.  Manually test connection: `docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT 1"`

#### Issue: Predictor crashes on startup
**Symptom:** `risk_predictor` container exits with functionality
**Checks:**
1.  Check predictor logs: `docker logs eu_brp_predictor`
2.  Verify data presence: `docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT COUNT(*) FROM asylum_data"`

#### Issue: API unresponsive
**Symptom:** Timeout or 502 Bad Gateway
**Solutions:**
1.  Verify predictor finished successfully
2.  Check API logs: `docker logs eu_brp_api`
3.  Test from inside Docker network: `docker exec eu_brp_api curl http://localhost:8000/health`

#### Issue: Dashboard not loading data
**Symptom:** "No prediction data available" message
**Solutions:**
1.  Check API accessibility from dashboard: `docker exec eu_brp_dashboard curl http://api_service:8000/api/v1/risk/latest`
2.  Wait for harvester/predictor to complete at least one full cycle (5-10 mins)
3.  Check DB data: `docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT COUNT(*) FROM risk_predictions"`

### 📊 Data Flow Understanding
`Eurostat API` -> `Harvester` -> `PostgreSQL` -> `Predictor` -> `PostgreSQL` -> `API` -> `Dashboard`

### ⏱️ Expected Wait Times
- **First Full Startup**: 10-15 minutes
    - DB Init: 30s
    - Harvester: 2-5 mins
    - Predictor: 5-10 mins
    - API/Dashboard: < 1 min
