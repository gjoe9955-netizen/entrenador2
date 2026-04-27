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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Variables de Entorno
TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')  # Valor de tu BOT_REPO_TOKEN
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

if not TOKEN or not GEMINI_KEY:
    logger.error("❌ Faltan variables de entorno esenciales.")
    exit(1)

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)

# --- Lógica Matemática Avanzada ---

def ajuste_dixon_coles(x, y, lh, la, rho=-0.15):
    """Ajuste para corregir la correlación de goles en marcadores bajos."""
    if x == 0 and y == 0: return 1 - (lh * la * rho)
    if x == 0 and y == 1: return 1 + (lh * rho)
    if x == 1 and y == 0: return 1 + (la * rho)
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def calcular_probabilidades(local, visitante, data):
    stats = data['LaLiga']['teams']
    avg = data['LaLiga']['averages']
    
    s_l = stats[local]
    s_v = stats[visitante]
    
    # Goles esperados (Lambdas) con Time-Decay del trainer
    lh = s_l['att_h'] * s_v['def_a'] * avg['league_home']
    la = s_v['att_a'] * s_l['def_h'] * avg['league_away']
    
    prob_h, prob_d, prob_a = 0, 0, 0
    
    # Matriz 7x7 para mayor cobertura de goles
    for x in range(7):
        for y in range(7):
            p = (poisson.pmf(x, lh) * poisson.pmf(y, la)) * ajuste_dixon_coles(x, y, lh, la)
            if x > y: prob_h += p
            elif x == y: prob_d += p
            else: prob_a += p
            
    return {
        "lh": lh, "la": la,
        "p_h": prob_h, "p_d": prob_d, "p_a": prob_a
    }

# --- Funciones de Datos ---

def obtener_datos_poisson():
    try:
        r = requests.get(URL_JSON, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"Error cargando JSON: {e}")
        return None

async def guardar_en_historial(partido, pick, analisis):
    if not GITHUB_TOKEN: return
    try:
        url_gh = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        
        r = requests.get(url_gh, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        content = json.loads(base64.b64decode(r.json()['content']).decode('utf-8')) if sha else []
        
        nuevo_pick = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "partido": partido,
            "pick_pronosticado": pick,
            "analisis_resumen": analisis[:300] + "...",
            "resultado_real": "Pendiente"
        }
        content.append(nuevo_pick)
        
        new_b64 = base64.b64encode(json.dumps(content, indent=4).encode('utf-8')).decode('utf-8')
        payload = {"message": f"Nuevo pick: {partido}", "content": new_b64, "sha": sha} if sha else {"message": "Crear historial", "content": new_b64}
        
        requests.put(url_gh, headers=headers, json=payload)
    except Exception as e:
        logger.error(f"Error historial: {e}")

# --- Handlers del Bot ---

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    await bot.reply_to(message, "⚽ **Calculadora Poisson Pro v2**\nUsa /predecir para analizar un partido o /help para ver cómo funciona.")

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    help_text = """
⚽ **GUÍA - POISSON PREDICTOR PRO**

**Comandos:**
/predecir - Inicia el análisis.
/historial - Últimos 5 registros.
/help - Esta guía.

**Tecnología:**
• **Time-Decay:** El modelo da más peso a los resultados recientes.
• **Dixon-Coles:** Ajuste matemático para predecir mejor los empates.
• **IA Gemini:** Analiza las probabilidades para encontrar el mejor 'Value'.
    """
    await bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['predecir'])
async def cmd_predecir(message):
    data = obtener_datos_poisson()
    if not data:
        await bot.reply_to(message, "❌ No se pudo cargar el modelo desde GitHub.")
        return
    
    markup = InlineKeyboardMarkup()
    teams = sorted(data['LaLiga']['teams'].keys())
    for i in range(0, len(teams), 2):
        row = [InlineKeyboardButton(teams[i], callback_query_data=f"L:{teams[i]}")]
        if i+1 < len(teams):
            row.append(InlineKeyboardButton(teams[i+1], callback_query_data=f"L:{teams[i+1]}"))
        markup.add(*row)
    
    await bot.send_message(message.chat.id, "🏟 Selecciona el equipo **LOCAL**:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
async def callback_query(call):
    data = obtener_datos_poisson()
    if not data: return

    if call.data.startswith("L:"):
        local = call.data.split(":")[1]
        markup = InlineKeyboardMarkup()
        teams = sorted(data['LaLiga']['teams'].keys())
        for i in range(0, len(teams), 2):
            t1 = teams[i]
            t2 = teams[i+1] if i+1 < len(teams) else None
            row = [InlineKeyboardButton(t1, callback_query_data=f"V:{local}:{t1}")]
            if t2: row.append(InlineKeyboardButton(t2, callback_query_data=f"V:{local}:{t2}"))
            markup.add(*row)
        await bot.edit_message_text(f"🏠 Local: **{local}**\nSelecciona el **VISITANTE**:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    elif call.data.startswith("V:"):
        _, local, visitante = call.data.split(":")
        if local == visitante:
            await bot.answer_callback_query(call.id, "❌ No pueden ser el mismo equipo.")
            return
        
        sent = await bot.edit_message_text(f"⏳ Procesando {local} vs {visitante}...", call.message.chat.id, call.message.message_id)
        
        res = calcular_probabilidades(local, visitante, data)
        
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Actúa como analista Pro de LaLiga. Datos Poisson (Ajuste Dixon-Coles):
        Partido: {local} vs {visitante}
        - Goles Esperados Local (Lambda H): {res['lh']:.2f}
        - Goles Esperados Visita (Lambda A): {res['la']:.2f}
        - Probabilidades: Local {res['p_h']:.1%}, Empate {res['p_d']:.1%}, Visita {res['p_a']:.1%}
        
        Tarea:
        1. Explica el favoritismo brevemente.
        2. Indica el pick con más VALUE.
        3. Da un marcador exacto.
        Tono directo, usa emojis.
        """
        
        try:
            response = model.generate_content(prompt)
            texto_final = f"🏟 **{local} vs {visitante}**\n\n{response.text}"
            await bot.edit_message_text(texto_final, call.message.chat.id, sent.message_id, parse_mode='Markdown')
            await guardar_en_historial(f"{local} vs {visitante}", "Análisis Generado", response.text)
        except Exception as e:
            await bot.edit_message_text(f"❌ Error IA: {e}", call.message.chat.id, sent.message_id)

@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    try:
        url_hist = f"https://raw.githubusercontent.com/{REPO_PATH}/main/{HISTORIAL_FILE}"
        r = requests.get(url_hist, timeout=10)
        if r.status_code == 200:
            logs = r.json()[-5:] # Últimos 5
            if not logs:
                await bot.reply_to(message, "📭 Historial vacío.")
                return
            texto = "📜 **ÚLTIMOS PRONÓSTICOS:**\n\n"
            for l in logs:
                res = l.get('resultado_real', 'Pendiente')
                texto += f"• `{l['fecha']}`: **{l['partido']}**\n  Result: `{res}`\n"
            await bot.reply_to(message, texto, parse_mode='Markdown')
        else:
            await bot.reply_to(message, "📂 No se pudo acceder al historial.")
    except Exception as e:
        await bot.reply_to(message, f"❌ Error: {e}")

if __name__ == "__main__":
    logger.info("🚀 Bot iniciado correctamente...")
    asyncio.run(bot.polling())
