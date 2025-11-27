"""
Fix robuste : vérifier que data['value'] n'est pas vide
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer la condition de vérification
old_check = "        if not data or 'value' not in data or 'dimension' not in data:"
new_check = "        if not data or 'value' not in data or 'dimension' not in data or not data.get('value'):"

content = content.replace(old_check, new_check)

# Ajouter aussi un log au début de parse_eurostat_json
old_start = '''def parse_eurostat_json(data_list):
    """
    Parses Eurostat JSON-stat format into a list of records.
    Now accepts a list of JSON responses (one per country).
    """
    if not data_list:
        return pd.DataFrame()
    
    all_records = []
    
    # Traiter chaque pays
    for data in data_list:'''

new_start = '''def parse_eurostat_json(data_list):
    """
    Parses Eurostat JSON-stat format into a list of records.
    Now accepts a list of JSON responses (one per country).
    """
    if not data_list:
        return pd.DataFrame()
    
    logging.info(f"Parsing {len(data_list)} country responses...")
    all_records = []
    
    # Traiter chaque pays
    for data in data_list:
        # Log structure for debugging
        if data:
            value_count = len(data.get('value', {})) if isinstance(data.get('value'), dict) else 0
            logging.info(f"Country data has {value_count} values")'''

content = content.replace(old_start, new_start)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Ajouté check robuste pour valeurs vides")
print("   - Vérifie maintenant que data['value'] n'est pas vide")
print("   - Ajoute logging du nombre de valeurs par pays")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
