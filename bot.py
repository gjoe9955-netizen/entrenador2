import os
import asyncio
import logging
import requests
from scipy.stats import poisson
from openai import OpenAI
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# ==================================================
# CONFIGURACIÓN INICIAL & LOGS
# ==================================================
load_dotenv()
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN_TELEGRAM")
FOOTBALL_DATA_KEY = os.getenv("API_KEY_FOOTBALL")
SAMBA_KEY = os.getenv("SAMBA_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

bot = AsyncTeleBot(TOKEN)

# ==================================================
# SISTEMA DE IA - CONFIGURACIÓN COMPLETA
# ==================================================
SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": [
        "DeepSeek-V3.1", "DeepSeek-V3.1-cb", "DeepSeek-V3.2",
        "Llama-4-Maverick-17B-128E-Instruct", "Meta-Llama-3.3-70B-Instruct"
    ],
    "nodos_groq": [
        "llama-3.3-70b-versatile", "groq/compound-mini",
        "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.1-8b-instant"
    ]
}

PROMTS_SISTEMA = {
    "estratega": """Eres un Analista Cuántico de Apuestas. 
    PROCESAMIENTO: Usa obligatoriamente los datos etiquetados: [POISSON], [xG], [CUOTA], [EDGE].
    MATEMÁTICAS: Usa LaTeX para fórmulas de probabilidad. Justifica el Stake según Kelly.
    SALIDA: ANALISIS TÉCNICO | COMPARATIVA xG vs POISSON | DECISIÓN FINAL.
    RESTRICCIÓN: Responde de forma ultra-concreta. Máximo 1000 caracteres.""",
    
    "auditor": """Eres un Gestor de Riesgos. Busca debilidades. 
    Compara el H2H con el Edge calculado. Si los datos son inconsistentes, RECHAZA el pick.
    RESTRICCIÓN: Máximo 500 caracteres."""
}

MAPEO_EQUIPOS = {
    "athletic": 77, Athletic Club, "atleti": 78, Club Atlético de Madrid, "osasuna": 79, "espanyol": 80,
    "barça": 81, "barcelona": 81, "getafe": 82, "real madrid": 86, 
    "rayo vallecano": 87, "levante": 88, "mallorca": 89, "real betis": 90, 
    "real sociedad": 92, "villarreal": 94, "valencia": 95, "alavés": 263, 
    "elche": 285, "girona": 298, "celta": 558, "sevilla": 559, "real oviedo": 1048
}

# ==================================================
# MOTOR DE CÁLCULO ESTADÍSTICO (LOS CABLES)
# ==================================================
def porcentaje(x): return f"{x*100:.2f}%"

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
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            matches = data.get('matches', [])
            if not matches: return None
            nombre = matches[0]['homeTeam']['name'] if matches[0]['homeTeam']['id'] == id_equipo else matches[0]['awayTeam']['name']
            goles = sum([m['score']['fullTime']['home'] if m['homeTeam']['id'] == id_equipo else m['score']['fullTime']['away'] for m in matches])
            xg = round(goles / len(matches), 2)
            w, e, p = 0, 0, 0
            for m in matches:
                win = m['score']['winner']
                if win == 'DRAW': e += 1
                elif (win == 'HOME_TEAM' and m['homeTeam']['id'] == id_equipo) or (win == 'AWAY_TEAM' and m['awayTeam']['id'] == id_equipo): w += 1
                else: p += 1
            return {"nombre": nombre, "xg": xg, "h2h": f"{w}-{e}-{p}"}
        logger.error(f"Error API: {r.status_code}")
    except Exception as e:
        logger.error(f"Excepción API: {e}")
    return None

async def ejecutar_ia(rol, prompt_data):
    cfg = SISTEMA_IA[rol]
    if not cfg["nodo"]: return "IA No configurada."
    api_key = SAMBA_KEY if cfg["api"] == "SAMBA" else GROQ_KEY
    base_url = "https://api.sambanova.ai/v1" if cfg["api"] == "SAMBA" else "https://api.groq.com/openai/v1"
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        r = await asyncio.to_thread(client.chat.completions.create,
            model=cfg["nodo"],
            messages=[{"role": "system", "content": PROMTS_SISTEMA[rol]},
                      {"role": "user", "content": f"DATASET:\n{prompt_data}"}],
            temperature=0.1, max_tokens=800)
        return r.choices[0].message.content
    except Exception as e:
        return f"Error IA: {str(e)[:50]}"

# ==================================================
# MANEJADORES DE COMANDOS
# ==================================================
@bot.message_handler(commands=['start', 'help'])
async def help_cmd(message):
    txt = "🤖 *BOT ANALISTA V5.8.9*\n\n" \
          "📊 `/pronostico ID vs ID` - Analizar partidos.\n" \
          "🏟 `/equipos` - Ver directorio de IDs.\n" \
          "⚙️ `/config` - Configurar Nodos IA."
    await bot.reply_to(message, txt, parse_mode="Markdown")

@bot.message_handler(commands=["equipos"])
async def equipos_cmd(message):
    tabla = "🏟 **DIRECTORIO DE IDs (La Liga)**\n" + "—" * 15 + "\n"
    for n, i in sorted(MAPEO_EQUIPOS.items(), key=lambda x: x[1]):
        tabla += f"`{i}` | {n.capitalize()}\n"
    await bot.reply_to(message, tabla, parse_mode="Markdown")

@bot.message_handler(commands=["pronostico"])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        return await bot.reply_to(message, "🚨 Configura la IA con /config")
    
    try:
        parts = message.text.lower().split()
        id_l, id_v = int(parts[1]), int(parts[3])
    except:
        return await bot.reply_to(message, "Formato: `/pronostico 86 vs 81`", parse_mode="Markdown")

    espera = await bot.reply_to(message, "📡 Consultando datos reales...")
    data_l, data_v = await asyncio.gather(obtener_data_api(id_l), obtener_data_api(id_v))

    if not data_l or not data_v:
        return await bot.edit_message_text("❌ Error API: Datos no disponibles o IDs incorrectos.", message.chat.id, espera.message_id)

    # Lógica de cálculo
    prob_l = calcular_poisson(data_l['xg'], data_v['xg'])
    cuota = 2.05 # Placeholder
    edge = (prob_l * cuota) - 1
    stake = criterio_kelly(prob_l, cuota)

    dataset = f"[POISSON]: {porcentaje(prob_l)}\n[xG]: {data_l['xg']} vs {data_v['xg']}\n[CUOTA]: {cuota}\n[EDGE]: {porcentaje(edge)}\n[H2H]: L:{data_l['h2h']} V:{data_v['h2h']}"
    
    est = await ejecutar_ia("estratega", dataset)
    aud = await ejecutar_ia("auditor", f"Data: {dataset}\nEstratega: {est}")

    res = (f"📊 *{data_l['nombre']} vs {data_v['nombre']}*\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"✅ Odds | ✅ Poisson | ✅ xG\n"
           f"✅ H2H  | ✅ Kelly\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"📈 Edge: `{porcentaje(edge)}` | Stake: `{stake}%` \n\n"
           f"🧠 *ESTRATEGA:*\n{est}\n\n🛡 *AUDITOR:*\n{aud}")
    
    await bot.edit_message_text(res, message.chat.id, espera.message_id, parse_mode="Markdown")

# ==================================================
# INTERFAZ DE CONFIGURACIÓN
# ==================================================
@bot.message_handler(commands=["config"])
async def config_cmd(message):
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Config Estratega", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ Panel de Configuración:", reply_markup=mk)

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

# ==================================================
# INICIO DEL BOT
# ==================================================
async def main():
    logger.info("Bot Analista V5.8.9 Iniciado")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
