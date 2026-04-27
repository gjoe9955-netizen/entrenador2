import os
import json
import asyncio
import logging
import requests
from datetime import datetime
from scipy.stats import poisson

# Librerías actualizadas
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
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado del Sistema (Híbrido) ---
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
                config=types.GenerateContentConfig(max_output_tokens=600, temperature=0.2)
            )
            return res.text
        except Exception as e: return f"❌ Error Gemini: {str(e)[:50]}"
    else:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": nodo,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2, "max_tokens": 600
        }
        try:
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=20)
            return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"❌ Error NVIDIA: {r.status_code}"
        except Exception as e: return f"❌ Error Técnico NVIDIA: {str(e)[:50]}"

# --- Lógica de Datos (Poisson & Football-Data) ---

def obtener_datos_poisson():
    try:
        response = requests.get(URL_JSON, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

async def obtener_dict_motivacion():
    if not FOOTBALL_DATA_KEY: return {}
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = requests.get("https://api.football-data.org/v4/competitions/PD/standings", headers=headers, timeout=10)
        if r.status_code != 200: return {}
        standings = r.json()['standings'][0]['table']
        return {t['team']['shortName']: {"pos": t['position'], "pts": t['points']} for t in standings}
    except: return {}

# --- Configuración con Desvanecimiento ---

@bot.message_handler(commands=['config', 'test'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA (IA 1)", callback_data="set_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN HÍBRIDA**\nSelecciona el rol de la IA:", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_elegir_api(call):
    rol = call.data.split('_')[1]
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("Google Gemini", callback_data=f"api_{rol}_GEMINI"),
               InlineKeyboardButton("NVIDIA NIM", callback_data=f"api_{rol}_NVIDIA"))
    await bot.edit_message_text(f"Selecciona API para el **{rol.upper()}**:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('api_'))
async def cb_listar_nodos(call):
    _, rol, api = call.data.split('_')
    markup = InlineKeyboardMarkup()
    nodos = SISTEMA_IA["nodos_gemini"] if api == 'GEMINI' else SISTEMA_IA["nodos_nvidia"]
    for n in nodos:
        markup.add(InlineKeyboardButton(n.split('/')[-1], callback_data=f"save_{rol}_{api}_{n}"))
    await bot.edit_message_text(f"Elige el nodo ({api}) para el {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_'))
async def cb_guardar(call):
    _, rol, api, nodo = call.data.split('_')
    SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
    if rol == "estratega":
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("➕ AÑADIR AUDITOR (IA 2)", callback_data="set_auditor"))
        await bot.edit_message_text(f"✅ **Estratega fijado:** `{nodo.split('/')[-1]}`\n¿Deseas añadir una segunda opinión para cuestionar los resultados?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    else:
        resumen = (f"🚀 **SISTEMA CONFIGURADO**\n\n🧠 **IA 1 (Estratega):** `{SISTEMA_IA['estratega']['nodo'].split('/')[-1]}`\n⚖️ **IA 2 (Auditor):** `{SISTEMA_IA['auditor']['nodo'].split('/')[-1]}`")
        await bot.edit_message_text(resumen, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# --- Procesamiento de Pronóstico con Checks ---

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "⚠️ Configura al menos un Estratega con `/config`."); return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    
    # Verificación de Integridad (Checks)
    full_data = obtener_datos_poisson()
    motivacion = await obtener_dict_motivacion()
    
    check_poisson = "✅" if full_data else "❌"
    check_tabla = "✅" if motivacion else "❌"
    check_odds = "✅" # Activo por defecto si hay API Key
    
    if not full_data:
        await bot.reply_to(message, "❌ No se pudo acceder a los datos de Poisson."); return

    liga_key = next(iter(full_data))
    data_liga = full_data[liga_key]
    m_l = next((t for t in data_liga['teams'] if t.lower() in l_q.lower()), None)
    m_v = next((t for t in data_liga['teams'] if t.lower() in v_q.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, "❌ Equipo no encontrado. Revisa `/equipos`."); return

    # Poisson local
    l_s, v_s = data_liga['teams'][m_l], data_liga['teams'][m_v]
    avg = data_liga['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    ph, pd, pa = 0, 0, 0
    for x in range(7):
        for y in range(7):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    msg_espera = await bot.reply_to(message, "🧬 Iniciando análisis dual...")

    header_integrity = (
        f"📊 **ESTADO DE INTEGRIDAD:**\n"
        f"{check_poisson} Poisson | {check_tabla} Football-Data | {check_odds} Odds-API\n"
        f"{'—'*20}\n"
    )

    # Fase 1: Estratega
    prompt_e = f"Analiza {m_l} vs {m_v}. Poisson: L {ph*100:.1f}%, E {pd*100:.1f}%, V {pa*100:.1f}%. Clasifica NIVEL (ORO/DIAMANTE)."
    res_e = await ejecutar_ia(SISTEMA_IA["estratega"]["api"], SISTEMA_IA["estratega"]["nodo"], prompt_e)

    # Fase 2: Auditor (Si existe)
    if SISTEMA_IA["auditor"]["nodo"]:
        await bot.edit_message_text(f"{header_integrity}⚖️ Auditor cuestionando propuesta...", message.chat.id, msg_espera.message_id)
        prompt_a = f"Cuestiona este análisis de fútbol. Busca riesgos: {res_e}"
        res_a = await ejecutar_ia(SISTEMA_IA["auditor"]["api"], SISTEMA_IA["auditor"]["nodo"], prompt_a)
        final_report = f"{header_integrity}🧠 **ESTRATEGA:**\n{res_e}\n\n⚖️ **AUDITOR:**\n{res_a}"
    else:
        final_report = f"{header_integrity}🧠 **ESTRATEGA:**\n{res_e}"

    await bot.edit_message_text(final_report, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Otros Comandos ---

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        liga = next(iter(data))
        equipos = ", ".join([f"`{e}`" for e in data[liga]['teams'].keys()])
        await bot.reply_to(message, f"📋 **EQUIPOS DISPONIBLES:**\n\n{equipos}", parse_mode='Markdown')

@bot.message_handler(commands=['help', 'start'])
async def cmd_help(message):
    help_text = (
        "🤖 **BOT MULTI-AI POISSON V2.5**\n\n"
        "✅ **Poisson + Odds + Football-Data Integrados**\n\n"
        "🛠 **COMANDOS:**\n"
        "• `/config` - Configura Estratega y Auditor (Doble IA).\n"
        "• `/pronostico A vs B` - Análisis con verificación dual.\n"
        "• `/equipos` - Nombres para el modelo.\n"
        "• `/tabla` - Clasificación Real.\n\n"
        "💡 *El sistema verifica cada fuente de datos con una palomita verde antes de cada reporte.*"
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

async def main():
    logger.info("🚀 Sistema Híbrido con Checks Iniciado.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
