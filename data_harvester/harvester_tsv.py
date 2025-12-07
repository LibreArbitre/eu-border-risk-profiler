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
import csv

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
    url = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/migr_asyappctzm/?format=TSV&compressed=false"
    
    # Download with stream to avoid memory issues and show progress
    local_filename = "/tmp/eurostat_data.tsv"
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded % (10 * 1024 * 1024) < 8192: # Log every ~10MB
                        logging.info(f"Downloaded {downloaded / (1024*1024):.1f} MB...")
        
        logging.info(f"Download complete. Total size: {downloaded / (1024*1024):.1f} MB")
        
        # Read file content for parsing
        with open(local_filename, 'r', encoding='utf-8') as f:
            tsv_content = f.read()
            
        return tsv_content
            
    except Exception as e:
        logging.error(f"Download failed: {e}")
        raise


def process_and_save_chunked(tsv_content, chunk_size=100000):
    """
    Parse le TSV Eurostat en chunks et sauvegarde au fur et à mesure.
    OPTIMISÉ: Filtre et agrège AVANT le melt pour réduire la consommation mémoire.
    """
    logging.info("Starting optimized chunked processing...")
    
    # EU countries to keep
    EU_COUNTRIES = {'AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'EL', 'ES', 
                    'FI', 'FR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 
                    'NL', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK'}
    
    try:
        # First read header to get columns
        header_df = pd.read_csv(
            StringIO(tsv_content), 
            sep='\t', 
            engine='c', 
            quoting=csv.QUOTE_NONE,
            on_bad_lines='warn',
            nrows=0
        )
        header_df.columns = header_df.columns.str.strip()
        columns = header_df.columns.tolist()
        
        # Define iterator
        chunk_iter = pd.read_csv(
            StringIO(tsv_content), 
            sep='\t', 
            engine='c', 
            quoting=csv.QUOTE_NONE,
            on_bad_lines='warn',
            chunksize=chunk_size,
            names=columns,
            header=0
        )
        
        total_rows = 0
        
        for i, df in enumerate(chunk_iter):
            logging.info(f"Processing chunk {i+1} ({len(df)} rows)...")
            
            # Clean columns
            df.columns = df.columns.str.strip()
            
            # La première colonne contient toutes les dimensions concaténées
            dimension_col = df.columns[0]
            
            # Séparer les dimensions
            dimensions = df[dimension_col].str.split(',', expand=True)
            
            if dimensions.shape[1] != 7:
                logging.warning(f"Chunk {i+1}: Unexpected dimensions {dimensions.shape[1]}, skipping")
                continue
            
            dimensions.columns = ['freq', 'unit', 'citizen', 'sex', 'applicant', 'age', 'geo']
            
            # ==== OPTIMISATION CLEF: Filtrer AVANT le melt ====
            # 1. Filtrer applicant == 'FRST'
            frst_mask = dimensions['applicant'] == 'FRST'
            # 2. Filtrer geo dans EU
            eu_mask = dimensions['geo'].isin(EU_COUNTRIES)
            # Combiner les masques
            valid_mask = frst_mask & eu_mask
            
            filtered_count = valid_mask.sum()
            if filtered_count == 0:
                logging.info(f"Chunk {i+1}: No valid rows after filter, skipping")
                continue
            
            logging.info(f"Chunk {i+1}: Filtered to {filtered_count} rows (FRST + EU)")
            
            # Appliquer le filtre au DataFrame original
            df_filtered = df[valid_mask].copy()
            dimensions_filtered = dimensions[valid_mask].copy()
            
            # Reconstruire avec dimensions
            df_filtered = pd.concat([
                dimensions_filtered[['geo', 'applicant']].reset_index(drop=True), 
                df_filtered.drop(columns=[dimension_col]).reset_index(drop=True)
            ], axis=1)
            
            # ==== OPTIMISATION: Agréger par geo_code AVANT le melt ====
            # Les colonnes de dates sont tout sauf 'geo' et 'applicant'
            date_cols = [c for c in df_filtered.columns if c not in ['geo', 'applicant']]
            
            # Convertir les valeurs en numériques (gérer les ': ' et espaces)
            for col in date_cols:
                df_filtered[col] = df_filtered[col].astype(str).str.replace(r'[^0-9.]', '', regex=True)
                df_filtered[col] = pd.to_numeric(df_filtered[col], errors='coerce').fillna(0).astype(int)
            
            # Grouper par geo et sommer toutes les nationalités/sexes/âges
            df_agg = df_filtered.groupby('geo')[date_cols].sum().reset_index()
            df_agg['applicant'] = 'FRST'
            
            logging.info(f"Chunk {i+1}: Aggregated to {len(df_agg)} rows (by geo_code)")
            
            # Maintenant le melt sur un DataFrame BEAUCOUP plus petit (27 lignes max)
            df_long = df_agg.melt(
                id_vars=['geo', 'applicant'], 
                var_name='date_raw', 
                value_name='total_applications'
            )
            
            # Parse dates - support YYYY-MM format
            df_long = df_long[df_long['date_raw'].str.match(r'^\d{4}-\d{2}$', na=False)]
            df_long['date'] = pd.to_datetime(df_long['date_raw'] + '-01', format='%Y-%m-%d', errors='coerce')
            df_long = df_long.dropna(subset=['date'])
            
            # Rename et préparer pour la DB
            df_final = df_long.rename(columns={
                'geo': 'geo_code',
                'applicant': 'applicant_type'
            })
            
            # Ajouter citizen_code comme 'TOTAL' (agrégé)
            df_final['citizen_code'] = 'TOTAL'
            
            # Select final columns
            final_cols = ['date', 'geo_code', 'citizen_code', 'applicant_type', 'total_applications']
            if not df_final.empty:
                df_final = df_final[final_cols]
                save_to_db(df_final)
                total_rows += len(df_final)
                logging.info(f"Chunk {i+1}: Saved {len(df_final)} records")
            
            # Libérer la mémoire
            del df, dimensions, df_filtered, dimensions_filtered, df_agg, df_long, df_final
            
        logging.info(f"Total records saved: {total_rows}")
            
    except Exception as e:
        logging.error(f"Chunk processing failed: {e}")
        raise

def filter_data(df):
    """
    Filtre les données pour ne garder que ce qui nous intéresse
    """
    logging.info(f"Filtering data... Starting with {len(df)} rows")
    
    # Filtrer pour First-time applicants (FRST)
    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'] == 'FRST'].copy()
        logging.info(f"After FRST filter: {len(df)} rows")
    
    # NOTE: On ne filtre plus sur citizen_code == 'TOTAL' car le dataset n'a pas cette valeur agrégée
    # Le citizen_code contient des codes pays individuels (AD, AE, AF, etc.)
    # On garde toutes les nationalités pour une analyse complète
    
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
        if_exists='append',  # Append pour le chunking
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
        
        # 1.5 Truncate table (mimic replace)
        engine = get_db_engine()
        with engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE asylum_data"))
            conn.commit()
            logging.info("Table asylum_data truncated.")
        
        # 2. Parser et Sauvegarder en chunks
        process_and_save_chunked(tsv_content)
        
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
