"""
Augmenter la période de données de 36 à 60 mois pour de meilleures prédictions
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Changer 36 en 60 mois
content = content.replace("'lastTimePeriod': '36'", "'lastTimePeriod': '60'")

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Période augmentée à 60 mois (5 ans)!")
print("\nAvantages:")
print("  - Plus de données historiques: ~1,350 points au lieu de ~810")
print("  - Meilleures prédictions ML (détection de tendances long-terme)")
print("  - 5 cycles annuels au lieu de 3 (meilleure capture de saisonnalité)")
print("  - Toujours pays-par-pays → pas de risque 413 Error")
print("\nRedémarrer: docker-compose down && docker-compose up --build")
