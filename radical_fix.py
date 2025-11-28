"""
Solution radicale: Agréger directement pendant le parsing, pas après
"""

with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Trouver la section où on crée all_records et la remplacer par une agrégation directe
old_append = """            all_records.append({
                'date': date_str,
                'geo_code': geo,
                'citizen_code': citizen,
                'applicant_type': app_type,
                'total_applications': v
            })"""

new_append = """            # Aggregate directly: skip citizen_code, accumulate by (date, geo, app_type)
            # Only keep FRST applicants
            if app_type != 'FRST':
                continue
            
            key = (date_str, geo, app_type)
            if key not in country_aggregates:
                country_aggregates[key] = 0
            country_aggregates[key] += v"""

# Aussi modifier le début de la boucle pour initialiser aggregates
old_loop_start = """    all_records = []
    
    # Traiter chaque pays
    for data in data_list:"""

new_loop_start = """    # Use dict for direct aggregation instead of list
    country_aggregates = {}
    
    # Traiter chaque pays
    for data in data_list:"""

# Et modifier la création du DataFrame
old_df_creation = """    # AGGRESSIVE FIX: Rebuild clean records list
    logging.info(f"Total records collected: {len(all_records)}")"""

new_df_creation = """    # Convert aggregates dict to DataFrame
    logging.info(f"Total aggregates: {len(country_aggregates)}")
    
    all_records = []
    for (date_str, geo, app_type), total in country_aggregates.items():
        all_records.append({
            'date': date_str,
            'geo_code': geo,
            'applicant_type': app_type,
            'total_applications': total
        })
    
    logging.info(f"Converted to {len(all_records)} records")"""

content = content.replace(old_append, new_append)
content = content.replace(old_loop_start, new_loop_start)
content = content.replace(old_df_creation, new_df_creation)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Solution radicale appliquée!")
print("\nChangements:")
print("  - Agrégation PENDANT le parsing (pas après)")
print("  - Filtre FRST directement dans la boucle")
print("  - Pas de DataFrame avec 12M rows")
print("  - Seulement ~600 rows au final")
print("\nCela évite complètement le bug Pandas!")
print("\nRestart:")
print("   docker-compose down -v")
print("   docker-compose up --build -d")
