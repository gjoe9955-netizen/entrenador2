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
FOOTBALL_DATA_KEY = os.getenv('FOOTBALL_DATA_KEY')
ODDS_API_KEY = os.getenv('ODDS_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Estado Global Dinámico ---
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

# --- Motores de IA (Blindado y Mapeado a Railway) ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    # Mapeo flexible según captura de pantalla del usuario
    s_key = os.getenv('SAMBA_KEY') or os.getenv('SAMBANOVA_API_KEY')
    g_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_KEY')
    
    if config["api"] == 'SAMBA':
        if not s_key: return "❌ Error: SAMBA_KEY no configurada en Railway."
        base_url = "https://api.sambanova.ai/v1"
        api_key = s_key
    else:
        if not g_key: return "❌ Error: GROQ_API_KEY no configurada en Railway."
        base_url = "https://api.groq.com/openai/v1"
        api_key = g_key

    try:
        # Inicialización con la llave correcta detectada
        client = OpenAI(api_key=api_key, base_url=base_url)
        res = await asyncio.to_thread(
            client.chat.completions.create,
            model=config["nodo"],
            messages=[
                {"role": "system", "content": "Eres un experto analista deportivo y gestor de banca senior. Tu tono es técnico y directo."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        logging.error(f"Error en {config['api']}: {e}")
        return f"❌ Error en Nodo {config['api']}: {str(e)[:60]}"

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

# --- APIs de Datos ---
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
                    oe = next(o['price'] for o in odds if o['name'] == 'Draw' or o['name'] == 'Tie')
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
        return "Sin datos directos.", False
    except: return "Error API.", False

# --- Pronóstico y Criterio de Kelly ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura los nodos con `/config`."); return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return

    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Analizando probabilidades...")

    try:
        raw_json = requests.get(URL_JSON).json()
        liga = next(iter(raw_json))
        m_l = next((t for t in raw_json[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
        m_v = next((t for t in raw_json[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)

        if not m_l or not m_v:
            await bot.edit_message_text("❌ Equipos no coinciden con el JSON.", message.chat.id, msg_espera.message_id); return

        c_l, c_e, c_v, check_odds = await obtener_datos_mercado(l_q)
        h2h_str, check_h2h = await obtener_h2h_directo(l_q, v_q)

        l_stats, v_stats = raw_json[liga]['teams'][m_l], raw_json[liga]['teams'][m_v]
        avg = raw_json[liga]['averages']
        
        mu_l = l_stats['att_h'] * v_stats['def_a'] * avg['league_home']
        mu_v = v_stats['att_a'] * l_stats['def_h'] * avg['league_away']
        
        ph, pd, pa = 0, 0, 0
        for x in range(7):
            for y in range(7):
                prob = poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v)
                if x > y: ph += prob
                elif x == y: pd += prob
                else: pa += prob

        edge = ph - (1/c_l)
        kelly = ((c_l * ph) - 1) / (c_l - 1) if edge > 0 else 0
        stake = round(max(0, min(kelly * 0.25 * 100, 5.0)), 2)
        nivel = "DIAMANTE 💎" if edge > 0.05 else "ORO 🥇" if edge > 0.02 else "PLATA 🥈" if edge > 0 else "SIN VALOR ⚠️"

        asyncio.create_task(guardar_en_github(nuevo_registro={
            "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l if edge > 0 else "No Bet",
            "poisson": f"{ph*100:.1f}%", "cuota": c_l, "edge": f"{edge*100:.1f}%",
            "stake": f"{stake}%", "nivel": nivel, "status": "⏳ PENDIENTE"
        }))

        header = f"🛠 REPORTE: {'✅' if check_odds else '❌'} Cuotas | ✅ Poisson ({ph*100:.1f}%) | {'✅' if check_h2h else '❌'} H2H\n{'—'*20}\n"
        prompt_e = (f"Analiza: {m_l} vs {m_v}. Poisson: {ph*100:.1f}%. Cuota: {c_l}. "
                    f"H2H: {h2h_str}. Edge: {edge*100:.1f}%. NIVEL: {nivel}. "
                    f"Criterio Kelly sugiere Stake {stake}%. Justifica el valor de la apuesta.")
        
        analisis = await ejecutar_ia("estratega", prompt_e)
        res_final = f"{header}{analisis}\n\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}` ({SISTEMA_IA['estratega']['nodo']})"

        if SISTEMA_IA["auditor"]["nodo"]:
            audit_prompt = f"Audita este pick: '{analisis}'. Prob: {ph*100:.1f}%. ¿Es prudente el Stake de {stake}%?"
            auditoria = await ejecutar_ia("auditor", audit_prompt)
            res_final += f"\n\n🛡 **AUDITOR:**\n{auditoria}\n(`{SISTEMA_IA['auditor']['nodo']}`)"

        await bot.edit_message_text(res_final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')
    except Exception as e:
        await bot.edit_message_text(f"❌ Error crítico: {str(e)[:100]}", message.chat.id, msg_espera.message_id)

# --- Comandos Adicionales ---
@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    try:
        r = requests.get(url).json()
        if not r: return await bot.reply_to(message, "📭 Vacío.")
        txt = "📜 **HISTORIAL:**\n"
        for i in r[-8:]:
            txt += f"📅 `{i['fecha']}` | **{i['partido']}** | {i['status']}\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer GitHub.")

@bot.message_handler(commands=['validar'])
async def cmd_validar(message):
    msg = await bot.reply_to(message, "🔍 Cruzando datos con API-Football...")
    try:
        historial = requests.get(f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}").json()
        data_api = await api_football_call("matches?status=FINISHED")
        actualizados = 0
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
                        actualizados += 1
        if actualizados > 0:
            await guardar_en_github(historial_completo=historial)
            await bot.edit_message_text(f"✅ Se validaron {actualizados} picks.", message.chat.id, msg.message_id)
        else: await bot.edit_message_text("ℹ️ Sin picks pendientes de validar.", message.chat.id, msg.message_id)
    except: await bot.edit_message_text("❌ Error en validación.", message.chat.id, msg.message_id)

@bot.message_handler(commands=['partidos'])
async def cmd_partidos(message):
    data = await api_football_call("matches?status=SCHEDULED")
    if not data: return
    txt = "📅 **PRÓXIMOS (HORA JUÁREZ)**\n\n"
    for m in data['matches'][:8]:
        dt = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=OFFSET_JUAREZ)
        txt += f"🕒 `{dt.strftime('%H:%M')}` | **{m['homeTeam']['shortName']} vs {m['awayTeam']['shortName']}**\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    data = await api_football_call("standings")
    if not data: return
    txt = "🏆 **POSICIONES:**\n"
    for t in data['standings'][0]['table'][:10]:
        txt += f"`{t['position']}.` **{t['team']['shortName']}** ({t['points']} pts)\n"
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    res = requests.get(URL_JSON).json()
    liga = next(iter(res))
    equipos = ", ".join([f"`{e}`" for e in res[liga]['teams'].keys()])
    await bot.reply_to(message, f"📋 **EQUIPOS VÁLIDOS:**\n{equipos}", parse_mode='Markdown')

# --- Menú de Configuración (Interactivo) ---
@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 ASIGNAR ESTRATEGA", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "🛠 **CONFIGURACIÓN DE RED IA**", reply_markup=markup)

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
    await bot.edit_message_text(f"Nodo {api} para {rol}:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sv_n_'))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split('_')
    lista = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
    SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}
    markup = InlineKeyboardMarkup()
    if rol == "estratega": markup.add(InlineKeyboardButton("⚖️ AÑADIR AUDITOR", callback_data="set_rol_auditor"))
    markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} configurado.", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call): await bot.edit_message_text("🚀 **SISTEMA ACTIVADO**", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=['help'])
async def cmd_help(message):
    txt = ("🤖 **BOT ANALISTA V5.1**\n\n"
           "• `/pronostico L vs V`: Probabilidad Poisson + Kelly + IA.\n"
           "• `/historial`: Picks registrados en GitHub.\n"
           "• `/validar`: Actualiza resultados reales.\n"
           "• `/config`: Cambia entre SambaNova y Groq.\n"
           "• `/partidos`: Próximos juegos (Hora Juárez).")
    await bot.reply_to(message, txt, parse_mode='Markdown')

async def main():
    logging.info("Bot Iniciado...")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
