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
# CONFIGURACIÓN DE LOGS PARA RAILWAY
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
# Cambiamos a la constante de la liga que confirmas que tienes activa
CODIGO_LIGA = "PD" 

# ==================================================
# MOTOR ESTADÍSTICO & IA
# ==================================================
def porcentaje(x): return f"{x*100:.2f}%"

def calcular_poisson(exp_l, exp_v):
    prob_l = sum(poisson.pmf(i, exp_l) * sum(poisson.pmf(j, exp_v) for j in range(i)) for i in range(1, 10))
    return round(prob_l, 4)

def criterio_kelly(prob, cuota):
    if cuota <= 1: return 0
    f_star = (prob * cuota - 1) / (cuota - 1)
    return round(max(0, f_star * 100 * 0.25), 2)

# ==================================================
# FUNCIONES DE API (FOOTBALL-DATA.ORG)
# ==================================================

async def obtener_equipos_liga():
    """Obtiene los IDs y nombres usando el código de la competición (PD)"""
    url = f"https://api.football-data.org/v4/competitions/{CODIGO_LIGA}/teams"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    
    try:
        logger.info(f"Intentando conectar a la liga: {CODIGO_LIGA}")
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=12)
        
        if r.status_code == 200:
            teams = r.json().get('teams', [])
            logger.info(f"Carga exitosa: {len(teams)} equipos encontrados.")
            return {team['name'].lower(): team['id'] for team in teams}
        
        logger.error(f"FALLO API EQUIPOS: Status {r.status_code} | Contenido: {r.text[:200]}")
        return r.status_code # Devolvemos el código de error para manejarlo en el comando
    except Exception as e:
        logger.critical(f"EXCEPCIÓN EN LLAMADA API: {e}")
        return None

async def obtener_data_api(id_equipo):
    """H2H Reciente y xG basado en los últimos 5 partidos"""
    url = f"https://api.football-data.org/v4/teams/{id_equipo}/matches?status=FINISHED&limit=5"
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    
    try:
        r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json()
            matches = data.get('matches', [])
            if not matches: return None
            
            m_ref = matches[0]
            nombre = m_ref['homeTeam']['name'] if m_ref['homeTeam']['id'] == int(id_equipo) else m_ref['awayTeam']['name']
            
            goles = 0
            w, e, p = 0, 0, 0
            for m in matches:
                es_local = m['homeTeam']['id'] == int(id_equipo)
                goles += m['score']['fullTime']['home'] if es_local else m['score']['fullTime']['away']
                
                win = m['score']['winner']
                if win == 'DRAW': e += 1
                elif (win == 'HOME_TEAM' and es_local) or (win == 'AWAY_TEAM' and not es_local): w += 1
                else: p += 1
                
            return {"nombre": nombre, "xg": round(goles/len(matches), 2), "h2h": f"{w}-{e}-{p}"}
    except Exception as e:
        logger.error(f"Error extrayendo H2H para {id_equipo}: {e}")
    return None

# ==================================================
# MANEJADORES DE COMANDOS
# ==================================================

@bot.message_handler(commands=["equipos"])
async def equipos_cmd(message):
    espera = await bot.reply_to(message, f"📡 Consultando equipos de {CODIGO_LIGA}...")
    resultado = await obtener_equipos_liga()
    
    if isinstance(resultado, int): # Es un código de error
        return await bot.edit_message_text(f"❌ Error {resultado} de la API. Verifica los logs de Railway.", message.chat.id, espera.message_id)
    
    if not resultado:
        return await bot.edit_message_text("❌ No se recibió respuesta de la API.", message.chat.id, espera.message_id)
    
    tabla = f"🏟 **DIRECTORIO {CODIGO_LIGA}**\n" + "—" * 20 + "\n"
    for nombre, id_team in sorted(resultado.items(), key=lambda x: x[0]):
        tabla += f"`{id_team}` | {nombre.title()}\n"
    
    await bot.edit_message_text(tabla, message.chat.id, espera.message_id, parse_mode="Markdown")

@bot.message_handler(commands=["pronostico"])
async def handle_pronostico(message):
    try:
        parts = message.text.replace("/pronostico", "").lower().split(" vs ")
        id_l = parts[0].strip()
        id_v = parts[1].strip()
    except:
        return await bot.reply_to(message, "Usa: `/pronostico ID_LOCAL vs ID_VISITANTE`")

    espera = await bot.reply_to(message, "⚙️ Procesando datos recientes...")
    data_l, data_v = await asyncio.gather(obtener_data_api(id_l), obtener_data_api(id_v))

    if not data_l or not data_v:
        return await bot.edit_message_text("❌ Error en datos. Asegúrate de usar los IDs de /equipos.", message.chat.id, espera.message_id)

    # Lógica de Poisson y Kelly
    prob_l = calcular_poisson(data_l['xg'], data_v['xg'])
    cuota = 2.0 # Placeholder
    edge = (prob_l * cuota) - 1
    stake = criterio_kelly(prob_l, cuota)

    dataset = (f"[POISSON]: {porcentaje(prob_l)}\n"
               f"[xG REC]: {data_l['xg']} vs {data_v['xg']}\n"
               f"[H2H]: L:{data_l['h2h']} V:{data_v['h2h']}")
    
    # Aquí llamarías a tus funciones ejecutar_ia si están configuradas
    res = (f"📊 *{data_l['nombre']} vs {data_v['nombre']}*\n"
           f"━━━━━━━━━━━━━━━━━━━━\n"
           f"📈 Edge: `{porcentaje(edge)}` | Stake: `{stake}%` \n\n"
           f"Dato H2H (5 part.): L:{data_l['h2h']} V:{data_v['h2h']}")
    
    await bot.edit_message_text(res, message.chat.id, espera.message_id, parse_mode="Markdown")

# (Se mantienen tus manejadores de /config e IA iguales)

async def main():
    logger.info("Bot v6.2 desplegado con éxito.")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
