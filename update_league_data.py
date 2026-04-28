import requests
import json
import os

# Configuración
API_KEY = os.getenv("FOOTBALL_DATA_KEY")
BASE_URL = "https://api.football-data.org/v4"
COMPETITION = "PD" # Primera División de España
FILE_NAME = "liga_data.json"

def fetch_data():
    headers = {'X-Auth-Token': API_KEY}
    
    # 1. Obtener Tabla de Posiciones (Standings)
    print("Obteniendo standings...")
    standings_res = requests.get(f"{BASE_URL}/competitions/{COMPETITION}/standings", headers=headers)
    
    # 2. Obtener Resultados de la Temporada (Matches)
    print("Obteniendo resultados de partidos...")
    matches_res = requests.get(f"{BASE_URL}/competitions/{COMPETITION}/matches", headers=headers)
    
    if standings_res.status_code == 200 and matches_res.status_code == 200:
        data = {
            "last_updated": matches_res.json().get("competition", {}).get("lastUpdated"),
            "standings": standings_res.json().get("standings", [{}])[0].get("table", []),
            "matches": matches_res.json().get("matches", [])
        }
        
        with open(FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"✅ {FILE_NAME} actualizado con éxito.")
    else:
        print(f"❌ Error al consultar la API. Status: {standings_res.status_code} / {matches_res.status_code}")

if __name__ == "__main__":
    if not API_KEY:
        print("❌ Error: No se encontró la variable API_KEY_FOOTBALL")
    else:
        fetch_data()
