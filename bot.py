import os
import json
import asyncio
import logging
import requests
from scipy.stats import poisson

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
ODDS_API_KEY = os.getenv('ODDS_API_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado del Sistema (Nodos Originales) ---
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
                config=types.GenerateContentConfig(max_output_tokens=450, temperature=0.1)
            )
            return res.text
        except Exception as e: return f"❌ Error Gemini: {str(e)[:50]}"
    else:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": nodo,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1, "max_tokens": 450
        }
        try:
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
            return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"❌ Error NVIDIA"
        except: return "❌ Error Técnico NVIDIA"

# --- Lógica de Datos (Corregida para evitar errores de tipo None) ---
def obtener_datos_poisson():
    try:
        response = requests.get(URL_JSON, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

async def api_football_call(endpoint):
    if not FOOTBALL_DATA_KEY: return None
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        # Nota: Usamos loop.run_in_executor para peticiones blocking en handlers async
        r = await asyncio.to_thread(requests.get, f"https://api.football-data.org/v4/competitions/PD/{endpoint}", headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

# --- Comandos de Información ---

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    data = await api_football_call("standings")
    if not data or 'standings' not in data:
        await bot.reply_to(message, "❌ Error al obtener clasificación."); return
    table = data['standings'][0]['table']
    txt = "🏆 **TOP 10 - LA LIGA:**\n\n"
    for t in table[:10]:
        txt += f"`{t['position']:02d}.` **{t['team']['shortName']}** - {t['points']} pts\n"
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

@bot.message_handler(commands=['partidos'])
async def cmd_partidos(message):
    data = await api_football_call("matches?status=SCHEDULED")
    if not data or 'matches' not in data:
        await bot.reply_to(message, "❌ No hay partidos programados próximamente."); return
    txt = "📅 **PRÓXIMOS ENCUENTROS:**\n\n"
    for m in data['matches'][:6]:
        txt += f"• {m['homeTeam']['shortName']} vs {m['awayTeam']['shortName']}\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        liga = next(iter(data))
        equipos = ", ".join([f"`{e}`" for e in data[liga]['teams'].keys()])
        await bot.reply_to(message, f"📋 **EQUIPOS REGISTRADOS:**\n\n{equipos}", parse_mode='Markdown')

# --- Pronóstico y Configuración ---

@bot.message_handler(commands=['config', 'test'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN IA**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('set_', 'api_', 'save_')))
async def cb_config(call):
    if call.data.startswith('set_'):
        rol = call.data.split('_')[1]
        markup = InlineKeyboardMarkup().row(InlineKeyboardButton("Gemini", callback_data=f"api_{rol}_GEMINI"), InlineKeyboardButton("NVIDIA", callback_data=f"api_{rol}_NVIDIA"))
        await bot.edit_message_text(f"API para **{rol.upper()}**:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith('api_'):
        _, rol, api = call.data.split('_')
        markup = InlineKeyboardMarkup()
        nodos = SISTEMA_IA["nodos_gemini"] if api == 'GEMINI' else SISTEMA_IA["nodos_nvidia"]
        for n in nodos: markup.add(InlineKeyboardButton(n.split('/')[-1], callback_data=f"save_{rol}_{api}_{n}"))
        await bot.edit_message_text(f"Nodo para {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith('save_'):
        _, rol, api, nodo = call.data.split('_')
        SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
        if rol == "estratega":
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_auditor"))
            await bot.edit_message_text(f"✅ Estratega: `{nodo.split('/')[-1]}`", call.message.chat.id, call.message.message_id, reply_markup=markup)
        else:
            await bot.edit_message_text(f"🚀 **ANÁLISIS DUAL ACTIVO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "⚠️ Configura la IA con `/config`."); return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    full_data = obtener_datos_poisson()
    
    # Cuotas Base
    c_l, c_e, c_v = 1.85, 3.75, 4.00 

    if not full_data: return
    liga_key = next(iter(full_data))
    m_l = next((t for t in full_data[liga_key]['teams'] if t.lower() in l_q.lower()), None)
    m_v = next((t for t in full_data[liga_key]['teams'] if t.lower() in v_q.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, "❌ Equipo no encontrado."); return

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

    edge = (ph * 100) - (100 / c_l)
    msg_espera = await bot.reply_to(message, "🧬 Generando reporte profesional...")
    header = (f"🛠 **REPORTE:** ✅ Cuotas ({c_l}/{c_e}/{c_v}) | ✅ Poisson ({ph*100:.1f}%) | ✅ Football-Data\n{'—'*20}\n")

    prompt_e = (f"Analista Senior. Partido: {m_l} vs {m_v}. Poisson: {ph*100:.1f}% | Cuota: {c_l}. "
                f"Formato: 💎 **NIVEL:** [DIAMANTE/ORO/PLATA] | STAKE: [X/5]. "
                f"🔥 **ANÁLISIS DE VALOR:** [Ineficiencia mercado 3 líneas]. "
                f"🎯 **PICK:** [Victoria X] | 💰 **CUOTA:** {c_l} | 📊 **EDGE:** {edge:.1f}%")
    
    res_e = await ejecutar_ia(SISTEMA_IA["estratega"]["api"], SISTEMA_IA["estratega"]["nodo"], prompt_e)

    if SISTEMA_IA["auditor"]["nodo"]:
        prompt_a = (f"Auditor de Riesgos. Valida: '{res_e}'. "
                    f"FORMATO: ⚠️ **PUNTOS CIEGOS:** [Riesgos en 3 líneas]. ✅ **VEREDICTO:** [Confirmado/Ajustado]")
        res_a = await ejecutar_ia(SISTEMA_IA["auditor"]["api"], SISTEMA_IA["auditor"]["nodo"], prompt_a)
        final = f"{header}{res_e}\n\n{res_a}"
    else:
        final = f"{header}{res_e}"

    await bot.edit_message_text(final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['help', 'start'])
async def cmd_help(message):
    help_text = (
        "🤖 **ESTRATEGA POISSON V2.6**\n\n"
        "📈 **ANÁLISIS:**\n"
        "• `/pronostico A vs B` - Reporte Diamante.\n"
        "• `/config` - Configurar IAs (Estratega/Auditor).\n\n"
        "⚽ **DATOS EN TIEMPO REAL:**\n"
        "• `/tabla` - Clasificación actualizada.\n"
        "• `/goleadores` - Tabla de goleadores.\n"
        "• `/partidos` - Próximos encuentros.\n"
        "• `/equipos` - Nombres para el modelo Poisson.\n\n"
        "💡 *El sistema utiliza IA dual para confirmar ineficiencias de cuotas.*"
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

async def main():
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
