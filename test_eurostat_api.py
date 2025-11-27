"""
Script de diagnostic pour tester l'API Eurostat
"""
import requests
import json

# URL et paramètres de l'API Eurostat
BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/migr_asyappctzm"
PARAMS = {
    'format': 'JSON',
    'lang': 'en',
    'applicant': 'NASY_APP',
    'age': 'TOTAL',
    'sex': 'T',
    'unit': 'PER',
    'citizen': 'TOTAL',
    'lastTimePeriod': '60'
}

print("🔍 Test de l'API Eurostat...")
print(f"URL: {BASE_URL}")
print(f"Paramètres: {PARAMS}\n")

try:
    response = requests.get(BASE_URL, params=PARAMS, timeout=30)
    print(f"✅ Status: {response.status_code}")
    print(f"✅ Content-Type: {response.headers.get('content-type')}\n")
    
    if response.status_code == 200:
        data = response.json()
        
        # Afficher la structure
        print("📊 Structure de la réponse:")
        print(f"   - Clés principales: {list(data.keys())}")
        
        if 'value' in data:
            print(f"   - Nombre de valeurs: {len(data['value'])}")
        else:
            print("   ⚠️ Pas de clé 'value' trouvée!")
            
        if 'dimension' in data:
            print(f"   - Dimensions: {list(data['dimension'].keys())}")
        else:
            print("   ⚠️ Pas de clé 'dimension' trouvée!")
            
        if 'id' in data:
            print(f"   - IDs: {data['id']}")
        else:
            print("   ⚠️ Pas de clé 'id' trouvée!")
            
        # Sauvegarder la réponse pour inspection
        with open('eurostat_response_debug.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("\n✅ Réponse complète sauvegardée dans 'eurostat_response_debug.json'")
        
        # Afficher un extrait
        print("\n📄 Extrait de la réponse (premières 500 caractères):")
        print(json.dumps(data, indent=2)[:500])
        
    else:
        print(f"❌ Erreur HTTP: {response.status_code}")
        print(f"   Réponse: {response.text[:500]}")
        
except requests.exceptions.Timeout:
    print("❌ Timeout - L'API Eurostat n'a pas répondu dans les 30 secondes")
except requests.exceptions.RequestException as e:
    print(f"❌ Erreur de requête: {e}")
except json.JSONDecodeError as e:
    print(f"❌ Erreur de parsing JSON: {e}")
    print(f"   Contenu reçu: {response.text[:500]}")
except Exception as e:
    print(f"❌ Erreur inattendue: {e}")
