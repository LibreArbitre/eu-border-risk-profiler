# Guide de Démarrage Rapide - Dokploy

## 🚀 Déploiement sur Dokploy

### Prérequis
- Dokploy installé et opérationnel
- Port `5432`, `8000`, `8501` disponibles (ou modifiés dans docker-compose.yml)

### Étapes de déploiement

#### 1. Créer un nouveau projet dans Dokploy
```bash
# Si vous utilisez Git, poussez le projet sur votre dépôt
git add .
git commit -m "Initial commit - EU Border Risk Profiler"
git push origin main
```

#### 2. Configurer les variables d'environnement dans Dokploy

Dans l'interface Dokploy, configurez les variables suivantes :

**Variables obligatoires :**
```
DB_USER=eubrp_user
DB_PASSWORD=CHANGEZ_MOI_AVEC_UN_MOT_DE_PASSE_FORT
DB_NAME=eubrp_db
DB_HOST=db
```

**Variables optionnelles (avec valeurs par défaut) :**
```
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_SECONDS=2
EXIT_ON_FAILURE=true
```

#### 3. Ordre de démarrage des services

Les services se lancent automatiquement dans l'ordre suivant grâce aux `depends_on` :

1. **db** (PostgreSQL) - démarre en premier
2. **data_harvester** - attend que la BDD soit healthy
3. **risk_predictor** - attend que le harvester réussisse
4. **api_service** - attend que le predictor réussisse
5. **dashboard** - attend que l'API soit healthy

#### 4. Vérifier que tout fonctionne

Une fois déployé, vérifiez les services :

**API Health Check :**
```bash
curl https://votre-domaine.com:8000/health
# Devrait retourner: {"status":"ok"}
```

**Swagger UI :**
Ouvrez `https://votre-domaine.com:8000/docs` dans votre navigateur

**Dashboard Streamlit :**
Ouvrez `https://votre-domaine.com:8501` dans votre navigateur

#### 5. Vérifier les logs dans Dokploy

Si un service ne démarre pas, consultez les logs :

1. **db** : Devrait afficher `database system is ready to accept connections`
2. **data_harvester** : Cherchez `Fetching data from Eurostat...` puis `Data saved successfully`
3. **risk_predictor** : Cherchez `Processing X countries...` puis `Predictions saved`
4. **api_service** : Devrait afficher `Application startup complete`
5. **dashboard** : Devrait afficher `You can now view your Streamlit app in your browser`

### 🔍 Diagnostic des problèmes courants

#### Problème : Harvester ne démarre pas
**Symptôme :** Container `data_harvester` en restart loop

**Solutions :**
1. Vérifiez que PostgreSQL est accessible :
   ```bash
   docker logs eu_brp_db
   ```
2. Vérifiez les credentials de BDD dans les variables d'environnement
3. Testez manuellement la connexion :
   ```bash
   docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT 1"
   ```

#### Problème : Predictor crash au démarrage
**Symptôme :** Container `risk_predictor` exit avec erreur

**Causes possibles corrigées dans cette version :**
- ✅ Import `pickle` manquant (corrigé)
- ✅ Table `model_registry_table` non définie (corrigé)
- ✅ Paramètre `engine` non passé (corrigé)

**Vérifications :**
```bash
# Vérifier les logs du predictor
docker logs eu_brp_predictor

# Vérifier que les données sont présentes
docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT COUNT(*) FROM asylum_data"
```

#### Problème : API ne répond pas
**Symptôme :** Timeout ou 502 Bad Gateway

**Solutions :**
1. Vérifiez que le predictor a terminé avec succès
2. Vérifiez les logs de l'API :
   ```bash
   docker logs eu_brp_api
   ```
3. Testez depuis l'intérieur du réseau Docker :
   ```bash
   docker exec eu_brp_api curl http://localhost:8000/health
   ```

#### Problème : Dashboard ne charge pas les données
**Symptôme :** Message "No prediction data available"

**Solutions :**
1. Vérifiez que l'API est accessible depuis le dashboard :
   ```bash
   docker exec eu_brp_dashboard curl http://api_service:8000/api/v1/risk/latest
   ```
2. Attendez que le harvester et predictor aient terminé au moins un cycle complet (peut prendre 5-10 minutes)
3. Vérifiez les données dans PostgreSQL :
   ```bash
   docker exec -it eu_brp_db psql -U user -d eubrp_db -c "SELECT COUNT(*) FROM risk_predictions"
   ```

### 📊 Comprendre le flux de données

```
Eurostat API (public, gratuit)
    ↓
data_harvester (récupère les données d'asile mensuelles)
    ↓
PostgreSQL (table: asylum_data)
    ↓
risk_predictor (calcule les scores de risque et entraîne le modèle ML)
    ↓
PostgreSQL (tables: risk_predictions, model_registry)
    ↓
api_service (expose les données via REST)
    ↓
dashboard (visualisation Streamlit)
```

### ⏱️ Temps d'attente attendus

- **Premier démarrage complet :** 10-15 minutes
  - DB init : 30 secondes
  - Harvester (download + insert) : 2-5 minutes
  - Predictor (calcul + ML training) : 5-10 minutes
  - API startup : 10 secondes
  - Dashboard startup : 30 secondes

### 🔄 Redémarrer manuellement un service

Si vous devez forcer un re-harvest ou re-prediction :

```bash
# Redémarrer le harvester
docker restart eu_brp_harvester

# Redémarrer le predictor
docker restart eu_brp_predictor
```

### 📝 Prochaines étapes recommandées

1. **Sécurité :** Changer le mot de passe PostgreSQL par défaut
2. **Monitoring :** Ajouter des alertes sur les health checks
3. **Backup :** Configurer des sauvegardes PostgreSQL régulières
4. **Tests :** Ajouter des tests unitaires (voir IMPLEMENTATION_PLAN_STATUS.md)
5. **Performance :** Ajouter un cache Redis pour l'API si nécessaire

---

**Besoin d'aide ?** Consultez :
- [README.md](README.md) pour l'architecture
- [OPERATIONS_GUIDE.md](OPERATIONS_GUIDE.md) pour les opérations
- Logs Dokploy pour le diagnostic en temps réel
