"""
FIX FINAL: Support des formats de temps 2023-11 ET 2023M11
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remplacer la gestion du temps
old_time_handling = """            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:
                y, m = time_str.split('M')
                date_str = f"{y}-{m:0>2}-01"  # Pad month with 0
            else:
                if not sample_logged:
                    logging.warning(f"Skipping record: invalid time format: {time_str}")
                continue"""

new_time_handling = """            # Convert time format to YYYY-MM-DD
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

content = content.replace(old_time_handling, new_time_handling)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Fixed time format handling!")
print("   Now supports: 2023M11 AND 2023-11")
print("\nRestart:")
print("   docker-compose restart data_harvester")
