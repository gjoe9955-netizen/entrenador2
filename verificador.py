import os
import json
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

# Configuración unificada
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
API_KEY_FOOTBALL = os.getenv('FOOTBALL_DATA_API_KEY') # Unificada
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

def obtener_resultados_recientes():
    """Consulta los resultados de LaLiga (PD)"""
    url = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
    headers = {"X-Auth-Token": API_KEY_FOOTBALL}
    try:
        r = requests.get(url, headers=headers, timeout=12)
        return r.json().get('matches', [])
    except:
        return []

def actualizar_historial():
    if not GITHUB_TOKEN or not API_KEY_FOOTBALL:
        print("❌ Faltan credenciales (GitHub o API Key).")
        return
    
    url_gh = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
    headers_gh = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    r = requests.get(url_gh, headers=headers_gh)
    if r.status_code != 200:
        print("❌ No se pudo acceder al historial en GitHub.")
        return
    
    file_data = r.json()
    historial = json.loads(base64.b64decode(file_data['content']).decode('utf-8'))
    resultados_reales = obtener_resultados_recientes()
    
    cambio = False
    for pick in historial:
        if "estado" not in pick or pick["estado"] == "Pendiente":
            for match in resultados_reales:
                h_name = match['homeTeam']['name'].lower()
                a_name = match['awayTeam']['name'].lower()
                
                # Match flexible entre el historial y la API
                if h_name in pick['partido'].lower() and a_name in pick['partido'].lower():
                    res = match['score']['fullTime']
                    pick["resultado_real"] = f"{res['home']}-{res['away']}"
                    pick["estado"] = "AUDITADO"
                    cambio = True
                    break

    if cambio:
        new_content = base64.b64encode(json.dumps(historial, indent=4).encode('utf-8')).decode('utf-8')
        payload = {"message": "🤖 Auditoría automática de resultados", "content": new_content, "sha": file_data['sha']}
        requests.put(url_gh, headers=headers_gh, json=payload)
        print("✅ Historial actualizado y subido a GitHub.")
    else:
        print("ℹ️ Nada nuevo que auditar.")

if __name__ == "__main__":
    actualizar_historial()
