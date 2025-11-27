"""
Solution finale : Télécharger les données pays par pays
L'API Eurostat limite la taille, donc on doit faire plusieurs petites requêtes au lieu d'une grosse
"""

# Lire le fichier harvester
with open('data_harvester/harvester.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Trouver et remplacer la fonction fetch_eurostat_data
new_fetch_function = '''@retry("Eurostat fetch")
def fetch_eurostat_data():
    """
    Fetch data from Eurostat API country by country to avoid 413 Payload Too Large.
    The API has strict size limits, so we fetch each EU country separately.
    """
    logging.info("Fetching data from Eurostat (country by country)...")
    
    # Liste des pays UE + quelques pays associés
    EU_COUNTRIES = [
        'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR',
        'DE', 'EL', 'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL',
        'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE'
    ]
    
    all_data = []
    
    for country in EU_COUNTRIES:
        try:
            params = {
                'format': 'JSON',
                'lang': 'en',
                'geo': country,
                'lastTimePeriod': '36'  # 3 years of data per country
            }
            logging.info(f"Fetching data for {country}...")
            response = requests.get(BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            country_data = response.json()
            all_data.append(country_data)
        except Exception as e:
            logging.warning(f"Failed to fetch data for {country}: {e}")
            # Continue with other countries even if one fails
            continue
    
    if not all_data:
        raise ValueError("No data fetched from any country")
    
    logging.info(f"Successfully fetched data for {len(all_data)} countries")
    return all_data
'''

# Trouver où commence fetch_eurostat_data (ligne ~78)
start_idx = None
end_idx = None
for i, line in enumerate(lines):
    if 'def fetch_eurostat_data():' in line:
        start_idx = i - 1  # Inclure le décorateur @retry
        # Trouver la fin de la fonction (prochaine def ou double retour chariot)
        for j in range(i + 1, len(lines)):
            if lines[j].startswith('def ') or (j < len(lines) - 1 and lines[j].strip() == '' and lines[j+1].strip() == ''):
                end_idx = j
                break
        break

if start_idx is not None and end_idx is not None:
    # Remplacer la fonction
    new_lines = lines[:start_idx] + [new_fetch_function + '\n\n'] + lines[end_idx:]
    
    # Modifier aussi parse_eurostat_json pour gérer une liste de données
    parse_function_new = '''def parse_eurostat_json(data_list):
    """
    Parses Eurostat JSON-stat format into a list of records.
    Now accepts a list of JSON responses (one per country).
    """
    if not data_list:
        return pd.DataFrame()
    
    all_records = []
    
    # Traiter chaque pays
    for data in data_list:
        if not data or 'value' not in data or 'dimension' not in data:
            continue

        # Extract dimensions
        dims = data['dimension']
        ids = data['id']

        values = data['value']
        dimensions_map = {}
        sizes = []

        # Prepare dimension mappings
        for dim_id in ids:
            dim_info = dims[dim_id]
            idx_map = dim_info['category']['index']
            inv_map = {int(v): k for k, v in idx_map.items()}
            dimensions_map[dim_id] = inv_map
            sizes.append(len(inv_map))

        # Calculate strides for index decoding
        strides = [1] * len(sizes)
        for i in range(len(sizes) - 2, -1, -1):
            strides[i] = strides[i+1] * sizes[i+1]

        # Iterate over values
        for k, v in values.items():
            try:
                idx = int(k)
            except ValueError:
                continue

            coords = {}

            # Decode index into dimension codes
            for i, dim_id in enumerate(ids):
                pos = (idx // strides[i]) % sizes[i]
                coords[dim_id] = dimensions_map[dim_id][pos]

            # Extract relevant fields
            time_str = coords.get('time')
            geo = coords.get('geo')
            citizen = coords.get('citizen')
            app_type = coords.get('asyl_app')

            # Convert time 2023M01 to 2023-01-01
            if time_str and 'M' in time_str:
                y, m = time_str.split('M')
                date_str = f"{y}-{m}-01"
            else:
                continue

            all_records.append({
                'date': date_str,
                'geo_code': geo,
                'citizen_code': citizen,
                'applicant_type': app_type,
                'total_applications': v
            })

    return pd.DataFrame(all_records)
'''
    
    # Trouver et remplacer parse_eurostat_json
    parse_start = None
    parse_end = None
    for i, line in enumerate(new_lines):
        if 'def parse_eurostat_json(data):' in line:
            parse_start = i
            for j in range(i + 1, len(new_lines)):
                if new_lines[j].startswith('def ') and j > i + 5:
                    parse_end = j
                    break
            break
    
    if parse_start is not None and parse_end is not None:
        final_lines = new_lines[:parse_start] + [parse_function_new + '\n'] + new_lines[parse_end:]
    else:
        final_lines = new_lines
    
    # Écrire le fichier
    with open('data_harvester/harvester.py', 'w', encoding='utf-8') as f:
        f.writelines(final_lines)
    
    print("✅ Harvester modifié pour télécharger pays par pays!")
    print("   - fetch_eurostat_data fait maintenant 27 requêtes (1 par pays)")
    print("   - parse_eurostat_json gère maintenant une liste de réponses")
    print("   - Chaque pays: 36 mois de données (au lieu de tout en une fois)")
    print("\nAvantages:")
    print("   - Évite l'erreur 413 Payload Too Large")
    print("   - Plus robuste (continue même si 1 pays échoue)")
    print("   - Toujours 3 ans de données par pays")
    print("\nRedémarrer: docker-compose down && docker-compose up --build")
else:
    print(f"❌ Impossible de trouver la fonction fetch_eurostat_data (start={start_idx}, end={end_idx})")
