# Deployment Guide

## 🚀 Deployment Overview

### Prerequisites
- Docker & Docker Compose installed.
- Ports `5432`, `8000`, `8501` available (or modified in `docker-compose.yml`).

### Deployment Steps

#### 1. Clone and Prepare
```bash
git clone <repository_url>
cd eu-border-risk-profiler
```

#### 2. Environment Configuration

Configure the following environment variables (either in a `.env` file or your deployment platform's secrets manager):

**Mandatory Variables:**
```
DB_USER=eubrp_user
DB_PASSWORD=CHANGE_ME_WITH_A_STRONG_PASSWORD
DB_NAME=eubrp_db
DB_HOST=db
```

**Optional Variables (with defaults):**
```
# Scheduler timezone (defaults to Europe/Paris). Drives the harvester (02:00)
# and predictor (03:00) daily run windows. Set to UTC if you prefer.
TZ=Europe/Paris

# Resilience knobs for harvester/predictor
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_SECONDS=2
EXIT_ON_FAILURE=true

# API authentication (optional, opt-in).
# Leave empty to keep the API open. When set, every protected endpoint
# requires the same value in the X-API-Key header. The bundled dashboard
# reads this same variable and forwards it automatically.
# Generate a value with: python -c "import secrets; print(secrets.token_urlsafe(32))"
API_KEY=
```

> **Note on the database port.** `docker-compose.yml` binds Postgres to
> `127.0.0.1:5432` (host loopback only). Other services in the compose
> network reach it via the internal `db` hostname regardless. Remove the
> `127.0.0.1:` prefix only if you need the database reachable on every host
> interface — which is rarely a good idea on a public server.

#### 3. Start the Stack

```bash
docker-compose up --build -d
```

**Service Startup Order:**
Services automatically start in the proper sequence:
1.  **db** (PostgreSQL) - starts first
2.  **data_harvester** - waits for DB to be healthy
3.  **risk_predictor** - waits for harvester to succeed
4.  **api_service** - waits for predictor to succeed
5.  **dashboard** - waits for API to be healthy

#### 4. Verify Functionality

Once deployed, verify the services:

**API Health Check:**
```bash
curl http://localhost:8000/health
# Should return: {"status":"ok"}
```

The `/health` endpoint stays public even when `API_KEY` is set; protected
endpoints return `401` if the header is missing or wrong:
```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/risk/predict
```

**Swagger UI:**
Open `http://localhost:8000/docs` in your browser.

**Streamlit Dashboard:**
Open `http://localhost:8501` in your browser.

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
    (add `-H "X-API-Key: $API_KEY"` if auth is enabled)
2.  Wait for harvester/predictor to complete at least one full cycle (5-10 mins)
3.  Check DB data: `docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT COUNT(*) FROM risk_predictions"`

#### Issue: Harvester reports unhealthy
**Symptom:** Container marked unhealthy after a few hours
**Cause:** The harvester health check verifies that a successful run touched
`/tmp/harvester_health` within `HARVESTER_HEALTH_MAX_AGE_SECONDS` (default
25 h). If the daily run fails repeatedly the container becomes unhealthy.
**Solutions:**
1.  Inspect the logs for the latest run: `docker logs eu_brp_harvester | tail -50`
2.  If Eurostat is unreachable, the run will retry on its next 24 h cycle.
3.  Restart the container to trigger an immediate fresh harvest if needed:
    `docker compose restart data_harvester`

### 📊 Data Flow Understanding
`Eurostat API` -> `Harvester` -> `PostgreSQL` -> `Predictor` -> `PostgreSQL` -> `API` -> `Dashboard`

### ⏱️ Expected Wait Times
- **First Full Startup**: 10-15 minutes
    - DB Init: 30s
    - Harvester: 2-5 mins
    - Predictor: 5-10 mins
    - API/Dashboard: < 1 min
