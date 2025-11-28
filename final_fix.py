"""
FIX FINAL : Utiliser 'FRST' au lieu de 'NASY' et gérer citizen_code correctement
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: NASY → FRST
old_filter = """    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'].str.contains('NASY', na=False)].copy()"""

new_filter = """    if 'applicant_type' in df.columns:
        df = df[df['applicant_type'] == 'FRST'].copy()  # First-time applicants"""

content = content.replace(old_filter, new_filter)

# Fix 2: Pour citizen_code, garder seulement TOTAL s'il existe, sinon tout
old_citizen_filter = """    if 'citizen_code' in df.columns:
        df = df[df['citizen_code'] == 'TOTAL'].copy()
        logging.info(f"After citizen filter: {len(df)} rows")"""

new_citizen_filter = """    if 'citizen_code' in df.columns:
        # Keep TOTAL if it exists, otherwise keep all
        if 'TOTAL' in df['citizen_code'].values:
            df = df[df['citizen_code'] == 'TOTAL'].copy()
            logging.info(f"After citizen filter (TOTAL): {len(df)} rows")
        else:
            logging.info(f"No TOTAL citizen_code, keeping all countries: {len(df)} rows")"""

content = content.replace(old_citizen_filter, new_citizen_filter)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ FIX FINAL APPLIQUÉ !")
print("\nCorrections:")
print("  - 'NASY' → 'FRST' (First-time applicants)")
print("  - Gestion intelligente de citizen_code")
print("\n🎉 Redémarrer: docker-compose down && docker-compose up --build")
print("\nATTENDU: Plusieurs milliers de rows après filtering !")
