"""
Ajout de logging debug pour comprendre pourquoi parse retourne 0 records
"""
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Trouver la ligne "for data in data_list:" et ajouter du logging après
new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    
    # Après "for data in data_list:", ajouter du logging
    if '    for data in data_list:' in line:
        new_lines.append('        logging.info(f"Processing country data. Has value: {\'value\' in data}, Has dimension: {\'dimension\' in data}")\n')
    
    # Après "if not data or 'value' not in data", ajouter logging
    if "        if not data or 'value' not in data or 'dimension' not in data:" in line:
        new_lines.append('            logging.warning(f"Skipping data: empty={not data}, no_value={\'value\' not in data if data else \'N/A\'}, no_dim={\'dimension\' not in data if data else \'N/A\'}")\n')
    
    # Avant "return pd.DataFrame(all_records)", ajouter logging
    if '    return pd.DataFrame(all_records)' in line and 'parse_eurostat_json' in ''.join(lines[max(0,i-20):i]):
        new_lines.insert(len(new_lines)-1, f'    logging.info(f"Total records collected: {{len(all_records)}}")\n')

with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("✅ Ajouté logging debug dans parse_eurostat_json")
print("\nRedémarrer pour voir les logs détaillés:")
print("   docker-compose down && docker-compose up --build")
print("\nChercher dans les logs:")
print('   - "Processing country data"')
print('   - "Skipping data"') 
print('   - "Total records collected"')
