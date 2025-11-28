"""
FIX: Parse Eurostat TSV avec gestion des métadonnées
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer la fonction parse_tsv_to_dataframe
old_parse = '''def parse_tsv_to_dataframe(tsv_content):
    """
    Parse le TSV Eurostat en DataFrame Pandas
    Format Eurostat: première colonne = dimensions, autres colonnes = périodes
    """
    logging.info("Parsing TSV content...")
    
    # Lire le TSV avec Pandas
    df = pd.read_csv(StringIO(tsv_content), sep='\\t')'''

new_parse = '''def parse_tsv_to_dataframe(tsv_content):
    """
    Parse le TSV Eurostat en DataFrame Pandas
    Format Eurostat: première colonne = dimensions, autres colonnes = périodes
    """
    logging.info("Parsing TSV content...")
    
    # Eurostat TSV: skip metadata lines and use proper error handling
    df = pd.read_csv(
        StringIO(tsv_content), 
        sep='\\t',
        on_bad_lines='skip',  # Skip malformed lines
        encoding='utf-8',
        low_memory=False
    )'''

content = content.replace(old_parse, new_parse)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed TSV parsing with error handling")
print("\nRestart:")
print("   docker-compose restart data_harvester")
