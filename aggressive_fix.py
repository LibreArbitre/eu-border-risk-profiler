"""
Solution AGGRESSIVE : Recréer proprement all_records avant DataFrame
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer COMPLÈTEMENT la création du DataFrame
old_dataframe_creation = """    # Create DataFrame and ensure clean column names
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

new_dataframe_creation = """    # AGGRESSIVE FIX: Rebuild clean records list
    logging.info(f"Total records collected: {len(all_records)}")
    
    clean_records = []
    for i, record in enumerate(all_records):
        # Only keep expected keys, ignore any extras
        clean_record = {
            'date': record.get('date'),
            'geo_code': record.get('geo_code'),
            'citizen_code': record.get('citizen_code'),
            'applicant_type': record.get('applicant_type'),
            'total_applications': record.get('total_applications')
        }
        clean_records.append(clean_record)
        
        # Log first record for debugging
        if i == 0:
            logging.info(f"First record keys: {list(record.keys())}")
            logging.info(f"First record: {record}")
            logging.info(f"Cleaned to: {clean_record}")
    
    # Create DataFrame from clean records
    df = pd.DataFrame(clean_records)
    
    logging.info(f"DataFrame created with shape: {df.shape}")
    logging.info(f"DataFrame columns: {df.columns.tolist()}")
    
    return df"""

content = content.replace(old_dataframe_creation, new_dataframe_creation)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Solution AGGRESSIVE appliquée!")
print("\nCe qui a été fait:")
print("  - Reconstruction complète de all_records en clean_records")
print("  - Extraction explicite de chaque clé attendue uniquement")
print("  - Ignore toutes clés parasites")
print("  - Logging du premier record pour debug")
print("\nCette fois ça DOIT marcher!")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
