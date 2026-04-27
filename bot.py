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

# --- Configuración de Logs para Railway ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
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

if not TOKEN or not GEMINI_KEY:
    logger.error("❌ Faltan variables de entorno esenciales.")
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
    except Exception as e:
        logger.error(f"Error cargando Poisson: {e}")
        return None

def obtener_contexto_gratuito(local, visitante):
    if not FOOTBALL_DATA_KEY:
        logger.warning("⚠️ FOOTBALL_DATA_KEY no configurada.")
        return "Error: API Key no configurada."
    
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    base_url = "https://api.football-data.org/v4/"
    # IDs: 2014 (Primera), 2017 (Segunda)
    competiciones = ["PD", "2017"]
    matches = []

    logger.info(f"🔍 Buscando racha para: {local} vs {visitante}")

    try:
        for comp in competiciones:
            r = requests.get(f"{base_url}competitions/{comp}/matches", headers=headers, params={"status": "FINISHED"}, timeout=10)
            if r.status_code == 200:
                matches.extend(r.json().get('matches', []))
            else:
                logger.error(f"Error API Football ({comp}): {r.status_code}")

        def extraer_racha(team_name):
            racha = []
            nombre_busqueda = team_name.lower()
            for m in reversed(matches):
                if len(racha) >= 5: break
                h_name = (m['homeTeam']['shortName'] or m['homeTeam']['name']).lower()
                a_name = (m['awayTeam']['shortName'] or m['awayTeam']['name']).lower()
                
                # Match flexible
                if nombre_busqueda in h_name or h_name in nombre_busqueda or nombre_busqueda in a_name or a_name in nombre_busqueda:
                    res = m['score']['fullTime']
                    if res['home'] == res['away']: racha.append("D")
                    elif (res['home'] > res['away'] and (nombre_busqueda in h_name or h_name in nombre_busqueda)) or \
                         (res['away'] > res['home'] and (nombre_busqueda in a_name or a_name in nombre_busqueda)):
                        racha.append("W")
                    else:
                        racha.append("L")
            return "-".join(racha) if racha else None

        racha_l = extraer_racha(local)
        racha_v = extraer_racha(visitante)
        
        if racha_l and racha_v:
            logger.info(f"✅ Rachas encontradas: {racha_l} / {racha_v}")
            return f"📊 RACHAS RECIENTES (PD/SD):\n- {local}: {racha_l}\n- {visitante}: {racha_v}\n(W=Gana, D=Empate, L=Pierde)"
        
        return "No se encontraron datos de rachas en PD/SD."
    except Exception as e:
        logger.error(f"Excepción en contexto: {e}")
        return "Error en conexión de datos."

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
        logger.error(f"Error guardando historial: {e}")

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
    help_text = "⚽ **PREDICTOR MULTILIGA**\n🔍 `/test` | 📈 `/pronostico L vs V` | 📜 `/historial` | 🧠 `/modelo`"
    await bot.reply_to(message, help_text, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
async def cmd_test(message):
    wait = await bot.reply_to(message, "🔍 Escaneando nodos...")
    modelos = await obtener_modelos_reales(GEMINI_KEY)
    await bot.delete_message(message.chat.id, wait.message_id)
    if not modelos:
        await bot.reply_to(message, "❌ Sin nodos."); return
    markup = InlineKeyboardMarkup()
    for m in modelos:
        markup.add(InlineKeyboardButton(f"Nodo: {m}", callback_data=f"set_{m}"))
    await bot.send_message(message.chat.id, "🎯 **SELECCIONE MOTOR IA:**", reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_'))
async def cb_set_model(call):
    config_ia["modelo_actual"] = call.data.split('_')[1]
    await bot.edit_message_text(f"✅ **NODO:** `{config_ia['modelo_actual']}`", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['modelo'])
async def cmd_modelo(message):
    status = f"`{config_ia['modelo_actual']}`" if config_ia["modelo_actual"] else "No asignado"
    await bot.reply_to(message, f"🧠 **Nodo activo:** {status}", parse_mode='Markdown')

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_analisis(message):
    if not config_ia["modelo_actual"]:
        await bot.reply_to(message, "⚠️ Usa `/test` primero."); return
    
    cmd = message.text.split()[0]
    raw = message.text.replace(cmd, "").strip()
    if " vs " not in raw:
        await bot.reply_to(message, "⚠️ Formato: `Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in raw.split(" vs ")]
    logger.info(f"🤖 Iniciando análisis para: {l_q} vs {v_q}")
    
    res = calcular_probabilidades(l_q, v_q)
    if not res:
        await bot.reply_to(message, "❌ Equipo no encontrado."); return

    sent = await bot.reply_to(message, f"📈 Analizando con `{config_ia['modelo_actual']}`...")

    contexto_real = obtener_contexto_gratuito(res['n_l'], res['n_v'])
    cuotas_data = obtener_cuotas_reales(res['n_l'], res['n_v'])
    
    check_poisson = "✅"
    check_contexto = "✅" if "RACHAS RECIENTES" in contexto_real else "❌"
    check_odds = "✅" if cuotas_data else "❌"
    
    texto_cuotas = f"L: {cuotas_data['precios'].get('L')} | E: {cuotas_data['precios'].get('E')} | V: {cuotas_data['precios'].get('V')}" if cuotas_data else "No disponibles"

    header_checks = (
        f"🛠 **REPORTE DE DATOS:**\n"
        f"{check_poisson} Base Poisson\n"
        f"{check_contexto} Rachas Reales (PD/SD)\n"
        f"{check_odds} Cuotas Mercado\n"
        f"──────────────────────────────\n\n"
    )

    try:
        model = genai.GenerativeModel(config_ia["modelo_actual"])
        prompt = f"""
Actúa como experto en Value Betting. Cruza estos datos:
PARTIDO: {res['n_l']} vs {res['n_v']}
POISSON: WinL {res['ph']*100:.1f}% | WinV {res['pa']*100:.1f}%
RACHAS: {contexto_real}
CUOTAS: {texto_cuotas}

FORMATO:
{header_checks}
🔥 **ANÁLISIS DE VALOR:** [Análisis]
🎯 **PICK:** [Mercado]
💰 **CUOTA:** [Precio]
⚠️ **CONFIANZA:** [Nivel]

PICK_RESUMEN: [4 palabras]
"""
        response = await asyncio.to_thread(model.generate_content, prompt)
        respuesta_ia = response.text
        if "REPORTE DE DATOS" not in respuesta_ia: respuesta_ia = header_checks + respuesta_ia

        try:
            await bot.edit_message_text(respuesta_ia, message.chat.id, sent.message_id, parse_mode='Markdown')
        except:
            await bot.edit_message_text(respuesta_ia, message.chat.id, sent.message_id, parse_mode=None)

        pick_compacto = respuesta_ia.split("PICK_RESUMEN:")[-1].strip().split('\n')[0][:50] if "PICK_RESUMEN:" in respuesta_ia else "No definido"
        await guardar_en_historial_github(f"{res['n_l']} vs {res['n_v']}", respuesta_ia, pick_compacto)
    except Exception as e:
        logger.error(f"Error en Gemini: {e}")
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
                texto += f"• `{l['fecha']}`: **{l['partido']}** | Pick: *{l.get('pick_pronosticado', 'N/A')}*\n"
            await bot.reply_to(message, texto, parse_mode='Markdown')
        else: await bot.reply_to(message, "📂 Historial vacío.")
    except: await bot.reply_to(message, "❌ Error al leer historial.")

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    try:
        data = obtener_datos_poisson()
        equipos_lista = sorted(data['LaLiga']['teams'].keys())
        await bot.reply_to(message, f"📋 **Equipos Reconocidos:**\n`{', '.join(equipos_lista)}`", parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer equipos.")

async def main():
    logger.info("🚀 Bot iniciado y esperando comandos...")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
