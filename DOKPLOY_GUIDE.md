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
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_SECONDS=2
EXIT_ON_FAILURE=true
```

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

**Swagger UI:**
Open `https://your-domain.com:8000/docs` in your browser.

**Streamlit Dashboard:**
Open `https://your-domain.com:8501` in your browser.

#### 5. Check Logs in Dokploy

If a service fails to start, check the logs:

1.  **db**: Should show `database system is ready to accept connections`
2.  **data_harvester**: Look for `Fetching data from Eurostat...` then `Data saved successfully`
3.  **risk_predictor**: Look for `Processing X countries...` then `Predictions saved`
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

### 📝 Recommended Next Steps
1.  **Security**: Change default PostgreSQL password
2.  **Monitoring**: Add alerts on health checks
3.  **Backup**: Configure regular PostgreSQL backups
4.  **Performance**: Add Redis cache for API if needed
