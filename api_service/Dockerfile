FROM python:3.11-slim-bookworm

# Keep application code under a dedicated package directory so module imports work
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Place the source code in /app/api_service so `api_service` is an importable package
COPY . /app/api_service

# Ensure the package is discoverable on PYTHONPATH for uvicorn and health checks
ENV PYTHONPATH=/app