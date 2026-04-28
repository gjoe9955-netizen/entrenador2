import os
import json
import asyncio
import logging
import requests
import base64
import io
import pandas as pd
from scipy.stats import poisson
from datetime import datetime, timedelta, timezone

from openai import OpenAI
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --- Configuración de Entorno ---
logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv('TOKEN_TELEGRAM')
FOOTBALL_DATA_KEY = os.getenv('API_KEY_FOOTBALL')
ODDS_API_KEY = os.getenv('API_KEY_ODDS')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

OFFSET_JUAREZ = -6
URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --- Diccionario de Mapeo: API/JSON -> CSV ---
MAPEO_EQUIPOS = {
    "Girona FC": "Girona",
    "Rayo Vallecano de Madrid": "Vallecano",
    "Villarreal CF": "Villarreal",
    "Real Oviedo": "Oviedo",
    "RCD Mallorca": "Mallorca",
    "FC Barcelona": "Barcelona",
    "Deportivo Alavés": "Alaves",
    "Levante UD": "Levante",
    "Valencia CF": "Valencia",
    "Real Sociedad de Fútbol": "Sociedad",
    "RC Celta de Vigo": "Celta",
    "Getafe CF": "Getafe",
    "Athletic Club": "Ath Bilbao",
    "Sevilla FC": "Sevilla",
    "RCD Espanyol de Barcelona": "Espanol",
    "Club Atlético de Madrid": "Ath Madrid",
    "Elche CF": "Elche",
    "Real Betis Balompié": "Betis",
    "Real Madrid CF": "Real Madrid",
    "CA Osasuna": "Osasuna"
}

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

# --- Lógica Estadística Avanzada ---
def ajuste_dixon_coles(x, y, lh, la, rho=-0.15):
    """Ajuste de correlación para marcadores bajos (Lógica Dixon-Coles)."""
    if x == 0 and y == 0: return 1 - (lh * la * rho)
    if x == 0 and y == 1: return 1 + (lh * rho)
    if x == 1 and y == 0: return 1 + (la * rho)
    if x == 1 and y == 1: return 1 - rho
    return 1.0

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    
    s_key = os.getenv('SAMBA_KEY') or os.getenv('SAMBANOVA_API_KEY')
    g_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_KEY')
    
    if config["api"] == 'SAMBA':
        if not s_key: return "❌ Error: SAMBA_KEY no configurada."
        base_url = "https://api.sambanova.ai/v1"
        api_key = s_key
    else:
        if not g_key: return "❌ Error: GROQ_API_KEY no configurada."
        base_url = "https://api.groq.com/openai/v1"
        api_key = g_key

    instrucciones = {
        "estratega": (
            "Eres un experto en Value Betting y modelos estadísticos. "
            "Analiza: 1) Probabilidad Poisson vs Cuota Real. 2) Tendencia H2H del CSV. "
            "Tu objetivo es identificar si existe una ventaja matemática real (Edge).\n\n"
            "REGLAS:\n"
            "- Si el Edge es > 2%, busca confirmación en el H2H para el PICK.\n"
            "- Si el Edge es negativo, el PICK debe ser NO APOSTAR.\n\n"
            "FORMATO OBLIGATORIO (Máx 100 palabras):\n"
            "• ANÁLISIS: Justificación técnica breve.\n"
            "• MERCADO RELEVANTE: Cuota analizada y su valor.\n"
            "• PREDICCIÓN: Pronóstico directo (1X2) o NO APOSTAR."
        ),
        "auditor": (
            "Eres un Auditor de Riesgos Matemáticos. PROHIBIDO SALUDAR.\n\n"
            "Valida: Si el Edge es > 0 y el H2H es favorable, aprueba el Stake. "
            "Si el Edge es negativo and el estratega sugiere apostar, reporta 'INCONGRUENCIA MATEMÁTICA'. "
            "Confirma que el Stake 0% es la única acción lógica ante falta de valor.\n\n"
            "Máximo 100 palabras."
        )
    }

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        res = await asyncio.to_thread(
            client.chat.completions.create,
            model=config["nodo"],
            messages=[
                {"role": "system", "content": instrucciones[rol]},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=400
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
            if nuevo_registro:
                index_existente = next((i for i, reg in enumerate(historial) 
                                      if reg['partido'] == nuevo_registro['partido'] 
                                      and reg['status'] == "⏳ PENDIENTE"), None)
                if index_existente is not None:
                    historial[index_existente] = nuevo_registro
                else:
                    historial.append(nuevo_registro)
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

async def api_football_call(params):
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    url = f"https://api.football-data.org/v4/competitions/PD/matches?{params}"
    try:
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
        logging.error(f"Error API Football: {r.status_code}")
        return None
    except Exception as e:
        logging.error(f"Error conexión API: {e}")
        return None

async def obtener_h2h_directo(equipo_l, equipo_v):
    URL_CSV = "https://www.football-data.co.uk/mmz4281/2526/SP1.csv"
    try:
        csv_l = MAPEO_EQUIPOS.get(equipo_l)
        csv_v = MAPEO_EQUIPOS.get(equipo_v)
        if not csv_l or not csv_v:
            csv_l = equipo_l.split()[0]
            csv_v = equipo_v.split()[0]
        r = await asyncio.to_thread(requests.get, URL_CSV, timeout=10)
        if r.status_code != 200: return "Error CSV.", False
        df = pd.read_csv(io.StringIO(r.text))
        mask = ((df['HomeTeam'] == csv_l) & (df['AwayTeam'] == csv_v) | (df['HomeTeam'] == csv_v) & (df['AwayTeam'] == csv_l))
        h2h = df[mask]
        if h2h.empty: return f"Sin H2H en CSV.", False
        l, v, e = 0, 0, 0
        for _, row in h2h.iterrows():
            is_l_home = (row['HomeTeam'] == csv_l)
            if row['FTR'] == 'H':
                if is_l_home: l += 1
                else: v += 1
            elif row['FTR'] == 'A':
                if is_l_home: v += 1
                else: l += 1
            else: e += 1
        return f"Local {l} | Vis {v} | Emp {e}", True
    except: return "Error CSV.", False

# --- Pronóstico ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura los nodos con `/config`."); return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or " vs " not in parts[1]:
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`."); return
    l_q, v_q = [t.strip() for t in parts[1].split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Ejecutando Poisson + Dixon-Coles...")
    try:
        try:
            raw_json = requests.get(URL_JSON, timeout=10).json()
        except:
            with open('modelo_poisson.json', 'r', encoding='utf-8') as f:
                raw_json = json.load(f)

        liga = next(iter(raw_json))
        m_l = next((t for t in raw_json[liga]['teams'] if t.lower() in l_q.lower() or l_q.lower() in t.lower()), None)
        m_v = next((t for t in raw_json[liga]['teams'] if t.lower() in v_q.lower() or v_q.lower() in t.lower()), None)
        if not m_l or not m_v:
            await bot.edit_message_text("❌ Equipos no coinciden.", message.chat.id, msg_espera.message_id); return
        
        c_l, c_e, c_v, check_odds = await obtener_datos_mercado(m_l)
        h2h_str, check_h2h = await obtener_h2h_directo(m_l, m_v)
        l_stats, v_stats = raw_json[liga]['teams'][m_l], raw_json[liga]['teams'][m_v]
        avg = raw_json[liga]['averages']
        
        # Lambdas
        mu_l = l_stats['att_h'] * v_stats['def_a'] * avg['league_home']
        mu_v = v_stats['att_a'] * l_stats['def_h'] * avg['league_away']
        
        # Probabilidades con Dixon-Coles
        ph, pd, pa = 0, 0, 0
        for x in range(7):
            for y in range(7):
                prob = (poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v)) * ajuste_dixon_coles(x, y, mu_l, mu_v)
                if x > y: ph += prob
                elif x == y: pd += prob
                else: pa += prob
        
        edge = ph - (1/c_l)
        kelly = ((c_l * ph) - 1) / (c_l - 1) if edge > 0 else 0
        stake = round(max(0, min(kelly * 0.25 * 100, 5.0)), 2)
        nivel = "DIAMANTE 💎" if edge > 0.05 else "ORO 🥇" if edge > 0.02 else "PLATA 🥈" if edge > 0 else "SIN VALOR ⚠️"
        
        await guardar_en_github(nuevo_registro={
            "fecha": (datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l if edge > 0 else "No Bet",
            "poisson": f"{ph*100:.1f}%", "cuota": c_l, "edge": f"{edge*100:.1f}%",
            "stake": f"{stake}%", "nivel": nivel, "status": "⏳ PENDIENTE"
        })
        
        # --- Generación de Reporte y Checks de Herramientas ---
        status_odds = "✅" if check_odds else "❌"
        status_h2h = "✅" if check_h2h else "❌"
        status_poisson = "✅" # Se marca como usado siempre que el cálculo Dixon-Coles finaliza.
        
        header = f"🛠 REPORTE TÉCNICO: {m_l} vs {m_v}\n"
        header += f"{status_odds} Odds | {status_poisson} Poisson | {status_h2h} H2H\n"
        header += f"{'—'*20}\n"

        prompt_e = (
            f"DATOS MATEMÁTICOS:\n"
            f"- Lambdas: L:{mu_l:.2f} | V:{mu_v:.2f}\n"
            f"- Poisson (Dixon-Coles): Gana:{ph*100:.1f}% | Empate:{pd*100:.1f}% | Pierde:{pa*100:.1f}%\n"
            f"- Mercado: Cuota {c_l} | Edge: {edge*100:.1f}%\n"
            f"- Historial H2H: {h2h_str}\n"
        )
        
        analisis = await ejecutar_ia("estratega", prompt_e)
        res_final = f"{header}{analisis}\n\n🛰 **NODO:** `{SISTEMA_IA['estratega']['nodo']}`"
        
        if SISTEMA_IA["auditor"]["nodo"]:
            auditoria = await ejecutar_ia("auditor", f"Edge {edge*100:.1f}% | Estratega: {analisis}")
            res_final += f"\n\n🛡 **AUDITORÍA:**\n{auditoria}"
            
        await bot.edit_message_text(res_final, message.chat.id, msg_espera.message_id, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Error Pronóstico: {e}")
        await bot.edit_message_text(f"❌ Error: {e}", message.chat.id, msg_espera.message_id)

# --- Comandos Visuales ---
@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
    try:
        r = requests.get(url).json()
        if not r: return await bot.reply_to(message, "📭 **HISTORIAL VACÍO**")
        txt = "📊 **RESUMEN DE OPERACIONES**\n"
        txt += f"{'—'*20}\n\n"
        for i in r[-7:]:
            status_val = i.get('status', '⏳ PENDIENTE')
            icon = "✅" if "WIN" in status_val or "REVISADO" in status_val else "❌" if "LOSS" in status_val else "➖" if "VOID" in status_val else "⏳"
            txt += f"{icon} **{i['partido']}**\n"
            txt += f"📅 `{i['fecha']}`\n"
            txt += f"🎯 **Pick:** `{i['pick']}` | 💰 **Stake:** `{i['stake']}`\n"
            if i.get("marcador_real"): txt += f"⚽ **Resultado:** `{i['marcador_real']}`\n"
            txt += f"📈 **Nivel:** {i['nivel']}\n"
            txt += f"{'—'*18}\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: await bot.reply_to(message, "❌ Error al leer datos.")

@bot.message_handler(commands=['validar'])
async def cmd_validar(message):
    msg = await bot.reply_to(message, "🔍 Validando resultados...")
    try:
        historial_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}"
        historial = requests.get(historial_url).json()
        
        data_api = await api_football_call("status=FINISHED")
        actualizados = 0
        if data_api and 'matches' in data_api:
            for item in historial:
                if item.get("status") == "⏳ PENDIENTE":
                    for m in data_api['matches']:
                        h_api, a_api = m['homeTeam']['shortName'].lower(), m['awayTeam']['shortName'].lower()
                        if h_api in item['partido'].lower() and a_api in item['partido'].lower():
                            res = m['score']['winner']
                            item['marcador_real'] = f"{m['score']['fullTime']['home']}-{m['score']['fullTime']['away']}"
                            if item['pick'] == "No Bet": 
                                item['status'] = "➖ VOID"
                            elif (res == 'HOME_TEAM' and h_api in item['pick'].lower()) or (res == 'AWAY_TEAM' and a_api in item['pick'].lower()):
                                item['status'] = "✅ WIN"
                            else: 
                                item['status'] = "❌ LOSS"
                            actualizados += 1
        if actualizados > 0:
            await guardar_en_github(historial_completo=historial)
            await bot.edit_message_text(f"✅ Se validaron {actualizados} picks.", message.chat.id, msg.message_id)
        else: await bot.edit_message_text("ℹ️ Sin picks pendientes terminados.", message.chat.id, msg.message_id)
    except Exception as e: 
        logging.error(f"Error validar: {e}")
        await bot.edit_message_text("❌ Error en validación.", message.chat.id, msg.message_id)

@bot.message_handler(commands=['partidos'])
async def cmd_partidos(message):
    ahora_utc = datetime.now(timezone.utc)
    fecha_inicio = ahora_utc.strftime('%Y-%m-%d')
    fecha_fin = (ahora_utc + timedelta(days=7)).strftime('%Y-%m-%d')
    
    msg_espera = await bot.reply_to(message, f"📡 Consultando calendario (del {fecha_inicio} al {fecha_fin})...")
    data = await api_football_call(f"dateFrom={fecha_inicio}&dateTo={fecha_fin}")
    
    if not data or not data.get('matches'):
        await bot.edit_message_text(f"📅 No hay partidos programados.", message.chat.id, msg_espera.message_id)
        return

    txt = "⚽ **PRÓXIMOS PARTIDOS (LALIGA)**\n"
    txt += f"📅 _Rango: {fecha_inicio} al {fecha_fin}_\n{'—'*20}\n\n"
    
    limite_actual = datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)
    encontrados = 0
    for m in data['matches']:
        dt_partido = datetime.strptime(m['utcDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=OFFSET_JUAREZ)
        if dt_partido >= limite_actual:
            txt += f"🕒 `{dt_partido.strftime('%d/%m %H:%M')}`\n"
            txt += f"**{m['homeTeam']['shortName']} vs {m['awayTeam']['shortName']}**\n"
            txt += f"`/pronostico {m['homeTeam']['shortName']} vs {m['awayTeam']['shortName']}`\n"
            txt += f"{'—'*15}\n"
            encontrados += 1

    if encontrados == 0: txt = "✅ No quedan más partidos para hoy."
    await bot.edit_message_text(txt, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['tabla'])
async def cmd_tabla(message):
    headers = {'X-Auth-Token': FOOTBALL_DATA_KEY}
    url = "https://api.football-data.org/v4/competitions/PD/standings"
    try:
        r = requests.get(url, headers=headers).json()
        txt = "🏆 **POSICIONES LALIGA:**\n"
        for t in r['standings'][0]['table'][:12]:
            txt += f"`{t['position']}.` **{t['team']['shortName']}** ({t['points']} pts)\n"
        await bot.reply_to(message, txt, parse_mode='Markdown')
    except: pass

@bot.message_handler(commands=['equipos'])
async def cmd_equipos(message):
    res = requests.get(URL_JSON).json()
    liga = next(iter(res))
    equipos = ", ".join([f"`{e}`" for e in res[liga]['teams'].keys()])
    await bot.reply_to(message, f"📋 **EQUIPOS VÁLIDOS:**\n{equipos}", parse_mode='Markdown')

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
    txt = ("🤖 **BOT ANALISTA V5.3**\n\n"
           "• `/pronostico L vs V`: Poisson + Dixon-Coles + Deep Analysis.\n"
           "• `/historial`: Picks registrados visuales.\n"
           "• `/validar`: Actualiza resultados reales.\n"
           "• `/config`: Cambia IAs (Samba/Groq).\n"
           "• `/partidos`: Próximos juegos de LaLiga.")
    await bot.reply_to(message, txt, parse_mode='Markdown')

async def main():
    logging.info("Iniciando Bot...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.polling(non_stop=True, timeout=60)
    except Exception as e:
        logging.error(f"Error en main: {e}")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
