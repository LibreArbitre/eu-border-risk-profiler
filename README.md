# EU Border Risk Profiler

The EU Border Risk Profiler is a containerized proof of concept that forecasts short-term operational pressure at EU borders.
It harvests Eurostat asylum application data, computes weighted risk scores, trains a lightweight forecasting model, and exposes
results through a FastAPI backend and Streamlit dashboard. Docker Compose orchestrates the database, data pipelines, API, and
visualization layers end to end.

## Architecture at a glance
- **PostgreSQL (`db`)**: Stores raw asylum data (`asylum_data`) and predicted risk scores (`risk_prediction`).
- **Data Harvester (`data_harvester`)**: Pulls `migr_asyappctzm` from Eurostat, cleans and normalizes the series, and loads the
  database. Built-in retry/backoff logic and health checks harden network and database operations.
- **Risk Predictor (`risk_predictor`)**: Calculates a weighted border risk score and generates three-month forecasts, persisting
the results back to PostgreSQL.
- **API Service (`api_service`)**: FastAPI application exposing REST endpoints (`/api/v1/risk/current`,
  `/api/v1/risk/predict`) plus a Swagger UI at `/docs`.
- **Dashboard (`dashboard`)**: Streamlit UI consuming the API to visualize current and projected risk levels, with hooks for
  heatmap-style views.

## Quick start
1. Ensure Docker and Docker Compose are installed.
2. From the repository root, start the stack:
   ```bash
   docker-compose up --build
   ```
3. Wait until all services report as **healthy** in `docker ps`.
4. Explore the platform:
   - API health: `http://localhost:8000/health`
   - Swagger UI: `http://localhost:8000/docs`
   - Dashboard: `http://localhost:8501`

## Data flow
1. The harvester fetches the latest asylum application figures, cleans them, and populates `asylum_data`.
2. The predictor ingests that history, computes current risk scores, and generates M+1 to M+3 forecasts stored in
   `risk_prediction`.
3. The API reads from PostgreSQL to serve JSON responses for current scores and predictions.
4. The dashboard calls the API to render tables and visualizations for analysts.

## Configuration highlights
- Credentials and connection details are managed via environment variables (`DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`).
- Resilience controls for harvester and predictor: `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`, `EXIT_ON_FAILURE`,
  and health file paths (`HARVESTER_HEALTH_FILE`, `PREDICTOR_HEALTH_FILE`).
- API health probe endpoint configurable with `API_HEALTH_URL`.
- Adjust exposed ports in `docker-compose.yml` if conflicts arise (`5432`, `8000`, `8501`).

## Operations
For end-to-end runbooks, health verification steps, and troubleshooting guidance, see the dedicated
[`OPERATIONS_GUIDE.md`](OPERATIONS_GUIDE.md).

## Implementation status
A cross-check of repository assets against the agreed implementation plan is available in
[`IMPLEMENTATION_PLAN_STATUS.md`](IMPLEMENTATION_PLAN_STATUS.md). It highlights completed deliverables and the remaining testing gap.
