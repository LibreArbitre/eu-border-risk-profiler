"""
FIX FINAL : Dédupliquer le DataFrame avant insertion DB
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Dans clean_data(), ajouter déduplication à la fin
old_return = """    # Ensure numeric
    df['total_applications'] = pd.to_numeric(df['total_applications'], errors='coerce').fillna(0).astype(int)
    return df"""

new_return = """    # Ensure numeric
    df['total_applications'] = pd.to_numeric(df['total_applications'], errors='coerce').fillna(0).astype(int)
    
    # CRITICAL: Remove duplicates before DB insert
    # Keep last occurrence (most recent data)
    before_dedup = len(df)
    df = df.drop_duplicates(subset=['date', 'geo_code', 'citizen_code', 'applicant_type'], keep='last')
    after_dedup = len(df)
    
    if before_dedup != after_dedup:
        logging.info(f"Removed {before_dedup - after_dedup} duplicate rows ({before_dedup} → {after_dedup})")
    
    return df"""

content = content.replace(old_return, new_return)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Ajouté déduplication du DataFrame!")
print("\nCe qui a été fait:")
print("  - drop_duplicates() sur clés: date, geo_code, citizen_code, applicant_type")
print("  - Garde la dernière occurrence (keep='last')")
print("  - Log le nombre de doublons supprimés")
print("\n🎉 Cette fois ça DEVRAIT marcher!")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
