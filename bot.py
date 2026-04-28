import os
import json
import asyncio
import logging
import requests
import base64
from scipy.stats import poisson
from datetime import datetime, timedelta

from google import genai
from google.genai import types
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
NVIDIA_KEY = os.getenv('NVIDIA_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        
        if historial_completo is None:
            if r.status_code == 200:
                historial = json.loads(base64.b64decode(r.json()['content']).decode('utf-8'))
            else:
                historial = []
            if nuevo_registro: historial.append(nuevo_registro)
        else:
            historial = historial_completo

        nuevo_contenido = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {
            "message": "🤖 Actualización de Historial",
            "content": nuevo_contenido,
            "sha": sha
        }
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- Estado Global ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_gemini": ['gemini-2.5-flash-lite', 'gemini-3.1-flash-lite-preview'],
    "nodos_nvidia": ['meta/llama-3.3-70b-instruct', 'meta/llama-3.1-8b-instruct']
}

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    if config["api"] == 'GEMINI':
        client = genai.Client(api_key=GEMINI_KEY)
        try:
            res = await asyncio.to_thread(
                client.models.generate_content, 
                model=config["nodo"], 
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )
            return res.text
        except: return "❌ Error en Nodo Gemini"
    else:
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"}
        payload = {"model": config["nodo"], "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        try:
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=15)
            return r.json()['choices'][0]['message']['content']
        except: return "❌ Error en Nodo NVIDIA"

# --- Núcleo Estadístico y APIs ---
async def obtener_datos_mercado(equipo_l):
    if not ODDS_API_KEY: return 1.85, 3.50, 4.00, False
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {'apiKey': ODDS_API_KEY, 'regions': 'eu', 'markets': 'h2h'}
        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)
        if r.status_code == 200:
            for match in r.json():
                home = match['home_team'].lower()
                query = equipo_l.lower()
                if query in home or home in query:
                    odds = match['bookmakers'][0]['markets'][0]['outcomes']
                    ol = next(o['price'] for o in odds if o['name'] == match['home_team'])
                    ov = next(o['price'] for o in odds if o['name'] == match['away_team'])
                    oe = next(o['price'] for o in odds if o['name'] == 'Draw')
                    return ol, oe, ov, True
    except: pass
    return 1.85, 3.50, 4.00, False

async def api_football_call(endpoint):
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        r = await asyncio.to_thread(requests.get, f"https://api.football-data.org/v4/competitions/PD/{endpoint}", headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

async def obtener_h2h_directo(equipo_l, equipo_v):
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    try:
        data = await api_football_call("teams")
        teams = data.get('teams', []) if data else []
        id_l = next((t['id'] for t in teams if equipo_l.lower() in t['shortName'].lower() or t['shortName'].lower() in equipo_l.lower()), None)
        id_v = next((t['id'] for t in teams if equipo_v.lower() in t['shortName'].lower() or t['shortName'].lower() in equipo_v.lower()), None)
        
        if id_l and id_v:
            url = f"https://api.football-data.org/v4/teams/{id_l}/matches?competitors={id_v}&status=FINISHED"
            r = await asyncio.to_thread(requests.get, url, headers=headers)
            matches = r.json().get('matches', [])
            if matches:
                l, v, e = 0, 0, 0
                for m in matches[:5]:
                    w = m['score']['winner']
                    if w == 'HOME_TEAM': l += 1
                    elif w == 'AWAY_TEAM': v += 1
                    else: e += 1
                return f"H2H Real: Local {l} | Visitante {v} | Empates {e}", True
        return "H2H: Sin datos directos.", False
    except: return "H2H: Error API.", False

# --- Comando Principal: Pronóstico ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura los nodos con `/config`."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Consultando APIs y Poisson...")

    raw_json = requests.get(URL_JSON)
    full_data = raw_json.json()
    check_json = True if raw_json.status_code == 200 else False
    
    c_l, c_e, c_v, check_odds = await obtener_datos_mercado(l_q)
    h2h, check_h2h = await obtener_h2h_directo(l_q, v_q)

    liga = next(iter(full_data))
    m_l = next((t for t in full_data[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
    m_v = next((t for t in full_data[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
    
    if not m_l or not m_v:
        await bot.edit_message_text("❌ Equipo no encontrado en el JSON.", message.chat.id, msg_espera.message_id); return

    l_s, v_s = full_data[liga]['teams'][m_l], full_data[liga]['teams'][m_v]
    avg = full_data[liga]['averages']
    lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
    la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
    
    ph, pd, pa = 0, 0, 0
    for x in range(6):
        for y in range(6):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la)
            if x > y: ph += p
            elif x == y: pd += p
            else: pa += p

    p_win = ph 
    p_percent = p_win * 100
    prob_implied = 1 / c_l
    edge_real = p_win - prob_implied
    
    if edge_real > 0:
        kelly = ((c_l * p_win) - 1) / (c_l - 1)
        stake_final = round(kelly * 0.25 * 100, 2)
        stake_final = max(0, min(stake_final, 5)) 
    else:
        stake_final = 0

    if edge_real > 0.05: nivel = "DIAMANTE 💎"
    elif edge_real > 0.02: nivel = "ORO 🥇"
    elif edge_real > 0: nivel = "PLATA 🥈"
    else: nivel = "RIESGO ALTO / SIN VALOR ⚠️"

    # Guardar en GitHub
    asyncio.create_task(guardar_en_github(nuevo_registro={
        "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
        "partido": f"{m_l} vs {m_v}",
        "pick": m_l if edge_real > 0 else "No Bet",
        "poisson": f"{p_percent:.1f}%",
        "cuota": c_l,
        "edge": f"{edge_real*100:.1f}%",
        "stake": f"{stake_final}%",
        "nivel": nivel,
        "status": "⏳ PENDIENTE"
    }))

    header = (f"🛠 REPORTE: {'✅' if check_odds else '❌'} Cuotas | "
              f"{'✅' if check_json else '❌'} Poisson ({p_percent:.1f}%) | "
              f"{'✅' if check_h2h else '❌'} H2H\n"
              f"————————————————————\n")
    
    prompt_e = (
        f"Analista Senior. Partido: {m_l} vs {m_v}.\n"
        f"Poisson: {p_percent:.1f}%. Cuota: {c_l}. H2H: {h2h}.\n"
        f"NIVEL: {nivel}. STAKE: {stake_final}%.\n\n"
        f"Formato: NIVEL, STAKE, VALOR (4 líneas técnicas), PICK, CUOTA, EDGE."
    )
    
    analisis = await ejecutar_ia("estratega", prompt_e)
    footer = f"\n\n{'—'*20}\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}` ({SISTEMA_IA['estratega']['nodo']})"

    if SISTEMA_IA["auditor"]["nodo"]:
        prompt_a = f"Auditor. Valida: '{analisis}'. Poisson: {p_percent:.1f}%. Reporta VEREDICTO."
        auditoria = await ejecutar_ia("auditor", prompt_a)
        footer += f"\n🛡 **AUDITOR:** `{SISTEMA_IA['auditor']['api']}` ({SISTEMA_IA['auditor']['nodo']})"
        final = f"{header}{analisis}\n\n{auditoria}{footer}"
    else:
        final = f"{header}{analisis}{footer}"

    await bot.edit_message_text(final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

# --- Gestión de Historial y Validación ---
@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    try:
        r = requests.get(url)
        historial = r.json()
        if not historial:
            await bot.reply_to(message, "📭 Historial vacío."); return
        txt = "📜 **HISTORIAL RECIENTE:**\n\n"
        for r in historial[-10:]:
            txt += f"📅 `{r['fecha']}`\n⚽ **{r['partido']}**\n🎯 Pick: `{r['pick']}` | {r['status']}\n{'—'*15}\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer historial.")

@bot.message_handler(commands=['validar'])
async def cmd_validar(message):
    msg_espera = await bot.reply_to(message, "🔍 Buscando resultados finales en la API...")
    url_h = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    
    try:
        historial = requests.get(url_h).json()
        data_api = await api_football_call("matches?status=FINISHED")
        if not data_api: await bot.edit_message_text("❌ No hay resultados nuevos en la API.", message.chat.id, msg_espera.message_id); return

        count = 0
        for item in historial:
            if item.get("status") == "⏳ PENDIENTE":
                for m in data_api['matches']:
                    h_api, a_api = m['homeTeam']['shortName'].lower(), m['awayTeam']['shortName'].lower()
                    if h_api in item['partido'].lower() and a_api in item['partido'].lower():
                        res = m['score']['winner']
                        # Lógica de validación
                        if item['pick'] == "No Bet": item['status'] = "➖ VOID"
                        elif (res == 'HOME_TEAM' and h_api in item['pick'].lower()) or \
                             (res == 'AWAY_TEAM' and a_api in item['pick'].lower()):
                            item['status'] = "✅ WIN"
                        else:
                            item['status'] = "❌ LOSS"
                        count += 1

        if count > 0:
            await guardar_en_github(historial_completo=historial)
            await bot.edit_message_text(f"✅ Se validaron {count} partidos nuevos.", message.chat.id, msg_espera.message_id)
        else:
            await bot.edit_message_text("ℹ️ No se encontraron cierres para los pendientes.", message.chat.id, msg_espera.message_id)
    except: await bot.edit_message_text("❌ Fallo en la validación.", message.chat.id, msg_espera.message_id)

# --- Comandos de Información ---
@bot.message_handler(commands=['partidos'])
async def cmd_partidos(message):
    data = await api_football_call("matches?status=SCHEDULED")
    if not data: return
    txt = "📅 **PARTIDOS (HORA JUÁREZ)**\n\n"
    for m in data['matches'][:10]:
        dt = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=OFFSET_JUAREZ)
        txt += f"🕒 `{dt.strftime('%H:%M')}` | `{dt.strftime('%d/%m')}`\n🏠 **{m['homeTeam']['shortName']}** vs 🚩 **{m['awayTeam']['shortName']}**\n{'—'*15}\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    data = await api_football_call("standings")
    if not data: return
    txt = "🏆 **POSICIONES:**\n\n"
    for t in data['standings'][0]['table'][:12]:
        txt += f"`{t['position']:02d}.` **{t['team']['shortName']}** | {t['points']} pts\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    res = requests.get(URL_JSON).json()
    liga = next(iter(res))
    equipos = ", ".join([f"`{e}`" for e in res[liga]['teams'].keys()])
    await bot.reply_to(message, f"📋 **EQUIPOS JSON:**\n\n{equipos}", parse_mode='Markdown')

# --- Gestión de Nodos y Configuración ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN DE RED**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("Gemini", callback_data=f"set_api_{rol}_GEMINI"),
        InlineKeyboardButton("NVIDIA", callback_data=f"set_api_{rol}_NVIDIA")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')
    nodos = SISTEMA_IA["nodos_gemini"] if api == 'GEMINI' else SISTEMA_IA["nodos_nvidia"]
    markup = InlineKeyboardMarkup()
    for n in nodos:
        markup.add(InlineKeyboardButton(n, callback_data=f"save_nodo_{rol}_{api}_{n}"))
    await bot.edit_message_text(f"Selecciona Nodo:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_nodo_'))
async def cb_save(call):
    _, _, rol, api, nodo = call.data.split('_')
    SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
    markup = InlineKeyboardMarkup()
    if rol == "estratega": markup.add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_rol_auditor"))
    markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} listo: `{nodo}`", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 **SISTEMA LISTO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    help_text = (
        "🤖 **SISTEMA V4.9 VALIDATE-GIT**\n\n"
        "📈 **ANÁLISIS:**\n"
        "• `/pronostico Local vs Visitante`: Análisis + Kelly.\n"
        "• `/historial`: Ver pronósticos y estados.\n"
        "• `/validar`: Cierra resultados pendientes desde la API.\n"
        "• `/config`: Nodos Estratega y Auditor.\n\n"
        "⚽ **INFO:** `/partidos`, `/tabla`, `/equipos`."
    )
    await bot.reply_to(message, help_text, parse_mode='Markdown')

async def main(): await bot.polling(non_stop=True)
if __name__ == "__main__": asyncio.run(main())
