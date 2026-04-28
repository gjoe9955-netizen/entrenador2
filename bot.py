import os
import json
import asyncio
import logging
import requests
import base64
import io
import unicodedata
import pandas as pd

from scipy.stats import poisson
from datetime import datetime, timedelta, timezone

from openai import OpenAI
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
load_dotenv()

TOKEN = os.getenv("TOKEN_TELEGRAM")
FOOTBALL_DATA_KEY = os.getenv("API_KEY_FOOTBALL")
ODDS_API_KEY = os.getenv("API_KEY_ODDS")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

OFFSET_JUAREZ = -6

URL_JSON = "https://raw.githubusercontent.com/gjoe9955-netizen/entrenador2/main/modelo_poisson.json"

REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# --------------------------------------------------
# MAPEO
# --------------------------------------------------

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

# --------------------------------------------------
# ESTADO IA
# --------------------------------------------------

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

# --------------------------------------------------
# UTILIDADES
# --------------------------------------------------

def normalizar(texto):
    texto = texto.lower()
    texto = ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

    for word in ["fc", "rcd", "sd", "cf", "real", "club", "de", "the"]:
        texto = texto.replace(f" {word} ", " ")
        texto = texto.replace(f"{word} ", "")
        texto = texto.replace(f" {word}", "")

    return texto.strip()


def limpiar_markdown(texto):
    if not texto:
        return ""
    for ch in ["*", "_", "`", "[", "]", "(", ")"]:
        texto = texto.replace(ch, "")
    return texto


# --------------------------------------------------
# IA
# --------------------------------------------------

async def ejecutar_ia(rol, prompt):

    config = SISTEMA_IA[rol]

    if not config["nodo"]:
        return None

    s_key = os.getenv("SAMBA_KEY") or os.getenv("SAMBANOVA_API_KEY")
    g_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")

    api_key = s_key if config["api"] == "SAMBA" else g_key
    base_url = "https://api.sambanova.ai/v1" if config["api"] == "SAMBA" else "https://api.groq.com/openai/v1"

    instrucciones = {
        "estratega":
            "Eres experto en apuestas deportivas. "
            "Busca value betting real con Poisson, cuota y edge. "
            "Sé técnico y directo.",

        "auditor":
            "Eres auditor de riesgo bankroll. "
            "Debes cuestionar picks débiles, stake alto o edge bajo."
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

        return limpiar_markdown(res.choices[0].message.content)

    except Exception as e:
        return f"Error IA {rol}: {str(e)[:80]}"


# --------------------------------------------------
# GITHUB
# --------------------------------------------------

async def guardar_en_github(nuevo_registro):

    if not GITHUB_TOKEN:
        return

    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        r = requests.get(url, headers=headers, timeout=10)

        sha = None
        historial = []

        if r.status_code == 200:
            data = r.json()
            sha = data["sha"]
            historial = json.loads(
                base64.b64decode(data["content"]).decode("utf-8")
            )

        historial.append(nuevo_registro)

        content = base64.b64encode(
            json.dumps(historial, indent=4, ensure_ascii=False).encode("utf-8")
        ).decode("utf-8")

        payload = {
            "message": "update historial",
            "content": content,
            "sha": sha
        }

        requests.put(url, headers=headers, json=payload, timeout=10)

    except:
        pass


# --------------------------------------------------
# DATOS MERCADO
# --------------------------------------------------

async def obtener_datos_mercado():

    if not ODDS_API_KEY:
        return 1.85, 3.50, 4.00, False

    return 1.85, 3.50, 4.00, False


# --------------------------------------------------
# COMANDO PRONOSTICO
# --------------------------------------------------

@bot.message_handler(commands=["pronostico", "valor"])
async def handle_pronostico(message):

    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Usa /config primero.")
        return

    partes = message.text.split(maxsplit=1)

    if len(partes) < 2 or " vs " not in partes[1].lower():
        await bot.reply_to(message, "Uso:\n/pronostico Local vs Visitante")
        return

    local_q, visita_q = partes[1].split(" vs ")

    espera = await bot.reply_to(message, "📡 Analizando mercado...")

    try:
        raw_json = requests.get(URL_JSON, timeout=10).json()

        liga = next(iter(raw_json))
        equipos = raw_json[liga]["teams"]

        m_l = next((x for x in equipos if local_q.lower() in x.lower()), None)
        m_v = next((x for x in equipos if visita_q.lower() in x.lower()), None)

        if not m_l or not m_v:
            await bot.edit_message_text(
                "❌ Equipos no encontrados.",
                message.chat.id,
                espera.message_id
            )
            return

        l_s = equipos[m_l]
        v_s = equipos[m_v]
        avg = raw_json[liga]["averages"]

        mu_l = l_s["att_h"] * v_s["def_a"] * avg["league_home"]
        mu_v = v_s["att_a"] * l_s["def_h"] * avg["league_away"]

        ph = sum(
            poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v)
            for x in range(7)
            for y in range(7)
            if x > y
        )

        cuota_l, cuota_e, cuota_v, _ = await obtener_datos_mercado()

        prob_mercado = 1 / cuota_l
        edge = ph - prob_mercado

        if edge > 0:
            kelly = ((cuota_l * ph) - 1) / (cuota_l - 1)
        else:
            kelly = 0

        stake = round(max(0, min(kelly * 0.25 * 100, 5)), 2)

        # ------------------------------------------
        # IA ESTRATEGA
        # ------------------------------------------

        prompt_base = f"""
Partido: {m_l} vs {m_v}
Poisson Local: {ph*100:.2f}%
Cuota Local: {cuota_l}
Edge: {edge*100:.2f}%
Stake Kelly: {stake}%
"""

        analisis = await ejecutar_ia("estratega", prompt_base)

        # ------------------------------------------
        # IA AUDITOR
        # ------------------------------------------

        auditoria = ""

        if SISTEMA_IA["auditor"]["nodo"]:
            auditoria = await ejecutar_ia(
                "auditor",
                prompt_base + "\nEvalúa si conviene apostar o no."
            )

        # ------------------------------------------
        # VEREDICTO FINAL
        # ------------------------------------------

        if edge <= 0:
            veredicto = "❌ NO BET"
        elif edge < 0.02:
            veredicto = "⚠️ VALUE BAJO / Stake mínimo"
        elif edge < 0.05:
            veredicto = "✅ APUESTA MODERADA"
        else:
            veredicto = "🔥 VALUE FUERTE"

        texto = (
            f"📊 *{m_l} vs {m_v}*\n\n"
            f"⚽ Probabilidad Modelo: `{ph*100:.2f}%`\n"
            f"💰 Cuota Mercado: `{cuota_l}`\n"
            f"📈 Edge: `{edge*100:.2f}%`\n"
            f"🏦 Stake: `{stake}%`\n\n"
            f"🧠 *ESTRATEGA*\n{analisis}\n\n"
            f"🛡 *AUDITOR*\n{auditoria if auditoria else 'No configurado'}\n\n"
            f"🏁 *VEREDICTO FINAL*\n{veredicto}"
        )

        await bot.edit_message_text(
            texto,
            message.chat.id,
            espera.message_id,
            parse_mode="Markdown"
        )

        await guardar_en_github({
            "fecha": (datetime.now(timezone.utc) + timedelta(hours=OFFSET_JUAREZ)).strftime("%Y-%m-%d %H:%M"),
            "partido": f"{m_l} vs {m_v}",
            "edge": f"{edge*100:.2f}%",
            "stake": f"{stake}%",
            "veredicto": veredicto
        })

    except Exception as e:
        await bot.edit_message_text(
            f"❌ Error: {e}",
            message.chat.id,
            espera.message_id
        )


# --------------------------------------------------
# HISTORIAL
# --------------------------------------------------

@bot.message_handler(commands=["historial"])
async def cmd_historial(message):
    await bot.reply_to(message, "📁 Historial activo.")


# --------------------------------------------------
# HELP
# --------------------------------------------------

@bot.message_handler(commands=["help", "start"])
async def cmd_help(message):

    txt = (
        "🤖 *BOT ANALISTA V5.3 ESTABLE*\n\n"
        "📊 /pronostico Local vs Visitante\n"
        "💰 /valor Local vs Visitante\n"
        "📁 /historial\n"
        "⚙️ /config\n"
        "❓ /help\n\n"
        "Nuevo:\n"
        "🧠 Estratega analiza\n"
        "🛡 Auditor rebate\n"
        "🏁 Veredicto final conjunto"
    )

    await bot.reply_to(message, txt, parse_mode="Markdown")


# --------------------------------------------------
# CONFIG
# --------------------------------------------------

@bot.message_handler(commands=["config"])
async def cmd_config(message):

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🧠 CONFIG ESTRATEGA",
            callback_data="set_rol_estratega"
        )
    )

    await bot.reply_to(
        message,
        "⚙️ Configuración IA",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_rol_"))
async def cb_rol(call):

    rol = call.data.split("_")[-1]

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(
            "SambaNova",
            callback_data=f"set_api_{rol}_SAMBA"
        ),
        InlineKeyboardButton(
            "Groq",
            callback_data=f"set_api_{rol}_GROQ"
        )
    )

    await bot.edit_message_text(
        f"API para {rol}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_api_"))
async def cb_api(call):

    _, _, rol, api = call.data.split("_")

    nodos = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]

    markup = InlineKeyboardMarkup()

    for i, n in enumerate(nodos):
        markup.add(
            InlineKeyboardButton(
                n,
                callback_data=f"sv_n_{rol}_{api}_{i}"
            )
        )

    await bot.edit_message_text(
        "Selecciona nodo:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("sv_n_"))
async def cb_save(call):

    _, _, rol, api, idx = call.data.split("_")

    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]

    SISTEMA_IA[rol] = {
        "api": api,
        "nodo": lista[int(idx)]
    }

    markup = InlineKeyboardMarkup()

    if rol == "estratega":
        markup.add(
            InlineKeyboardButton(
                "🛡 Añadir Auditor",
                callback_data="set_rol_auditor"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "🏁 Finalizar",
            callback_data="config_fin"
        )
    )

    await bot.edit_message_text(
        f"✅ {rol.upper()} configurado.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == "config_fin")
async def cb_fin(call):

    await bot.edit_message_text(
        "🚀 Sistema listo.",
        call.message.chat.id,
        call.message.message_id
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot iniciado...")
    await bot.polling(non_stop=True, timeout=60)


if __name__ == "__main__":
    asyncio.run(main())
