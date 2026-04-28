import os
import json
import requests
import base64
from dotenv import load_dotenv

load_dotenv()

# --- Configuración Corregida ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
# Usamos el nombre exacto de tus capturas de GitHub/Railway
API_KEY_FOOTBALL = os.getenv('FOOTBALL_DATA_API_KEY') 
REPO_PATH = "gjoe9955-netizen/entrenador2"
# Unificado con el nombre que usa el bot
HISTORIAL_FILE = "historial.json" 

def obtener_resultados_recientes():
    """Consulta los resultados finalizados de LaLiga"""
    url = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
    headers = {"X-Auth-Token": API_KEY_FOOTBALL}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json().get('matches', [])
        return []
    except Exception as e:
        print(f"❌ Error al consultar API: {e}")
        return []

def normalizar_nombre(nombre):
    """Limpia nombres para facilitar la coincidencia"""
    if not nombre: return ""
    return nombre.lower().replace("rcd", "").replace("cf", "").replace("real", "").strip()

def actualizar_historial():
    if not GITHUB_TOKEN:
        print("❌ Error: No se encontró GITHUB_TOKEN.")
        return
    
    # 1. Obtener Historial actual desde GitHub
    url_gh = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
    headers_gh = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        res_get = requests.get(url_gh, headers=headers_gh)
        if res_get.status_code != 200:
            print(f"❌ No se pudo obtener el historial de GitHub: {res_get.text}")
            return
            
        file_data = res_get.json()
        content = base64.b64decode(file_data['content']).decode('utf-8')
        historial = json.loads(content)

        # 2. Obtener resultados reales
        resultados_reales = obtener_resultados_recientes()
        if not resultados_reales:
            print("⚠️ No se obtuvieron resultados nuevos de la API.")
            return

        cambio = False
        # 3. Cruzar datos
        for pick in historial:
            # Sincronizado con el status del bot (con emoji)
            if pick.get("status") == "⏳ PENDIENTE":
                equipo_l, equipo_v = pick["partido"].split(" vs ")
                
                for match in resultados_reales:
                    api_l = match['homeTeam']['name']
                    api_v = match['awayTeam']['name']
                    
                    if normalizar_nombre(equipo_l) == normalizar_nombre(api_l) and \
                       normalizar_nombre(equipo_v) == normalizar_nombre(api_v):
                        
                        goles_l = match['score']['fullTime']['home']
                        goles_v = match['score']['fullTime']['away']
                        marcador_real = f"{goles_l}-{goles_v}"
                        
                        pick["marcador_real"] = marcador_real
                        pick["status"] = "✅ REVISADO" # Mantenemos el estilo de emojis
                        
                        # Determinar ganador real
                        if goles_l > goles_v: pick["ganador_real"] = "Local"
                        elif goles_l < goles_v: pick["ganador_real"] = "Visitante"
                        else: pick["ganador_real"] = "Empate"
                        
                        cambio = True
                        print(f"✅ Resultado encontrado: {pick['partido']} -> {marcador_real}")
                        break

        if cambio:
            # Serializar correctamente
            json_str = json.dumps(historial, indent=4, ensure_ascii=False)
            new_content = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
            
            payload = {
                "message": "Auditoría automática de resultados 🏟️",
                "content": new_content,
                "sha": file_data['sha']
            }
            res_put = requests.put(url_gh, headers=headers_gh, json=payload)
            if res_put.status_code == 200:
                print("🚀 Historial sincronizado con éxito en GitHub.")
            else:
                print(f"❌ Error al subir a GitHub: {res_put.text}")
        else:
            print("ℹ️ No hay nuevos resultados que coincidan con los picks pendientes.")

    except Exception as e:
        print(f"❌ Error general: {e}")

if __name__ == "__main__":
    actualizar_historial()
