-- Fichier: db_init/db_schema.sql

-- TABLE 1: Données brutes d'asile (alimentée par Data_Harvester)
CREATE TABLE IF NOT EXISTS asylum_data (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    geo_code VARCHAR(10) NOT NULL,       -- Code Pays (e.g., FR, DE)
    citizen_code VARCHAR(10) NOT NULL,   -- Code Nationalité
    applicant_type VARCHAR(50) NOT NULL, -- Type de demandeur (e.g., FIRST_TIME)
    total_applications INTEGER,          -- Nombre total de demandes
    extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexation pour optimiser la recherche de données brutes
CREATE UNIQUE INDEX idx_unique_data ON asylum_data (date, geo_code, citizen_code, applicant_type);


-- TABLE 2: Scores de risque et Prédictions (alimentée par Risk_Predictor)
CREATE TABLE IF NOT EXISTS model_registry (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(100) NOT NULL,            -- Nom logique du modèle (ex: random_forest_risk)
    geo_code VARCHAR(10) NOT NULL,               -- Portée du modèle (par pays)
    model_version VARCHAR(50) NOT NULL,          -- Version générée à l'entraînement
    trained_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hyperparameters JSONB,                       -- Hyperparamètres utilisés lors de l'entraînement
    model_artifact BYTEA NOT NULL                -- Binaire sérialisé du modèle (pickle)
);

CREATE UNIQUE INDEX idx_model_registry_geo_version ON model_registry (model_name, geo_code, model_version);

CREATE TABLE IF NOT EXISTS risk_predictions (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,                          -- Date de la donnée source (Mois Analysé)
    geo_code VARCHAR(10) NOT NULL,
    risk_score_calculated NUMERIC(5, 2) NOT NULL, -- Score de risque pondéré (0.00 à 100.00)
    prediction_target_month DATE NOT NULL,       -- Mois prédit (M+1, M+2, M+3)
    predicted_risk_score NUMERIC(5, 2),           -- Médiane des arbres (point estimate)
    predicted_risk_score_p10 NUMERIC(5, 2),       -- 10e percentile des arbres (borne basse)
    predicted_risk_score_p90 NUMERIC(5, 2),       -- 90e percentile des arbres (borne haute)
    model_id INTEGER REFERENCES model_registry(id), -- Identifiant du modèle utilisé
    prediction_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_id VARCHAR(64) NOT NULL
);

-- Migration sûre pour les bases déjà initialisées : ajoute les colonnes si elles
-- manquent. Pas d'effet si elles existent déjà.
ALTER TABLE risk_predictions
    ADD COLUMN IF NOT EXISTS predicted_risk_score_p10 NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS predicted_risk_score_p90 NUMERIC(5, 2);

-- Index pour optimiser la recherche par pays et par date de prédiction
CREATE UNIQUE INDEX idx_unique_prediction ON risk_predictions (run_id, geo_code, prediction_target_month);
CREATE INDEX idx_predictions_snapshot_date ON risk_predictions (prediction_date);