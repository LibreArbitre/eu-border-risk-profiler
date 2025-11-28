"""
Fix: Retirer citizen_code du drop_duplicates car elle n'existe plus après aggregation
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Mettre à jour drop_duplicates pour ne plus utiliser citizen_code
old_dedup = "df = df.drop_duplicates(subset=['date', 'geo_code', 'citizen_code', 'applicant_type'], keep='last')"
new_dedup = "df = df.drop_duplicates(subset=['date', 'geo_code', 'applicant_type'], keep='last')"

content = content.replace(old_dedup, new_dedup)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed drop_duplicates!")
print("   Removed 'citizen_code' from subset (column doesn't exist after aggregation)")
print("\nRestart:")
print("   docker-compose restart data_harvester")
