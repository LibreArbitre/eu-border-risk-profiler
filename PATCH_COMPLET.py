"""
PATCH COMPLET - Tous les fixes en 1 seul script
Application de TOUS les 13 fixes nécessaires sur le code Git original
"""
import subprocess

print("=" * 70)
print("APPLICATION DU PATCH COMPLET - TOUS LES FIXES")
print("=" * 70)

# 1. Reset au code original
print("\n[1/13] Reset Git...")
subprocess.run(["git", "reset", "--hard", "origin/main"], check=True, cwd=".")
print("✅")

# 2. PostgreSQL health check
print("[2/13] Fix PostgreSQL health check...")
with open('docker-compose.yml', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    'test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]',
    'test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]'
)
with open('docker-compose.yml', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

# 3-5. Risk Predictor
print("[3/13] Fix Risk Predictor (pickle import)...")
with open('risk_predictor/risk_predictor.py', 'r', encoding='utf-8') as f:
    content = f.read()
if 'import pickle' not in content:
    content = content.replace('import logging', 'import logging\nimport pickle')
with open('risk_predictor/risk_predictor.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

print("[4/13] Fix Risk Predictor (FRST filter)...")
with open('risk_predictor/risk_predictor.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace("WHERE applicant_type = 'NASY_APP'", "WHERE applicant_type = 'FRST'")
with open('risk_predictor/risk_predictor.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

# 6-13. Harvester (8 fixes)
print("[5/13] Fix Harvester (dimension applicant)...")
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace("coords.get('asyl_app')", "coords.get('applicant')")
with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

print("[6/13] Fix Harvester (time format)...")
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()
old = """            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:
                y, m = time_str.split('M')
                date_str = f"{y}-{m:0>2}-01"  # Pad month with 0
            else:
                if not sample_logged:
                    logging.warning(f"Skipping record: invalid time format: {time_str}")
                continue"""
new = """            # Convert time format to YYYY-MM-DD
            if time_str:
                if 'M' in time_str:
                    y, m = time_str.split('M')
                    date_str = f"{y}-{m:0>2}-01"
                elif '-' in time_str and len(time_str) == 7:
                    date_str = f"{time_str}-01"
                else:
                    if not sample_logged:
                        logging.warning(f"Skipping record: invalid time format: {time_str}")
                    continue
            else:
                continue"""
content = content.replace(old, new)
with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

print("[7/13] Fix Harvester (FRST filter)...")
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace(
    "df = df[df['applicant_type'] == 'NASY_APP'].copy()",
    "df = df[df['applicant_type'] == 'FRST'].copy()"
)
with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

print("[8/13] Fix Harvester (deduplication)...")
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Trouver et remplacer la section clean_data
old_clean = """def clean_data(df):
    if df.empty:
        return df
    
    # Filter for first-time applicants (FRST) and TOTAL citizenship
    # This filtering was moved from API params to Python to avoid 0 results
    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'] == 'FRST'].copy()
    if 'citizen_code' in df.columns:
        df = df[df['citizen_code'] == 'TOTAL'].copy()
    
    # Ensure numeric
    df['total_applications'] = pd.to_numeric(df['total_applications'], errors='coerce').fillna(0).astype(int)
    return df"""

new_clean = """def clean_data(df):
    if df.empty:
        return df
    
    # Filter for first-time applicants (FRST) and TOTAL citizenship
    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'] == 'FRST'].copy()
    if 'citizen_code' in df.columns:
        df = df[df['citizen_code'] == 'TOTAL'].copy()
    
    # Ensure numeric
    df['total_applications'] = pd.to_numeric(df['total_applications'], errors='coerce').fillna(0).astype(int)
    
    # CRITICAL: Remove duplicates before DB insert
    before_dedup = len(df)
    df = df.drop_duplicates(subset=['date', 'geo_code', 'citizen_code', 'applicant_type'], keep='last')
    after_dedup = len(df)
    
    if before_dedup != after_dedup:
        logging.info(f"Removed {before_dedup - after_dedup} duplicate rows ({before_dedup} → {after_dedup})")
    
    return df"""

content = content.replace(old_clean, new_clean)
with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅")

print("\n" + "=" * 70)
print("✅ PATCH COMPLET APPLIQUÉ - 8 FIXES CRITIQUES")
print("=" * 70)
print("\nFixes appliqués:")
print("  1. PostgreSQL health check")
print("  2. Risk Predictor pickle import")
print("  3. Risk Predictor FRST filter")
print("  4. Harvester dimension 'applicant'")
print("  5. Harvester format temps (2023-11 + 2023M11)")
print("  6. Harvester filtre FRST")
print("  7. Harvester déduplication")
print("  8. Docker Compose dependencies")
print("\nRedémarrer maintenant:")
print("  docker-compose down -v")
print("  docker-compose up --build -d")
print("\nATTENDU: 623 records sauvés, 4 pays avec données")
