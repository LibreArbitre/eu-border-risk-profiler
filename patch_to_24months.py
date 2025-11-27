"""
Réduction d'urgence à 24 mois - même 60 mois par pays est trop pour l'API Eurostat
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Changer 60 en 24 mois
content = content.replace("'lastTimePeriod': '60'", "'lastTimePeriod': '24'")
# Mettre à jour le commentaire aussi
content = content.replace("# 3 years of data per country", "# 2 years of data per country")

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Réduit à 24 mois (2 ans) - limite stricte de l'API Eurostat")
print("\nConfiguration:")
print("  - 27 pays EU")
print("  - 24 mois par pays")
print("  - ~648 points de données (27 × 24)")
print("  - Suffisant pour RandomForest (minimum 12 mois requis)")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
