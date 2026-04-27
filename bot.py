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
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"
URL_JSON = f"https://raw.githubusercontent.com/{REPO_PATH}/main/modelo_poisson.json"

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
config_ia = {"modelo_actual": "gemini-1.5-flash"} # Modelo por defecto

# --- EL MOTOR DE TEST ORIGINAL (RESTAURADO) ---
async def obtener_modelos_reales(api_key):
    try:
        genai.configure(api_key=api_key)
        aptos = []
        # Lista los modelos disponibles en tu cuenta de Google AI
        for m in genai.list_models():
            nombre = m.name.split('/')[-1]
            if 'generateContent' in m.supported_generation_methods:
                if any(x in nombre.lower() for x in ['flash', 'pro', '1.5', '2.0']):
                    try:
                        test_model = genai.GenerativeModel(nombre)
                        # Test rápido de respuesta
                        await asyncio.to_thread(test_model.generate_content, "hi", generation_config={"max_output_tokens": 1})
                        aptos.append(nombre)
                    except: continue
        aptos.sort(reverse=True)
        return aptos[:6]
    except: return []

# --- Lógica Matemática (Con Dixon-Coles) ---
def ajuste_dixon_coles(x, y, lh, la, rho=-0.15):
    if x == 0 and y == 0: return 1 - (lh * la * rho)
    if x == 0 and y == 1: return 1 + (lh * rho)
    if x == 1 and y == 0: return 1 + (la * rho)
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def calcular_probabilidades(local, visitante, data):
    stats = data['LaLiga']['teams']
    avg = data['LaLiga']['averages']
    # Match flexible de nombres
    m_l = next((t for t in stats if t.lower() in local.lower() or local.lower() in t.lower()), None)
    m_v = next((t for t in stats if t.lower() in visitante.lower() or visitante.lower() in t.lower()), None)
    
    if not m_l or not m_v: return None
    
    lh = stats[m_l]['att_h'] * stats[m_v]['def_a'] * avg['league_home']
    la = stats[m_v]['att_a'] * stats[m_l]['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(7):
        for y in range(7):
            p = (poisson.pmf(x, lh) * poisson.pmf(y, la)) * ajuste_dixon_coles(x, y, lh, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p
    return {"lh": lh, "la": la, "ph": ph, "pd": pd, "pa": pa, "n_l": m_l, "n_v": m_v}

# --- Handlers ---
@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos disponibles...")
    modelos = await obtener_modelos_reales(GEMINI_KEY)
    await bot.delete_message(message.chat.id, wait.message_id)
    if not modelos:
        await bot.reply_to(message, "❌ No se encontraron nodos activos."); return
    
    markup = InlineKeyboardMarkup()
    for m in modelos:
        markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
    await bot.send_message(message.chat.id, "🎯 **SELECCIONE MOTOR IA:**", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set_model(call):
    config_ia["modelo_actual"] = call.data.split('_')[1]
    await bot.edit_message_text(f"✅ **NODO SELECCIONADO:** `{config_ia['modelo_actual']}`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['predecir', 'pronostico'])
async def handle_analisis(message):
    if not config_ia["modelo_actual"]:
        await bot.reply_to(message, "⚠️ Usa `/test` para activar un nodo."); return

    raw = message.text.replace("/predecir", "").replace("/pronostico", "").strip()
    if " vs " not in raw:
        await bot.reply_to(message, "⚠️ Formato: `Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in raw.split(" vs ")]
    r = requests.get(URL_JSON); data = r.json()
    res = calcular_probabilidades(l_q, v_q, data)
    
    if not res:
        await bot.reply_to(message, "❌ Equipo no encontrado."); return

    sent = await bot.reply_to(message, f"📈 Analizando con `{config_ia['modelo_actual']}`...")

    # --- EL PROMPT ORIGINAL (RESTAURADO) ---
    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        prompt = f"""
Actúa como experto en Value Betting. Cruza estos datos:
PARTIDO: {res['n_l']} vs {res['n_v']}
POISSON (Dixon-Coles): WinL {res['ph']*100:.1f}% | WinV {res['pa']*100:.1f}% | Empate {res['pd']*100:.1f}%
LAMBDAS: Local {res['lh']:.2f} | Visita {res['la']:.2f}

FORMATO:
🔥 **ANÁLISIS DE VALOR:** [Análisis técnico basado en Lambdas]
🎯 **PICK:** [Mercado recomendado]
⚠️ **CONFIANZA:** [Nivel 1-10]
💰 **MARCADOR EXACTO:** [Resultado]

PICK_RESUMEN: [4 palabras clave]
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        await bot.edit_message_text(f"🏟 **{res['n_l']} vs {res['n_v']}**\n\n{response.text}", message.chat.id, sent.message_id, parse_mode='Markdown')
    except Exception as e:
        await bot.edit_message_text(f"❌ Error IA: {str(e)[:100]}", message.chat.id, sent.message_id)

@bot.message_handler(commands=['start', 'help'])
async def cmd_start(message):
    await bot.reply_to(message, "⚽ **POISSON PRO**\n/test - Escanear Nodos\n/predecir Local vs Visitante\n/equipos - Ver lista")

if __name__ == "__main__":
    asyncio.run(bot.polling(non_stop=True))
