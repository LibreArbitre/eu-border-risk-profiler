# 🤖 Architecture du Projet : EU Border Risk Profiler - AGENTS.md

Ce document décrit les principaux composants logiciels (Agents) et leurs interactions au sein du projet. L'architecture est orientée vers la conteneurisation (Docker) et l'exécution asynchrone pour la gestion des données à grande échelle.

---

## 🎯 Objectif Principal

Développer un outil de **Prédiction de Risque aux Frontières de l'UE** basé sur les données d'asile mensuelles d'Eurostat (`migr_asyappctzm`), utilisant l'IA pour anticiper les tendances.

## 🛠️ Agents Logiciels et Rôles

Le système est divisé en trois agents principaux communiquant via la base de données et l'API.

### 1. Agent: Data_Harvester (Agent de Récolte de Données)

| Rôle | Tâches Principales | Technologies Clés |
| :--- | :--- | :--- |
| **Extraction & Nettoyage** | 1. Interroger l'API JSON-stat d'Eurostat (`migr_asyappctzm`). | **Python**, `requests` |
| | 2. Filtrer les dimensions (Ex: Primo-demandeurs, 5 dernières années). | **Pandas** |
| | 3. Nettoyer les données (gestion des valeurs manquantes, conversion des types). | **Pandas** |
| | 4. Stocker les séries temporelles nettoyées dans la BDD. | **SQLAlchemy** / PostgreSQL |
| **Fréquence** | Exécution planifiée (quotidienne ou hebdomadaire). | **Cronjob** / Docker Compose |

### 2. Agent: Risk_Predictor (Agent de Prédiction de Risques)

| Rôle | Tâches Principales | Technologies Clés |
| :--- | :--- | :--- |
| **Analyse** | 1. Récupérer les données brutes nettoyées de la BDD. | **Python**, `SQLAlchemy` |
| | 2. Calculer le **Score de Risque Frontalier** (formule pondérée interne) par pays/mois. | **NumPy**, **Pandas** |
| **Modélisation (IA)** | 3. Entraîner le modèle de prédiction (ex: $Scikit-learn$ ou $Prophet$) sur les données historiques. | **Scikit-learn** ou **Prophet** |
| | 4. Générer la prédiction des Scores de Risque pour les 3 prochains mois ($M+1, M+2, M+3$). | **Scikit-learn** |
| | 5. Stocker les résultats du Score et de la Prédiction dans la BDD. | **SQLAlchemy** / PostgreSQL |

### 3. Agent: API_Service (Agent de Service Web)

| Rôle | Tâches Principales | Technologies Clés |
| :--- | :--- | :--- |
| **Backend** | 1. Exposer une API REST simple pour l'accès aux données. | **FastAPI** |
| | 2. Points de terminaison : `/api/v1/risk/current` (Score le plus récent), `/api/v1/risk/predict` (Prédictions). | **Pydantic** |
| **Visualisation (Frontend)** | 3. Servir un tableau de bord web pour la visualisation. | **Streamlit** ou **Dash** |
| | 4. Afficher la carte de chaleur des scores de risque prédits. | **Plotly** / $Folium$ |

---

## ⚙️ Exigences d'Implémentation

* **Conteneurisation :** Tous les agents doivent être conteneurisés individuellement.
* **Orchestration :** Utilisation de **`docker-compose.yml`** pour définir et démarrer les services (Database, Data\_Harvester, Risk\_Predictor, API\_Service).
* **Base de Données :** PostgreSQL est la base recommandée pour la gestion des séries temporelles.