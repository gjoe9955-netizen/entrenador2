import os
import json
import asyncio
import logging
import requests
import base64
from scipy.stats import poisson
from datetime import datetime, timedelta

from openai import OpenAI
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
SAMBA_KEY = os.getenv('SAMBA_KEY')
GROQ_KEY = os.getenv('GROQ_KEY')
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado Global ---
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": [
        "DeepSeek-V3.1", "DeepSeek-V3.1-cb", "DeepSeek-V3.2", 
        "Llama-4-Maverick-17B-128E-Instruct", "Meta-Llama-3.3-70B-Instruct"
    ],
    "nodos_groq": [
        "llama-3.3-70b-versatile", "groq/compound-mini", 
        "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant", "groq/compound"
    ]
}

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    base_url = "https://api.sambanova.ai/v1" if config["api"] == 'SAMBA' else "https://api.groq.com/openai/v1"
    key = SAMBA_KEY if config["api"] == 'SAMBA' else GROQ_KEY

    try:
        client = OpenAI(api_key=key, base_url=base_url)
        # Ajuste de mensajes para compatibilidad total con Samba/Groq
        res = await asyncio.to_thread(
            client.chat.completions.create,
            model=config["nodo"],
            messages=[
                {"role": "system", "content": "Eres un experto analista deportivo senior y gestor de banca."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        logging.error(f"Error en {config['api']}: {e}")
        return f"❌ Error en Nodo {config['api']}: {str(e)[:50]}"

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers)
        sha = r.json()['sha'] if r.status_code == 200 else None
        
        if historial_completo is None:
            historial = json.loads(base64.b64decode(r.json()['content']).decode('utf-8')) if r.status_code == 200 else []
            if nuevo_registro: historial.append(nuevo_registro)
        else:
            historial = historial_completo

        nuevo_contenido = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')
        payload = {"message": "🤖 Actualización Historial", "content": nuevo_contenido, "sha": sha}
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

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
                if equipo_l.lower() in home or home in equipo_l.lower():
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

    try:
        raw_json = requests.get(URL_JSON).json()
        liga = next(iter(raw_json))
        m_l = next((t for t in raw_json[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
        m_v = next((t for t in raw_json[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)

        if not m_l or not m_v:
            await bot.edit_message_text("❌ Equipo no encontrado en el JSON.", message.chat.id, msg_espera.message_id); return

        c_l, c_e, c_v, check_odds = await obtener_datos_mercado(l_q)
        h2h, check_h2h = await obtener_h2h_directo(l_q, v_q)

        l_s, v_s = raw_json[liga]['teams'][m_l], raw_json[liga]['teams'][m_v]
        avg = raw_json[liga]['averages']
        lh = l_s['att_h'] * v_s['def_a'] * avg['league_home']
        la = v_s['att_a'] * l_s['def_h'] * avg['league_away']
        
        ph, pd, pa = 0, 0, 0
        for x in range(6):
            for y in range(6):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la)
                if x > y: ph += p
                elif x == y: pd += p
                else: pa += p

        p_percent = ph * 100
        prob_implied = 1 / c_l
        edge_real = ph - prob_implied
        # Cálculo bajo Método Kelly (fracción 0.25)
        stake_final = round((((c_l * ph) - 1) / (c_l - 1)) * 0.25 * 100, 2) if edge_real > 0 else 0
        stake_final = max(0, min(stake_final, 5)) 

        nivel = "DIAMANTE 💎" if edge_real > 0.05 else "ORO 🥇" if edge_real > 0.02 else "PLATA 🥈" if edge_real > 0 else "SIN VALOR ⚠️"

        asyncio.create_task(guardar_en_github(nuevo_registro={
            "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l if edge_real > 0 else "No Bet",
            "poisson": f"{p_percent:.1f}%", "cuota": c_l, "edge": f"{edge_real*100:.1f}%",
            "stake": f"{stake_final}%", "nivel": nivel, "status": "⏳ PENDIENTE"
        }))

        header = f"🛠 REPORTE: {'✅' if check_odds else '❌'} Cuotas | ✅ Poisson ({p_percent:.1f}%) | {'✅' if check_h2h else '❌'} H2H\n{'—'*20}\n"
        # Prompt enriquecido con Criterio de Kelly
        prompt_e = f"Analiza: {m_l} vs {m_v}. Prob. Poisson: {p_percent:.1f}%. Cuota: {c_l}. H2H: {h2h}. Criterio de Kelly sugiere Stake: {stake_final}%. NIVEL: {nivel}. Justifica técnicamente."
        
        analisis = await ejecutar_ia("estratega", prompt_e)
        footer = f"\n\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}` ({SISTEMA_IA['estratega']['nodo']})"
        
        if SISTEMA_IA["auditor"]["nodo"]:
            auditoria = await ejecutar_ia("auditor", f"Valida: '{analisis}'. Prob: {p_percent:.1f}%. Cuota: {c_l}. ¿Es coherente el Stake Kelly de {stake_final}%?")
            footer += f"\n🛡 **AUDITOR:** `{SISTEMA_IA['auditor']['api']}` ({SISTEMA_IA['auditor']['nodo']})"
            final = f"{header}{analisis}\n\n{auditoria}{footer}"
        else:
            final = f"{header}{analisis}{footer}"

        await bot.edit_message_text(final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')
    except Exception as e:
        await bot.edit_message_text(f"❌ Error crítico: {str(e)}", message.chat.id, msg_espera.message_id)

# --- Comandos de Información y Validación ---
@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    try:
        r = requests.get(url).json()
        if not r: await bot.reply_to(message, "📭 Historial vacío."); return
        txt = "📜 **HISTORIAL RECIENTE:**\n\n"
        for i in r[-10:]:
            txt += f"📅 `{i['fecha']}`\n⚽ **{i['partido']}**\n🎯 Pick: `{i['pick']}` | {i['status']}\n{'—'*15}\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer historial.")

@bot.message_handler(commands=['validar'])
async def cmd_validar(message):
    msg_espera = await bot.reply_to(message, "🔍 Validando resultados...")
    try:
        historial = requests.get(f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}").json()
        data_api = await api_football_call("matches?status=FINISHED")
        count = 0
        for item in historial:
            if item.get("status") == "⏳ PENDIENTE":
                for m in data_api['matches']:
                    h_api, a_api = m['homeTeam']['shortName'].lower(), m['awayTeam']['shortName'].lower()
                    if h_api in item['partido'].lower() and a_api in item['partido'].lower():
                        res = m['score']['winner']
                        if item['pick'] == "No Bet": item['status'] = "➖ VOID"
                        elif (res == 'HOME_TEAM' and h_api in item['pick'].lower()) or (res == 'AWAY_TEAM' and a_api in item['pick'].lower()):
                            item['status'] = "✅ WIN"
                        else: item['status'] = "❌ LOSS"
                        count += 1
        if count > 0:
            await guardar_en_github(historial_completo=historial)
            await bot.edit_message_text(f"✅ Se validaron {count} partidos.", message.chat.id, msg_espera.message_id)
        else: await bot.edit_message_text("ℹ️ Sin resultados nuevos.", message.chat.id, msg_espera.message_id)
    except: await bot.edit_message_text("❌ Fallo en validación.", message.chat.id, msg_espera.message_id)

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

# --- Configuración de Nodos ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN DE RED**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"),
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')
    nodos = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
    markup = InlineKeyboardMarkup()
    for idx, n in enumerate(nodos):
        markup.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{idx}"))
    await bot.edit_message_text(f"Selecciona Nodo {api}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sv_n_'))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split('_')
    lista = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
    seleccion = lista[int(idx)]
    SISTEMA_IA[rol] = {"api": api, "nodo": seleccion}
    markup = InlineKeyboardMarkup()
    if rol == "estratega": markup.add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_rol_auditor"))
    markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} listo: `{seleccion}`", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call): await bot.edit_message_text("🚀 **SISTEMA LISTO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    txt = ("🤖 **BOT ANALISTA V5.1 - COMANDOS:**\n\n"
           "• `/pronostico L vs V`: Genera análisis estadístico (Poisson), cálculo de valor (Value Bet) y gestión de banca (Criterio de Kelly).\n"
           "• `/historial`: Muestra los últimos 10 pronósticos registrados en GitHub.\n"
           "• `/validar`: Cruza el historial pendiente con resultados reales para marcar WIN/LOSS.\n"
           "• `/config`: Menú interactivo para alternar entre APIs (SambaNova/Groq) y seleccionar modelos (DeepSeek, Llama 4, etc).\n"
           "• `/partidos`: Próximos 10 partidos de LaLiga en hora local (Juárez).\n"
           "• `/tabla`: Posiciones actuales de la competición.\n"
           "• `/equipos`: Lista los nombres exactos requeridos por el motor Poisson.")
    await bot.reply_to(message, txt, parse_mode='Markdown')

async def main(): await bot.polling(non_stop=True)
if __name__ == "__main__": asyncio.run(main())
