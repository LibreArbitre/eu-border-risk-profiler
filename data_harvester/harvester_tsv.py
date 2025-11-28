"""
NOUVEAU HARVESTER SIMPLIFIÉ - Bulk Download TSV Eurostat
Remplace complètement l'ancien harvester problématique
"""
import os
import logging
import time
from datetime import datetime
import pandas as pd
import requests
from sqlalchemy import create_engine, text
from io import StringIO

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Database connection
def get_db_engine():
    db_host = os.getenv('DB_HOST', 'db')
    db_user = os.getenv('DB_USER', 'user')
    db_pass = os.getenv('DB_PASSWORD', 'password')
    db_name = os.getenv('DB_NAME', 'eubrp_db')
    
    return create_engine(f'postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}')

def download_eurostat_tsv():
    """
    Télécharge le fichier TSV complet depuis Eurostat
    Dataset: migr_asyappctzm (Asylum applications by citizenship)
    """
    logging.info("Downloading Eurostat TSV bulk file...")
    
    # URL du bulk download Eurostat
    url = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/migr_asyappctzm/?format=TSV&compressed=true"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        # Le fichier est compressé, requests le décompresse automatiquement
        content = response.text
        
        logging.info(f"Downloaded {len(content)} bytes")
        return content
    
    except Exception as e:
        logging.error(f"Failed to download TSV: {e}")
        raise

def parse_tsv_to_dataframe(tsv_content):
    """
    Parse le TSV Eurostat en DataFrame Pandas
    Format Eurostat: première colonne = dimensions, autres colonnes = périodes
    """
    logging.info("Parsing TSV content...")
    
    # Lire le TSV avec Pandas
    df = pd.read_csv(StringIO(tsv_content), sep='\t')
    
    logging.info(f"TSV loaded: {df.shape[0]} rows, {df.shape[1]} columns")
    logging.info(f"Columns: {df.columns.tolist()[:5]}...")  # First 5
    
    # La première colonne contient toutes les dimensions concaténées
    # Format: freq,unit,citizen,sex,asyl_app,age,geo\TIME_PERIOD
    dimension_col = df.columns[0]
    
    # Séparer les dimensions
    dimensions = df[dimension_col].str.split(',', expand=True)
    dimensions.columns = ['freq', 'unit', 'citizen', 'sex', 'applicant', 'age', 'geo']
    
    # Joindre avec les valeurs temporelles
    time_cols = [col for col in df.columns if col != dimension_col]
    
    # Restructurer en format long
    records = []
    total_periods = len(time_cols)
    
    logging.info(f"Processing {len(df)} dimension combinations × {total_periods} time periods...")
    
    for idx, row in df.iterrows():
        dims = dimensions.iloc[idx]
        
        for time_col in time_cols:
            value = row[time_col]
            
            # Ignorer les valeurs manquantes (: dans Eurostat)
            if pd.isna(value) or value == ':' or value == ': ':
                continue
            
            try:
                value = float(value.strip())
            except:
                continue
            
            # Parser le format de temps (ex: 2023M11)
            if 'M' in time_col:
                year, month = time_col.split('M')
                date_str = f"{year}-{month.zfill(2)}-01"
            else:
                continue
            
            records.append({
                'date': date_str,
                'geo_code': dims['geo'],
                'citizen_code': dims['citizen'],
                'applicant_type': dims['applicant'],
                'total_applications': int(value)
            })
        
        # Log progress every 1000 rows
        if (idx + 1) % 1000 == 0:
            logging.info(f"Processed {idx + 1}/{len(df)} dimension combinations...")
    
    result_df = pd.DataFrame(records)
    logging.info(f"Created DataFrame with {len(result_df)} records")
    
    return result_df

def filter_data(df):
    """
    Filtre les données pour ne garder que ce qui nous intéresse
    """
    logging.info(f"Filtering data... Starting with {len(df)} rows")
    
    # Filtrer pour First-time applicants (FRST)
    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'] == 'FRST'].copy()
        logging.info(f"After FRST filter: {len(df)} rows")
    
    # Filtrer pour TOTAL citizenship (agrégé)
    if 'citizen_code' in df.columns:
        df = df[df['citizen_code'] == 'TOTAL'].copy()
        logging.info(f"After TOTAL filter: {len(df)} rows")
    
    # Filtrer pour les 27 pays UE
    eu_countries = ['AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'EL', 'ES', 
                    'FI', 'FR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 
                    'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK']
    
    df = df[df['geo_code'].isin(eu_countries)].copy()
    logging.info(f"After EU filter: {len(df)} rows")
    
    # Dédupliquer
    before = len(df)
    df = df.drop_duplicates(subset=['date', 'geo_code', 'citizen_code', 'applicant_type'], keep='last')
    after = len(df)
    
    if before != after:
        logging.info(f"Removed {before - after} duplicates")
    
    return df

def save_to_db(df):
    """
    Sauvegarde le DataFrame en PostgreSQL
    """
    if df.empty:
        logging.info("No data to save")
        return
    
    logging.info(f"Saving {len(df)} records to database...")
    
    engine = get_db_engine()
    
    # Utiliser to_sql de Pandas - beaucoup plus simple !
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
    """
    Fonction principale du harvester
    """
    logging.info("=" * 60)
    logging.info("EUROSTAT TSV BULK DOWNLOAD HARVESTER")
    logging.info("=" * 60)
    
    try:
        # 1. Télécharger le TSV
        tsv_content = download_eurostat_tsv()
        
        # 2. Parser en DataFrame
        df = parse_tsv_to_dataframe(tsv_content)
        
        # 3. Filtrer
        df = filter_data(df)
        
        # 4. Sauvegarder
        save_to_db(df)
        
        logging.info("=" * 60)
        logging.info("✅ HARVEST COMPLETED SUCCESSFULLY")
        logging.info("=" * 60)
        
    except Exception as e:
        logging.error(f"❌ Harvest failed: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    # Health check mode
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--healthcheck':
        sys.exit(0)
    
    # Run harvest immediately on startup
    run_harvest()
    
    # Then start scheduler for daily runs
    logging.info("Scheduler started. Next run in 24 hours...")
    while True:
        time.sleep(86400)  # 24 hours
        run_harvest()
