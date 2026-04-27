import os
import json
import asyncio
import logging
import requests
import base64
from datetime import datetime
import telebot
from telebot.async_telebot import AsyncTeleBot
from google import generativeai as genai
from scipy.stats import poisson
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Logs ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
config_ia = {"modelo_actual": None}

# --- MOTOR DE TEST (INTACTO) ---
async def obtener_modelos_reales(api_key):
    try:
        genai.configure(api_key=api_key)
        aptos = []
        for m in genai.list_models():
            nombre = m.name.split('/')[-1]
            if 'generateContent' in m.supported_generation_methods:
                if any(x in nombre.lower() for x in ['flash', 'pro', '1.5', '2.0']):
                    try:
                        test_model = genai.GenerativeModel(nombre)
                        await asyncio.to_thread(test_model.generate_content, "hi", generation_config={"max_output_tokens": 1})
                        aptos.append(nombre)
                    except: continue
        aptos.sort(reverse=True)
        return aptos[:6]
    except: return []

# --- FUNCIONES DE DATOS ---
def obtener_datos_poisson():
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        response = requests.get(URL_JSON, headers=headers, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

def obtener_contexto_gratuito(local, visitante):
    if not FOOTBALL_DATA_KEY: return "Error: API Key no configurada."
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    base_url = "https://api.football-data.org/v4/"
    competiciones = ["PD", "2017"] # PD = LaLiga, 2017 = Segunda
    matches = []
    try:
        for comp in competiciones:
            r = requests.get(f"{base_url}competitions/{comp}/matches", headers=headers, params={"status": "FINISHED"}, timeout=10)
            if r.status_code == 200: matches.extend(r.json().get('matches', []))
        
        def extraer_racha(team_name):
            racha = []
            nombre_busqueda = team_name.lower()
            for m in reversed(matches):
                if len(racha) >= 5: break
                h_name = (m['homeTeam'].get('shortName') or m['homeTeam'].get('name') or "").lower()
                a_name = (m['awayTeam'].get('shortName') or m['awayTeam'].get('name') or "").lower()
                if nombre_busqueda in h_name or h_name in nombre_busqueda or nombre_busqueda in a_name or a_name in nombre_busqueda:
                    res = m['score']['fullTime']
                    if res['home'] == res['away']: racha.append("D")
                    elif (res['home'] > res['away'] and (nombre_busqueda in h_name or h_name in nombre_busqueda)) or \
                         (res['away'] > res['home'] and (nombre_busqueda in a_name or a_name in nombre_busqueda)): racha.append("W")
                    else: racha.append("L")
            return "-".join(racha) if racha else None

        r_l, r_v = extraer_racha(local), extraer_racha(visitante)
        return f"📊 RACHAS (5 últ.):\n- {local}: {r_l}\n- {visitante}: {r_v}" if r_l and r_v else "Sin rachas recientes."
    except: return "Error en rachas."

def obtener_cuotas_reales(local, visitante):
    if not ODDS_API_KEY: return None
    # Probamos en La Liga y Segunda
    ligas = ["soccer_spain_la_liga", "soccer_spain_segunda_division"]
    try:
        for liga in ligas:
            url = f"https://api.the-odds-api.com/v1/sports/{liga}/odds/"
            params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200: continue
            
            for match in r.json():
                h, a = match['home_team'].lower(), match['away_team'].lower()
                l_q, v_q = local.lower(), visitante.lower()
                # Búsqueda flexible mejorada
                if (l_q in h or h in l_q) and (v_q in a or a in v_q):
                    bookie = match['bookmakers'][0]
                    cuotas = bookie['markets'][0]['outcomes']
                    res_cuotas = {}
                    for o in cuotas:
                        if o['name'] == match['home_team']: res_cuotas['L'] = o['price']
                        elif o['name'] == match['away_team']: res_cuotas['V'] = o['price']
                        else: res_cuotas['E'] = o['price']
                    return {"bookie": bookie['title'], "precios": res_cuotas}
        return None
    except: return None

# --- HANDLERS ---
@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos...")
    modelos = await obtener_modelos_reales(GEMINI_KEY)
    await bot.delete_message(message.chat.id, wait.message_id)
    if not modelos:
        await bot.reply_to(message, "❌ Sin nodos."); return
    markup = InlineKeyboardMarkup()
    for m in modelos: markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
    await bot.send_message(message.chat.id, "🎯 **SELECCIONE MOTOR IA:**", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set_model(call):
    config_ia["modelo_actual"] = call.data.split('_')[1]
    await bot.edit_message_text(f"✅ **NODO:** `{config_ia['modelo_actual']}`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not config_ia["modelo_actual"]:
        await bot.reply_to(message, "⚠️ Usa `/test` primero."); return
    raw = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if " vs " not in raw:
        await bot.reply_to(message, "⚠️ Formato: `Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in raw.split(" vs ")]
    
    # 1. Poisson
    full_data = obtener_datos_poisson()
    if not full_data: 
        await bot.reply_to(message, "❌ Error: No hay datos de Poisson en GitHub."); return
    
    data_liga = full_data.get('LaLiga')
    m_l = next((t for t in data_liga['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
    m_v = next((t for t in data_liga['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, "❌ Equipo no encontrado en el modelo Poisson."); return

    # Cálculo Probabilidades
    l_s, v_s = data_liga['teams'][m_l], data_liga['teams'][m_v]
    avg = data_liga['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    ph, pd, pa = 0, 0, 0
    for x in range(9):
        for y in range(9):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    sent = await bot.reply_to(message, f"📈 Analizando con `{config_ia['modelo_actual']}`...")
    
    # 2. Contexto y Cuotas
    contexto = obtener_contexto_gratuito(m_l, m_v)
    cuotas_data = obtener_cuotas_reales(m_l, m_v)
    texto_cuotas = f"L: {cuotas_data['precios'].get('L')} | E: {cuotas_data['precios'].get('E')} | V: {cuotas_data['precios'].get('V')}" if cuotas_data else "No disponibles"
    
    header_checks = f"🛠 **REPORTE:** {'✅' if cuotas_data else '❌'} Cuotas | ✅ Poisson | ✅ Rachas\n"

    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        prompt = f"""
Actúa como experto en Value Betting y Analista de Datos.
PARTIDO: {m_l} vs {m_v}
ESTADÍSTICA POISSON: WinL {ph*100:.1f}%, Empate {pd*100:.1f}%, WinV {pa*100:.1f}%
RACHAS RECIENTES: {contexto}
CUOTAS MERCADO: {texto_cuotas}

Tu tarea:
1. Analiza el VALOR: ¿La cuota es mayor que lo que dice Poisson?
2. Detecta CONTRADICCIONES: ¿Poisson dice que gana uno pero las rachas dicen lo contrario?
3. Da un veredicto final.

FORMATO:
{header_checks}
🔥 **ANÁLISIS DE VALOR:** [Breve]
⚠️ **PUNTOS CIEGOS/CONTRADICCIONES:** [Si Poisson y Rachas no coinciden, avisa aquí]
🎯 **PICK:** [Mercado]
💰 **CUOTA:** [Precio]
⚠️ **CONFIANZA:** [Nivel]

PICK_RESUMEN: [4 palabras]
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        respuesta_ia = response.text
        if "REPORTE" not in respuesta_ia: respuesta_ia = header_checks + respuesta_ia
        
        try: await bot.edit_message_text(respuesta_ia, message.chat.id, sent.message_id, parse_mode='Markdown')
        except: await bot.edit_message_text(respuesta_ia, message.chat.id, sent.message_id, parse_mode=None)

    except Exception as e:
        await bot.edit_message_text(f"❌ Error: {str(e)[:50]}", message.chat.id, sent.message_id)

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        equipos = sorted(data['LaLiga']['teams'].keys())
        await bot.reply_to(message, f"📋 **Equipos en el modelo:**\n`{', '.join(equipos)}`", parse_mode='Markdown')

async def main():
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
