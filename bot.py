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
            "message": "🤖 Actualización de Historial",
            "content": nuevo_contenido,
            "sha": sha
        }
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"Error GitHub: {e}")

# --- Test de Aptitud Reforzado (Gemini & Groq) ---
async def probar_modelo_reforzado(api, nodo):
    prompt_test = (
        "Analiza: Probabilidad Poisson 65%, Cuota 1.90. "
        "¿Hay valor? Responde: 'VALOR: SI' o 'VALOR: NO'."
    )
    
    intentos = 0
    max_intentos = 2
    
    while intentos < max_intentos:
        intentos += 1
        try:
            if api == 'GEMINI':
                client = genai.Client(api_key=GEMINI_KEY)
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=nodo,
                        contents=prompt_test,
                        config=types.GenerateContentConfig(
                            max_output_tokens=15, 
                            temperature=0.1
                        )
                    ),
                    timeout=20.0
                )
                texto = response.text.upper()
            
            elif api == 'GROQ':
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": nodo, 
                    "messages": [{"role": "user", "content": prompt_test}], 
                    "max_tokens": 15, 
                    "temperature": 0.1
                }
                response = await asyncio.wait_for(
                    asyncio.to_thread(requests.post, url, headers=headers, json=payload),
                    timeout=20.0
                )
                if response.status_code == 200:
                    texto = response.json()['choices'][0]['message']['content'].upper()
                else:
                    raise Exception(f"HTTP {response.status_code}")

            if "SI" in texto:
                return True, "Apto (Lógica OK)"
            return False, f"No apto (Respuesta: {texto[:10]}...)"

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                if intentos < max_intentos:
                    await asyncio.sleep(10)
                    continue
                else:
                    return False, "Saturado (Límite reintentos)"
            
            if "TimeoutError" in error_msg or "timeout" in error_msg.lower():
                return False, "Lento (Superó 20s)"
            
            return False, f"Error: {error_msg[:20]}"
            
    return False, "Error desconocido"

# --- Motores de IA ---
async def ejecutar_ia(rol, prompt):
    config = SISTEMA_IA[rol]
    if not config["nodo"]: return None
    sys_instruction = "Eres un analista senior de riesgos. Tu objetivo es evaluar la probabilidad de Poisson contra la cuota de mercado usando el criterio de Kelly. Responde con tecnicismos y enfoque profesional."

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

# --- COMANDOS ---

@bot.message_handler(commands=['start', 'help'])
async def send_welcome(message):
    txt = (
        "🤖 **CENTRO DE AYUDA - SISTEMA DE PRONÓSTICOS**\n"
        "————————————————————\n"
        "🛠 **COMANDOS DE CONFIGURACIÓN:**\n"
        "1️⃣ `/scan_nodos [LISTA]`\n"
        "   Verifica qué modelos están activos y responden correctamente.\n"
        "   *Ej:* `/scan_nodos GROQ:llama-3.3-70b-versatile GEMINI:gemini-1.5-flash`\n\n"
        "2️⃣ `/config`\n"
        "   Abre el panel interactivo para asignar un modelo 'vivo' al rol de **Estratega**.\n\n"
        "3️⃣ `/ver_nodos`\n"
        "   Muestra el estado actual del sistema y qué modelo está analizando los picks.\n\n"
        "📊 **COMANDOS DE ANÁLISIS:**\n"
        "4️⃣ `/pronostico L vs V` o `/valor L vs V`\n"
        "   Realiza el cálculo estadístico Poisson, consulta cuotas reales y genera un Ticket de Valor con análisis de IA.\n"
        "   *Ej:* `/pronostico Real Madrid vs Barcelona`\n"
        "————————————————————\n"
        "💡 *Nota: El sistema usa Kelly Fractional (0.25) para gestionar el riesgo automáticamente.*"
    )
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['ver_nodos'])
async def ver_nodos(message):
    est = SISTEMA_IA["estratega"]
    txt = (
        "📡 **ESTADO DE LA RED IA**\n\n"
        f"🧠 **Estratega:** `{est['nodo'] if est['nodo'] else 'No configurado'}`\n"
        f"🌐 **API:** `{est['api'] if est['api'] else 'N/A'}`\n\n"
        "✅ **Nodos Disponibles (Vivos):**\n"
    )
    for api, lista in SISTEMA_IA["vivos"].items():
        nodos = ", ".join([f"`{n}`" for n in lista]) if lista else "Ninguno"
        txt += f"┣ {api}: {nodos}\n"
    
    await bot.reply_to(message, txt, parse_mode='Markdown')

@bot.message_handler(commands=['scan_nodos'])
async def scan_nodos(message):
    input_text = message.text.replace('/scan_nodos', '').strip()
    if input_text:
        SISTEMA_IA["candidatos"] = {"GEMINI": [], "GROQ": []}
        for seccion in input_text.split():
            if ':' in seccion:
                api, modelos = seccion.split(':')
                api = api.upper()
                if api in SISTEMA_IA["candidatos"]:
                    SISTEMA_IA["candidatos"][api] = modelos.split(',')

    if not any(SISTEMA_IA["candidatos"].values()):
        await bot.reply_to(message, "⚠️ Indica modelos para escanear.\nEj: `/scan_nodos GROQ:modelo1 GEMINI:modelo2`")
        return

    msg = await bot.reply_to(message, "🚀 **INICIANDO SCAN REFORZADO**\n⏳ 20s timeout | Máx 2 intentos | 6s enfriamiento")
    SISTEMA_IA["vivos"] = {"GEMINI": [], "GROQ": []}
    
    for api, modelos in SISTEMA_IA["candidatos"].items():
        for i, m in enumerate(modelos):
            status_text = f"🧪 Evaluando {api}: `{m}`..."
            await bot.edit_message_text(status_text, message.chat.id, msg.message_id, parse_mode='Markdown')
            
            es_apto, info = await probar_modelo_reforzado(api, m)
            
            if es_apto:
                SISTEMA_IA["vivos"][api].append(m)
                logging.info(f"✅ {api}:{m} - APTO")
            
            if i < len(modelos) - 1:
                await asyncio.sleep(6)

    reporte = "📋 **RESULTADO FINAL DEL SCAN:**\n\n"
    for api in ["GEMINI", "GROQ"]:
        vivos = SISTEMA_IA["vivos"][api]
        reporte += f"🔹 **{api}:** {len(vivos)} aptos\n"
        for v in vivos: reporte += f"  └ `{v}`\n"
    
    await bot.edit_message_text(reporte + "\nUsa `/config` para asignar el rol de estratega.", message.chat.id, msg.message_id, parse_mode='Markdown')

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
        kelly = ((c_l * ph) - 1) / (c_l - 1) if edge_real > 0 else 0
        stake_final = max(0, min(round(kelly * 0.25 * 100, 2), 5.0))

        header = (
            f"🏟 **{m_l.upper()} vs {m_v.upper()}**\n"
            f"————————————————————\n"
        )
        
        ticket = (
            f"🎫 **TICKET DE VALOR:**\n"
            f"```\n"
            f"PICK:  {m_l}\n"
            f"CUOTA: {c_l:.2f}\n"
            f"PROB:  {ph*100:.1f}%\n"
            f"EDGE:  {edge_real*100:+.1f}%\n"
            f"STAKE: {stake_final}%\n"
            f"```\n"
        )

        prompt_e = f"Partido: {m_l} vs {m_v}. Probabilidad Poisson: {ph*100:.1f}%. Cuota Mercado: {c_l:.2f}. Ventaja (Edge): {edge_real*100:+.1f}%. Kelly Stake Sugerido: {stake_final}%. Realiza un veredicto técnico."
        analisis = await ejecutar_ia("estratega", prompt_e)
        
        asyncio.create_task(guardar_en_github(nuevo_registro={
            "fecha": (datetime.utcnow() + timedelta(hours=OFFSET_JUAREZ)).strftime('%Y-%m-%d %H:%M'),
            "partido": f"{m_l} vs {m_v}", "pick": m_l if stake_final > 0 else "No Bet",
            "poisson": f"{ph*100:.1f}%", "cuota": c_l, "edge": f"{edge_real*100:.1f}%", "stake": f"{stake_final}%", "status": "⏳ PENDIENTE"
        }))

        final_msg = f"{header}{ticket}🧠 **ANÁLISIS ESTRATÉGICO:**\n_{analisis}_\n\n🛰 Nodo: `{SISTEMA_IA['estratega']['nodo']}`"
        await bot.edit_message_text(final_msg, message.chat.id, msg_espera.message_id, parse_mode='Markdown')

    except Exception as e:
        await bot.edit_message_text(f"❌ Error: {str(e)}", message.chat.id, msg_espera.message_id)

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
        await bot.answer_callback_query(call.id, f"❌ Sin nodos aptos en {api}. Usa /scan_nodos primero.", show_alert=True); return
    markup = InlineKeyboardMarkup()
    for n in vivos: markup.add(InlineKeyboardButton(n, callback_data=f"save_nodo_{rol}_{api}_{n}"))
    await bot.edit_message_text(f"Nodos Aptos ({api}):", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_nodo_'))
async def cb_save(call):
    _, _, rol, api, nodo = call.data.split('_')
    SISTEMA_IA[rol] = {"api": api, "nodo": nodo}
    await bot.edit_message_text(f"🚀 **{rol.upper()} LISTO**\nNodo: `{nodo}`", call.message.chat.id, call.message.message_id)

async def main():
    logging.info("Iniciando Bot...")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())
