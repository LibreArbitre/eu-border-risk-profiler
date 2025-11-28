"""
Fix NASY_APP → FRST dans clean_data()
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix le filtre
content = content.replace(
    "df = df[df['applicant_type'] == 'NASY_APP'].copy()",
    "df = df[df['applicant_type'] == 'FRST'].copy()"
)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed filter: NASY_APP → FRST")
print("\nRestart:")
print("   docker-compose restart data_harvester")
