import os
import json
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

# Configuración
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
API_KEY_FOOTBALL = os.getenv('FOOTBALL_API_KEY')
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

def obtener_resultados_recientes():
    """Consulta los resultados de los últimos 3 días en LaLiga"""
    url = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
    headers = {"X-Auth-Token": API_KEY_FOOTBALL}
    try:
        r = requests.get(url, headers=headers)
        return r.json().get('matches', [])
    except:
        return []

def actualizar_historial():
    if not GITHUB_TOKEN: return
    
    # 1. Obtener Historial de GitHub
    url_gh = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
    headers_gh = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    r = requests.get(url_gh, headers=headers_gh)
    if r.status_code != 200: return
    
    file_data = r.json()
    historial = json.loads(base64.b64decode(file_data['content']).decode('utf-8'))
    resultados_reales = obtener_resultados_recientes()
    
    cambio = False
    for pick in historial:
        # Solo revisamos los que no tengan estado aún
        if "estado" not in pick:
            for match in resultados_reales:
                local_real = match['homeTeam']['shortName']
                visit_real = match['awayTeam']['shortName']
                
                # Buscamos coincidencia de equipos en el pick
                if local_real.lower() in pick['partido'].lower() and visit_real.lower() in pick['partido'].lower():
                    goles_l = match['score']['fullTime']['home']
                    goles_v = match['score']['fullTime']['away']
                    marcador_real = f"{goles_l}-{goles_v}"
                    
                    # Guardamos el resultado real
                    pick["resultado_real"] = marcador_real
                    
                    # Verificación simple: ¿Acertó el ganador?
                    # (Esta lógica se puede hacer más compleja según el pick de la IA)
                    pick["estado"] = "REVISADO" 
                    cambio = True
                    break

    if cambio:
        new_content = base64.b64encode(json.dumps(historial, indent=4).encode('utf-8')).decode('utf-8')
        payload = {"message": "Auditoría de resultados", "content": new_content, "sha": file_data['sha']}
        requests.put(url_gh, headers=headers_gh, json=payload)
        print("✅ Historial actualizado con resultados reales.")
    else:
        print("ℹ️ No hay partidos nuevos para cerrar.")

if __name__ == "__main__":
    actualizar_historial()
