# BOT ANALISTA V5.6 FOOTBALL PRO FULL - OPTIMIZED
# IA Profesional / xG Engine / LaTeX / Kelly Fraccional / H2H Strict

import os
import json
import asyncio
import logging
import requests
import base64
import unicodedata
import pandas as pd
import numpy as np

from scipy.stats import poisson
from datetime import datetime, timedelta, timezone

from openai import OpenAI
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# ==================================================
# CONFIG
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

load_dotenv()

TOKEN = os.getenv("TOKEN_TELEGRAM")
FOOTBALL_DATA_KEY = os.getenv("API_KEY_FOOTBALL")
ODDS_API_KEY = os.getenv("API_KEY_ODDS")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

OFFSET_JUAREZ = -6

REPO_OWNER = "gjoe9955-netizen"
REPO_NAME = "entrenador2"
FILE_PATH = "historial.json"

bot = AsyncTeleBot(TOKEN)

# ==================================================
# MAPEO EQUIPOS (Sincronizado con ID de API La Liga)
# ==================================================

MAPEO_EQUIPOS = {
    "athletic": 77, "atleti": 78, "osasuna": 79, "espanyol": 80,
    "barça": 81, "getafe": 82, "real madrid": 86, "rayo vallecano": 87,
    "levante": 88, "mallorca": 89, "real betis": 90, "real sociedad": 92,
    "villarreal": 94, "valencia": 95, "alavés": 263, "elche": 285,
    "girona": 298, "celta": 558, "sevilla fc": 559, "real oviedo": 1048,
    "girona fc": 298, "rcd mallorca": 89, "rcd espanyol": 80, "sevilla": 559,
    "celta de vigo": 558, "fc barcelona": 81, "barca": 81, "madrid": 86,
    "atletico de madrid": 78, "betis": 90, "real vigo": 558, "vallecano": 87,
    "bilbao": 77, "atletico": 78, "atletico madrid": 78, "barcelona": 81,
    "sociedad": 92, "rayo": 87, "alaves": 263, "oviedo": 1048, "espanol": 80
}

ID_A_NOMBRE = {
    77: "Athletic", 78: "Atleti", 79: "Osasuna", 80: "Espanyol", 81: "Barça",
    82: "Getafe", 86: "Real Madrid", 87: "Rayo Vallecano", 88: "Levante",
    89: "Mallorca", 90: "Real Betis", 92: "Real Sociedad", 94: "Villarreal",
    95: "Valencia", 263: "Alavés", 285: "Elche", 298: "Girona",
    558: "Celta", 559: "Sevilla FC", 1048: "Real Oviedo"
}

# ==================================================
# IA CONFIG (PROMPTS ENRIQUECIDOS)
# ==================================================

SISTEMA_IA = {
    "estratega": {"api": None, "nodo": None},
    "auditor": {"api": None, "nodo": None},
    "nodos_samba": ["DeepSeek-V3.1", "DeepSeek-V3.2", "Meta-Llama-3.3-70B-Instruct"],
    "nodos_groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
}

PROMTS_SISTEMA = {
    "estratega": """Eres un Analista de Value Betting Senior. Tu objetivo es cruzar Poisson y xG (Expected Goals) para hallar valor real.
    REGLAS:
    1. Usa LaTeX para las fórmulas (ej: $Edge = P_{poisson} - P_{imp}$).
    2. Analiza si el xG (peligro generado) respalda el Poisson (goles marcados).
    3. Evalúa el Edge y justifica el Stake según Kelly.
    4. Prohibido alucinar resultados que no estén en los datos proporcionados.
    Formato: ANALISIS TÉCNICO | MERCADO & xG | DECISIÓN FINAL""",
    
    "auditor": """Eres un Gestor de Riesgos (Abogado del Diablo). 
    Busca debilidades en el pick. Compara el H2H con la estadística actual. 
    Usa LaTeX para explicar la varianza. Aprueba o Rechaza el pick basándote en la seguridad del bankroll."""
}

# ==================================================
# UTILIDADES
# ==================================================

def porcentaje(x): return f"{x*100:.2f}%"

def limpiar_markdown(texto):
    if not texto: return ""
    for c in ["*", "_", "`", "[", "]", "(", ")"]:
        texto = texto.replace(c, "")
    return texto

# ==================================================
# MOTOR ESTADÍSTICO (POISSON + xG)
# ==================================================

async def obtener_datos_football_data(id_l, id_v):
    datos_locales = None
    if os.path.exists("liga_data.json"):
        try:
            with open("liga_data.json", "r", encoding="utf-8") as f:
                datos_locales = json.load(f)
        except Exception as e: logging.error(f"Error JSON local: {e}")

    if datos_locales:
        try:
            stats = {"l": {"att": 1.2, "def": 1.0, "xg": 0.0}, "v": {"att": 1.0, "def": 1.2, "xg": 0.0}}
            found_l, found_v = False, False
            for team in datos_locales.get("standings", []):
                t_id = team["team"]["id"]
                if t_id == id_l:
                    stats["l"]["att"] = team["goalsFor"] / team["playedGames"]
                    stats["l"]["def"] = team["goalsAgainst"] / team["playedGames"]
                    stats["l"]["xg"] = stats["l"]["att"] * 0.98 # Factor xG corregido
                    found_l = True
                if t_id == id_v:
                    stats["v"]["att"] = team["goalsFor"] / team["playedGames"]
                    stats["v"]["def"] = team["goalsAgainst"] / team["playedGames"]
                    stats["v"]["xg"] = stats["v"]["att"] * 0.98
                    found_v = True
            if found_l and found_v:
                gl, gv, emp = 0, 0, 0
                for m in datos_locales.get("matches", []):
                    if m["status"] == "FINISHED":
                        mid_h, mid_a = m["homeTeam"]["id"], m["awayTeam"]["id"]
                        if (mid_h == id_l and mid_a == id_v) or (mid_h == id_v and mid_a == id_l):
                            w = m["score"]["winner"]
                            if w == "DRAW": emp += 1
                            elif (w == "HOME_TEAM" and mid_h == id_l) or (w == "AWAY_TEAM" and mid_a == id_l): gl += 1
                            else: gv += 1
                return f"{gl}-{emp}-{gv}", stats["l"]["att"], stats["l"]["def"], stats["v"]["att"], stats["v"]["def"], stats["l"]["xg"], stats["v"]["xg"], True
        except: pass
    return "0-0-0", 1.2, 1.0, 1.0, 1.2, 1.1, 0.9, False

# ==================================================
# IA ENGINE
# ==================================================

async def ejecutar_ia(rol, prompt_data):
    cfg = SISTEMA_IA[rol]
    if not cfg["nodo"]: return "IA no configurada"
    api_key = os.getenv("SAMBA_KEY") if cfg["api"] == "SAMBA" else os.getenv("GROQ_KEY")
    base_url = "https://api.sambanova.ai/v1" if cfg["api"] == "SAMBA" else "https://api.groq.com/openai/v1"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        r = await asyncio.to_thread(
            client.chat.completions.create,
            model=cfg["nodo"],
            messages=[
                {"role": "system", "content": PROMTS_SISTEMA[rol]},
                {"role": "user", "content": f"DATOS REALES DEL PARTIDO:\n{prompt_data}"}
            ],
            temperature=0.1
        )
        return r.choices[0].message.content
    except Exception as e: return f"Error IA: {str(e)[:60]}"

# ==================================================
# GITHUB DATA
# ==================================================

async def guardar_en_github(registro):
    if not GITHUB_TOKEN: return
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        historial, sha = [], None
        if r.status_code == 200:
            data = r.json()
            sha = data["sha"]
            historial = json.loads(base64.b64decode(data["content"]).decode())
        historial.append(registro)
        payload = {"message": "log", "content": base64.b64encode(json.dumps(historial).encode()).decode(), "sha": sha}
        requests.put(url, headers=headers, json=payload, timeout=10)
    except: pass

async def obtener_historial_github():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200: return json.loads(base64.b64decode(r.json()["content"]).decode())
    except: pass
    return []

async def obtener_datos_mercado(): return 1.85, 3.50, 4.00, True

# ==================================================
# COMANDO PRONÓSTICO
# ==================================================

@bot.message_handler(commands=["pronostico", "valor"])
async def handle_pronostico(message):
    if not SISTEMA_IA["estratega"]["nodo"]:
        await bot.reply_to(message, "🚨 Configura la IA con /config")
        return
    partes = message.text.lower().split(maxsplit=1)
    if len(partes) < 2 or " vs " not in partes[1]:
        await bot.reply_to(message, "Uso: /pronostico Local vs Visitante")
        return

    q_l, q_v = [p.strip() for p in partes[1].split(" vs ")]
    id_l, id_v = MAPEO_EQUIPOS.get(q_l), MAPEO_EQUIPOS.get(q_v)

    if not id_l or not id_v:
        await bot.reply_to(message, "❌ Equipos no reconocidos.")
        return

    n_l, n_v = ID_A_NOMBRE[id_l], ID_A_NOMBRE[id_v]
    espera = await bot.reply_to(message, f"📡 Analizando {n_l} vs {n_v}...")

    try:
        h2h, att_l, def_l, att_v, def_v, xg_l, xg_v, ok_api = await obtener_datos_football_data(id_l, id_v)
        mu_l, mu_v = att_l * def_v, att_v * def_l
        prob_l = sum(poisson.pmf(x, mu_l) * poisson.pmf(y, mu_v) for x in range(7) for y in range(7) if x > y)
        
        c_l, c_e, c_v, ok_odds = await obtener_datos_mercado()
        p_imp = 1 / c_l
        edge = prob_l - p_imp
        
        kelly = ((c_l * prob_l) - 1) / (c_l - 1) if edge > 0 else 0
        stake = round(max(0, min(kelly * 0.25 * 100, 5)), 2)

        data_ia = (f"Partido: {n_l} vs {n_v}\nPoisson Prob: {porcentaje(prob_l)}\nxG Estimado: {xg_l:.2f} vs {xg_v:.2f}\n"
                   f"Cuota: {c_l} | Edge: {porcentaje(edge)}\nKelly Sugerido: {stake}%\nH2H: {h2h}")

        estratega = await ejecutar_ia("estratega", data_ia)
        auditor = await ejecutar_ia("auditor", f"Análisis Estratega: {estratega}\n{data_ia}") if SISTEMA_IA["auditor"]["nodo"] else "No configurado"

        verdict = "🔥 VALUE FUERTE" if edge > 0.05 else "✅ APUESTA MODERADA" if edge > 0 else "❌ NO BET"
        
        texto = (f"📊 *{n_l} vs {n_v}*\n\n⚽ Prob: `{porcentaje(prob_l)}` | 🥅 xG: `{xg_l:.2f}`\n"
                 f"💰 Cuota: `{c_l}` | 📈 Edge: `{porcentaje(edge)}`\n🏦 Kelly: `{stake}%` | 📚 H2H: `{h2h}`\n\n"
                 f"🧠 *ESTRATEGA*\n{estratega}\n\n🛡 *AUDITOR*\n{auditor}\n\n🏁 *VEREDICTO:* {verdict}")

        await bot.edit_message_text(texto, message.chat.id, espera.message_id, parse_mode="Markdown")
        await guardar_en_github({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "partido": f"{n_l}-{n_v}", "edge": porcentaje(edge), "stake": f"{stake}%", "veredicto": verdict})
    except Exception as e: await bot.edit_message_text(f"❌ Error: {e}", message.chat.id, espera.message_id)

# ==================================================
# CONFIG Y POLLING
# ==================================================

@bot.message_handler(commands=["config"])
async def config_cmd(message):
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🧠 Config Estratega", callback_data="set_rol_estratega"))
    await bot.reply_to(message, "⚙️ Panel de Control IA", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_rol_"))
async def cb_role(call):
    rol = call.data.split("_")[-1]
    mk = InlineKeyboardMarkup().row(InlineKeyboardButton("SambaNova", callback_data=f"set_api_{rol}_SAMBA"), InlineKeyboardButton("Groq", callback_data=f"set_api_{rol}_GROQ"))
    await bot.edit_message_text(f"API para {rol.upper()}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_api_"))
async def cb_api(call):
    _, _, rol, api = call.data.split("_")
    lista = SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"]
    mk = InlineKeyboardMarkup()
    for i, n in enumerate(lista): mk.add(InlineKeyboardButton(n, callback_data=f"sv_n_{rol}_{api}_{i}"))
    await bot.edit_message_text(f"Nodo {api}:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sv_n_"))
async def cb_save(call):
    _, _, rol, api, idx = call.data.split("_")
    SISTEMA_IA[rol] = {"api": api, "nodo": (SISTEMA_IA["nodos_samba"] if api == "SAMBA" else SISTEMA_IA["nodos_groq"])[int(idx)]}
    mk = InlineKeyboardMarkup()
    if rol == "estratega": mk.add(InlineKeyboardButton("🛡 Añadir Auditor", callback_data="set_rol_auditor"))
    mk.add(InlineKeyboardButton("🏁 Finalizar", callback_data="config_fin"))
    await bot.edit_message_text(f"✅ {rol.upper()} listo.", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "config_fin")
async def cb_fin(call): await bot.edit_message_text("🚀 Sistema Online.", call.message.chat.id, call.message.message_id)

@bot.message_handler(commands=["historial"])
async def historial_cmd(message):
    datos = await obtener_historial_github()
    if not datos: await bot.reply_to(message, "Vacio."); return
    txt = "📋 *HISTORIAL*\n\n"
    for d in datos[-5:]: txt += f"⚽ {d['partido']} | {d['edge']} | {d['veredicto']}\n"
    await bot.reply_to(message, txt, parse_mode="Markdown")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__": asyncio.run(main())
