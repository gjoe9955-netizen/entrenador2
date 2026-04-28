import os
import json
import requests
import time

def actualizar():
    api_key = os.getenv("API_KEY_FOOTBALL")
    if not api_key:
        print("❌ No se encontró la API KEY")
        return

    headers = {'X-Auth-Token': api_key}
    # ID 2014 = Primera División de España (PD)
    LIGA_ID = "2014"
    
    print(f"📡 Descargando datos de La Liga (ID: {LIGA_ID})...")
    
    try:
        # 1. Obtener Clasificación (para los promedios de goles/stats)
        url_standings = f"https://api.football-data.org/v4/competitions/{LIGA_ID}/standings"
        res_standings = requests.get(url_standings, headers=headers).json()
        
        # 2. Obtener Partidos Finalizados (para el H2H)
        # Esperamos un segundo para no saturar la API gratuita (rate limit)
        time.sleep(2) 
        url_matches = f"https://api.football-data.org/v4/competitions/{LIGA_ID}/matches?status=FINISHED"
        res_matches = requests.get(url_matches, headers=headers).json()

        # Estructuramos el JSON final como lo espera el bot.py
        data_final = {
            "standings": [],
            "matches": []
        }

        if "standings" in res_standings:
            # Extraemos la tabla de posiciones plana
            data_final["standings"] = res_standings["standings"][0]["table"]
            print("✅ Clasificación obtenida.")

        if "matches" in res_matches:
            data_final["matches"] = res_matches["matches"]
            print(f"✅ {len(res_matches['matches'])} partidos históricos obtenidos.")

        # Guardar el archivo que el bot leerá localmente
        with open("liga_data.json", "w", encoding="utf-8") as f:
            json.dump(data_final, f, indent=4, ensure_ascii=False)
        
        print("🚀 Archivo liga_data.json generado correctamente.")

    except Exception as e:
        print(f"💥 Error durante la actualización: {e}")

if __name__ == "__main__":
    actualizar()
