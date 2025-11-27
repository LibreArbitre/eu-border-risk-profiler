# Fonctionnement Détaillé - EU Border Risk Profiler

## 🎯 Vue d'Ensemble

Cette application analyse les données d'asile de l'Union Européenne pour **prédire les tendances futures** de pression migratoire aux frontières. Elle combine :
- **Data Engineering** : collecte et traitement de données via l'API Eurostat
- **Machine Learning** : modèle de prédiction de séries temporelles
- **Visualisation** : dashboard interactif avec cartes géographiques

## 📊 Cas d'Usage Concret

**Exemple d'utilisation :**
1. En **novembre 2024**, le système récupère les données d'asile de janvier 2020 à octobre 2024
2. Il calcule un **score de risque** pour chaque pays basé sur :
   - Le volume de demandes d'asile
   - La variation mensuelle (hausse/baisse)
3. Il **prédit** les scores de risque pour **décembre 2024, janvier 2025, février 2025**
4. Un analyste consulte le dashboard pour identifier les pays nécessitant plus de ressources

**Lien avec l'actualité :** Les demandes d'asile fluctuent selon les crises géopolitiques (guerre, catastrophes naturelles). Ce système permet d'anticiper les besoins en personnel, hébergement, etc.

---

## 🔄 Flux de Données Complet (Cycle de Vie)

### Phase 1 : Collecte de Données (Data Harvester)

**Fréquence :** Une fois par jour (2h du matin par défaut)

```
API Eurostat (publique, gratuite)
    ↓
Requête HTTP GET avec paramètres
    ↓
JSON-stat format (standard Eurostat)
    ↓
Parsing et nettoyage (pandas)
    ↓
PostgreSQL - Table: asylum_data
```

**Données récupérées :**
- **Source** : Dataset `migr_asyappctzm` (Asylum applications - monthly data)
- **Période** : 60 derniers mois (configurable via `lastTimePeriod`)
- **Granularité** : Mensuelle
- **Dimensions** :
  - Date (format : 2024M11 → 2024-11-01)
  - Code pays (FR, DE, IT, ES, etc.)
  - Type de demandeur (NASY_APP = primo-demandeurs)
  - Nombre de demandes

**Exemple de données brutes :**
| Date       | Pays | Type     | Demandes |
|------------|------|----------|----------|
| 2024-10-01 | FR   | NASY_APP | 8,245    |
| 2024-10-01 | DE   | NASY_APP | 15,320   |
| 2024-11-01 | FR   | NASY_APP | 9,100    |

**Code pertinent :** `data_harvester/harvester.py` lignes 78-154

---

### Phase 2 : Calcul du Score de Risque (Risk Predictor)

**Fréquence :** Une fois par jour (3h du matin, après le harvester)

#### Étape 2.1 : Calcul du Score de Risque

**Formule mathématique :**

```python
# Pour chaque pays et chaque mois :

# 1. Normalisation du volume (0 à 1)
vol_norm = total_applications / max_applications_historique

# 2. Calcul de la variation mensuelle
variation = (demandes_mois_actuel - demandes_mois_precedent) / demandes_mois_precedent

# 3. Score de risque pondéré (0 à 100)
risk_score = (0.4 * vol_norm + 0.6 * max(variation, 0)) * 100
```

**Explication :**
- **40% du score** = volume absolu de demandes
- **60% du score** = variation positive (hausse)
- Plus la variation est forte et positive → plus le risque est élevé
- Les variations négatives ne réduisent pas le score (clip à 0)

**Exemple :**
```
France - Octobre 2024 :
  - Demandes : 9,000
  - Max historique : 15,000
  - Demandes mois précédent : 8,000

vol_norm = 9000 / 15000 = 0.6
variation = (9000 - 8000) / 8000 = 0.125 (12.5% de hausse)

risk_score = (0.4 × 0.6 + 0.6 × 0.125) × 100
           = (0.24 + 0.075) × 100
           = 31.5
```

**Code pertinent :** `risk_predictor/risk_predictor.py` lignes 175-196

---

#### Étape 2.2 : Entraînement du Modèle ML 🤖

**TYPE DE MODÈLE : RandomForestRegressor (scikit-learn)**

⚠️ **IMPORTANT** : Ce n'est **PAS du Deep Learning** !
- Pas de réseaux de neurones
- Pas besoin de GPU (RTX 5070 Ti totalement inutile ici)
- Temps d'entraînement : **quelques secondes** sur un CPU basique
- Taille du modèle : **quelques Ko à quelques Mo**

**Paramètres du modèle :**
```python
MODEL_HYPERPARAMS = {
    "n_estimators": 50,      # 50 arbres de décision
    "random_state": 42       # Pour la reproductibilité
}
```

**Features (variables d'entrée) :**
```python
# Pour prédire le score au mois M+1 :
features = [
    lag_1,   # Score de risque au mois M (actuel)
    lag_2,   # Score de risque au mois M-1
    lag_3,   # Score de risque au mois M-2
    month    # Numéro du mois (1-12, pour capturer la saisonnalité)
]
```

**Target (variable à prédire) :**
- Le score de risque au mois suivant

**Processus d'entraînement :**
1. **Récupération de l'historique** : tous les scores de risque calculés précédemment
2. **Création des features** : décalages temporels (lags)
3. **Entraînement** : fit du RandomForest sur les données historiques
4. **Persistance** : sauvegarde du modèle dans PostgreSQL (table `model_registry`)

**Exemple de dataset d'entraînement :**
| lag_1 | lag_2 | lag_3 | month | target (score M+1) |
|-------|-------|-------|-------|-------------------|
| 28.5  | 25.3  | 22.1  | 8     | 31.2              |
| 31.2  | 28.5  | 25.3  | 9     | 35.7              |
| 35.7  | 31.2  | 28.5  | 10    | 38.4              |

**Code pertinent :** `risk_predictor/risk_predictor.py` lignes 135-154

---

#### Étape 2.3 : Persistance du Modèle (Model Registry)

**Stratégie de réentraînement : Intelligent & Optimisé**

```python
def get_or_train_model(engine, geo_code, train_df):
    # 1. Chercher un modèle existant pour ce pays
    model, model_id = load_latest_model(engine, geo_code)
    
    if model and model_id:
        # RÉUTILISER le modèle existant (pas de réentraînement)
        return model, model_id
    
    # 2. Sinon, entraîner un nouveau modèle
    model = train_model(train_df)
    model_id = persist_model(engine, geo_code, model)
    return model, model_id
```

**Comportement :**

| Scénario | Action |
|----------|--------|
| **1er run (aucun modèle)** | Entraîne un nouveau modèle et le sauvegarde |
| **Runs suivants (modèle existe)** | **RÉUTILISE** le modèle existant (pas de réentraînement) |
| **Nouveau pays détecté** | Entraîne un modèle spécifique pour ce pays |

**Stockage dans PostgreSQL :**
```sql
CREATE TABLE model_registry (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(100),           -- 'random_forest_risk'
    geo_code VARCHAR(10),              -- 'FR', 'DE', etc.
    model_version VARCHAR(50),         -- 'v20241127183000'
    trained_at TIMESTAMP,
    hyperparameters JSONB,             -- {"n_estimators": 50, ...}
    model_artifact BYTEA               -- Modèle sérialisé (pickle)
);
```

**Taille typique :** ~200-500 Ko par modèle (très léger !)

**Code pertinent :** `risk_predictor/risk_predictor.py` lignes 86-154

---

#### Étape 2.4 : Génération des Prédictions

**Objectif :** Prédire les scores de risque pour M+1, M+2, M+3

```python
# Prédiction itérative (autoregressive)

# Dernier point connu : Novembre 2024, score = 35.7
last_score = 35.7
lags = [35.7, 31.2, 28.5]  # Scores des 3 derniers mois

# Prédiction Décembre 2024 (M+1)
features_dec = [35.7, 31.2, 28.5, 12]  # month=12
pred_dec = model.predict([features_dec])  # → 38.2

# Prédiction Janvier 2025 (M+2)
lags = [38.2, 35.7, 31.2]  # Shift des lags
features_jan = [38.2, 35.7, 31.2, 1]   # month=1
pred_jan = model.predict([features_jan])  # → 39.5

# Prédiction Février 2025 (M+3)
lags = [39.5, 38.2, 35.7]
features_feb = [39.5, 38.2, 35.7, 2]   # month=2
pred_feb = model.predict([features_feb])  # → 41.1
```

**Données sauvegardées dans `risk_predictions` :**
| Date Source | Pays | Score Calculé | Mois Cible  | Score Prédit | Model ID |
|-------------|------|---------------|-------------|--------------|----------|
| 2024-11-01  | FR   | 35.7          | 2024-12-01  | 38.2         | 42       |
| 2024-11-01  | FR   | 35.7          | 2025-01-01  | 39.5         | 42       |
| 2024-11-01  | FR   | 35.7          | 2025-02-01  | 41.1         | 42       |

**Code pertinent :** `risk_predictor/risk_predictor.py` lignes 211-246

---

### Phase 3 : Exposition via API (FastAPI)

**Endpoints REST disponibles :**

```bash
# 1. Health check
GET /health
→ {"status": "ok"}

# 2. Scores de risque les plus récents (observés)
GET /api/v1/risk/latest
→ [
    {"geo_code": "FR", "risk_score": 35.7, "date": "2024-11-01", "type": "observed"},
    {"geo_code": "DE", "risk_score": 42.3, "date": "2024-11-01", "type": "observed"},
    ...
  ]

# 3. Prédictions M+1, M+2, M+3
GET /api/v1/risk/predict
→ [
    {"geo_code": "FR", "risk_score": 38.2, "date": "2024-12-01", "type": "predicted"},
    {"geo_code": "FR", "risk_score": 39.5, "date": "2025-01-01", "type": "predicted"},
    ...
  ]

# 4. Historique pour un pays spécifique
GET /api/v1/data/history/FR
→ [
    {"date": "2024-01-01", "total": 7890},
    {"date": "2024-02-01", "total": 8234},
    ...
  ]
```

**Documentation auto-générée :** `http://localhost:8000/docs` (Swagger UI)

**Code pertinent :** `api_service/main.py`

---

### Phase 4 : Visualisation (Streamlit Dashboard)

**Interface utilisateur :**

1. **Carte choroplèthe de l'Europe**
   - Couleur par intensité de risque prédit
   - Affiche M+1 par défaut
   - Basée sur Plotly (interactif)

2. **Top 10 pays à risque**
   - Classement par score moyen
   - Tableau de données

3. **Analyse par pays**
   - Sélection d'un pays
   - Graphique d'évolution historique des demandes d'asile
   - Tendance visuelle

**URL :** `http://localhost:8501`

**Code pertinent :** `api_service/dashboard.py`

---

## 🚀 Réponses à Tes Questions Spécifiques

### Q1 : Le modèle sera-t-il réentraîné avec de nouvelles données ?

**Réponse : OUI, mais intelligemment**

- **À la création (1er run)** : Entraînement complet sur tout l'historique disponible
- **Runs quotidiens suivants** : **RÉUTILISATION** du modèle existant (pas de réentraînement)
- **Raison** : Le modèle RandomForest est stable et ne nécessite pas de réentraînement fréquent
- **Exception** : Si tu supprimes explicitement la table `model_registry`, le système réentraînera

**Avantage :** Performance optimale (pas de réentraînement inutile)

**Si tu veux forcer un réentraînement :**
```sql
-- Supprimer tous les modèles
DELETE FROM model_registry;

-- Supprimer le modèle pour un pays spécifique
DELETE FROM model_registry WHERE geo_code = 'FR';
```

---

### Q2 : Dois-je entraîner sur mon PC local (AMD 5900X + RTX 5070 Ti) ?

**Réponse : NON, absolument pas ! 😄**

**Pourquoi ta RTX 5070 Ti (16 Go VRAM) est inutile ici :**

| Critère | Deep Learning | Ce Projet (ML Classique) |
|---------|---------------|--------------------------|
| Type de modèle | CNN, Transformers, LLM | RandomForest (arbres de décision) |
| Librairies | PyTorch, TensorFlow | scikit-learn |
| Utilise le GPU ? | **OUI** (indispensable) | **NON** (CPU uniquement) |
| Temps d'entraînement | Heures/jours | **Secondes** |
| Taille du modèle | Go (modèles géants) | **Ko** (quelques centaines) |
| RAM nécessaire | 16+ Go | **< 1 Go** |
| VRAM nécessaire | 8-24 Go | **0 Go** |

**Ressources réelles utilisées :**
- **CPU** : ~2-5 secondes d'utilisation (1 cœur)
- **RAM** : ~200-500 Mo
- **Stockage** : ~300 Ko par modèle

**Ton VPS peut largement gérer :**
- Même un VPS à 5€/mois (1 vCPU, 1 Go RAM) suffit
- L'entraînement se fait **directement sur le VPS**
- Aucune dépendance GPU (scikit-learn est CPU-only)

---

### Q3 : Dois-je utiliser Google Colab ou Amazon SageMaker ?

**Réponse : NON, totalement surdimensionné !**

**Colab/SageMaker sont pertinents pour :**
- Entraîner des modèles de Deep Learning (réseaux de neurones profonds)
- Datasets massifs (millions de lignes)
- Besoins GPU (training de LLMs, Computer Vision, etc.)

**Ton cas d'usage :**
- Dataset : ~27 pays × 60 mois = **1,620 lignes**
- Modèle : RandomForest (50 arbres)
- Training time : **< 10 secondes**

**C'est comme utiliser un camion de déménagement pour transporter une lettre** 😅

---

## 🔧 Architecture Technique Simplifiée

```
┌─────────────────────────────────────────────────────────┐
│                    VPS Dokploy                          │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ PostgreSQL   │  │ Data         │  │ Risk         │ │
│  │ (persistance)│◄─│ Harvester    │◄─│ Predictor    │ │
│  │              │  │ (daily 2am)  │  │ (daily 3am)  │ │
│  └──────┬───────┘  └──────────────┘  └──────┬───────┘ │
│         │                                     │         │
│         │                                     │         │
│         │          ┌──────────────┐          │         │
│         └─────────►│ FastAPI      │◄─────────┘         │
│                    │ (port 8000)  │                    │
│                    └──────┬───────┘                    │
│                           │                            │
│                    ┌──────▼───────┐                    │
│                    │ Streamlit    │                    │
│                    │ Dashboard    │                    │
│                    │ (port 8501)  │                    │
│                    └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
                    [Utilisateur Web]
```

---

## 📈 Exemple de Cycle Complet (Timeline)

**Jour 1 - Premier démarrage :**
```
00:00 → Docker Compose démarre tous les services
00:01 → PostgreSQL ready
00:02 → Data Harvester démarre
        ├─ Télécharge 60 mois de données depuis Eurostat
        ├─ Parse et nettoie ~1,620 lignes
        └─ Insert dans asylum_data
00:07 → Data Harvester terminé ✓
00:08 → Risk Predictor démarre
        ├─ Charge les données depuis asylum_data
        ├─ Calcule les scores de risque pour ~27 pays
        ├─ Entraîne 27 modèles RandomForest (1 par pays)
        ├─ Sauvegarde dans model_registry
        ├─ Génère prédictions M+1, M+2, M+3
        └─ Insert dans risk_predictions
00:15 → Risk Predictor terminé ✓
00:16 → API Service démarre et expose les endpoints
00:17 → Dashboard démarre et affiche les visualisations
```

**Jour 2 et suivants (cycle quotidien) :**
```
02:00 → Data Harvester
        └─ Télécharge les nouvelles données (update incrémental)
        
03:00 → Risk Predictor
        ├─ Charge les données mises à jour
        ├─ Calcule les nouveaux scores
        ├─ RÉUTILISE les modèles existants (pas de réentraînement)
        └─ Génère nouvelles prédictions
```

---

## 💡 Pourquoi ce Choix de ML Léger ?

**Avantages du RandomForest pour ce cas d'usage :**

1. **Simplicité** : Facile à interpréter et déboguer
2. **Robustesse** : Gère bien les données manquantes
3. **Pas de tuning complexe** : Fonctionne out-of-the-box
4. **Léger** : Idéal pour VPS basique
5. **Rapide** : Prédictions en millisecondes
6. **Suffisant** : Pour des séries temporelles simples, pas besoin de LSTM/Transformers

**Quand utiliser du Deep Learning à la place :**
- Dataset massif (> 1 million de lignes)
- Relations complexes non-linéaires
- Séries temporelles très longues (> 1000 points par série)
- Données multimodales (texte + images + séries temporelles)

**Dans ton cas :** RandomForest est **le bon choix** 👍

---

## 🎓 Résumé Exécutif

| Aspect | Détail |
|--------|--------|
| **Données** | Demandes d'asile mensuelles UE (API Eurostat gratuite) |
| **Collecte** | Automatique, quotidienne (2h du matin) |
| **ML** | RandomForest (scikit-learn, CPU-only) |
| **Entraînement** | 1 fois au démarrage, puis réutilisation |
| **Temps training** | < 10 secondes par pays |
| **Prédictions** | M+1, M+2, M+3 (3 mois futurs) |
| **Infrastructure** | VPS basique suffit (1 CPU, 1-2 Go RAM) |
| **GPU nécessaire ?** | **NON** ❌ |
| **Colab/SageMaker ?** | **NON** ❌ |
| **Déploiement** | Docker Compose sur Dokploy |
| **Coût** | Quasi-gratuit (VPS ~5-10€/mois) |

---

## 📚 Ressources Complémentaires

- **API Eurostat** : https://wikis.ec.europa.eu/display/EUROSTATHELP/API
- **Dataset migr_asyappctzm** : https://ec.europa.eu/eurostat/databrowser/view/migr_asyappctzm
- **RandomForest sklearn** : https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestRegressor.html
- **FastAPI Docs** : https://fastapi.tiangolo.com/
- **Streamlit** : https://streamlit.io/

---

**Questions ?** N'hésite pas ! 😊
