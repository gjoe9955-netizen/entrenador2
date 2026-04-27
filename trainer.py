import os
import requests
import json
import pandas as pd

# Configuración unificada con tus Workflows
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
URL = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
HEADERS = {"X-Auth-Token": API_KEY}

def train_spain():
    if not API_KEY:
        print("❌ ERROR: No se encontró FOOTBALL_DATA_API_KEY en las variables de entorno.")
        return

    try:
        print("Consultando datos de LaLiga (PD) en Football-Data.org...")
        response = requests.get(URL, headers=HEADERS, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Error API ({response.status_code}): {response.text}")
            return

        data = response.json()
        matches = data.get('matches', [])
        
        if not matches:
            print("⚠️ No se encontraron partidos finalizados para procesar.")
            return

        goles = []
        for m in matches:
            if m.get('score') and m['score'].get('fullTime'):
                goles.append({
                    'home': m['homeTeam']['name'],
                    'away': m['awayTeam']['name'],
                    'goals_h': m['score']['fullTime']['home'],
                    'goals_a': m['score']['fullTime']['away']
                })
        
        df = pd.DataFrame(goles)
        
        # Cálculos de promedios de la liga
        avg_h = float(df['goals_h'].mean())
        avg_a = float(df['goals_a'].mean())
        
        teams_stats = {}
        # Obtener lista única de equipos
        equipos_unicos = sorted(pd.unique(df[['home', 'away']].values.ravel()))
        
        for team in equipos_unicos:
            h_df = df[df['home'] == team]
            a_df = df[df['away'] == team]
            
            # Cálculo de Fuerza de Ataque y Defensa (Poisson)
            teams_stats[team] = {
                "att_h": float(h_df['goals_h'].mean() / avg_h) if not h_df.empty else 1.0,
                "def_h": float(h_df['goals_a'].mean() / avg_a) if not h_df.empty else 1.0,
                "att_a": float(a_df['goals_a'].mean() / avg_a) if not a_df.empty else 1.0,
                "def_a": float(a_df['goals_h'].mean() / avg_h) if not a_df.empty else 1.0
            }

        # Estructura final del JSON optimizada para el bot
        output = {
            "LaLiga": {
                "averages": {
                    "league_home": avg_h,
                    "league_away": avg_a
                },
                "teams": teams_stats,
                "equipo_nombres": equipos_unicos  # Lista para que el bot no use la API
            }
        }

        with open('modelo_poisson.json', 'w') as f:
            json.dump(output, f, indent=4)
            
        print(f"✅ Modelo generado con {len(equipos_unicos)} equipos de LaLiga.")

    except Exception as e:
        print(f"❌ Error crítico en el entrenamiento: {e}")

if __name__ == "__main__":
    train_spain()
