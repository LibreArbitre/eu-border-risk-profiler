"""
Patch urgente pour réduire lastTimePeriod de 60 à 36 mois
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer 60 par 36
content = content.replace("'lastTimePeriod': '60'", "'lastTimePeriod': '36'")

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Reduced lastTimePeriod from 60 to 36 months")
print("   This should fix the 413 Payload Too Large error")
print("\nRestart: docker-compose down && docker-compose up --build")
