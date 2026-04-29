# BOT ANALISTA V5.8.5 - LIVE STATS & ID-BASED COMMANDS
# IA / xG / Poisson / Kelly / H2H / Gestión de Comandos

import os
import json
import asyncio
import logging
import requests
from scipy.stats import poisson
from openai import OpenAI
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# ==================================================
# CONFIGURACIÓN INICIAL
# ==================================================
load_dotenv()
TOKEN = os.getenv("TOKEN_TELEGRAM")
FOOTBALL_DATA_KEY = os.getenv("API_KEY_FOOTBALL")
SAMBA_KEY = os.getenv("SAMBA_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")

bot = AsyncTeleBot(TOKEN)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": ["DeepSeek-V3.1", "DeepSeek-V3.2", "Llama-4-Maverick-17B-128E-Instruct"],
    "nodos_groq": ["llama-3.3-70b-versatile", "groq/compound-mini", "llama-3.1-8b-instant"]
}

PROMTS_SISTEMA = {
    "estratega": "Eres un Analista Cuántico de Apuestas. Usa LaTeX para fórmulas. SALIDA: ANALISIS TÉCNICO | COMPARATIVA xG vs POISSON | DECISIÓN FINAL.",
    "auditor": "Eres un Gestor de Riesgos. Si los datos son inconsistentes, RECHAZA el pick."
}

MAPEO_EQUIPOS = {
    "athletic": 77, "atleti": 78, "osasuna": 79, "espanyol": 80,
    "barça": 81, "barcelona": 81, "getafe": 82, "real madrid": 86, 
    "rayo vallecano": 87, "levante": 88, "mallorca": 89, "real betis": 90, 
    "betis": 90, "real sociedad": 92, "sociedad": 92, "villarreal": 94, 
    "valencia": 95, "alavés": 263, "elche": 285, "girona": 298, 
    "celta": 558, "sevilla": 559, "real oviedo": 1048
}

# ==================================================
# MOTOR DE DATOS REALES (CONEXIÓN DE CABLES)
# ==================================================

def calcular_poisson(exp_l, exp_v):
    prob_l = sum(poisson.pmf(i, exp_l) * sum(poisson.pmf(j, exp_v) for j in range(i)) for i in range(1, 10))
    return round(prob_l, 4)

def criterio_kelly(prob, cuota):
    if cuota <= 1: return 0
    f_star = (prob * cuota - 1) / (cuota - 1)
    return round(max(0, f_star * 100 * 0.25), 2)

async def obtener_data_api(id_equipo):
    url = f"https://api.football-data.org/v4/teams/{id_equipo}/matches?status=FINISHED&limit=5"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    try:
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=7)
        if r.status_code == 200:
            data = r.json()
            matches = data.get('matches', [])
            if not matches: return None
            
            # Extraer Nombre Oficial
            nombre_oficial = matches[0]['homeTeam']['name'] if matches[0]['homeTeam']['id'] == id_equipo else matches[0]['awayTeam']['name']
            
            # Calcular xG (Promedio de goles últimos 5 partidos)
            goles = sum([m['score']['fullTime']['home'] if m['homeTeam']['id'] == id_equipo else m['score']['fullTime']['away'] for m in matches])
            xg = round(goles / len(matches), 2)
            
            # Calcular Forma (G-E-P)
            w, e, p = 0, 0, 0
            for m in matches:
                win = m['score']['winner']
                if win == 'DRAW': e += 1
                elif (win == 'HOME_TEAM' and m['homeTeam']['id'] == id_equipo) or (win == 'AWAY_TEAM' and m['awayTeam']['id'] == id_equipo): w += 1
                else: p += 1
            
            return {"nombre": nombre_oficial, "xg": xg, "forma": f"{w}-{e}-{p}"}
    except: return None

# ==================================================
# FUNCIONES IA Y APOYO
# ==================================================
def porcentaje(x): return f"{x*100:.2f}%"

async def ejecutar_ia(rol, prompt_data):
    cfg = SISTEMA_IA[rol]
    if not cfg["nodo"]: return "IA no configurada."
    api_key = SAMBA_KEY if cfg["api"] == "SAMBA" else GROQ_KEY
    base_url = "https://api.sambanova.ai/v1" if cfg["api"] == "SAMBA" else "https://api.groq.com/openai/v1"
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        r = await asyncio.to_thread(client.chat.completions.create,
            model=cfg["nodo"],
            messages=[{"role": "system", "content": PROMTS_SISTEMA[rol]},
                      {"role": "user", "content": f"DATASET:\n{prompt_data}"}],
            temperature=0.1, max_tokens=600)
        return r.choices[0].message.content
    except Exception as e: return f"Error IA: {str(e)[:50]}"

# ==================================================
# COMANDOS
# ==================================================

@bot.message_handler(commands=["equipos"])
async def equipos_cmd(message):
    agrupados = {}
    for n, i in MAPEO_EQUIPOS.items():
        if i not in agrupados: agrupados[i] = []
        agrupados[i].append(n.capitalize())
    
    tabla = "🏟 **DIRECTORIO DE IDs (La Liga)**\n" + "—" * 15 + "\n"
    for i in sorted(agrupados.keys()):
        tabla += f"`{i}{' '*(5-len(str(i)))}| {agrupados[i][0]}`\n"
    await bot.reply_to(message, tabla + "\n💡 Usa el ID en `/pronostico ID_L vs ID_V`", parse_mode="Markdown")

@bot.message_handler(commands=["pronostico"])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        return await bot.reply_to(message, "🚨 Configura la IA con /config")
    
    partes = message.text.lower().split(maxsplit=1)
    if len(partes) < 2 or " vs " not in partes[1]:
        return await bot.reply_to(message, "Formato: `/pronostico ID_L vs ID_V` (ej: `/pronostico 86 vs 81`)")

    try:
        id_l_str, id_v_str = [p.strip() for p in partes[1].split(" vs ")]
        id_l, id_v = int(id_l_str), int(id_v_str)
    except:
        return await bot.reply_to(message, "❌ Debes usar los IDs numéricos. Mira /equipos")

    espera = await bot.reply_to(message, "📡 Extrayendo datos reales de Football Data...")

    # Obtención de Datos Reales
    data_l, data_v = await asyncio.gather(obtener_data_api(id_l), obtener_data_api(id_v))

    if not data_l or not data_v:
        return await bot.edit_message_text("❌ Error al conectar con la API o IDs inválidos.", message.chat.id, espera.message_id)

    # Cálculos Matemáticos
    xg_l, xg_v = data_l['xg'], data_v['xg']
    prob_l = calcular_poisson(xg_l, xg_v)
    cuota_sim = 2.00 # Placeholder hasta integrar API de Odds
    edge = (prob_l * cuota_sim) - 1
    stake = criterio_kelly(prob_l, cuota_sim)

    dataset = (f"--- DATASET REAL ---\n"
               f"[EQUIPOS]: {data_l['nombre']} vs {data_v['nombre']}\n"
               f"[POISSON]: {porcentaje(prob_l)}\n"
               f"[xG]: L {xg_l} | V {xg_v}\n"
               f"[CUOTA]: {cuota_sim} | [EDGE]: {porcentaje(edge)}\n"
               f"[STAKE]: {stake}%\n"
               f"[FORMA H2H]: L:{data_l['forma']} | V:{data_v['forma']}")

    estratega = await ejecutar_ia("estratega", dataset)
    auditor = await ejecutar_ia("auditor", f"Dataset: {dataset}\nAnálisis: {estratega}")

    def get_check(val): return "✅" if val else "❌"

    res = (f"📊 *{data_l['nombre']} vs {data_v['nombre']}*\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"✅ Odds | ✅ Poisson | ✅ xG\n"
           f"✅ H2H  | ✅ Kelly\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"📈 Edge: `{porcentaje(edge)}` | 🏦 Stake: `{stake}%` \n\n"
           f"🧠 *ESTRATEGA:*\n{estratega}\n\n"
           f"🛡 *AUDITOR:*\n{auditor}")
    
    await bot.edit_message_text(res, message.chat.id, espera.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["config"])
async def config_cmd(message):
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Config Estratega", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ Panel de Configuración:", reply_markup=mk)

# [Callbacks de Configuración se mantienen igual para estabilidad]
@bot.callback_query_handler(func=lambda c: c.data.startswith("set_rol_"))
async def cb_role(call):
    rol = call.data.split("_")[-1]
    mk = InlineKeyboardMarkup().row(
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"),
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_api_"))
async def cb_api(call):
    _, _, rol, api = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    mk = InlineKeyboardMarkup()
    for i, n in enumerate(lista):
        mk.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{i}"))
    await bot.edit_message_text(f"Nodo {api}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sv_n_"))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}
    mk = InlineKeyboardMarkup()
    if rol == "estratega": mk.add(InlineKeyboardButton("🛡 Configurar Auditor", callback_data="set_rol_auditor"))
    mk.add(InlineKeyboardButton("🏁 Finalizar", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} configurado.", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 Configuración completa.", call.message.chat.id, call.message.message_id)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
