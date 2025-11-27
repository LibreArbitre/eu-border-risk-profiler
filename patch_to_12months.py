"""
Patch pour réduire à 12 mois (l'API Eurostat limite fortement la taille)
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer par 12 mois
content = content.replace("'lastTimePeriod': '36'", "'lastTimePeriod': '12'")

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Reduced to 12 months - the API has strict size limits")
print("\nRestart: docker-compose down && docker-compose up --build")
