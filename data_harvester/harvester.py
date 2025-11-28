"""
HARVESTER AVEC DONNÉES SYNTHÉTIQUES RÉALISTES
Génère des données d'asile basées sur des patterns réels européens

Avantages:
- Fonctionne 100% du temps
- Données pour TOUS les 27 pays UE
- Patterns réalistes (tendances, variations)
- Parfait pour POC/Demo
"""
import os
import logging
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

# Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# 27 pays UE
EU_COUNTRIES = {
    'DE': {'name': 'Germany', 'base': 50000, 'variation': 0.3},
    'FR': {'name': 'France', 'base': 40000, 'variation': 0.25},
    'IT': {'name': 'Italy', 'base': 35000, 'variation': 0.3},
    'ES': {'name': 'Spain', 'base': 30000, 'variation': 0.25},
    'EL': {'name': 'Greece', 'base': 25000, 'variation': 0.4},
    'AT': {'name': 'Austria', 'base': 12000, 'variation': 0.2},
    'BE': {'name': 'Belgium', 'base': 10000, 'variation': 0.2},
    'NL': {'name': 'Netherlands', 'base': 15000, 'variation': 0.2},
    'SE': {'name': 'Sweden', 'base': 18000, 'variation': 0.25},
    'PL': {'name': 'Poland', 'base': 5000, 'variation': 0.3},
    'CZ': {'name': 'Czechia', 'base': 3000, 'variation': 0.2},
    'RO': {'name': 'Romania', 'base': 2500, 'variation': 0.25},
    'BG': {'name': 'Bulgaria', 'base': 3500, 'variation': 0.3},
    'HU': {'name': 'Hungary', 'base': 2000, 'variation': 0.2},
    'PT': {'name': 'Portugal', 'base': 4000, 'variation': 0.2},
    'DK': {'name': 'Denmark', 'base': 6000, 'variation': 0.15},
    'FI': {'name': 'Finland', 'base': 5000, 'variation': 0.2},
    'SK': {'name': 'Slovakia', 'base': 1500, 'variation': 0.2},
    'IE': {'name': 'Ireland', 'base': 4500, 'variation': 0.2},
    'HR': {'name': 'Croatia', 'base': 2000, 'variation': 0.25},
    'SI': {'name': 'Slovenia', 'base': 1800, 'variation': 0.2},
    'LT': {'name': 'Lithuania', 'base': 1500, 'variation': 0.25},
    'LV': {'name': 'Latvia', 'base': 1200, 'variation': 0.2},
    'EE': {'name': 'Estonia', 'base': 1000, 'variation': 0.2},
    'CY': {'name': 'Cyprus', 'base': 8000, 'variation': 0.3},
    'LU': {'name': 'Luxembourg', 'base': 1500, 'variation': 0.15},
    'MT': {'name': 'Malta', 'base': 3000, 'variation': 0.3}
}

def get_db_engine():
    """Connexion PostgreSQL"""
    db_host = os.getenv('DB_HOST', 'db')
    db_user = os.getenv('DB_USER', 'user')
    db_pass = os.getenv('DB_PASSWORD', 'password')
    db_name = os.getenv('DB_NAME', 'eubrp_db')
    
    return create_engine(f'postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}')

def generate_realistic_data():
    """
    Génère des données d'asile réalistes pour 27 pays UE
    Période: 24 derniers mois
    """
    logging.info("Generating synthetic asylum data...")
    
    # Dates: 24 derniers mois
    end_date = datetime.now().replace(day=1)
    start_date = end_date - timedelta(days=730)  # ~24 mois
    
    dates = pd.date_range(start=start_date, end=end_date, freq='MS')
    
    records = []
    total_generated = 0
    
    # Pour chaque pays
    for geo_code, info in EU_COUNTRIES.items():
        base_applications = info['base']
        variation = info['variation']
        
        # Générer série temporelle avec tendance + saisonnalité
        for i, date in enumerate(dates):
            # Tendance générale (légère diminution depuis 2023)
            trend = 1.0 - (i / len(dates)) * 0.15
            
            # Saisonnalité (plus de demandes en été/automne)
            month = date.month
            seasonal = 1.0 + 0.1 * np.sin((month - 3) * np.pi / 6)
            
            # Variation aléatoire
            random_var = np.random.normal(1.0, variation)
            
            # Calcul final
            applications = int(base_applications * trend * seasonal * random_var / 12)
            applications = max(0, applications)  # Pas de valeurs négatives
            
            records.append({
                'date': date.strftime('%Y-%m-%d'),
                'geo_code': geo_code,
                'citizen_code': 'TOTAL',
                'applicant_type': 'FRST',
                'total_applications': applications
            })
            total_generated += 1
    
    df = pd.DataFrame(records)
    
    logging.info(f"Generated {total_generated} records for {len(EU_COUNTRIES)} countries")
    logging.info(f"Date range: {df['date'].min()} to {df['date'].max()}")
    logging.info(f"Total applications (sum): {df['total_applications'].sum():,}")
    
    # Statistiques par pays
    country_stats = df.groupby('geo_code')['total_applications'].agg(['sum', 'mean'])
    logging.info(f"Top 5 countries by total: \\n{country_stats.sort_values('sum', ascending=False).head()}")
    
    return df

def save_to_db(df):
    """Sauvegarde dans PostgreSQL"""
    if df.empty:
        logging.info("No data to save")
        return
    
    logging.info(f"Saving {len(df)} records to database...")
    
    engine = get_db_engine()
    
    # Utiliser to_sql - simple et fiable
    df.to_sql(
        'asylum_data',
        engine,
        if_exists='replace',  # Remplace les anciennes données
        index=False,
        method='multi',
        chunksize=1000
    )
    
    logging.info("✅ Data saved successfully")

def run_harvest():
    """Fonction principale"""
    logging.info("=" * 70)
    logging.info("SYNTHETIC DATA HARVESTER")
    logging.info("Generating realistic asylum data for EU-27")
    logging.info("=" * 70)
    
    try:
        # Générer les données
        df = generate_realistic_data()
        
        # Sauvegarder
        save_to_db(df)
        
        logging.info("=" * 70)
        logging.info("✅ HARVEST COMPLETED SUCCESSFULLY")
        logging.info(f"   Total records: {len(df)}")
        logging.info(f"   Countries: {df['geo_code'].nunique()}")
        logging.info(f"   Time periods: {df['date'].nunique()}")
        logging.info("=" * 70)
        
    except Exception as e:
        logging.error(f"❌ Harvest failed: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    import sys
    
    # Health check
    if len(sys.argv) > 1 and sys.argv[1] == '--healthcheck':
        sys.exit(0)
    
    # Run harvest once
    run_harvest()
    
    # Scheduler (daily regeneration)
    logging.info("Scheduler started. Next run in 24 hours...")
    while True:
        time.sleep(86400)
        run_harvest()
