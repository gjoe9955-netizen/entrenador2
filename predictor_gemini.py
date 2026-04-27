import google.generativeai as genai
import json
import os
from scipy.stats import poisson

# Configura tu API KEY de Gemini
genai.configure(api_key="TU_API_KEY_DE_GEMINI")
model = genai.GenerativeModel('gemini-1.5-flash')

def obtener_analisis_ia(local, visitante, data_poisson):
    # Prompt diseñado para que la IA no invente, sino que analice
    prompt = f"""
    Actúa como un experto analista de datos deportivos de LaLiga Española.
    Basado en mi modelo matemático de Poisson, tengo estos datos para el partido {local} vs {visitante}:
    
    - Goles esperados {local}: {data_poisson['lambda_h']:.2f}
    - Goles esperados {visitante}: {data_poisson['lambda_a']:.2f}
    - Probabilidad Victoria {local}: {data_poisson['prob_h']*100:.2f}%
    - Probabilidad Empate: {data_poisson['prob_d']*100:.2f}%
    - Probabilidad Victoria {visitante}: {data_poisson['prob_a']*100:.2f}%
    
    Escribe un análisis breve (máximo 4 párrafos) para un grupo de Telegram. 
    Incluye:
    1. Una interpretación de por qué el modelo da esos favoritos.
    2. Un marcador exacto más probable.
    3. Un consejo de "pick" (ejemplo: Over 2.5 goles, Gana Local, etc).
    Usa emojis y un tono profesional pero emocionante.
    """
    
    response = model.generate_content(prompt)
    return response.text

def predecir_con_ia(local, visitante):
    # Cargar tu JSON generado por el trainer.py
    with open('modelo_poisson.json', 'r') as f:
        data = json.load(f)
    
    stats_l = data['teams'][local]
    stats_v = data['teams'][visitante]
    avg = data['averages']
    
    # Cálculos de Poisson
    lh = stats_l['att_h'] * stats_v['def_a'] * avg['league_home']
    la = stats_v['att_a'] * stats_l['def_h'] * avg['league_away']
    
    # Calcular probabilidades 1X2 simplificadas
    ph, pd, pa = 0, 0, 0
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    datos_partido = {'lambda_h': lh, 'lambda_a': la, 'prob_h': ph, 'prob_d': pd, 'prob_a': pa}
    
    # Llamar a Gemini
    analisis = obtener_analisis_ia(local, visitante, datos_partido)
    print(analisis)

# Prueba
if __name__ == "__main__":
    predecir_con_ia("Real Madrid", "Real Betis")
