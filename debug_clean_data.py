"""
Ajouter logging dans clean_data pour voir les valeurs réelles
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Trouver clean_data et ajouter du logging
old_clean_start = """def clean_data(df):
    if df.empty:
        return df
    
    # Filter for first-time applicants (NASY_APP) and TOTAL citizenship
    # This filtering was moved from API params to Python to avoid 0 results
    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'].str.contains('NASY', na=False)].copy()"""

new_clean_start = """def clean_data(df):
    if df.empty:
        return df
    
    # Log data before filtering
    logging.info(f"Before filtering: {len(df)} rows")
    if 'applicant_type' in df.columns:
        applicant_values = df['applicant_type'].unique()
        logging.info(f"Unique applicant_type values: {applicant_values[:10]}")  # Show first 10
    if 'citizen_code' in df.columns:
        citizen_values = df['citizen_code'].unique()
        logging.info(f"Unique citizen_code values (first 10): {citizen_values[:10]}")
    
    # Filter for first-time applicants (NASY_APP) and TOTAL citizenship
    # This filtering was moved from API params to Python to avoid 0 results
    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'].str.contains('NASY', na=False)].copy()
        logging.info(f"After applicant filter: {len(df)} rows")"""

content = content.replace(old_clean_start, new_clean_start)

# Ajouter aussi logging après citizen filter
old_citizen = """    if 'citizen_code' in df.columns:
        df = df[df['citizen_code'] == 'TOTAL'].copy()
    
    # Ensure numeric"""

new_citizen = """    if 'citizen_code' in df.columns:
        df = df[df['citizen_code'] == 'TOTAL'].copy()
        logging.info(f"After citizen filter: {len(df)} rows")
    
    # Ensure numeric"""

content = content.replace(old_citizen, new_citizen)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Ajouté logging dans clean_data()")
print("\nCe qui sera loggé:")
print("  - Nombre de rows avant filtrage")
print("  - Valeurs uniques de applicant_type")
print("  - Valeurs uniques de citizen_code")
print("  - Nombre de rows après chaque filtre")
print("\nRedémarrer: docker-compose down && docker-compose up")
