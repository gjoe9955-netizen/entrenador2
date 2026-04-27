import os
import json
import asyncio
import logging
import telebot
from telebot.async_telebot import AsyncTeleBot
from google import generativeai as genai
from scipy.stats import poisson
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración e Inyección de Entorno ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Captura de variables con los nombres que usas en Railway
TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')

# Validación de seguridad profesional
if not TOKEN or not GEMINI_KEY:
    logging.error("❌ Variables de entorno no detectadas. Verifica el panel de Railway.")
    exit(1)

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)

# --- Utilidades de IA ---
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
                        # Test de respuesta rápida
                        await asyncio.to_thread(test_model.generate_content, "hi", generation_config={"max_output_tokens": 1})
                        aptos.append(nombre)
                        await asyncio.sleep(0.1)
                    except: continue
        aptos.sort(reverse=True)
        return aptos[:6]
    except: return []

# Estado global del nodo
config_ia = {"modelo_actual": "gemini-1.5-flash"}

# --- Lógica de Poisson ---
def calcular_probabilidades(local, visitante):
    try:
        with open('modelo_poisson.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        if local not in data['teams'] or visitante not in data['teams']: return None
        
        l_s, v_s = data['teams'][local], data['teams'][visitante]
        avg = data['averages']
        
        lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
        la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
        
        ph, pd, pa = 0, 0, 0
        for x in range(9):
            for y in range(9):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la)
                if x > y: ph += p
                elif x == y: pd += p
                else: pa += p
        return {"lh": lh, "la": la, "ph": ph, "pd": pd, "pa": pa}
    except: return None

# --- Manejadores de Comandos ---

@bot.message_handler(commands=['start', 'help'])
async def cmd_start(message):
    text = (
        "⚽ <b>ANALISTA DEPORTIVO IA</b>\n"
        "───────────────────\n"
        "└ /test - Configura nodos de IA\n"
        "└ /pronostico Local vs Visitante\n"
        "└ /equipos - Lista de base de datos\n"
        "└ /modelo - Nodo activo"
    )
    await bot.reply_to(message, text, parse_mode='HTML')

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos disponibles...", parse_mode='HTML')
    modelos = await obtener_modelos_reales(GEMINI_KEY)
    await bot.delete_message(message.chat.id, wait.message_id)
    
    if not modelos:
        await bot.reply_to(message, "❌ No se encontraron nodos disponibles."); return
        
    markup = InlineKeyboardMarkup()
    for m in modelos:
        markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
    await bot.send_message(message.chat.id, "🎯 <b>SELECCIONE MOTOR IA:</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set_model(call):
    nuevo_modelo = call.data.split('_')[1]
    config_ia["modelo_actual"] = nuevo_modelo
    await bot.edit_message_text(f"🚀 <b>NODO CONFIGURADO:</b>\n<code>{nuevo_modelo}</code>", call.message.chat.id, call.message.message_id, parse_mode='HTML')

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    cmd = message.text.split()[0]
    raw = message.text.replace(cmd, "").strip()
    
    if " vs " not in raw:
        await bot.reply_to(message, "⚠️ Formato: `Local vs Visitante`", parse_mode='Markdown'); return

    local, visitante = [t.strip() for t in raw.split(" vs ")]
    res = calcular_probabilidades(local, visitante)
    
    if not res:
        await bot.reply_to(message, "❌ Equipos no encontrados."); return

    sent = await bot.reply_to(message, "📉 Generando análisis probabilístico...")
    
    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        tipo = "cuotas de valor" if "valor" in cmd else "pronóstico directo"
        prompt = (
            f"Actúa como tipster experto. Partido: {local} vs {visitante}. "
            f"Probabilidades Poisson: Local {res['ph']*100:.1f}%, Empate {res['pd']*100:.1f}%, Visitante {res['pa']*100:.1f}%. "
            f"Goles: {res['lh']:.2f} - {res['la']:.2f}. "
            f"Dame un {tipo} breve con emojis."
        )
        
        # Ejecución asíncrona para no bloquear el bot
        response = await asyncio.to_thread(model.generate_content, prompt)
        await bot.edit_message_text(response.text, message.chat.id, sent.message_id)
    except Exception as e:
        await bot.edit_message_text(f"⚠️ Error en IA: {str(e)[:50]}", message.chat.id, sent.message_id)

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    try:
        with open('modelo_poisson.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        lista = ", ".join(sorted(data['teams'].keys()))
        await bot.reply_to(message, f"📋 <b>Equipos:</b>\n<code>{lista}</code>", parse_mode='HTML')
    except: await bot.reply_to(message, "❌ Error al leer JSON.")

@bot.message_handler(commands=['modelo'])
async def cmd_modelo(message):
    await bot.reply_to(message, f"🧠 <b>Nodo:</b> <code>{config_ia['modelo_actual']}</code>", parse_mode='HTML')

# --- Ciclo de Ejecución ---
async def main():
    logging.info("🚀 Bot Deportivo Asíncrono Iniciado")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
