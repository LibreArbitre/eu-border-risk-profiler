"""
FIX CRITIQUE : Corriger les noms de dimensions et format de temps
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: asyl_app → applicant
content = content.replace("coords.get('asyl_app')", "coords.get('applicant')")

# Fix 2: Format de temps 2023-11 au lieu de 2023M11
old_time_parse = """            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:
                y, m = time_str.split('M')
                date_str = f"{y}-{m:0>2}-01"  # Pad month with 0
            else:
                if not sample_logged:
                    logging.warning(f"Skipping record: invalid time format: {time_str}")
                continue"""

new_time_parse = """            # Convert time format to YYYY-MM-DD
            if time_str:
                # Handle both 2023M01 and 2023-11 formats
                if 'M' in time_str:
                    y, m = time_str.split('M')
                    date_str = f"{y}-{m:0>2}-01"
                elif '-' in time_str and len(time_str) == 7:  # YYYY-MM format
                    date_str = f"{time_str}-01"
                else:
                    if not sample_logged:
                        logging.warning(f"Skipping record: invalid time format: {time_str}")
                    continue
            else:
                continue"""

content = content.replace(old_time_parse, new_time_parse)

# Fix 3: Dans clean_data aussi
content = content.replace("df['applicant_type'] == 'NASY_APP'", "df['applicant_type'].str.contains('NASY', na=False)")

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ BUGS CRITIQUES CORRIGÉS !")
print("\nCorrections:")
print("  1. asyl_app → applicant (bonne dimension)")
print("  2. Support format temps: 2023-11 ET 2023M11")
print("  3. Filtre NASY plus flexible (.contains au lieu de ==)")
print("\n🚀 Redémarrer: docker-compose down && docker-compose up --build")
print("\nATTENDU: Parsed > 0 records !")
