# eu-border-risk-profiler
AI-powered PoC to forecast EU Border Risk Scores. Integrates Eurostat asylum data with a Python/ML model to predict operational pressure M+3. Uses Docker, FastAPI, and PostgreSQL.

## Résilience des services

Les agents de récolte (`data_harvester`) et de prédiction (`risk_predictor`) appliquent désormais des stratégies de retry avec backoff exponentiel sur les appels réseaux et base de données. Les paramètres peuvent être ajustés via variables d'environnement :

- `RETRY_MAX_ATTEMPTS` (défaut `3`) : nombre maximum de tentatives avant de considérer l'opération en échec.
- `RETRY_BACKOFF_SECONDS` (défaut `2`) : délai initial avant retry, doublé après chaque tentative.
- `EXIT_ON_FAILURE` (défaut `true`) : force l'arrêt du conteneur après un échec de job afin que Docker Compose puisse le redémarrer.
- `HARVESTER_HEALTH_FILE` / `PREDICTOR_HEALTH_FILE` : chemin du fichier d'état utilisé par les sondes de santé internes.

Des sondes `healthcheck` Docker Compose vérifient l'état écrit par chaque service (`python /app/<service>.py --healthcheck`). En cas d'échec persistant malgré les retries, le job journalise l'erreur et le conteneur se termine avec un code non nul, permettant à Docker de le relancer.
