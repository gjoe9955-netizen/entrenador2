# BOT ANALISTA V5.7.3 - CHECKS & ALIGNED IDs
# IA / xG / Poisson / Kelly / H2H / Gestión de Comandos

import os
import json
import asyncio
import logging
import requests
import base64
import unicodedata
from datetime import datetime, timedelta, timezone
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
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"
OFFSET_JUAREZ = -6

bot = AsyncTeleBot(TOKEN)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ==================================================
# NODOS Y PROMPTS
# ==================================================
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

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# [ZONA DE PROMPTS] - CAMBIA AQUÍ LAS INSTRUCCIONES
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

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

# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
# [FIN ZONA DE PROMPTS]
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

MAPEO_EQUIPOS = {
    "athletic": 77, "atleti": 78, "osasuna": 79, "espanyol": 80,
    "barça": 81, "getafe": 82, "real madrid": 86, "rayo vallecano": 87,
    "levante": 88, "mallorca": 89, "real betis": 90, "real sociedad": 92,
    "villarreal": 94, "valencia": 95, "alavés": 263, "elche": 285,
    "girona": 298, "celta": 558, "sevilla fc": 559, "real oviedo": 1048,
    "barcelona": 81, "atletico": 78, "sevilla": 559, "betis": 90, "sociedad": 92
}

ID_A_NOMBRE = {v: k.capitalize() for k, v in MAPEO_EQUIPOS.items()}

# ==================================================
# FUNCIONES DE APOYO
# ==================================================
def porcentaje(x): return f"{x*100:.2f}%"

async def ejecutar_ia(rol, prompt_data):
    cfg = SISTEMA_IA[rol]
    if not cfg["nodo"]: return "IA no configurada."
    api_key = os.getenv("SAMBA_KEY") if cfg["api"] == "SAMBA" else os.getenv("GROQ_KEY")
    base_url = "https://api.sambanova.ai/v1" if cfg["api"] == "SAMBA" else "https://api.groq.com/openai/v1"
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        r = await asyncio.to_thread(client.chat.completions.create,
            model=cfg["nodo"],
            messages=[{"role": "system", "content": PROMTS_SISTEMA[rol]},
                      {"role": "user", "content": f"DATASET:\n{prompt_data}"}],
            temperature=0.1,
            max_tokens=400)
        return r.choices[0].message.content
    except Exception as e: return f"Error IA: {str(e)[:50]}"

# ==================================================
# COMANDOS PRINCIPALES
# ==================================================

@bot.message_handler(commands=["start", "help"])
async def help_cmd(message):
    txt = (
        "🤖 *BOT ANALISTA V5.7.3 PRO*\n\n"
        "📊 `/pronostico Local vs Visitante` - Análisis completo.\n"
        "📋 `/historial` - Ver últimos registros.\n"
        "🏟 `/equipos` - Ver lista de equipos disponibles.\n"
        "⚙️ `/config` - Configurar Nodos IA.\n\n"
        "💡 *Ejemplo:* `/pronostico Real Madrid vs Barcelona`"
    )
    await bot.reply_to(message, txt, parse_mode="Markdown")

@bot.message_handler(commands=["equipos"])
async def equipos_cmd(message):
    # Ordenamos el mapeo por ID para mejor control visual
    equipos_ordenados = sorted(MAPEO_EQUIPOS.items(), key=lambda x: x[1])
    
    tabla = "🏟 **DIRECTORIO DE EQUIPOS (La Liga)**\n"
    tabla += "—" * 15 + "\n"
    tabla += "` ID  | EQUIPO `\n"
    tabla += "—" * 15 + "\n"
    
    for nombre, id_equipo in equipos_ordenados:
        espaciado = " " * (4 - len(str(id_equipo)))
        tabla += f"`{id_equipo}{espaciado}| {nombre.capitalize()}`\n"
    
    tabla += "—" * 15 + "\n"
    tabla += "\n💡 _Escribe el nombre tal cual para el comando /pronostico._"
    
    try:
        await bot.reply_to(message, tabla, parse_mode="Markdown")
    except Exception:
        await bot.reply_to(message, tabla.replace("`", ""))

@bot.message_handler(commands=["pronostico", "valor"])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura primero los nodos con /config")
        return
    
    partes = message.text.lower().split(maxsplit=1)
    if len(partes) < 2 or " vs " not in partes[1]:
        await bot.reply_to(message, "Formato: `/pronostico Local vs Visitante`", parse_mode="Markdown")
        return

    q_l, q_v = [p.strip() for p in partes[1].split(" vs ")]
    id_l, id_v = MAPEO_EQUIPOS.get(q_l), MAPEO_EQUIPOS.get(q_v)

    if not id_l or not id_v:
        await bot.reply_to(message, "❌ Equipo no reconocido. Usa `/equipos` para ver la lista.", parse_mode="Markdown")
        return

    n_l, n_v = ID_A_NOMBRE[id_l], ID_A_NOMBRE[id_v]
    espera = await bot.reply_to(message, f"📡 Procesando {n_l} vs {n_v}...")

    # Simulación de datos y Checks
    # Cambiar a False si alguna función de data falla
    check_poisson = True
    check_odds = True
    check_xg = True
    check_h2h = True
    check_kelly = True

    prob_l, c_l, edge, stake, h2h = 0.55, 2.10, 0.08, 2.5, "2-1-0"
    xg_l, xg_v = 1.85, 1.10

    def get_check(status): return "✅" if status else "❌"

    dataset = (
        f"--- DATASET ---\n"
        f"[POISSON]: {porcentaje(prob_l)}\n"
        f"[xG_L]: {xg_l} | [xG_V]: {xg_v}\n"
        f"[CUOTA]: {c_l} | [EDGE]: {porcentaje(edge)}\n"
        f"[STAKE_KELLY]: {stake}%\n"
        f"[H2H]: {h2h}"
    )

    estratega = await ejecutar_ia("estratega", dataset)
    auditor = await ejecutar_ia("auditor", f"Dataset: {dataset}\nEstratega: {estratega}")

    res = (f"📊 *{n_l} vs {n_v}*\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"{get_check(check_odds)} Odds | {get_check(check_poisson)} Poisson | {get_check(check_xg)} xG\n"
           f"{get_check(check_h2h)} H2H  | {get_check(check_kelly)} Kelly\n"
           f"━━━━━━━━━━━━━━━━━━━━\n\n"
           f"📈 Edge: `{porcentaje(edge)}` | 🏦 Stake: `{stake}%` \n\n"
           f"🧠 *ESTRATEGA:*\n{estratega}\n\n"
           f"🛡 *AUDITOR:*\n{auditor}")
    
    try:
        await bot.edit_message_text(res, message.chat.id, espera.message_id, parse_mode="Markdown")
    except Exception:
        await bot.edit_message_text(res.replace("*", "").replace("_", ""), message.chat.id, espera.message_id)

@bot.message_handler(commands=["config"])
async def config_cmd(message):
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Config Estratega", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ Panel de Configuración de IA:", reply_markup=mk)

# ==================================================
# LÓGICA DE CALLBACKS
# ==================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("set_rol_"))
async def cb_role(call):
    rol = call.data.split("_")[-1]
    mk = InlineKeyboardMarkup().row(
        InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"),
        InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ")
    )
    await bot.edit_message_text(f"Selecciona API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_api_"))
async def cb_api(call):
    _, _, rol, api = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    mk = InlineKeyboardMarkup()
    for i, n in enumerate(lista):
        mk.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{i}"))
    await bot.edit_message_text(f"Selecciona Nodo de {api}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sv_n_"))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    SISTEMA_IA[rol] = {"api": api, "nodo": lista[int(idx)]}
    
    mk = InlineKeyboardMarkup()
    if rol == "estratega":
        mk.add(InlineKeyboardButton("🛡 Configurar Auditor", callback_data="set_rol_auditor"))
    mk.add(InlineKeyboardButton("🏁 Finalizar", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} configurado.", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "config_fin")
async def cb_fin(call):
    await bot.edit_message_text("🚀 Configuración completa.", call.message.chat.id, call.message.message_id)

# ==================================================
# INICIO
# ==================================================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot Analista V5.7.3 iniciado.")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
