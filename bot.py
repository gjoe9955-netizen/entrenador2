import os
import json
import asyncio
import logging
import requests
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
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado del Sistema ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_gemini": ['gemini-2.0-flash-exp', 'gemini-1.5-flash'],
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
            return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"❌ Error NVIDIA: {r.status_code}"
        except Exception as e: return f"❌ Error Técnico NVIDIA: {str(e)[:50]}"

# --- Lógica de Datos ---

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
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA (IA 1)", callback_data="set_estratega"))
    await bot.reply_to(message, "🛠 **MODO PROFESIONAL**\nConfigura la jerarquía de análisis:", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith(('set_', 'api_', 'save_')))
async def cb_config_handler(call):
    if call.data.startswith('set_'):
        rol = call.data.split('_')[1]
        markup = InlineKeyboardMarkup().row(
            InlineKeyboardButton("Google Gemini", callback_data=f"api_{rol}_GEMINI"),
            InlineKeyboardButton("NVIDIA NIM", callback_data=f"api_{rol}_NVIDIA")
        )
        await bot.edit_message_text(f"Selecciona API para el **{rol.upper()}**:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    
    elif call.data.startswith('api_'):
        _, rol, api = call.data.split('_')
        markup = InlineKeyboardMarkup()
        nodos = SISTEMA_IA["nodos_gemini"] if api == 'GEMINI' else SISTEMA_IA["nodos_nvidia"]
        for n in nodos:
            markup.add(InlineKeyboardButton(n.split('/')[-1], callback_data=f"save_{rol}_{api}_{n}"))
        await bot.edit_message_text(f"Elige el nodo para el {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    
    elif call.data.startswith('save_'):
        _, rol, api, nodo = call.data.split('_')
        SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
        if rol == "estratega":
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("➕ AÑADIR AUDITOR (IA 2)", callback_data="set_auditor"))
            await bot.edit_message_text(f"✅ **IA 1 (Estratega) Lista.**\n¿Deseas una segunda opinión para coherencia?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        else:
            resumen = (f"🚀 **SISTEMA DUAL CONFIGURADO**\n\n🧠 **Estratega:** `{SISTEMA_IA['estratega']['nodo'].split('/')[-1]}`\n⚖️ **Auditor:** `{SISTEMA_IA['auditor']['nodo'].split('/')[-1]}`")
            await bot.edit_message_text(resumen, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

# --- Procesamiento de Pronóstico con Consenso ---

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "⚠️ Configura la IA con `/config` primero."); return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ Usa: `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    full_data = obtener_datos_poisson()
    motivacion = await obtener_dict_motivacion()
    
    # Cuotas (Simuladas o vía API)
    c_l, c_e, c_v = 1.75, 4.30, 4.60 

    if not full_data: return
    liga_key = next(iter(full_data))
    m_l = next((t for t in full_data[liga_key]['teams'] if t.lower() in l_q.lower()), None)
    m_v = next((t for t in full_data[liga_key]['teams'] if t.lower() in v_q.lower()), None)
    
    if not m_l or not m_v:
        await bot.reply_to(message, "❌ Equipo no encontrado. Revisa `/equipos`."); return

    # Poisson local
    l_s, v_s = full_data[liga_key]['teams'][m_l], full_data[liga_key]['teams'][m_v]
    avg = full_data[liga_key]['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    ph, pd, pa = 0, 0, 0
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    prob_p = ph * 100
    edge = prob_p - (100 / c_l)

    msg_espera = await bot.reply_to(message, "🧬 Generando reporte profesional...")

    header = (f"🛠 **REPORTE:** ✅ Cuotas ({c_l}/{c_e}/{c_v}) | ✅ Poisson ({prob_p:.1f}%) | ✅ Tabla (Check)\n{'—'*20}\n")

    # PROMPT ESTRATEGA (Jerarquía y Valor)
    prompt_e = (
        f"Eres un analista senior. Partido: {m_l} vs {m_v}.\n"
        f"POISSON: {prob_p:.1f}% | CUOTA: {c_l} | EDGE: {edge:.1f}%\n"
        f"CONSTRÚYELO ASÍ:\n"
        f"💎 **NIVEL:** [DIAMANTE/ORO/PLATA] | STAKE: [X/5]\n"
        f"🔥 **ANÁLISIS DE VALOR:** [Explica la ineficiencia de mercado en 3 líneas]\n"
        f"🎯 **PICK:** [Victoria X] | 💰 **CUOTA:** {c_l} | 📊 **EDGE:** {edge:.1f}%"
    )
    res_e = await ejecutar_ia(SISTEMA_IA["estratega"]["api"], SISTEMA_IA["estratega"]["nodo"], prompt_e)

    # PROMPT AUDITOR (Congruencia y Puntos Ciegos)
    if SISTEMA_IA["auditor"]["nodo"]:
        await bot.edit_message_text(f"{header}⚖️ IA Auditora validando reporte...", message.chat.id, msg_espera.message_id)
        prompt_a = (
            f"Analiza el reporte de tu colega: '{res_e}'.\n"
            f"Busca PUNTOS CIEGOS (lesiones, rachas o trampas de mercado).\n"
            "RESPONDE SIGUIENDO ESTE FORMATO:\n"
            "⚠️ **PUNTOS CIEGOS:** [Máximo 3 líneas]\n"
            "✅ **VEREDICTO:** [Confirmado / Ajustar nivel]"
        )
        res_a = await ejecutar_ia(SISTEMA_IA["auditor"]["api"], SISTEMA_IA["auditor"]["nodo"], prompt_a)
        reporte_final = f"{header}{res_e}\n\n{res_a}"
    else:
        reporte_final = f"{header}{res_e}"

    await bot.edit_message_text(reporte_final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Gestión de Ayuda y Equipos ---

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    data = obtener_datos_poisson()
    if data:
        liga = next(iter(data))
        equipos = ", ".join([f"`{e}`" for e in data[liga]['teams'].keys()])
        await bot.reply_to(message, f"📋 **EQUIPOS EN SISTEMA:**\n\n{equipos}", parse_mode='Markdown')

@bot.message_handler(commands=['help', 'start'])
async def cmd_help(message):
    help_text = (
        "🤖 **BOT MULTI-API POISSON V2.5**\n\n"
        "🛠 **COMANDOS OPERATIVOS:**\n"
        "• `/config` - Configura el equipo de IAs (Estratega y Auditor).\n"
        "• `/pronostico Local vs Visitante` - Genera el reporte de valor DIAMANTE/ORO.\n"
        "• `/equipos` - Muestra la lista de nombres aceptados por el modelo.\n"
        "• `/test` - Alias rápido para re-configurar nodos.\n\n"
        "📊 **FLUJO DE TRABAJO:**\n"
        "1. El sistema verifica Poisson, Cuotas y Posición en Tabla.\n"
        "2. El **Estratega** busca ineficiencias de mercado.\n"
        "3. El **Auditor** busca puntos ciegos para asegurar la congruencia.\n\n"
        "💡 *Usa siempre el formato 'A vs B' para que el bot identifique los equipos.*"
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

async def main():
    logger.info("🚀 Sistema Híbrido Profesional Iniciado.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
