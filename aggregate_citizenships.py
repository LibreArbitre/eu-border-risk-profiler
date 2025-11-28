"""
Modifier le harvester pour agréger toutes les citizenships au lieu de filtrer TOTAL
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer la section de filtrage citizen_code
old_citizen_filter = """    if 'citizen_code' in df.columns:
        # Keep TOTAL if it exists, otherwise keep all
        if 'TOTAL' in df['citizen_code'].values:
            df = df[df['citizen_code'] == 'TOTAL'].copy()
            logging.info(f"After citizen filter (TOTAL): {len(df)} rows")
        else:
            logging.info(f"No TOTAL citizen_code, keeping all countries: {len(df)} rows")"""

new_citizen_filter = """    # Aggregate all citizen_code values by summing per (date, geo_code, applicant_type)
    if 'citizen_code' in df.columns:
        logging.info(f"Before aggregation: {len(df)} rows")
        df = df.groupby(['date', 'geo_code', 'applicant_type'], as_index=False)['total_applications'].sum()
        logging.info(f"After aggregation by country: {len(df)} rows")"""

content = content.replace(old_citizen_filter, new_citizen_filter)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Harvester modifié!")
print("\nChangement:")
print("  - Au lieu de filtrer pour citizen_code='TOTAL'")
print("  - On agrège toutes les citizenships par pays")
print("\nCela donnera des données pour tous les 27 pays UE!")
print("\nPour appliquer:")
print("  docker-compose down")
print("  docker-compose up --build -d")
