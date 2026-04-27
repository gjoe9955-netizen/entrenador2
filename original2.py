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

# --- Configuración ---
load_dotenv()
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_PATH = "gjoe9955-netizen/entrenador2"
HISTORIAL_FILE = "historial_picks.json"

if not TOKEN or not GEMINI_KEY:
    logging.error("❌ Faltan variables de entorno TOKEN_TELEGRAM o GEMINI_KEY.")
    exit(1)

bot = AsyncTeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)

config_ia = {"modelo_actual": None}

# --- Funciones de Datos ---
def obtener_datos_poisson():
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        response = requests.get(URL_JSON, headers=headers, timeout=10)
        return response.json() if response.status_code == 200 else None
    except: return None

def obtener_cuotas_reales(local, visitante):
    if not ODDS_API_KEY: return None
    try:
        url = "https://api.the-odds-api.com/v1/sports/soccer_spain_la_liga/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200: return None
        data = r.json()
        for match in data:
            h, a = match['home_team'].lower(), match['away_team'].lower()
            if (local.lower() in h or h in local.lower()) and (visitante.lower() in a or a in visitante.lower()):
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

async def guardar_en_historial_github(partido, analisis, pick_ia):
    if not GITHUB_TOKEN: return
    try:
        url = f"https://api.github.com/repos/{REPO_PATH}/contents/{HISTORIAL_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers)
        if r.status_code != 200: return
        file_data = r.json()
        sha = file_data['sha']
        content = json.loads(base64.b64decode(file_data['content']).decode('utf-8'))
        nuevo_registro = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "partido": partido,
            "pick_pronosticado": pick_ia,
            "analisis_resumen": analisis[:200] + "...",
            "resultado_real": "Pendiente"
        }
        content.append(nuevo_registro)
        new_content_b64 = base64.b64encode(json.dumps(content, indent=4).encode('utf-8')).decode('utf-8')
        payload = {"message": f"Log: {partido}", "content": new_content_b64, "sha": sha}
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error guardando historial: {e}")

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

def calcular_probabilidades(local, visitante):
    try:
        full_data = obtener_datos_poisson()
        if not full_data: return None
        data = full_data.get('LaLiga')
        if not data: return None
        m_l = next((t for t in data['teams'] if t.lower() in local.lower() or local.lower() in t.lower()), None)
        m_v = next((t for t in data['teams'] if t.lower() in visitante.lower() or visitante.lower() in t.lower()), None)
        if not m_l or not m_v: return None
        l_s, v_s = data['teams'][m_l], data['teams'][m_v]
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
        return {"lh": lh, "la": la, "ph": ph, "pd": pd, "pa": pa, "n_l": m_l, "n_v": m_v}
    except: return None

# --- Manejadores ---

@bot.message_handler(commands=['start', 'help'])
async def cmd_help(message):
    help_text = (
        "⚽ **PREDICTOR POISSON IA - GUÍA DE USO**\n"
        "──────────────────────────────\n"
        "🔍 `/test` : Escanea y selecciona nodo Gemini.\n"
        "📈 `/pronostico Local vs Visitante` : Análisis Poisson + Cuotas Reales.\n"
        "📋 `/equipos` : Lista equipos de LaLiga.\n"
        "🧠 `/modelo` : Muestra nodo activo.\n"
        "📜 `/historial` : Últimos 5 pronósticos."
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos de IA...")
    modelos = await obtener_modelos_reales(GEMINI_KEY)
    await bot.delete_message(message.chat.id, wait.message_id)
    if not modelos:
        await bot.reply_to(message, "❌ No se detectaron nodos."); return
    markup = InlineKeyboardMarkup()
    for m in modelos:
        markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
    await bot.send_message(message.chat.id, "🎯 **SELECCIONE MOTOR IA:**", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set_model(call):
    config_ia["modelo_actual"] = call.data.split('_')[1]
    await bot.edit_message_text(f"✅ **NODO ASIGNADO:** `{config_ia['modelo_actual']}`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not config_ia["modelo_actual"]:
        await bot.reply_to(message, "⚠️ Error: Nodo no asignado. Usa `/test`."); return
    cmd = message.text.split()[0]
    raw = message.text.replace(cmd, "").strip()
    if " vs " not in raw:
        await bot.reply_to(message, "⚠️ Formato: `Local vs Visitante`."); return
    l_q, v_q = [t.strip() for t in raw.split(" vs ")]
    res = calcular_probabilidades(l_q, v_q)
    if not res:
        await bot.reply_to(message, "❌ Equipo no encontrado."); return
    sent = await bot.reply_to(message, f"📈 Analizando con `{config_ia['modelo_actual']}`...")
    
    cuotas_data = obtener_cuotas_reales(res['n_l'], res['n_v'])
    texto_cuotas = "No disponibles"
    if cuotas_data:
        p = cuotas_data['precios']
        texto_cuotas = f"L: {p.get('L')} | E: {p.get('E')} | V: {p.get('V')} (vía {cuotas_data['bookie']})"

    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        prompt = f"""
Actúa como un Tipster Profesional Experto en Value Betting.
PARTIDO: {res['n_l']} vs {res['n_v']}

MÉTRICAS POISSON:
- Victoria {res['n_l']}: {res['ph']*100:.1f}% (Justa: {1/res['ph']:.2f})
- Empate: {res['pd']*100:.1f}% (Justa: {1/res['pd']:.2f})
- Victoria {res['n_v']}: {res['pa']*100:.1f}% (Justa: {1/res['pa']:.2f})

CUOTAS MERCADO REAL:
{texto_cuotas}

FORMATO DE RESPUESTA:
🔥 **ANÁLISIS DE VALOR:** [Compara Poisson vs Mercado]
🎯 **PICK RECOMENDADO:** [Mercado]
💰 **CUOTA:** [Precio]
⚠️ **CONFIANZA:** [Bajo/Medio/Alto]

PICK_RESUMEN: [Máximo 4 palabras]
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        respuesta_ia = response.text
        pick_compacto = "No definido"
        if "PICK_RESUMEN:" in respuesta_ia:
            pick_compacto = respuesta_ia.split("PICK_RESUMEN:")[-1].strip().split('\n')[0][:50]
        if len(respuesta_ia) > 4000:
            respuesta_ia = respuesta_ia[:3900] + "\n\n(Recortado)"
        try:
            await bot.edit_message_text(respuesta_ia, message.chat.id, sent.message_id, parse_mode='Markdown')
        except:
            await bot.edit_message_text(respuesta_ia, message.chat.id, sent.message_id)
        await guardar_en_historial_github(f"{res['n_l']} vs {res['n_v']}", respuesta_ia, pick_compacto)
    except Exception as e:
        await bot.edit_message_text(f"❌ Error: {str(e)[:50]}", message.chat.id, sent.message_id)

@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    try:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        url_hist = f"https://raw.githubusercontent.com/{REPO_PATH}/main/{HISTORIAL_FILE}"
        r = requests.get(url_hist, headers=headers)
        if r.status_code == 200:
            logs = r.json()[-5:]
            texto = "📜 **ÚLTIMOS PRONÓSTICOS:**\n\n"
            for l in logs:
                res_real = f" | Real: `{l.get('resultado_real', 'Pendiente')}`"
                pick = f"\n   🎯 Pick: *{l.get('pick_pronosticado', 'N/A')}*"
                texto += f"• `{l['fecha']}`: **{l['partido']}**{res_real}{pick}\n"
            await bot.reply_to(message, texto, parse_mode='Markdown')
        else: await bot.reply_to(message, "📂 Historial vacío.")
    except: await bot.reply_to(message, "❌ Error al leer historial.")

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    try:
        data = obtener_datos_poisson()
        equipos_lista = sorted(data['LaLiga']['teams'].keys())
        await bot.reply_to(message, f"📋 **Equipos (LaLiga):**\n`{', '.join(equipos_lista)}`", parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer equipos.")

@bot.message_handler(commands=['modelo'])
async def cmd_modelo(message):
    status = f"`{config_ia['modelo_actual']}`" if config_ia["modelo_actual"] else "No asignado"
    await bot.reply_to(message, f"🧠 Nodo activo: {status}", parse_mode='Markdown')

async def main():
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
