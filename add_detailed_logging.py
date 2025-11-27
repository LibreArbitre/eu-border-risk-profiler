"""
Ajouter logging détaillé dans la boucle de parsing pour identifier le problème
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Ajouter logging après "for k, v in values.items():"
old_loop_start = """        # Iterate over values
        for k, v in values.items():
            try:
                idx = int(k)
            except ValueError:
                continue"""

new_loop_start = """        # Iterate over values
        sample_logged = False
        for k, v in values.items():
            try:
                idx = int(k)
            except ValueError:
                continue"""

content = content.replace(old_loop_start, new_loop_start)

# Ajouter logging pour voir les coords décodées
old_decode = """            # Extract relevant fields
            time_str = coords.get('time')
            geo = coords.get('geo')
            citizen = coords.get('citizen')
            app_type = coords.get('asyl_app')

            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:"""

new_decode = """            # Extract relevant fields
            time_str = coords.get('time')
            geo = coords.get('geo')
            citizen = coords.get('citizen')
            app_type = coords.get('asyl_app')
            
            # Log first record to see structure
            if not sample_logged:
                logging.info(f"Sample coords: time={time_str}, geo={geo}, citizen={citizen}, app_type={app_type}, value={v}")
                logging.info(f"All coord keys: {list(coords.keys())}")
                sample_logged = True

            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:"""

content = content.replace(old_decode, new_decode)

# Ajouter compteur de records skippés
old_continue = """            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:
                y, m = time_str.split('M')
                date_str = f"{y}-{m}-01"
            else:
                continue"""

new_continue = """            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:
                y, m = time_str.split('M')
                date_str = f"{y}-{m:0>2}-01"  # Pad month with 0
            else:
                if not sample_logged:
                    logging.warning(f"Skipping record: invalid time format: {time_str}")
                continue"""

content = content.replace(old_continue, new_continue)

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Ajouté logging détaillé dans la boucle de parsing")
print("\nCe qui sera loggé:")
print("  - Exemple de coords décodées (1er record)")
print("  - Toutes les clés de dimensions disponibles")
print("  - Records skippés avec raison")
print("\nRedémarrer: docker-compose down && docker-compose up")
