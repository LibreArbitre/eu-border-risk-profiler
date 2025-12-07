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
    Parse le TSV Eurostat en chunks et sauvegarde au fur et à mesure
    """
    logging.info("Starting chunked processing...")
    
    # Use C engine for speed, disable quoting to handle backslashes in header
    # Read in chunks
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
            
            # DEBUG: Show first row and columns
            if i == 0:
                logging.info(f"DEBUG: Columns = {df.columns.tolist()[:10]}")
                logging.info(f"DEBUG: First row sample = {df.iloc[0].head(5).to_dict()}")
            
            # La première colonne contient toutes les dimensions concaténées
            dimension_col = df.columns[0]
            
            # Séparer les dimensions
            dimensions = df[dimension_col].str.split(',', expand=True)
            
            # DEBUG: Show dimensions
            if i == 0:
                logging.info(f"DEBUG: dimension_col name = '{dimension_col}'")
                logging.info(f"DEBUG: dimensions.shape = {dimensions.shape}")
                logging.info(f"DEBUG: First dim row = {dimensions.iloc[0].tolist()}")
            
            if dimensions.shape[1] == 7:
                dimensions.columns = ['freq', 'unit', 'citizen', 'sex', 'applicant', 'age', 'geo']
            else:
                logging.warning(f"Chunk {i+1}: Unexpected dimensions {dimensions.shape[1]}, skipping chunk")
                continue

            # Assign dimensions back
            df = pd.concat([dimensions, df.drop(columns=[dimension_col])], axis=1)
            
            # Melt
            id_vars = ['freq', 'unit', 'citizen', 'sex', 'applicant', 'age', 'geo']
            id_vars = [c for c in id_vars if c in df.columns]
            
            df_long = df.melt(id_vars=id_vars, var_name='date_raw', value_name='value_raw')
            
            # DEBUG: After melt
            if i == 0:
                logging.info(f"DEBUG: After melt: {len(df_long)} rows")
                logging.info(f"DEBUG: date_raw samples = {df_long['date_raw'].head(10).tolist()}")
                logging.info(f"DEBUG: value_raw samples = {df_long['value_raw'].head(10).tolist()}")
            
            # Filter missing
            before_filter = len(df_long)
            df_long = df_long[~df_long['value_raw'].isin([':', ': ', 'nan', ''])]
            df_long = df_long.dropna(subset=['value_raw'])
            if i == 0:
                logging.info(f"DEBUG: After missing filter: {len(df_long)} rows (removed {before_filter - len(df_long)})")
            
            # Clean values
            df_long['value_clean'] = df_long['value_raw'].astype(str).str.replace(r'[a-zA-Z\\s]', '', regex=True)
            before_clean = len(df_long)
            df_long = df_long[df_long['value_clean'] != '']
            if i == 0:
                logging.info(f"DEBUG: After value_clean filter: {len(df_long)} rows (removed {before_clean - len(df_long)})")
                logging.info(f"DEBUG: value_clean samples = {df_long['value_clean'].head(5).tolist()}")
            
            df_long['total_applications'] = pd.to_numeric(df_long['value_clean'], errors='coerce').fillna(0).astype(int)
            
            # Parse dates - support both YYYY-MM format (e.g., 2008-01) and YYYYMNN format (e.g., 2023M11)
            # First, detect the format
            if i == 0:
                logging.info(f"DEBUG: date_raw first value = '{df_long['date_raw'].iloc[0] if len(df_long) > 0 else 'N/A'}'")
            
            # Try YYYY-MM format first (most common now)
            date_mask_yyyymm = df_long['date_raw'].str.match(r'^\d{4}-\d{2}$', na=False)
            date_mask_yyyymnn = df_long['date_raw'].str.contains('M', na=False)
            
            if i == 0:
                logging.info(f"DEBUG: Rows matching YYYY-MM: {date_mask_yyyymm.sum()}, YYYYMNN: {date_mask_yyyymnn.sum()}")
            
            # Parse YYYY-MM format
            df_yyyymm = df_long[date_mask_yyyymm].copy()
            if not df_yyyymm.empty:
                df_yyyymm['date'] = pd.to_datetime(df_yyyymm['date_raw'] + '-01', format='%Y-%m-%d', errors='coerce')
            
            # Parse YYYYMNN format
            df_yyyymnn = df_long[date_mask_yyyymnn].copy()
            if not df_yyyymnn.empty:
                df_yyyymnn['year'] = df_yyyymnn['date_raw'].str.split('M').str[0]
                df_yyyymnn['month'] = df_yyyymnn['date_raw'].str.split('M').str[1]
                df_yyyymnn['date'] = pd.to_datetime(df_yyyymnn['year'] + '-' + df_yyyymnn['month'] + '-01', errors='coerce')
                df_yyyymnn = df_yyyymnn.drop(columns=['year', 'month'], errors='ignore')
            
            # Combine results
            df_long = pd.concat([df_yyyymm, df_yyyymnn], ignore_index=True)
            
            before_date2 = len(df_long)
            df_long = df_long.dropna(subset=['date'])
            if i == 0:
                logging.info(f"DEBUG: After date parse: {len(df_long)} rows (removed {before_date2 - len(df_long)})")
            
            # Rename
            df_final = df_long.rename(columns={
                'geo': 'geo_code',
                'citizen': 'citizen_code',
                'applicant': 'applicant_type'
            })
            
            # DEBUG: Before filter_data
            if i == 0:
                logging.info(f"DEBUG: Before filter_data: {len(df_final)} rows")
                if len(df_final) > 0:
                    logging.info(f"DEBUG: applicant_type unique = {df_final['applicant_type'].unique()[:10].tolist()}")
                    logging.info(f"DEBUG: citizen_code unique = {df_final['citizen_code'].unique()[:10].tolist()}")
                    logging.info(f"DEBUG: geo_code unique = {df_final['geo_code'].unique()[:10].tolist()}")
            
            # Filter data (FRST, TOTAL, EU)
            df_final = filter_data(df_final)
            
            # Select final columns
            final_cols = ['date', 'geo_code', 'citizen_code', 'applicant_type', 'total_applications']
            if not df_final.empty:
                df_final = df_final[final_cols]
                save_to_db(df_final)
                total_rows += len(df_final)
            
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
