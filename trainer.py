import os
import requests
import json
import pandas as pd

# Configuración Football-Data.org
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
# Quitamos el filtro de temporada fija para que la API nos de lo que tenga disponible
URL = "https://api.football-data.org/v4/competitions/PD/matches?status=FINISHED"
HEADERS = {"X-Auth-Token": API_KEY}

def train_spain():
    if not API_KEY:
        print("❌ ERROR: No se encontró la API KEY.")
        return

    try:
        print("Consultando LaLiga Española...")
        response = requests.get(URL, headers=HEADERS, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Error API ({response.status_code}): {response.text}")
            # Creamos un archivo vacío para que git add no falle
            with open('modelo_poisson.json', 'w') as f: json.dump({"error": "api_fail"}, f)
            return

        data = response.json()
        matches = data.get('matches', [])
        
        if not matches:
            print("⚠️ No hay partidos terminados.")
            with open('modelo_poisson.json', 'w') as f: json.dump({"error": "no_matches"}, f)
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
        avg_h, avg_a = float(df['goals_h'].mean()), float(df['goals_a'].mean())
        
        teams_stats = {}
        teams = pd.unique(df[['home', 'away']].values.ravel())
        
        for team in teams:
            h_df, a_df = df[df['home'] == team], df[df['away'] == team]
            teams_stats[team] = {
                "att_h": float(h_df['goals_h'].mean() / avg_h) if not h_df.empty else 1.0,
                "def_h": float(h_df['goals_a'].mean() / avg_a) if not a_df.empty else 1.0,
                "att_a": float(a_df['goals_a'].mean() / avg_a) if not a_df.empty else 1.0,
                "def_a": float(a_df['goals_h'].mean() / avg_h) if not a_df.empty else 1.0
            }

        output = {"LaLiga": {"averages": {"league_home": avg_h, "league_away": avg_a}, "teams": teams_stats}}

        with open('modelo_poisson.json', 'w') as f:
            json.dump(output, f, indent=4)
        print("✅ Archivo generado exitosamente.")

    except Exception as e:
        print(f"❌ Error: {e}")
        with open('modelo_poisson.json', 'w') as f: json.dump({"error": str(e)}, f)

if __name__ == "__main__":
    train_spain()
