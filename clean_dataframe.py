"""
FIX: Nettoyer le DataFrame après parse pour éviter les colonnes dupliquées
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Modifier la fin de parse_eurostat_json pour s'assurer qu'on a un DataFrame propre
old_return = """    return pd.DataFrame(all_records)"""

new_return = """    # Create DataFrame and ensure clean column names
    df = pd.DataFrame(all_records)
    
    if df.empty:
        return df
    
    # Reset index to avoid any issues with duplicate indices
    df = df.reset_index(drop=True)
    
    # Ensure we only have the expected columns (drop any extras)
    expected_cols = ['date', 'geo_code', 'citizen_code', 'applicant_type', 'total_applications']
    actual_cols = [col for col in expected_cols if col in df.columns]
    
    logging.info(f"DataFrame created with columns: {df.columns.tolist()}")
    logging.info(f"Keeping only expected columns: {actual_cols}")
    
    return df[actual_cols].copy()"""

content = content.replace(old_return, new_return)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Ajouté nettoyage du DataFrame après parsing")
print("\nCe qui a été fait:")
print("  - Reset index pour éviter duplications")
print("  - Filtrage explicite des colonnes attendues")
print("  - Suppression de toutes colonnes parasites")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
