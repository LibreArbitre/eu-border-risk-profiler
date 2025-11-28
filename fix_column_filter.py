"""
Ajouter logging pour voir la structure du DataFrame avant insertion + limiter les colonnes
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Ajouter logging avant to_dict
old_to_dict = """                # Convert date string to proper format if needed, but PG handles 'YYYY-MM-DD'

                data_to_insert = df.to_dict(orient='records')"""

new_to_dict = """                # Convert date string to proper format if needed, but PG handles 'YYYY-MM-DD'
                
                # CRITICAL: Keep only the required columns
                required_cols = ['date', 'geo_code', 'citizen_code', 'applicant_type', 'total_applications']
                logging.info(f"DataFrame columns before filtering: {df.columns.tolist()[:20]}")  # First 20
                
                # Filter to keep only required columns
                df_filtered = df[required_cols].copy()
                logging.info(f"Filtered to {len(df_filtered.columns)} required columns")
                logging.info(f"Sample record: {df_filtered.head(1).to_dict(orient='records')}")

                data_to_insert = df_filtered.to_dict(orient='records')"""

content = content.replace(old_to_dict, new_to_dict)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Ajouté filtrage des colonnes avant insertion")
print("\n")
print("  - Garde seulement date, geo_code, citizen_code, applicant_type, total_applications")
print("  - Log les colonnes du DataFrame")
print("  - Devrait corriger l'erreur SQLAlchemy")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
