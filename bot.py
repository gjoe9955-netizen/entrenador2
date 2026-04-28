import os
import json
import asyncio
import logging
import requests
import base64
import io
import unicodedata
import pandas as pd
from difflib import SequenceMatcher
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

# --- Diccionario de Mapeo ---
MAPEO_EQUIPOS = {
    "Girona FC": "Girona", "Rayo Vallecano de Madrid": "Vallecano",
    "Villarreal CF": "Villarreal", "Real Oviedo": "Oviedo",
    "RCD Mallorca": "Mallorca", "FC Barcelona": "Barcelona",
    "Deportivo Alavés": "Alaves", "Levante UD": "Levante",
    "Valencia CF": "Valencia", "Real Sociedad de Fútbol": "Sociedad",
    "RC Celta de Vigo": "Celta", "Getafe CF": "Getafe",
    "Athletic Club": "Ath Bilbao", "Sevilla FC": "Sevilla",
    "RCD Espanyol de Barcelona": "Espanol", "Club Atlético de Madrid": "Ath Madrid",
    "Elche CF": "Elche", "Real Betis Balompié": "Betis",
    "Real Madrid CF": "Real Madrid", "CA Osasuna": "Osasuna"
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

# --- Utilidades ---
def normalizar(texto):
    if not texto:
        return ""
    texto = texto.lower()
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    for word in ["fc", "rcd", "sd", "cf", "real", "club", "de", "the"]:
        texto = texto.replace(f" {word} ", " ").replace(f"{word} ", "").replace(f" {word}", "")
    return texto.strip()

def calcular_similitud(a, b):
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]:
        return None

    s_key = os.getenv('SAMBA_KEY') or os.getenv('SAMBANOVA_API_KEY')
    g_key = os.getenv('GROQ_API_KEY') or os.getenv('GROQ_KEY')

    api_key = s_key if config["api"] == 'SAMBA' else g_key
    base_url = "https://api.sambanova.ai/v1" if config["api"] == 'SAMBA' else "https://api.groq.com/openai/v1"

    instrucciones = {
        "estratega": (
            "Eres un experto en Value Betting. Analiza Poisson vs Cuota y H2H.\n"
            "FORMATO: • ANÁLISIS, • MERCADO RELEVANTE, • PREDICCIÓN."
        ),
        "auditor": "Eres un Auditor de Riesgos. Valida si el Edge justifica el Stake. Máximo 40 palabras."
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
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"❌ Error en Nodo {config['api']}: {str(e)[:50]}"

# --- Persistencia GitHub ---
async def guardar_en_github(nuevo_registro=None, historial_completo=None):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        r = requests.get(url, headers=headers)
        sha = r.json().get('sha') if r.status_code == 200 else None

        if historial_completo is None:
            historial = json.loads(base64.b64decode(r.json()['content']).decode('utf-8')) if r.status_code == 200 else []
            if nuevo_registro:
                historial = [reg for reg in historial if reg['partido'] != nuevo_registro['partido']]
                historial.append(nuevo_registro)
        else:
            historial = historial_completo

        content = base64.b64encode(json.dumps(historial, indent=4, ensure_ascii=False).encode('utf-8')).decode('utf-8')

        requests.put(
            url,
            headers=headers,
            json={"message": "🤖 Update Historial", "content": content, "sha": sha}
        )

    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- APIs de Datos ---
async def obtener_datos_mercado(equipo_l):
    if not ODDS_API_KEY:
        return 1.85, 3.50, 4.00, False

    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds/"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h',
            'oddsFormat': 'decimal'
        }

        r = await asyncio.to_thread(requests.get, url, params=params, timeout=10)

        if r.status_code == 200:
            data = r.json()
            mejor_match = None
            max_ratio = 0

            for match in data:
                ratio = calcular_similitud(equipo_l, match['home_team'])
                if ratio > max_ratio:
                    max_ratio = ratio
                    mejor_match = match

            if mejor_match and max_ratio > 0.70:
                for bookmaker in mejor_match['bookmakers']:
                    m_data = bookmaker['markets'][0]['outcomes']
                    try:
                        ol = next(o['price'] for o in m_data if o['name'] == mejor_match['home_team'])
                        ov = next(o['price'] for o in m_data if o['name'] == mejor_match['away_team'])
                        oe = next(o['price'] for o in m_data if o['name'] in ['Draw', 'Tie'])
                        return ol, oe, ov, True
                    except:
                        continue

        logging.warning(f"No hallado match para {equipo_l}")

    except Exception as e:
        logging.error(f"Error Odds: {e}")

    return 1.85, 3.50, 4.00, False

async def obtener_h2h_directo(equipo_l, equipo_v):
    URL_CSV = "https://www.football-data.co.uk/mmz4281/2526/SP1.csv"

    try:
        csv_l = MAPEO_EQUIPOS.get(equipo_l, equipo_l)
        csv_v = MAPEO_EQUIPOS.get(equipo_v, equipo_v)

        r = await asyncio.to_thread(requests.get, URL_CSV, timeout=10)
        df = pd.read_csv(io.StringIO(r.text))

        mask = (
            ((df['HomeTeam'] == csv_l) & (df['AwayTeam'] == csv_v)) |
            ((df['HomeTeam'] == csv_v) & (df['AwayTeam'] == csv_l))
        )

        h2h = df[mask]

        if h2h.empty:
            return "Sin H2H.", False

        l, v, e = 0, 0, 0

        for _, row in h2h.iterrows():
            if row['FTR'] == 'H':
                l += 1 if row['HomeTeam'] == csv_l else 0
                v += 1 if row['HomeTeam'] == csv_v else 0
            elif row['FTR'] == 'A':
                v += 1 if row['HomeTeam'] == csv_l else 0
                l += 1 if row['HomeTeam'] == csv_v else 0
            else:
                e += 1

        return f"L {l} | V {v} | E {e}", True

    except:
        return "CSV N/A", False

# --- HELP ---
@bot.message_handler(commands=['help', 'start'])
async def cmd_help(message):
    txt = (
        "🤖 **COMANDOS DISPONIBLES**\n\n"
        "📊 `/pronostico Local vs Visitante`\n"
        "Analiza partido con Poisson + Odds + Kelly.\n\n"
        "💰 `/valor Local vs Visitante`\n"
        "Alias de /pronostico.\n\n"
        "📁 `/historial`\n"
        "Muestra últimos pronósticos guardados.\n\n"
        "⚙️ `/config`\n"
        "Configura IA Estratega y Auditor.\n\n"
        "❓ `/help`\n"
        "Muestra esta ayuda.\n\n"
        "🧪 **Ejemplo:**\n"
        "`/pronostico Real Madrid vs Barcelona`"
    )
    await bot.reply_to(message, txt, parse_mode='Markdown')

# --- Comandos Principales ---
@bot.message_handler(commands=['pronostico', 'valor'])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura con `/config`.")
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2 or " vs " not in parts[1].lower():
        await bot.reply_to(message, "⚠️ `/pronostico Local vs Visitante`.")
        return

    l_q, v_q = [t.strip() for t in parts[1].lower().split(" vs ")]
    msg_espera = await bot.reply_to(message, "📡 Analizando mercado...")

    try:
        res_json = await asyncio.to_thread(requests.get, URL_JSON, timeout=10)
        raw_json = res_json.json()
        liga = next(iter(raw_json))

        m_l = next((t for t in raw_json[liga]['teams'] if l_q in t.lower() or t.lower() in l_q), None)
        m_v = next((t for t in raw_json[liga]['teams'] if v_q in t.lower() or t.lower() in v_q), None)

        if not m_l or not m_v:
            await bot.edit_message_text("❌ Equipos no hallados en el modelo.", message.chat.id, msg_espera.message_id)
            return

        c_l, c_e, c_v, check_odds = await obtener_datos_mercado(m_l)
        h2h_str, check_h2h = await obtener_h2h_directo(m_l, m_v)

        l_s = raw_json[liga]['teams'][m_l]
        v_s = raw_json[liga]['teams'][m_v]
        avg = raw_json[liga]['averages']

        mu_l = l_s['att_h'] * v_s['def_a'] * avg['league_home']
        mu_v = v_s['att_a'] * l_s['def_h'] * avg['league_away']

        ph = sum(
            poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v)
            for x in range(7)
            for y in range(7)
            if x > y
        )

        prob_mercado = 1 / c_l
        prob_final = (ph * 0.70) + (prob_mercado * 0.30)

        edge = prob_final - prob_mercado

        b = c_l - 1
        q = 1 - prob_final
        kelly = ((b * prob_final) - q) / b if b > 0 else 0
        stake = round(max(0, kelly * 0.25) * 100, 2)

        nivel = (
            "DIAMANTE 💎" if edge > 0.05 else
            "ORO 🥇" if edge > 0.02 else
            "PLATA 🥈" if edge > 0 else
            "SIN VALOR ⚠️"
        )

        await guardar_en_github(
            nuevo_registro={
                "fecha": (datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
                "partido": f"{m_l} vs {m_v}",
                "pick": m_l if edge > 0 else "No Bet",
                "poisson": f"{ph*100:.1f}%",
                "cuota": c_l,
                "edge": f"{edge*100:.1f}%",
                "stake": f"{stake}%",
                "nivel": nivel,
                "status": "⏳ PENDIENTE"
            }
        )

        header = f"🛠 REPORTE: {'✅' if check_odds else '❌'} Cuotas | ✅ Poisson | {'✅' if check_h2h else '❌'} H2H\n{'—'*20}\n"

        analisis = await ejecutar_ia(
            "estratega",
            f"Analiza {m_l} vs {m_v}.\n"
            f"Poisson: {ph*100:.1f}%\n"
            f"Prob Final: {prob_final*100:.1f}%\n"
            f"Cuotas: {c_l}, {c_e}, {c_v}\n"
            f"H2H: {h2h_str}\n"
            f"Stake Kelly: {stake}%"
        )

        res_final = f"{header}{analisis}\n\n🛰 **ESTRATEGA:** `{SISTEMA_IA['estratega']['api']}`"

        if SISTEMA_IA["auditor"]["nodo"]:
            auditoria = await ejecutar_ia(
                "auditor",
                f"Edge {edge*100:.1f}% | Stake: {stake}% | Pick: {m_l}"
            )
            res_final += f"\n\n🛡 **AUDITOR:**\n{auditoria}"

        await bot.edit_message_text(
            res_final,
            message.chat.id,
            msg_espera.message_id,
            parse_mode='Markdown'
        )

    except Exception as e:
        await bot.edit_message_text(f"❌ Error Crítico: {e}", message.chat.id, msg_espera.message_id)

@bot.message_handler(commands=['historial'])
async def cmd_historial(message):
    try:
        r = requests.get(f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/{FILE_PATH}").json()

        if not r:
            await bot.reply_to(message, "📭 Historial vacío.")
            return

        txt = "📊 **ÚLTIMOS PRONÓSTICOS**\n\n"

        for i in r[-8:]:
            status = i.get('status', '⏳ PENDIENTE')
            icon = "✅" if "WIN" in status else "❌" if "LOSS" in status else "⏳"

            txt += f"{icon} **{i['partido']}**\n🎯 `{i['pick']}` | 💰 Edge: `{i['edge']}` | Stake: `{i['stake']}`\n{'—'*15}\n"

        await bot.reply_to(message, txt, parse_mode='Markdown')

    except:
        await bot.reply_to(message, "❌ Error al conectar con GitHub.")

@bot.message_handler(commands=['config'])
async def cmd_config(message):
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🧠 CONFIG ESTRATEGA", callback_data="set_rol_estratega")
    )
    await bot.reply_to(message, "🛠 **AJUSTES DE RED IA**", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rol_'))
async def cb_rol(call):
    rol = call.data.split('_')[-1]

    markup = InlineKeyboardMarkup().row(
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"),
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ")
    )

    await bot.edit_message_text(
        f"Selecciona API para {rol.upper()}:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_api_'))
async def cb_api(call):
    _, _, rol, api = call.data.split('_')

    nodos = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]

    markup = InlineKeyboardMarkup()

    for idx, n in enumerate(nodos):
        markup.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{idx}"))

    await bot.edit_message_text(
        f"Selecciona Nodo {api}:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('sv_n_'))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split('_')

    lista = SISTEMA_IA["nodos_samba"] if api == 'SAMBA' else SISTEMA_IA["nodos_groq"]
    SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}

    markup = InlineKeyboardMarkup()

    if rol == "estratega":
        markup.add(InlineKeyboardButton("🛡 AÑADIR AUDITOR", callback_data="set_rol_auditor"))

    markup.add(InlineKeyboardButton("🏁 FINALIZAR", callback_data="config_fin"))

    await bot.edit_message_text(
        f"✅ {rol.upper()} listo.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text(
        "🚀 **MODELO OPERATIVO**",
        call.message.chat.id,
        call.message.message_id
    )

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot encendido...")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
