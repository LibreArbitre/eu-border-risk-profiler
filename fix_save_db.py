"""
Fix save_to_db: retirer citizen_code de required_cols
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Dans save_to_db, mettre à jour required_cols
old_required = "required_cols = ['date', 'geo_code', 'citizen_code', 'applicant_type', 'total_applications']"
new_required = "required_cols = ['date', 'geo_code', 'applicant_type', 'total_applications']"

content = content.replace(old_required, new_required)

# Aussi dans la définition de la table SQL
old_table = """                asylum_table = table('asylum_data',
                    column('date'),
                    column('geo_code'),
                    column('citizen_code'),
                    column('applicant_type'),
                    column('total_applications')
                )"""

new_table = """                asylum_table = table('asylum_data',
                    column('date'),
                    column('geo_code'),
                    column('applicant_type'),
                    column('total_applications')
                )"""

content = content.replace(old_table, new_table)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed save_to_db!")
print("   - Removed citizen_code from required_cols")
print("   - Updated table definition")
print("\nNOTE: La table DB a aussi citizen_code, il faudra peut-être la recréer")
print("\nRestart:")
print("   docker-compose down -v  # -v pour reset DB")
print("   docker-compose up --build -d")
