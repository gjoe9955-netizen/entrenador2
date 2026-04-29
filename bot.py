import os
import json
import asyncio
import logging
import requests
import base64
import html # Para limpiar el texto de la IA
from scipy.stats import poisson
from datetime import datetime, timedelta, timezone

import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GROQ_KEY = os.getenv('GROQ_API_KEY')
SAMBA_KEY = os.getenv('SAMBA_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('API_KEY_ODDS')
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

    "nodos_samba": [
        "DeepSeek-V3.1",
        "DeepSeek-V3.1-cb",
        "DeepSeek-V3.2",
        "Llama-4-Maverick-17B-128E-Instruct",
        "Meta-Llama-3.3-70B-Instruct"
    ],

    "nodos_groq": [
        "llama-3.3-70b-versatile",
        "groq/compound-mini",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "llama-3.1-8b-instant",
        "groq/compound"
    ]
}

# --- Motores de IA (Groq & SambaNova) ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    if config["api"] == 'GROQ':
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    else:
        url = "https://api.sambanova.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {SAMBA_KEY}", "Content-Type": "application/json"}

    payload = {
        "model": config["nodo"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }

    try:
        r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=15)
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
        logging.error(f"Error IA {config['api']}: {e}")
        return f"❌ Error en Nodo {config['api']}"

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
                return f"Local {l} | Visitante {v} | Empates {e}", True
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

    # Corregido: datetime.now(timezone.utc)
    fecha_hoy = (datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M')
    
    asyncio.create_task(guardar_en_github(nuevo_registro={
        "fecha": fecha_hoy,
        "partido": f"{m_l} vs {m_v}",
        "pick": m_l if edge_real > 0 else "No Bet",
        "poisson": f"{p_percent:.1f}%",
        "cuota": c_l,
        "edge": f"{edge_real*100:.1f}%",
        "stake": f"{stake_final}%",
        "nivel": nivel,
        "status": "⏳ PENDIENTE"
    }))

    header = (f"<b>🛠 REPORTE:</b> {'✅' if check_odds else '❌'} Cuotas | "
              f"{'✅' if check_json else '❌'} Poisson ({p_percent:.1f}%) | "
              f"{'✅' if check_h2h else '❌'} H2H\n"
              f"————————————————————\n")
    
    prompt_e = (
        f"ERES UN ANALISTA DE ÉLITE. Evalúa: {m_l} vs {m_v}.\n"
        f"VARIABLES:\n- Poisson: {p_percent:.1f}%\n- Cuota Mercado: {c_l}\n- H2H API: {h2h}\n\n"
        f"FORMATO:\n🎯 PICK: {m_l if edge_real > 0 else 'No Bet'}\n📈 NIVEL: {nivel}\n💰 STAKE: {stake_final}%\n"
        f"🔬 MÉTRICAS: P_Final [%], Cuota Justa, Edge [%]\n📝 ANÁLISIS: Breve."
    )
    
    analisis_raw = await ejecutar_ia("estratega", prompt_e)
    # Escapamos el texto de la IA para evitar errores de HTML
    analisis = html.escape(analisis_raw)
    
    footer = f"\n\n{'—'*20}\n🛰 <b>ESTRATEGA:</b> <code>{SISTEMA_IA['estratega']['api']}</code> ({SISTEMA_IA['estratega']['nodo']})"

    if SISTEMA_IA["auditor"]["nodo"]:
        prompt_a = f"Auditor. Valida: '{analisis_raw}'. Poisson: {p_percent:.1f}%. Reporta VEREDICTO."
        auditoria_raw = await ejecutar_ia("auditor", prompt_a)
        auditoria = html.escape(auditoria_raw)
        footer += f"\n🛡 <b>AUDITOR:</b> <code>{SISTEMA_IA['auditor']['api']}</code> ({SISTEMA_IA['auditor']['nodo']})"
        final = f"{header}{analisis}\n\n{auditoria}{footer}"
    else:
        final = f"{header}{analisis}{footer}"

    # Cambiado a parse_mode='HTML' para mayor estabilidad con texto de IA
    await bot.edit_message_text(final, message.chat.id, msg_espera.message_id, parse_mode='HTML')

# --- Gestión de Historial y Validación ---
@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    try:
        r = requests.get(url)
        historial = r.json()
        if not historial:
            await bot.reply_to(message, "📭 Historial vacío."); return
        txt = "📜 <b>HISTORIAL RECIENTE:</b>\n\n"
        for r in historial[-10:]:
            txt += f"📅 <code>{r['fecha']}</code>\n⚽ <b>{r['partido']}</b>\n🎯 Pick: <code>{r['pick']}</code> | {r['status']}\n{'—'*15}\n"
        await bot.reply_to(message, txt, parse_mode='HTML')
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
    txt = "📅 <b>PARTIDOS (HORA JUÁREZ)</b>\n\n"
    for m in data['matches'][:10]:
        dt = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=OFFSET_JUAREZ)
        txt += f"🕒 <code>{dt.strftime('%H:%M')}</code> | <code>{dt.strftime('%d/%m')}</code>\n🏠 <b>{m['homeTeam']['shortName']}</b> vs 🚩 <b>{m['awayTeam']['shortName']}</b>\n{'—'*15}\n"
    await bot.reply_to(message, txt, parse_mode='HTML')

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    data = await api_football_call("standings")
    if not data: return
    txt = "🏆 <b>POSICIONES:</b>\n\n"
    for t in data['standings'][0]['table'][:12]:
        txt += f"<code>{t['position']:02d}.</code> <b>{t['team']['shortName']}</b> | {t['points']} pts\n"
    await bot.reply_to(message, txt, parse_mode='HTML')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    res = requests.get(URL_JSON).json()
    liga = next(iter(res))
    equipos = ", ".join([f"<code>{e}</code>" for e in res[liga]['teams'].keys()])
    await bot.reply_to(message, f"📋 <b>EQUIPOS JSON:</b>\n\n{equipos}", parse_mode='HTML')

# --- Gestión de Nodos y Configuración ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "🛠 <b>CONFIGURACIÓN DE RED</b>", reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ"),
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')
    nodos = SISTEMA_IA["nodos_groq"] if api == 'GROQ' else SISTEMA_IA["nodos_samba"]
    markup = InlineKeyboardMarkup()
    for idx, nombre in enumerate(nodos):
        markup.add(InlineKeyboardButton(nombre, callback_data=f"sv_{rol[0]}_{api[0]}_{idx}"))
    await bot.edit_message_text(f"Selecciona Nodo para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sv_'))
async def cb_save(call):
    _, r_init, a_init, idx = call.data.split('_')
    rol = "estratega" if r_init == 'e' else "auditor"
    api = "GROQ" if a_init == 'G' else "SAMBA"
    lista = SISTEMA_IA["nodos_groq"] if api == "GROQ" else SISTEMA_IA["nodos_samba"]
    nodo_sel = lista[int(idx)]
    
    SISTEMA_IA[rol] = {"api": api, "nodo": nodo_sel}
    
    markup = InlineKeyboardMarkup()
    if rol == "estratega": markup.add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_rol_auditor"))
    markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} listo: <code>{nodo_sel}</code>", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 <b>SISTEMA LISTO</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML')

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    help_text = (
        "🤖 <b>SISTEMA V5.1 FIX</b>\n\n"
        "📈 <b>ANÁLISIS:</b>\n"
        "• <code>/pronostico Local vs Visitante</code>: Análisis + Kelly.\n"
        "• <code>/historial</code>: Últimos pronósticos.\n"
        "• <code>/validar</code>: Sincroniza resultados GitHub.\n"
        "• <code>/config</code>: Configura IA.\n\n"
        "⚽ <b>INFORMACIÓN:</b>\n"
        "• <code>/partidos</code>: Próximos encuentros.\n"
        "• <code>/tabla</code>: Posiciones liga.\n"
        "• <code>/equipos</code>: Lista equipos JSON.\n"
    )
    await bot.reply_to(message, help_text, parse_mode='HTML')

async def main(): 
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__": 
    asyncio.run(main())
