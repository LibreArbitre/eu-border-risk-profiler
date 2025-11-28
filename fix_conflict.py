"""
Fix ON CONFLICT clause: retirer citizen_code
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix la clause ON CONFLICT
old_conflict = "index_elements=['date', 'geo_code', 'citizen_code', 'applicant_type']"
new_conflict = "index_elements=['date', 'geo_code', 'applicant_type']"

content = content.replace(old_conflict, new_conflict)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed ON CONFLICT clause!")
print("   Removed 'citizen_code' from index_elements")
print("\nRestart:")
print("   docker-compose down -v")
print("   docker-compose up --build -d")
