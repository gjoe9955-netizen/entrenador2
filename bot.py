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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
GEMINI_KEY = os.getenv('GEMINI_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
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
    "candidatos": {"GEMINI": [], "GROQ": []},
    "vivos": {"GEMINI": [], "GROQ": []}
}

# --- Persistencia en GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    if not GITHUB_TOKEN: return
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
            "message": "🤖 Actualización de Historial - Kelly & Validate",
            "content": nuevo_contenido,
            "sha": sha
        }
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- Test de Aptitud Matemática (Poisson) ---
async def test_aptitud_matematica(api, nodo):
    prompt_test = "Responde solo el numero: Si lambda es 2.0, cual es la probabilidad de x=0 en Poisson? (Punto decimal)"
    try:
        if api == 'GEMINI':
            client = genai.Client(api_key=GEMINI_KEY)
            res = await asyncio.to_thread(client.models.generate_content, model=nodo, contents=prompt_test)
            return any(x in res.text for x in ["0.13", "0,13"])
        
        elif api == 'GROQ':
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": nodo, "messages": [{"role": "user", "content": prompt_test}], "max_tokens": 10}
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                texto = r.json()['choices'][0]['message']['content']
                return any(x in texto for x in ["0.13", "0,13"])
        return False
    except: return False

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    sys_instruction = "Eres un analista senior de riesgos. Evalúa Poisson vs Mercado usando Kelly. Responde con tecnicismos y precisión."

    try:
        if config["api"] == 'GEMINI':
            client = genai.Client(api_key=GEMINI_KEY)
            res = await asyncio.to_thread(client.models.generate_content, model=config["nodo"], contents=prompt, config=types.GenerateContentConfig(system_instruction=sys_instruction, temperature=0.1))
            return res.text
        
        elif config["api"] == 'GROQ':
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": config["nodo"], "messages": [{"role": "system", "content": sys_instruction}, {"role": "user", "content": prompt}], "temperature": 0.1}
            r = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=15)
            return r.json()['choices'][0]['message']['content']
    except: return f"❌ Error en Nodo {config['api']}"

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

# --- COMANDOS PRINCIPALES ---

@bot.message_handler(commands=['scan_nodos'])
async def scan_nodos(message):
    input_text = message.text.replace('/scan_nodos', '').strip()
    if input_text:
        for seccion in input_text.split():
            if ':' in seccion:
                api, modelos = seccion.split(':')
                api = api.upper()
                if api in SISTEMA_IA["candidatos"]:
                    SISTEMA_IA["candidatos"][api] = modelos.split(',')

    if not any(SISTEMA_IA["candidatos"].values()):
        await bot.reply_to(message, "⚠️ Indica modelos. Ej: `/scan_nodos GROQ:llama-3.3-70b-versatile`")
        return

    msg = await bot.reply_to(message, "📡 Testeando aptitud matemática de los nodos...")
    SISTEMA_IA["vivos"] = {"GEMINI": [], "GROQ": []}
    reporte = "🔎 **REPORTE DE NODOS:**\n\n"

    for api, modelos in SISTEMA_IA["candidatos"].items():
        for m in modelos:
            if await test_aptitud_matematica(api, m):
                SISTEMA_IA["vivos"][api].append(m)
                reporte += f"✅ `{api}:{m}` - APTO\n"
            else:
                reporte += f"❌ `{api}:{m}` - NO APTO\n"
            await asyncio.sleep(1.5)

    await bot.edit_message_text(reporte + "\nUsa `/config` para asignar roles.", message.chat.id, msg.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura nodos con `/config`."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Calculando Poisson y Kelly...")

    try:
        raw_json = requests.get(URL_JSON)
        full_data = raw_json.json()
        c_l, c_e, c_v, check_odds = await obtener_datos_mercado(l_q)
        h2h, check_h2h = await obtener_h2h_directo(l_q, v_q)

        liga = next(iter(full_data))
        m_l = next((t for t in full_data[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
        m_v = next((t for t in full_data[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
        
        if not m_l or not m_v:
            await bot.edit_message_text("❌ Equipo no localizado en DB Poisson.", message.chat.id, msg_espera.message_id); return

        l_s, v_s = full_data[liga]['teams'][m_l], full_data[liga]['teams'][m_v]
        avg = full_data[liga]['averages']
        lh, la = l_s['att_h'] * v_s['def_a'] * avg['league_home'], v_s['att_a'] * l_s['def_h'] * avg['league_away']
        
        ph = sum(poisson.pmf(x, lh) * poisson.pmf(y, la) for x in range(7) for y in range(7) if x > y)
        
        edge_real = ph - (1/c_l)
        if edge_real > 0:
            kelly = ((c_l * ph) - 1) / (c_l - 1)
            stake_final = max(0, min(round(kelly * 0.25 * 100, 2), 5.0))
        else: stake_final = 0

        nivel = "DIAMANTE 💎" if edge_real > 0.05 else "ORO 🥇" if edge_real > 0.02 else "PLATA 🥈" if edge_real > 0 else "SIN VALOR ⚠️"

        header = f"🛠 REPORTE: {'✅' if check_odds else '❌'} Cuotas | {'✅' if ph > 0 else '❌'} Poisson ({ph*100:.1f}%) | {'✅' if check_h2h else '❌'} H2H\n{'—'*15}\n"
        prompt_e = f"Partido: {m_l} vs {m_v}. Poisson: {ph*100:.1f}%. Cuota: {c_l}. H2H: {h2h}. NIVEL: {nivel}. STAKE: {stake_final}%.\nFormato: NIVEL, STAKE, VALOR (4 líneas), PICK, CUOTA, EDGE."
        
        analisis = await ejecutar_ia("estratega", prompt_e)
        
        asyncio.create_task(guardar_en_github(nuevo_registro={
            "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l if edge_real > 0 else "No Bet",
            "poisson": f"{ph*100:.1f}%", "cuota": c_l, "edge": f"{edge_real*100:.1f}%", "stake": f"{stake_final}%", "status": "⏳ PENDIENTE"
        }))

        footer = f"\n\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}` ({SISTEMA_IA['estratega']['nodo']})"
        await bot.edit_message_text(header + analisis + footer, message.chat.id, msg_espera.message_id, parse_mode='Markdown')
    except Exception as e:
        await bot.edit_message_text(f"❌ Error: {str(e)}", message.chat.id, msg_espera.message_id)

# --- COMANDOS DE INFORMACIÓN Y GESTIÓN ---

@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    try:
        r = requests.get(url)
        historial = r.json()
        txt = "📜 **HISTORIAL RECIENTE:**\n\n"
        for r in historial[-8:]:
            txt += f"📅 `{r['fecha']}` | ⚽ **{r['partido']}**\n🎯 Pick: `{r['pick']}` | {r['status']}\n{'—'*15}\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Historial no disponible.")

@bot.message_handler(commands=['validar'])
async def cmd_validar(message):
    msg = await bot.reply_to(message, "🔍 Buscando cierres en Football-Data API...")
    try:
        url_h = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
        historial = requests.get(url_h).json()
        data_api = await api_football_call("matches?status=FINISHED")
        count = 0
        for item in historial:
            if item.get("status") == "⏳ PENDIENTE":
                for m in data_api['matches']:
                    h_api, a_api = m['homeTeam']['shortName'].lower(), m['awayTeam']['shortName'].lower()
                    if h_api in item['partido'].lower() and a_api in item['partido'].lower():
                        res = m['score']['winner']
                        if item['pick'] == "No Bet": item['status'] = "➖ VOID"
                        elif (res == 'HOME_TEAM' and h_api in item['pick'].lower()) or (res == 'AWAY_TEAM' and a_api in item['pick'].lower()): item['status'] = "✅ WIN"
                        else: item['status'] = "❌ LOSS"
                        count += 1
        if count > 0:
            await guardar_en_github(historial_completo=historial)
            await bot.edit_message_text(f"✅ Se validaron {count} partidos.", message.chat.id, msg.message_id)
        else: await bot.edit_message_text("ℹ️ Nada nuevo que validar.", message.chat.id, msg.message_id)
    except: await bot.edit_message_text("❌ Fallo en validación.", message.chat.id, msg.message_id)

@bot.message_handler(commands=['partidos', 'tabla', 'equipos'])
async def info_commands(message):
    cmd = message.text.split()[0][1:]
    if cmd == 'partidos':
        data = await api_football_call("matches?status=SCHEDULED")
        txt = "📅 **PRÓXIMOS PARTIDOS:**\n\n"
        for m in data['matches'][:8]:
            dt = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=OFFSET_JUAREZ)
            txt += f"🕒 `{dt.strftime('%H:%M')}` | **{m['homeTeam']['shortName']}** vs **{m['awayTeam']['shortName']}**\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    elif cmd == 'tabla':
        data = await api_football_call("standings")
        txt = "🏆 **POSICIONES LA LIGA:**\n\n"
        for t in data['standings'][0]['table'][:10]:
            txt += f"`{t['position']:02d}.` **{t['team']['shortName']}** | {t['points']} pts\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    elif cmd == 'equipos':
        res = requests.get(URL_JSON).json()
        liga = next(iter(res))
        await bot.reply_to(message, f"📋 **EQUIPOS POISSON:**\n\n" + ", ".join([f"`{e}`" for e in res[liga]['teams'].keys()]), parse_mode='Markdown')

@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ **CONFIGURACIÓN DE RED**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]
    markup = InlineKeyboardMarkup().row(*(InlineKeyboardButton(api, callback_data=f"set_api_{rol}_{api}") for api in ["GEMINI", "GROQ"]))
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')
    vivos = SISTEMA_IA["vivos"][api]
    if not vivos:
        await bot.answer_callback_query(call.id, f"❌ Sin nodos aptos en {api}", show_alert=True); return
    markup = InlineKeyboardMarkup()
    for n in vivos: markup.add(InlineKeyboardButton(n, callback_data=f"save_nodo_{rol}_{api}_{n}"))
    await bot.edit_message_text(f"Nodos disponibles ({api}):", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_nodo_'))
async def cb_save(call):
    _, _, rol, api, nodo = call.data.split('_')
    SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
    await bot.edit_message_text(f"🚀 **{rol.upper()} LISTO**\nNodo: `{nodo}`", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    await bot.reply_to(message, "🤖 **BET-BOT v6.1 - CLEAN**\n\n"
                                "📈 **ACCIONES:**\n"
                                "• `/scan_nodos API:mod1,mod2` - Test matemático.\n"
                                "• `/config` - Asigna Estratega.\n"
                                "• `/pronostico Local vs Visitante` - Análisis + Kelly.\n"
                                "• `/validar` - Cierra resultados en GitHub.\n"
                                "• `/historial` - Ver últimos picks.\n\n"
                                "⚽ **INFO:** `/partidos`, `/tabla`, `/equipos`.", parse_mode='Markdown')

async def main():
    logging.info("Iniciando Bot...")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
