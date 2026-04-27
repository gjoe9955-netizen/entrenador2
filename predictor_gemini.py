import google.generativeai as genai
import json
import os
from scipy.stats import poisson
from dotenv import load_dotenv

load_dotenv()

# Configuración
GENAI_KEY = os.getenv("GEMINI_KEY")
genai.configure(api_key=GENAI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def ajuste_dixon_coles(x, y, lh, la, rho=-0.15):
    """Ajuste de correlación para marcadores bajos."""
    if x == 0 and y == 0: return 1 - (lh * la * rho)
    if x == 0 and y == 1: return 1 + (lh * rho)
    if x == 1 and y == 0: return 1 + (la * rho)
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def obtener_analisis_ia(local, visitante, res):
    """Genera el análisis profundo usando los resultados del cálculo"""
    prompt = f"""
    Eres un analista de Big Data deportivo especializado en LaLiga. 
    Analiza el siguiente cruce basado en el modelo Poisson con ajuste Dixon-Coles:
    
    PARTIDO: {local} vs {visitante}
    - Goles Esperados (Lambda) Local: {res['lh']:.2f}
    - Goles Esperados (Lambda) Visita: {res['la']:.2f}
    
    PROBABILIDADES CALCULADAS:
    - Victoria {local}: {res['p_h']:.1%}
    - Empate: {res['p_d']:.1%}
    - Victoria {visitante}: {res['p_a']:.1%}
    
    INSTRUCCIONES:
    1. Evalúa si el partido tiende a ser Over o Under (basado en la suma de Lambdas).
    2. Identifica el 'Value': Si un equipo tiene >50% pero su Lambda es ajustada, advierte el riesgo.
    3. Propón un marcador exacto y un pick de alto valor (ej. Gana o Empata, Ambos marcan, etc.).
    Tono: Profesional, técnico y directo para apostadores expertos.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ Error en la generación de IA: {e}"

def predecir_con_ia(local, visitante):
    """Función principal para ejecutar desde consola o test"""
    if not os.path.exists('modelo_poisson.json'):
        return "❌ Error: modelo_poisson.json no encontrado. Ejecuta trainer.py primero."

    with open('modelo_poisson.json', 'r') as f:
        data = json.load(f)
    
    try:
        stats = data['LaLiga']['teams']
        avg = data['LaLiga']['averages']
        
        s_l, s_v = stats[local], stats[visitante]
        
        # Lambdas
        lh = s_l['att_h'] * s_v['def_a'] * avg['league_home']
        la = s_v['att_a'] * s_l['def_h'] * avg['league_away']
        
        ph, pd, pa = 0, 0, 0
        for x in range(7):
            for y in range(7):
                p = (poisson.pmf(x, lh) * poisson.pmf(y, la)) * ajuste_dixon_coles(x, y, lh, la)
                if x > y: ph += p
                elif x == y: pd += p
                else: pa += p
        
        resultados = {"lh": lh, "la": la, "p_h": ph, "p_d": pd, "p_a": pa}
        return obtener_analisis_ia(local, visitante, resultados)

    except KeyError as e:
        return f"❌ Error: El equipo {e} no está en la base de datos."

if __name__ == "__main__":
    # Test rápido de consola
    print(predecir_con_ia("Real Madrid CF", "FC Barcelona"))
