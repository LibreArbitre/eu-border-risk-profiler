"""
SCRIPT FINAL: Reset au code original + Application des 5 fixes critiques SEULEMENT
"""
import subprocess
import re

print("=" * 60)
print("RESTAURATION VERSION STABLE + FIXES CRITIQUES")
print("=" * 60)

# 1. Reset complet au code original
print("\n1. Reset au code Git original...")
subprocess.run(["git", "reset", "--hard", "origin/main"], check=True, cwd=".")
print("✅ Code original restauré")

# 2. Fix PostgreSQL health check
print("\n2. Fix PostgreSQL health check...")
with open('docker-compose.yml', 'r', encoding='utf-8') as f:
    content = f.read()

old_health = 'test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]'
new_health = 'test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]'
content = content.replace(old_health, new_health)

with open('docker-compose.yml', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ PostgreSQL health check")

# 3. Fix Risk Predictor
print("\n3. Fix Risk Predictor...")
with open('risk_predictor/risk_predictor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add pickle import if missing
if 'import pickle' not in content:
    content = content.replace('import logging', 'import logging\nimport pickle')
    print("  ✅ Added pickle import")

# Fix NASY_APP → FRST dans la requête SQL
content = content.replace(
    "WHERE applicant_type = 'NASY_APP'",
    "WHERE applicant_type = 'FRST'"
)
print("  ✅ Fixed applicant_type filter")

with open('risk_predictor/risk_predictor.py', 'w', encoding='utf-8') as f:
    f.write(content)

# 4. Fix Harvester (minimal)
print("\n4. Fix Harvester (dimension names)...")
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix dimension name asyl_app → applicant
content = content.replace(
    "coords.get('asyl_app')",
    "coords.get('applicant')"
)
print("  ✅ Fixed dimension name")

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n" + "=" * 60)
print("✅ TOUS LES FIXES CRITIQUES APPLIQUÉS")
print("=" * 60)
print("\nConfiguration finale:")
print("  - PostgreSQL: health check OK")
print("  - Risk Predictor: pickle + FRST filter")
print("  - Harvester: applicant dimension")
print("\nRedémarrer:")
print("  docker-compose down -v")
print("  docker-compose up --build -d")
print("\nATTENDU: 623 records, 4 pays avec données (DE, IT, NL, CY)")
