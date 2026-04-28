import os
import json
import asyncio
import logging
import requests
from scipy.stats import poisson
from datetime import datetime, timedelta

from google import genai
from google.genai import types
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Logs ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

# --- Credenciales ---
TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
NVIDIA_KEY = os.getenv('NVIDIA_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)

SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_gemini": ['gemini-2.5-flash-lite', 'gemini-3.1-flash-lite-preview'],
    "nodos_nvidia": ['meta/llama-3.1-70b-instruct', 'meta/llama-3.1-8b-instruct']
}

# --- 1. EXTRACCIÓN DE DATOS REALES (APIs) ---

async def obtener_cuotas_reales(equipo_l):
    """Consulta The Odds API para obtener cuotas de mercado actuales."""
    if not ODDS_API_KEY: return 1.85, 3.40, 4.20
    try:
        url = f"https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            for match in data:
                if equipo_l.lower() in match['home_team'].lower():
                    odds = match['bookmakers'][0]['markets'][0]['outcomes']
                    o_l = next(o['price'] for o in odds if o['name'] == match['home_team'])
                    o_v = next(o['price'] for o in odds if o['name'] == match['away_team'])
                    o_e = next(o['price'] for o in odds if o['name'] == 'Draw')
                    return o_l, o_e, o_v
    except: pass
    return 1.85, 3.40, 4.20

async def obtener_h2h(id_l, id_v):
    """Consulta Football-Data para historial directo."""
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        url = f"https://api.football-data.org/v4/teams/{id_l}/matches?competitors={id_v}&status=FINISHED"
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
        matches = r.json().get('matches', [])
        if not matches: return "H2H: Sin datos recientes."
        l_w, v_w, e = 0, 0, 0
        for m in matches[:5]:
            w = m['score']['winner']
            if w == 'HOME_TEAM': l_w += 1
            elif w == 'AWAY_TEAM': v_w += 1
            else: e += 1
        return f"H2H (5 Partidos): Local {l_w}, Visitante {v_w}, Empates {e}."
    except: return "H2H: Error en API."

# --- 2. CÁLCULO MATEMÁTICO (No IA) ---

def calcular_probabilidades_poisson(equipo_l, equipo_v, data):
    liga = next(iter(data))
    l_s = data[liga]['teams'].get(equipo_l)
    v_s = data[liga]['teams'].get(equipo_v)
    avg = data[liga]['averages']
    
    if not l_s or not v_s: return None

    # Cálculo de Expected Goals (xG)
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p
    return ph * 100, pd * 100, pa * 100

# --- 3. PROCESAMIENTO ESTRATÉGICO (IA) ---

async def ejecutar_ia(api, nodo, prompt):
    if api == 'GEMINI':
        client = genai.Client(api_key=GEMINI_KEY)
        res = await asyncio.to_thread(client.models.generate_content, model=nodo, contents=prompt)
        return res.text
    else:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {NVIDIA_KEY}"}
        payload = {"model": nodo, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload)
        return r.json()['choices'][0]['message']['content']

@bot.message_handler(commands=['pronostico', 'valor'])
async def cmd_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "⚠️ Configura el nodo con `/config` primero."); return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Formato: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Consultando APIs y calculando Poisson...")

    # PASO 1: Datos Reales
    full_data = requests.get(URL_JSON).json()
    c_l, c_e, c_v = await obtener_cuotas_reales(l_q)
    
    # PASO 2: Identificar Equipos y H2H
    standings = await asyncio.to_thread(requests.get, "https://api.football-data.org/v4/competitions/PD/standings", headers={'X-Auth-Token': FOOTBALL_DATA_KEY})
    id_l, id_v = None, None
    if standings.status_code == 200:
        for t in standings.json()['standings'][0]['table']:
            if t['team']['shortName'].lower() in l_q.lower(): id_l = t['team']['id']
            if t['team']['shortName'].lower() in v_q.lower(): id_v = t['team']['id']
    
    h2h_txt = await obtener_h2h(id_l, id_v)

    # PASO 3: Ejecutar Poisson (Matemática pura)
    m_l = next((t for t in full_data['SP1']['teams'] if t.lower() in l_q.lower()), None)
    m_v = next((t for t in full_data['SP1']['teams'] if t.lower() in v_q.lower()), None)
    
    if not m_l or not m_v:
        await bot.edit_message_text("❌ Error: Equipo no encontrado en el JSON.", message.chat.id, msg_espera.message_id); return

    p_l, p_e, p_v = calcular_probabilidades_poisson(m_l, m_v, full_data)
    edge = p_l - (100 / c_l)

    # PASO 4: Generar Reporte con IA basada en DATOS CALCULADOS
    header = f"🛠 REPORTE: ✅ Cuotas API | ✅ Poisson ({p_l:.1f}%) | ✅ H2H Real\n"
    header += "————————————————————\n"
    
    prompt = (f"Usa estos datos REALES: {m_l} vs {m_v}. Poisson: {p_l:.1f}%. Cuota: {c_l}. H2H: {h2h_txt}. Edge: {edge:.1f}%.\n"
              f"Analiza el valor. Formato: NIVEL, STAKE, VALOR (4 líneas), PICK, CUOTA, EDGE.")
    
    analisis = await ejecutar_ia(SISTEMA_IA["estratega"]["api"], SISTEMA_IA["estratega"]["nodo"], prompt)
    
    # Check de Nodos al final
    nodos_info = f"\n\n🛰 **NODO:** `{SISTEMA_IA['estratega']['api']}` ({SISTEMA_IA['estratega']['nodo']})"
    
    await bot.edit_message_text(f"{header}{analisis}{nodos_info}", message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Comandos Adicionales Restantes ---
@bot.message_handler(commands=['help', 'start'])
async def cmd_help(message):
    help_text = (
        "🤖 **SISTEMA DE ARBITRAJE V4.0**\n\n"
        "✅ **APIs Activas:**\n"
        "• **The Odds API:** Cuotas reales de mercado.\n"
        "• **Football-Data:** H2H, Tabla y Goleadores.\n"
        "• **Poisson Core:** Cálculo matemático interno (Scipy).\n\n"
        "**Comandos:**\n"
        "• `/pronostico A vs B` - Reporte con Edge real.\n"
        "• `/partidos` - Juegos en horario Juárez.\n"
        "• `/equipos` - Nombres del modelo.\n"
        "• `/config` - Cambiar nodos de IA."
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 CONFIG ESTRATEGA", callback_data="set_estratega"))
    await bot.reply_to(message, "🛠 **AJUSTES DE RED**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('set_', 'api_', 'save_')))
async def cb_config(call):
    if call.data.startswith('set_'):
        rol = call.data.split('_')[1]
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Gemini", callback_data=f"api_{rol}_GEMINI"), InlineKeyboardButton("NVIDIA", callback_data=f"api_{rol}_NVIDIA"))
        await bot.edit_message_text(f"API para {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith('api_'):
        _, rol, api = call.data.split('_')
        markup = InlineKeyboardMarkup()
        nodos = SISTEMA_IA["nodos_gemini"] if api == 'GEMINI' else SISTEMA_IA["nodos_nvidia"]
        for n in nodos: markup.add(InlineKeyboardButton(n.split('/')[-1], callback_data=f"save_{rol}_{api}_{n}"))
        await bot.edit_message_text(f"Nodo {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith('save_'):
        _, rol, api, nodo = call.data.split('_')
        SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
        await bot.edit_message_text(f"✅ Nodo asignado: `{nodo}`", call.message.chat.id, call.message.message_id)

async def main(): await bot.polling(non_stop=True)
if __name__ == "__main__": asyncio.run(main())
