# Operations Guide

This guide explains how to operate the EU Border Risk Profiler once `docker-compose` has started the stack.
It covers service validation, common workflows, and troubleshooting tips for running the platform in a containerized environment.

## 1. Verify the stack
1. Run `docker-compose up --build` from the repository root.
2. Confirm all containers are healthy:
   - Database: `docker ps --filter name=eu_brp_db --format '{{.Names}}: {{.Status}}'`
   - Harvester: `docker ps --filter name=eu_brp_harvester --format '{{.Names}}: {{.Status}}'`
   - Predictor: `docker ps --filter name=eu_brp_predictor --format '{{.Names}}: {{.Status}}'`
   - API: `docker ps --filter name=eu_brp_api --format '{{.Names}}: {{.Status}}'`
   - Dashboard: `docker ps --filter name=eu_brp_dashboard --format '{{.Names}}: {{.Status}}'`
3. If a service restarts, inspect logs with `docker logs <container_name>` to understand the retry/backoff cycle.

## 2. Validate database readiness
- Connect to PostgreSQL from your host: `psql -h localhost -p 5432 -U user -d eubrp_db` (credentials follow environment variables in `docker-compose.yml`).
- Check tables:
  - `\dt` should list `asylum_data` and `risk_prediction`.
  - `SELECT COUNT(*) FROM asylum_data;` confirms ingestion.
  - `SELECT * FROM risk_prediction ORDER BY prediction_date DESC LIMIT 5;` validates predictor output.

## 3. Exercise the API
- Base URL: `http://localhost:8000`.
- Health check: `curl http://localhost:8000/health`.
- Current scores: `curl http://localhost:8000/api/v1/risk/current`.
- Forward predictions: `curl http://localhost:8000/api/v1/risk/predict`.
- Interactive docs: open `http://localhost:8000/docs` for the FastAPI Swagger UI.

## 4. Use the dashboard
- Navigate to `http://localhost:8501` to open the Streamlit dashboard.
- Refresh the dashboard after a new harvest/prediction cycle to reflect updated metrics.
- If the dashboard fails to load data, ensure the `API_URL` environment variable is set to `http://api_service:8000` inside Compose or `http://localhost:8000` when running locally.

## 5. Rerun data pipelines
- To rerun only the harvester: `docker-compose run --rm data_harvester`.
- To rerun only the predictor: `docker-compose run --rm risk_predictor`.
- Each job writes a health file (`HARVESTER_HEALTH_FILE`, `PREDICTOR_HEALTH_FILE`) and exits non-zero on failure so Compose can restart it.

## 6. Environment configuration
Key environment variables (override in a `.env` file or directly in Compose):
- `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`
- `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`, `EXIT_ON_FAILURE`
- `HARVESTER_HEALTH_FILE`, `PREDICTOR_HEALTH_FILE`
- `API_HEALTH_URL` (for the API service health probe)

## 7. Troubleshooting
- **Database connection errors**: Verify PostgreSQL is healthy and credentials match. Restart dependent services after fixing credentials.
- **Empty predictions**: Ensure the harvester completed successfully; the predictor depends on harvested data.
- **Health checks failing**: Inspect the health file paths and container logs. Increase retry intervals with `RETRY_BACKOFF_SECONDS` if needed.
- **Port conflicts**: If ports `5432`, `8000`, or `8501` are busy on the host, edit `docker-compose.yml` to remap the exposed ports.

## 8. Shutdown and cleanup
- Stop services: `docker-compose down`.
- Remove persisted data (destructive): `docker-compose down -v` to drop the `db_data` volume and start fresh.
