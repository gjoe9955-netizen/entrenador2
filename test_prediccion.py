import google.generativeai as genai
import json
import os
from scipy.stats import poisson

# Configuración (Usa tu clave real o variable de entorno)
GEMINI_KEY = os.getenv("GEMINI_KEY")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def obtener_analisis_ia(local, visitante, data_poisson):
    # Prompt de alto nivel sincronizado con el Bot
    prompt = f"""
Actúa como un Senior Tipster experto en LaLiga con 20 años de experiencia en análisis estadístico.
Tu objetivo es realizar un análisis técnico para inversores deportivos.

DATOS DEL PARTIDO:
⚽ Encuentro: {local} vs {visitante}
📊 Expectativa de Goles (Lambda): {local} ({data_poisson['lambda_h']:.2f}) | {visitante} ({data_poisson['lambda_a']:.2f})
📈 Probabilidades Poisson: Victoria Local {data_poisson['prob_h']*100:.1f}%, Empate {data_poisson['prob_d']*100:.2f}%, Victoria Visitante {data_poisson['prob_a']*100:.2f}%

ESTRUCTURA DE RESPUESTA:
1️⃣ **EL OJO DEL EXPERTO**: Análisis técnico de las probabilidades.
2️⃣ **MARCADOR PROBABLE**: Escenario exacto basado en Lambda.
3️⃣ **PICK DE VALOR**: Mercado recomendado.
4️⃣ **STAKE/CONFIANZA**: [1 al 10]

Finaliza con:
PICK_RESUMEN: [4 palabras clave en mayúsculas]
"""
    
    response = model.generate_content(prompt)
    return response.text

def predecir_con_ia(local_q, visitante_q):
    with open('modelo_poisson.json', 'r') as f:
        full_data = json.load(f)
    
    data = full_data["LaLiga"]
    teams = data['teams']
    
    # Búsqueda flexible de equipos
    m_l = next((t for t in teams if local_q.lower() in t.lower()), None)
    m_v = next((t for t in teams if visitante_q.lower() in t.lower()), None)
    
    if not m_l or not m_v:
        print("❌ Error: Uno o ambos equipos no están en el modelo.")
        return

    stats_l = teams[m_l]
    stats_v = teams[m_v]
    avg = data['averages']
    
    # Cálculos de Poisson
    lh = stats_l['att_h'] * stats_v['def_a'] * avg['league_home']
    la = stats_v['att_a'] * stats_l['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(9):
        for y in range(9):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    datos_partido = {'lambda_h': lh, 'lambda_a': la, 'prob_h': ph, 'prob_d': pd, 'prob_a': pa}
    
    analisis = obtener_analisis_ia(m_l, m_v, datos_partido)
    print(analisis)

if __name__ == "__main__":
    # Prueba con nombres flexibles
    predecir_con_ia("Real Madrid", "Barcelona")
