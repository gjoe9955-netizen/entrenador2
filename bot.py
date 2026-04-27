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

# --- Configuración Inicial ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
NVIDIA_KEY = os.getenv('NVIDIA_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

# Ajuste para Ciudad Juárez (UTC - 6)
OFFSET_JUAREZ = -6

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado del Sistema ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_gemini": ['gemini-2.5-flash-lite', 'gemini-3.1-flash-lite-preview'],
    "nodos_nvidia": ['meta/llama-3.1-70b-instruct', 'meta/llama-3.1-8b-instruct']
}

# --- Motores de Comunicación ---
async def ejecutar_ia(api, nodo, prompt):
    if api == 'GEMINI':
        client = genai.Client(api_key=GEMINI_KEY)
        try:
            res = await asyncio.to_thread(
                client.models.generate_content, 
                model=nodo, 
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=500, temperature=0.1)
            )
            return res.text
        except Exception as e: return f"❌ Error Gemini: {str(e)[:50]}"
    else:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": nodo,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1, "max_tokens": 500
        }
        try:
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
            return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"❌ Error NVIDIA"
        except: return "❌ Error Técnico NVIDIA"

# --- Lógica de Datos & H2H ---
def obtener_datos_poisson():
    try:
        response = requests.get(URL_JSON, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

async def api_football_call(endpoint):
    if not FOOTBALL_DATA_KEY: return None
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = await asyncio.to_thread(requests.get, f"https://api.football-data.org/v4/competitions/PD/{endpoint}", headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

async def obtener_h2h_historico(id_l, id_v):
    if not FOOTBALL_DATA_KEY or not id_l or not id_v: return "Sin historial disponible."
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        url = f"https://api.football-data.org/v4/teams/{id_l}/matches?competitors={id_v}&status=FINISHED"
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
        if r.status_code == 200:
            matches = r.json().get('matches', [])
            if not matches: return "No hay enfrentamientos previos registrados recientemente."
            l_win, v_win, emp = 0, 0, 0
            for m in matches[:5]:
                win = m['score']['winner']
                if win == 'HOME_TEAM': l_win += 1
                elif win == 'AWAY_TEAM': v_win += 1
                else: emp += 1
            return f"H2H (5 Partidos): Local {l_win} | Visitante {v_win} | Empates {emp}."
        return "Historial no recuperable."
    except: return "Error consultando H2H."

# --- Comandos de Información (RESTAURADOS) ---

@bot.message_handler(commands=['partidos'])
async def cmd_partidos(message):
    data = await api_football_call("matches?status=SCHEDULED")
    if not data or 'matches' not in data:
        await bot.reply_to(message, "❌ No hay partidos programados."); return
    
    txt = "📅 **PRÓXIMOS PARTIDOS (CD. JUÁREZ)**\n\n"
    for m in data['matches'][:10]:
        dt_utc = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ")
        dt_local = dt_utc + timedelta(hours=OFFSET_JUAREZ)
        
        txt += f"🕒 `{dt_local.strftime('%H:%M')}` | `{dt_local.strftime('%d/%m')}`\n"
        txt += f"🏠 **{m['homeTeam']['shortName']}** vs 🚩 **{m['awayTeam']['shortName']}**\n"
        txt += f"{'—'*15}\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    data = await api_football_call("standings")
    if not data: await bot.reply_to(message, "❌ Error de conexión."); return
    table = data['standings'][0]['table']
    txt = "🏆 **CLASIFICACIÓN LA LIGA:**\n\n"
    for t in table[:12]:
        txt += f"`{t['position']:02d}.` **{t['team']['shortName']}** | {t['points']} pts\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['goleadores'])
async def cmd_goleadores(message):
    data = await api_football_call("scorers")
    if not data or 'scorers' not in data:
        await bot.reply_to(message, "❌ Error al obtener goleadores."); return
    txt = "⚽ **PICHICHI ACTUAL:**\n\n"
    for s in data['scorers'][:8]:
        txt += f"• {s['player']['name']} ({s['team']['shortName']}): **{s['goals']}**\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        liga = next(iter(data))
        equipos = ", ".join([f"`{e}`" for e in data[liga]['teams'].keys()])
        await bot.reply_to(message, f"📋 **EQUIPOS EN MODELO POISSON:**\n\n{equipos}", parse_mode='Markdown')

# --- Análisis con Poisson + H2H ---

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "⚠️ Configura la IA con `/config`."); return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    full_data = obtener_datos_poisson()
    if not full_data: return

    standings = await api_football_call("standings")
    id_l, id_v = None, None
    if standings:
        for t in standings['standings'][0]['table']:
            if t['team']['shortName'].lower() in l_q.lower(): id_l = t['team']['id']
            if t['team']['shortName'].lower() in v_q.lower(): id_v = t['team']['id']

    h2h_txt = await obtener_h2h_historico(id_l, id_v)
    
    liga_key = next(iter(full_data))
    m_l = next((t for t in full_data[liga_key]['teams'] if t.lower() in l_q.lower()), None)
    m_v = next((t for t in full_data[liga_key]['teams'] if t.lower() in v_q.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, "❌ Equipo no encontrado en el JSON de Poisson."); return

    l_s, v_s = full_data[liga_key]['teams'][m_l], full_data[liga_key]['teams'][m_v]
    avg = full_data[liga_key]['averages']
    lh, la = l_s['att_h'] * v_s['def_a'] * avg['league_home'], v_s['att_a'] * l_s['def_h'] * avg['league_away']
    ph, pd, pa = 0, 0, 0
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    edge = (ph * 100) - (100 / 1.85)
    msg_espera = await bot.reply_to(message, "🧬 Procesando Poisson + H2H Histórico...")

    prompt_e = (f"Analista Senior. Partido: {m_l} vs {m_v}.\n"
                f"POISSON: L {ph*100:.1f}%, E {pd*100:.1f}%, V {pa*100:.1f}%\n"
                f"HISTORIAL H2H: {h2h_txt}\n\n"
                f"FORMATO:\n💎 **NIVEL:** [Nivel]\n🔥 **VALOR:** [Análisis técnico]\n🎯 **PICK:** [Pick] | 📊 **EDGE:** {edge:.1f}%")
    
    res_e = await ejecutar_ia(SISTEMA_IA["estratega"]["api"], SISTEMA_IA["estratega"]["nodo"], prompt_e)

    if SISTEMA_IA["auditor"]["nodo"]:
        prompt_a = (f"Auditor de Riesgos. Valida: '{res_e}' usando el H2H '{h2h_txt}'.\n"
                    f"FORMATO: ⚠️ **RIESGOS:** [Puntos ciegos] | ✅ **VEREDICTO:** [Veredicto]")
        res_a = await ejecutar_ia(SISTEMA_IA["auditor"]["api"], SISTEMA_IA["auditor"]["nodo"], prompt_a)
        final = f"🛠 **REPORTE ESTRATÉGICO**\n{'—'*20}\n{res_e}\n\n{res_a}"
    else:
        final = f"🛠 **REPORTE ESTRATÉGICO**\n{'—'*20}\n{res_e}"

    await bot.edit_message_text(final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Configuración & Ayuda ---

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
        if rol == "estratega":
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_auditor"))
            await bot.edit_message_text(f"✅ Estratega: `{nodo.split('/')[-1]}`", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            await bot.edit_message_text(f"🚀 **SISTEMA DUAL ACTIVO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['config', 'test'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN DE IA**", reply_markup=markup)

@bot.message_handler(commands=['help', 'start'])
async def cmd_help(message):
    help_text = (
        "🤖 **ESTRATEGA POISSON V2.8 (Juárez Time)**\n\n"
        "📈 **ANÁLISIS PRO:**\n"
        "• `/pronostico A vs B` - Reporte con Poisson + H2H.\n"
        "• `/config` - Configurar Estratega y Auditor.\n\n"
        "⚽ **DATOS DE LIGA:**\n"
        "• `/partidos` - Próximos 10 encuentros (Hora local).\n"
        "• `/tabla` - Clasificación actualizada.\n"
        "• `/goleadores` - Tabla de anotadores.\n"
        "• `/equipos` - Listado para nombres exactos.\n\n"
        "💡 *Usa `/equipos` para copiar los nombres exactos y evitar errores en el pronóstico.*"
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

async def main():
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
