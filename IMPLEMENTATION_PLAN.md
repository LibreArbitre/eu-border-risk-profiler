# 🗺️ IMPLEMENTATION_PLAN.md : EU Border Risk Profiler

Ce plan guide l'implémentation du **EU Border Risk Profiler**, de la configuration de l'environnement au déploiement des services. Chaque étape correspond à un objectif de développement clair, idéal pour être assigné à un agent LLM ou pour servir de *sprint* de travail.

### Étape 1 : Configuration de l'Environnement (Infrastructure)

**Objectif :** Mettre en place l'environnement de base et la communication entre les services.

* **Tâche 1.1 :** Créer la structure de dossiers du projet (`/data_harvester`, `/risk_predictor`, `/api_service`, `/db`, etc.).
* **Tâche 1.2 :** Définir le fichier **`docker-compose.yml`** initial pour lancer le service de base de données **PostgreSQL** (Agent de stockage) et le réseau interne de Docker.
* **Tâche 1.3 :** Créer les **`Dockerfile`** pour chaque agent (base Python/Alpine recommandée) et le fichier de dépendances **`requirements.txt`** initial pour chaque agent.

### Étape 2 : Data_Harvester (Agent de Récolte de Données)

**Objectif :** Télécharger, nettoyer et stocker les données d'asile d'Eurostat (`migr_asyappctzm`).

* **Tâche 2.1 :** Développer le script Python (`harvester.py`) pour **interroger l'API Eurostat JSON-stat** en utilisant la bibliothèque `requests` et **filtrer** les données sur les primo-demandeurs et les pays cibles.
* **Tâche 2.2 :** Implémenter le **nettoyage des données** dans `harvester.py` (gestion des colonnes, renommage, conversion des types).
* **Tâche 2.3 :** Définir le **schéma de la base de données** (table `asylum_data`) et écrire le code `SQLAlchemy` pour **insérer** les données nettoyées.
* **Tâche 2.4 :** Tester l'exécution du conteneur `data_harvester` pour s'assurer qu'il remplit correctement la base de données.

### Étape 3 : Risk_Predictor (Agent de Prédiction de Risques)

**Objectif :** Calculer le Score de Risque et entraîner le modèle d'IA pour la prédiction.

* **Tâche 3.1 :** Créer une fonction dans un fichier `risk_calculator.py` pour **récupérer les données** de la BDD et calculer le **Score de Risque Frontalier** pondéré (ex : *pondération de 60% pour la variation mensuelle, 40% pour la moyenne historique*).
* **Tâche 3.2 :** Mettre en œuvre le **modèle d'IA** (ex: $Prophet$, $ARIMA$, ou Régression Simple) pour **prédire** le Score de Risque agrégé sur les **trois prochains mois**.
* **Tâche 3.3 :** Créer une table `risk_prediction` dans la BDD et coder la logique pour **stocker** les résultats du Score et de la Prédiction (date de prédiction, pays, valeur $M+1$, $M+2$, $M+3$).
* **Tâche 3.4 :** Tester l'exécution du conteneur `risk_predictor` pour valider le calcul et la persistance des résultats.

### Étape 4 : API_Service (Agent de Service Web)

**Objectif :** Exposer les résultats de l'analyse et les visualiser.

* **Tâche 4.1 :** Développer l'API REST en **FastAPI** (`main.py`) et définir les modèles de données de réponse **Pydantic** pour le Score et la Prédiction.
* **Tâche 4.2 :** Créer les points de terminaison (`/api/v1/risk/current` et `/api/v1/risk/predict`) qui **interrogent la BDD** et renvoient les données au format JSON.
* **Tâche 4.3 :** Développer le **Tableau de Bord $Streamlit$** ou $Dash$ qui **consomme les points de terminaison** de l'API.
* **Tâche 4.4 :** Intégrer une **carte interactive** ($Plotly$ ou $Folium$) pour visualiser la prédiction du mois $M+1$ sous forme de carte de chaleur.
* **Tâche 4.5 :** Créer un fichier **`models.py`** pour les schémas Pydantic.

### Étape 5 : Finalisation et Documentation

**Objectif :** Rendre le projet professionnel et prêt à être présenté.

* **Tâche 5.1 :** Finaliser le fichier **`docker-compose.yml`** pour assurer l'orchestration complète de tous les services (y compris l'ordonnancement des tâches pour le *Harvester*).
* **Tâche 5.2 :** Rédiger un fichier **`README.md`** professionnel et convaincant.
* **Tâche 5.3 :** Ajouter des tests unitaires de base pour l'extraction et le calcul de risques.