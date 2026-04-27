import json
from scipy.stats import poisson

def predecir_partido(local, visitante):
    # 1. Cargar el motor que entrenamos
    with open('modelo_poisson.json', 'r') as f:
        data = json.load(f)
    
    # 2. Extraer datos del JSON
    stats_local = data['teams'][local]
    stats_visita = data['teams'][visitante]
    avg = data['averages']
    
    # 3. Calcular la expectativa de goles (Lambda)
    # Goles Local = Ataque Local * Defensa Visitante * Promedio Goles Casa Liga
    lambda_h = stats_local['att_h'] * stats_visita['def_a'] * avg['league_home']
    
    # Goles Visitante = Ataque Visitante * Defensa Local * Promedio Goles Fuera Liga
    lambda_a = stats_visita['att_a'] * stats_local['def_h'] * avg['league_away']
    
    print(f"--- Análisis: {local} vs {visitante} ---")
    print(f"Expectativa de goles {local}: {lambda_h:.2f}")
    print(f"Expectativa de goles {visitante}: {lambda_a:.2f}")

    # 4. Calcular Probabilidades (1X2)
    prob_h, prob_d, prob_a = 0, 0, 0
    for x in range(7): # Goles max local
        for y in range(7): # Goles max visita
            p = poisson.pmf(x, lambda_h) * poisson.pmf(y, lambda_a)
            if x > y: prob_h += p
            elif x == y: prob_d += p
            else: prob_a += p

    print(f"\nProbabilidades:")
    print(f"Victoria {local}: {prob_h*100:.2f}%")
    print(f"Empate: {prob_d*100:.2f}%")
    print(f"Victoria {visitante}: {prob_a*100:.2f}%")

# --- PRUEBA REAL ---
# Nota: Usa los nombres exactos que aparecen en tu modelo_poisson.json
# Ejemplo: predecir_partido("Real Madrid", "Barcelona")
