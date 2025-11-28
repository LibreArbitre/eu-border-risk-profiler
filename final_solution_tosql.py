"""
SOLUTION FINALE: Remplacer toute la logique save_to_db par df.to_sql() simple
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Trouver et remplacer toute la fonction save_to_db
import re

# Pattern pour trouver la fonction complète
pattern = r'@retry\("DB save"\)\s*\ndef save_to_db\(df\):.*?(?=\n@|\ndef [a-z_]+\(|\nif __name__|$)'

# Nouvelle fonction simple
new_function = '''@retry("DB save")
def save_to_db(df):
    if df.empty:
        logging.info("No data to save.")
        return
    
    engine = get_db_engine()
    logging.info(f"Saving {len(df)} records to DB using to_sql()...")
    
    # Use pandas to_sql - much simpler!
    df.to_sql(
        'asylum_data',
        engine,
        if_exists='append',
        index=False,
        method='multi',  # Batch insert
        chunksize=500
    )
    
    logging.info("Data saved successfully.")

'''

content = re.sub(pattern, new_function, content, flags=re.DOTALL)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ SOLUTION FINALE appliquée!")
print("\nRemplacé save_to_db par version simple avec df.to_sql()")
print("  - Plus de problème ON CONFLICT")
print("  - Plus de suffixes _m0, _m1")
print("  - Pandas gère tout")
print("\nNOTE: La table doit permettre les duplicates maintenant")
print("\nRestart:")
print("   docker-compose down -v")
print("   docker-compose up --build -d")
