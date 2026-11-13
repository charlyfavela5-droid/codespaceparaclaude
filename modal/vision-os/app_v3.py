"""
Visión OS v3 — centro de control de Visión Agencia (Modal) + AGENTE DE PROSPECTOS.
12 nov 2026, orden de Carlos. SIN DESPLEGAR Y SIN PROBAR EN VIVO: solo revisado de sintaxis y con pruebas simuladas.

Qué cambia contra app.py (v1):
 1. El COO gratuito ya no necesita FREE_LLM_URL: llama directo a guardian-llm (clase Guardian, método pensar),
    igual que cambios_rapidos. Si existe FREE_LLM_URL se usa como respaldo. Claude entra solo si hay ANTHROPIC_API_KEY.
 2. Agente de prospectos: a todo número NUEVO que escribe le contesta solo por WhatsApp (si AUTO_REPLY=1):
    saluda, ofrece la muestra gratis y pide los datos del negocio. Guarda la conversación y los datos en la ficha
    del prospecto. Precio, cobro, quejas o dudas que no sabe -> acuse corto + «Te necesito» a Carlos.
 3. Candados para no contestarle a quien no es prospecto:
    - Si ya hay mensajes tuyos en ese chat (cliente, familia, conocido) NO contesta: solo deja borrador.
    - Si no se puede revisar el historial del chat, tampoco contesta (borrador y aviso).
    - BLOCKED_CHATS: chats que nunca se tocan.
    - Tope de respuestas por prospecto al día (MAX_PROSPECT_REPLIES, 8 por defecto).
    - Nunca manda un texto con precios o cifras de dinero: lo cambia por el acuse y te avisa.
 4. El webhook contesta 200 al instante y procesa aparte (el modelo en CPU tarda); no repite mensajes ya vistos.
 5. v3 · ACUSE INSTANTÁNEO: en cuanto entra el mensaje de un prospecto (antes de que piense la IA) sale
    «Recibido ✅ Procesando tu mensaje…». Lo manda el propio webhook, no espera al modelo. Pasa por los mismos
    candados (no sale a clientes, conocidos ni bloqueados) y como máximo uno cada ACK_EVERY_SEC (300 s) por chat.
    Para que salga en ~1 s el contenedor web debe estar despierto: WEB_MIN_CONTAINERS = 1 (cuesta CPU todo el día);
    en 0 es gratis en reposo pero el primer mensaje tras un rato tarda lo que tarde en despertar Modal.
 6. FORWARD_URL (opcional): reenvía cada aviso de WaAPI a otro webhook (el de waapi-webhook / guardian-llm),
    porque WaAPI solo manda a una URL.

Despliegue: modal deploy app_v3.py   (misma cuenta que guardian-llm: charlyfavela5)
Secretos: «vision-os» (ADMIN_KEY, WEBHOOK_SECRET, OWNER_CHAT, AUTO_REPLY...) y «nexus-env» (WAAPI_TOKEN, WAAPI_INSTANCE).
"""
import asyncio
import hashlib
import hmac
import json
import os
import re
import time
import uuid

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("fastapi[standard]", "httpx")
    .add_local_file("panel.html", "/root/panel.html")
)
app = modal.App(
    "vision-os",
    image=image,
    secrets=[modal.Secret.from_name("nexus-env"), modal.Secret.from_name("vision-os"), modal.Secret.from_name("alertas")],
)
db = modal.Dict.from_name("vision-os-db", create_if_missing=True)

COLLECTIONS = ("clients", "tasks", "prospects", "inbox")
CATEGORIES = ("anuncio", "campaña", "seguimiento", "prospecto", "otro")

WAAPI = "https://waapi.app/api/v1"
GITHUB = "https://api.github.com"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ---------------------------------------------------------------- almacenamiento
def put(coll: str, doc: dict) -> dict:
    doc.setdefault("id", uuid.uuid4().hex[:10])
    doc["updatedAt"] = int(time.time())
    doc.setdefault("createdAt", doc["updatedAt"])
    db[f"{coll}:{doc['id']}"] = doc
    return doc


def get(coll: str, doc_id: str):
    try:
        return db[f"{coll}:{doc_id}"]
    except KeyError:
        return None


def rows(coll: str) -> list:
    out = [db[k] for k in db.keys() if k.startswith(coll + ":")]
    return sorted(out, key=lambda d: d.get("updatedAt", 0), reverse=True)


def remove(coll: str, doc_id: str):
    try:
        db.pop(f"{coll}:{doc_id}")
    except KeyError:
        pass


SEED_CLIENTS = [
    ("Mariano", "Casas", "Terminar video; el gancho tiene la voz desincronizada, arreglar con MiniMax.", "video"),
    ("Jesús (Rar Amore)", "Cápsulas con resveratrol", "Ya recibió video e imágenes; propone anuncios nuevos.", "campaña"),
    ("Empeños", "Empeños", "Decidió hacer 1 video; imágenes bien.", "video"),
    ("Renova", "Renova", "Audio aprobado; faltan frames y referencia visual.", "video"),
    ("Ginecólogo", "Consultorio", "Video virgen sin subtítulos; quiere llegar a 9.", "video"),
    ("Alberto", "Dentista", "Video pendiente.", "video"),
    ("Caser", "Caser", "Video pendiente.", "video"),
    ("Manuel Fotografía", "Fotografía", "Contento con su video; corregir un número que la IA quitó.", "seguimiento"),
    ("Rafael", "—", "Campaña sin resultado; pide promoción Buen Fin; se le debe un video.", "campaña"),
    ("José", "—", "Prueba social subida; mensajes cuestan $30; busca referencias.", "seguimiento"),
]


def seed_if_empty():
    if rows("clients"):
        return
    for name, biz, note, phase in SEED_CLIENTS:
        put("clients", {
            "name": name, "business": biz, "note": note, "phase": phase,
            "phone": "", "chatId": "", "videos": 0, "images": 0, "metaAccount": "",
            "goal": "1 video + 3 imágenes en calificación 8",
        })


# ---------------------------------------------------------------- IA: guardián gratuito + Claude
_S = {"type": "string"}
COO_SCHEMA = {
    "type": "object",
    "required": ["category", "urgency", "summary", "missing", "reply", "escalate"],
    "properties": {
        "category": {"enum": list(CATEGORIES)},
        "urgency": {"enum": ["alta", "media", "baja"]},
        "summary": _S,
        "missing": {"type": "array", "items": _S},
        "reply": _S,
        "escalate": {"type": "boolean"},
    },
}
COO_SYSTEM = """Eres el COO de Visión Agencia (Nogales, México). Hablas español mexicano casual y directo.
Recibes un mensaje de WhatsApp y el contexto del contacto. Responde SOLO un JSON con:
{"category": "anuncio|campaña|seguimiento|prospecto|otro",
 "urgency": "alta|media|baja",
 "summary": "una línea",
 "missing": ["datos que faltan; pídelos todos juntos, no uno por uno"],
 "reply": "respuesta sugerida corta para WhatsApp",
 "escalate": true|false}
escalate=true si hay queja fuerte, dinero, decisión estratégica o no estás seguro."""

PROSPECT_SCHEMA = {
    "type": "object",
    "required": ["es_prospecto", "reply", "etapa", "nombre", "negocio", "giro", "ciudad", "que_vende", "escalate", "motivo"],
    "properties": {
        "es_prospecto": {"type": "boolean"},
        "reply": _S,
        "etapa": {"enum": ["nuevo", "pidiendo_datos", "datos_completos", "no_interesado"]},
        "nombre": _S, "negocio": _S, "giro": _S, "ciudad": _S, "que_vende": _S,
        "escalate": {"type": "boolean"},
        "motivo": _S,
    },
}
FIRST_PITCH = (
    "¡Hola! Gracias por escribir 🙌 Soy de Visión Agencia. Estamos en Sonora y trabajamos 100% en línea con negocios de todo México.\n\n"
    "Le ofrecemos *atención gratis* con nuestro método automatizado para llegar a *8 de 10*: le armamos su video y su campaña, y "
    "*antes de gastar un peso en pauta* nuestro sistema califica el anuncio con los criterios de calidad de Facebook. "
    "Solo lo lanzamos cuando llega a *8 de 10*. Abajo de 8 se paga por vistas y no llegan mensajes; esa es la diferencia "
    "entre un anuncio caro y uno barato.\n\n"
    "Resultados reales de clientes nuestros:\n"
    "• Limpieza: 33 mensajes a $1.39 cada uno\n"
    "• Impermeabilización: 18 mensajes a $2.87 cada uno\n\n"
    "Para armarle su *muestra gratis*, ¿me ayuda con esto?\n"
    "1️⃣ ¿A qué se dedica y en qué ciudad?\n"
    "2️⃣ 3 fotos o videos de su trabajo (del celular está bien)\n"
    "3️⃣ ¿Qué precio o promoción quiere anunciar?\n"
    "4️⃣ Un reel o anuncio que le guste, de referencia\n\n"
    "Con eso le hago una *muestra con su propio material* y le digo en cuánto califica, sin costo y antes de subir nada 👌"
)
SECOND_PITCH = (
    "Le cuento lo que hemos aprendido generando campañas que llegan a *8 de 10* 📊\n"
    "• Abajo de 8, Facebook cobra por vistas y no llegan mensajes; por eso calificamos cada anuncio antes de pagar pauta.\n"
    "• Lo que más sube la calificación es el material real: fotos o videos de su negocio, de usted atendiendo, y su voz.\n"
    "• Un gancho concreto en los primeros segundos y una sola idea por anuncio.\n"
    "• Una prueba que dé confianza, como el testimonio de un cliente con su permiso.\n"
    "• Texto corto y grande, y un botón directo a WhatsApp.\n"
    "• Tomamos como guía los videos más virales de su giro para encontrar el ángulo que más convence.\n\n"
    "El 70% de lo que invertimos en producción se va en responder lo que Facebook evalúa de cada anuncio, y yo lo guío paso a paso "
    "para que sus anuncios lleguen a 8 con todo lo que hemos aprendido.\n"
    "Con este sistema la atención es clara y rápida: sus mensajes se contestan en segundos y puede preguntar «¿cómo va?» cuando quiera.\n\n"
    "Pruebe *gratis* la muestra de anuncios y video; si le convence, serían *$500* 👌"
)
PRECIO_OK = re.compile(r"\$\s?500\b|\b500\s*(pesos|mxn)\b", re.I)  # único precio autorizado por Carlos
DEFAULT_PITCH = (
    "Visión Agencia arma video y campaña de Facebook e Instagram para negocios de todo México, 100% en línea. Atención gratis con "
    "nuestro método automatizado para llegar a 8 de 10: antes de gastar en pauta, el sistema califica el anuncio y solo se lanza "
    "con 8 o más. Muestra gratis de anuncios y video con el propio material del cliente; si le convence, son $500 (único precio "
    "que puedes decir: nada de otros precios, paquetes ni descuentos). Si no manda material real, se genera, y tras la calificación "
    "se le explica cómo afecta no usar material ni voz reales. Datos a pedir: giro y ciudad, 3 fotos o videos de su trabajo, "
    "precio o promoción que quiere anunciar, y un reel o anuncio de referencia. Háblale de usted."
)
PROSPECT_SYSTEM = """Eres quien atiende por WhatsApp a los prospectos de Visión Agencia (Nogales, Sonora, México).
Escribes como una persona del equipo: español mexicano, amable, directo, mensajes cortos (máximo 4 renglones), sin tecnicismos.

Qué ofrece la agencia (no agregues nada más):
{pitch}

Tu trabajo en esta conversación:
1. Saluda (solo la primera vez) y dile lo de la muestra gratis.
2. Consigue estos datos, pidiendo JUNTOS los que falten, no uno por uno: nombre de la persona, nombre del negocio,
   giro, ciudad, qué quiere vender o promocionar, y su página de Facebook o Instagram si tiene.
3. Cuando ya tengas negocio, giro, ciudad y qué vende: etapa = "datos_completos" y le dices que con eso se arma
   su muestra. No des fecha ni hora.
4. La atención NO termina con los datos: sigue atendiéndolo personalmente hasta que reciba su muestra completa
   (3 imágenes y 1 video). Mientras tanto contesta sus dudas y pídele material real para su muestra: fotos o videos
   de su negocio y un audio con su voz (si no tiene, la muestra se hace con material generado).

No agregues argumentos de venta: contesta lo que preguntó y pide lo que falte. Nunca vuelvas a pedir un dato que ya tienes.
Prohibido: urgencias o escasez inventadas, garantizar ventas o resultados, testimonios o cifras inventadas.

Reglas que NO se rompen:
- El único precio que puedes decir es el de la oferta ($500 si le convence la muestra gratis). Nunca des otros precios, costos,
  paquetes, descuentos, plazos de entrega ni resultados garantizados. Si pregunta por cobro, pagos o algo más de precio, si se queja, si pide hablar con una persona, o si no sabes qué contestar: escalate = true.
- No inventes datos del prospecto ni de la agencia. Dato que no dijo = cadena vacía.
- Mensajes como «¡Hola! Quiero más información» o «info» vienen de nuestros anuncios: es_prospecto = true.
- es_prospecto = false si el mensaje NO es de alguien interesado en anuncios o publicidad para su negocio
  (un conocido, un proveedor, spam, número equivocado, alguien que ofrece algo). En ese caso reply = "".
- Si dice que no le interesa: etapa = "no_interesado", despídete en un renglón y no insistas.
- No digas que eres una IA salvo que lo pregunte; si lo pregunta, di la verdad: eres el asistente automático
  de la agencia y Carlos revisa todo.
Responde SOLO con el JSON."""

ACK_ESCALATE = "Recibido ✅ Eso te lo contesta Carlos directamente, ya le avisé. En un momento te escribe."
ACK_FIRST = ("¡Hola! Gracias por escribir a Visión Agencia ✅ Recibimos tu mensaje. "
             "¿Me compartes el nombre de tu negocio, a qué se dedica y en qué ciudad está?")
ACK_FAST = "Recibido ✅ Procesando tu mensaje…"
# Convencimiento en poca dosis: un renglón al final de 1 de cada 3 respuestas, rotando. Solo cosas verdaderas.
ARGUMENTOS = [
    "La muestra es gratis y sin compromiso: la ve y decide.",
    "Calificamos cada anuncio y solo publicamos lo que llega a 8 de 10, para no gastar en pauta que no trae mensajes.",
    "Con fotos y su voz reales el anuncio sale más fuerte que con material genérico.",
    "Tomamos como guía los videos más virales de su giro para encontrar el ángulo que más convence.",
    "El Buen Fin es buen momento para tener sus anuncios listos.",
]
PIDE_MATERIAL = ("Para su muestra (3 imágenes y 1 video) nos ayuda mucho que nos mande por aquí fotos o videos de su negocio "
                 "y un audio corto con su voz. Si no tiene, la hacemos con material generado.")
_tareas: set = set()  # tareas de fondo vivas (reenvío del webhook)
WEB_MIN_CONTAINERS = 0  # 1 = acuse en ~1 s siempre (cuesta); 0 = gratis en reposo
MONEY = re.compile(r"\$|\b\d[\d,.]*\s*(pesos|mxn|usd|dls|dólares|dolares|mil\b)", re.I)


async def guardian(messages: list, schema: dict, max_tokens: int = 420) -> dict:
    """Modelo gratuito de Modal (guardian-llm, Qwen en CPU). Devuelve el dict JSON o lanza error."""
    cls = modal.Cls.from_name("guardian-llm", "Guardian")
    r = await cls().pensar.remote.aio(messages, max_tokens=max_tokens, temperatura=0.0, esquema=schema)
    j = r.get("json") if isinstance(r, dict) else None
    if not isinstance(j, dict):
        raise RuntimeError(f"guardián sin JSON: {str(r)[:120]}")
    return j


async def chat_openai(messages: list) -> str:
    """Respaldo opcional: cualquier endpoint estilo OpenAI (FREE_LLM_URL)."""
    import httpx
    url, key, model = env("FREE_LLM_URL"), env("FREE_LLM_KEY"), env("FREE_LLM_MODEL", "default")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={"model": model, "temperature": 0.2, "messages": messages},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def chat_claude(messages: list) -> str:
    import httpx
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
            json={"model": env("CLAUDE_MODEL", "claude-sonnet-5-5"), "max_tokens": 700,
                  "system": system, "messages": rest},
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


def loose_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    data = json.loads(m.group(0)) if m else {}
    if not isinstance(data, dict) or not data:
        raise RuntimeError("respuesta sin JSON")
    return data


async def think(messages: list, schema: dict, prefer_claude: bool = False) -> tuple:
    """Cadena de respaldo: guardián gratis -> endpoint OpenAI (si hay) -> Claude (si hay). Devuelve (json, quién)."""
    errors = []
    chain = [("guardián", lambda: guardian(messages, schema))]
    if env("FREE_LLM_URL"):
        async def _o():
            return loose_json(await chat_openai(messages))
        chain.append(("gratis-url", _o))
    if env("ANTHROPIC_API_KEY"):
        async def _c():
            return loose_json(await chat_claude(messages))
        chain.append(("claude", _c))
        if prefer_claude:
            chain.insert(0, chain.pop())
    for name, fn in chain:
        try:
            return await fn(), name
        except Exception as e:
            errors.append(f"{name}: {str(e)[:120]}")
    raise RuntimeError(" | ".join(errors))


def clean_coo(data: dict) -> dict:
    if data.get("category") not in CATEGORIES:
        data["category"] = "otro"
    if data.get("urgency") not in ("alta", "media", "baja"):
        data["urgency"] = "media"
    data["missing"] = data.get("missing") if isinstance(data.get("missing"), list) else []
    data["reply"] = str(data.get("reply") or "")
    data["summary"] = str(data.get("summary") or "")
    data["escalate"] = bool(data.get("escalate"))
    return data


async def triage(message: str, context: str) -> dict:
    msgs = [{"role": "system", "content": COO_SYSTEM},
            {"role": "user", "content": f"Contexto del contacto:\n{context}\n\nMensaje:\n{message}"}]
    try:
        out, used = await think(msgs, COO_SCHEMA)
        out = clean_coo(out)
    except Exception as e:
        return {"category": "otro", "urgency": "media", "summary": "", "missing": [], "reply": "",
                "escalate": True, "error": str(e)[:200], "by": "nadie"}
    if out["escalate"] and used != "claude" and env("ANTHROPIC_API_KEY"):
        try:
            out2, used = await think(msgs, COO_SCHEMA, prefer_claude=True)
            out = clean_coo(out2)
        except Exception as e:
            out["error"] = str(e)[:200]
    out["by"] = used
    return out


# ---------------------------------------------------------------- WhatsApp (WaAPI)
def only_digits(chat_id: str) -> str:
    return re.sub(r"\D", "", (chat_id or "").split("@")[0])


def instance() -> str:
    return env("WAAPI_INSTANCE", "106321")


ACK_KINDS = ("acuse",)


def _dia_sonora(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t - 7 * 3600))


def _log_envios(chat_id: str) -> list:
    """[[timestamp, "acuse"|"auto"], ...] de las últimas 24 h."""
    now = time.time()
    out = []
    for x in (db.get(f"auto:{chat_id}") or []):
        t, k = (x, "auto") if isinstance(x, (int, float)) else (x[0], x[1])
        if now - t < 86400:
            out.append([t, k])
    return out


def freno(chat_id: str, kind: str) -> str:
    """Tope general de mensajes automáticos por chat (clientes y prospectos). Devuelve el motivo si NO debe salir.
    - Respuestas: máximo AUTO_MAX_HORA (4) por hora y AUTO_MAX_DIA (10) al día (día de Sonora).
    - Acuses («Recibido…»): no cuentan para el tope, pero no salen si ya le escribimos hace menos de ACK_QUIET_SEC (600 s).
    El dueño y los envíos manuales del panel no se frenan."""
    if kind == "manual" or is_owner(chat_id):
        return ""
    now = time.time()
    glob = [t for t in (db.get("auto_global") or []) if now - t < 60]  # acelerador: todos los chats juntos
    if len(glob) >= int(env("AUTO_MAX_MIN", "15")):
        return f"acelerador global ({env('AUTO_MAX_MIN', '15')} mensajes por minuto entre todos los chats)"
    log = _log_envios(chat_id)
    if kind in ACK_KINDS:
        ultimo = max((t for t, _ in log), default=0)
        return "acuse de más (ya le escribimos hace poco)" if now - ultimo < int(env("ACK_QUIET_SEC", "600")) else ""
    resp = [t for t, k in log if k not in ACK_KINDS]
    if len([t for t in resp if now - t < 3600]) >= int(env("AUTO_MAX_HORA", "4")):
        return f"tope de {env('AUTO_MAX_HORA', '4')} mensajes automáticos por hora"
    if len([t for t in resp if _dia_sonora(t) == _dia_sonora(now)]) >= int(env("AUTO_MAX_DIA", "10")):
        return f"tope de {env('AUTO_MAX_DIA', '10')} mensajes automáticos al día"
    return ""


def contar_envio(chat_id: str, kind: str):
    now = time.time()
    db[f"auto:{chat_id}"] = _log_envios(chat_id) + [[now, kind]]
    db["auto_global"] = [t for t in (db.get("auto_global") or []) if now - t < 60] + [now]


async def wa_send(chat_id: str, text: str, kind: str = "auto") -> dict:
    """kind: "auto" (respuesta automática), "acuse" (Recibido…), "manual" (desde el panel: no se frena)."""
    motivo = freno(chat_id, kind)
    if motivo:
        if kind not in ACK_KINDS:  # lo importante no se pierde: queda de borrador y a Carlos le avisa (1 vez por hora)
            put("inbox", {"phone": only_digits(chat_id), "chatId": chat_id, "name": "", "clientId": "", "text": "",
                          "category": "otro", "urgency": "media", "summary": f"Frenado: {motivo}. Mándalo tú desde el panel.",
                          "missing": [], "draft": text, "by": "freno", "read": False, "sent": False})
            k = f"frenoaviso:{chat_id}"
            if time.time() - (db.get(k) or 0) > 3600:
                db[k] = time.time()
                await tell_owner(f"Visión OS: frené un mensaje automático a {only_digits(chat_id)} ({motivo}). "
                                 "Quedó de borrador en el panel.")
        return {"status": 429, "body": f"frenado: {motivo}", "frenado": True}
    import httpx
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{WAAPI}/instances/{instance()}/client/action/send-message",
            headers={"Authorization": f"Bearer {env('WAAPI_TOKEN')}"},
            json={"chatId": chat_id, "message": text},
        )
        status = r.status_code
        try:  # WaAPI responde 200 aunque falle: el error real viene en data.status
            if (r.json().get("data") or {}).get("status") == "error":
                status = 502
        except Exception:
            pass
        if status < 300 and kind != "manual" and not is_owner(chat_id):
            contar_envio(chat_id, kind)
        return {"status": status, "body": r.text[:300]}


SYSTEM_TYPES = {"e2e_notification", "notification_template", "notification", "gp2", "call_log", "protocol", "revoked", "ciphertext"}


def _find_messages(obj, depth: int = 0):
    """Busca la lista de mensajes dentro de la respuesta de WaAPI sin asumir su forma exacta."""
    if depth > 5:
        return None
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any(("fromMe" in x or "message" in x) for x in obj):
            return obj
        return [] if not obj else None
    if isinstance(obj, dict):
        for k in ("messages", "data"):
            if k in obj:
                found = _find_messages(obj[k], depth + 1)
                if found is not None:
                    return found
    return None


async def chat_has_my_messages(chat_id: str):
    """True si en ese chat ya hay mensajes enviados desde tu WhatsApp (contacto conocido).
    False si no hay ninguno. None si no se pudo saber (se trata como conocido: no se contesta solo)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{WAAPI}/instances/{instance()}/client/action/fetch-messages",
                headers={"Authorization": f"Bearer {env('WAAPI_TOKEN')}"},
                json={"chatId": chat_id, "limit": 200},
            )
        if r.status_code >= 400:
            return None
        msgs = _find_messages(r.json())
        if msgs is None:
            return None
        for m in msgs:
            m = m.get("message", m) if isinstance(m, dict) else {}
            if str(m.get("type", "chat")) in SYSTEM_TYPES:  # avisos de WhatsApp (cifrado, plantillas): no son mensajes tuyos
                continue
            mid = m.get("id") if isinstance(m.get("id"), dict) else {}
            if m.get("fromMe") or mid.get("fromMe"):
                return True
        return False
    except Exception:
        return None


def extract_message(payload: dict):
    """WaAPI manda {event, instanceId, data:{message:{...}}}; se lee de forma defensiva."""
    data = payload.get("data") or payload
    msg = data.get("message") or data
    body = msg.get("body") or msg.get("text") or ""
    sender = msg.get("from") or msg.get("author") or ""
    mid = msg.get("id")
    from_me = bool(msg.get("fromMe")) or (isinstance(mid, dict) and bool(mid.get("fromMe")))
    if isinstance(mid, dict):
        mid = mid.get("_serialized") or mid.get("id") or ""
    name = (msg.get("_data") or {}).get("notifyName", "") or msg.get("notifyName", "")
    status = bool(msg.get("isStatus")) or sender == "status@broadcast"
    return {"sender": sender, "body": str(body), "from_me": from_me, "name": name,
            "id": str(mid or ""), "status": status, "media": bool(msg.get("hasMedia")), "type": str(msg.get("type") or "")}


def find_client(chat_id: str):
    phone = only_digits(chat_id)
    for c in rows("clients"):
        if c.get("chatId") and c["chatId"] == chat_id:
            return c
        p = only_digits(c.get("phone", ""))
        if p and len(p) >= 10 and phone.endswith(p[-10:]):
            return c
    return None


def owner_chat() -> str:
    if env("OWNER_CHAT"):
        return env("OWNER_CHAT")
    d = only_digits(env("OWNER_NUMBER"))
    return f"{d}@c.us" if d else ""


def is_owner(chat_id: str) -> bool:
    if env("OWNER_CHAT") and chat_id == env("OWNER_CHAT"):
        return True
    d = only_digits(env("OWNER_NUMBER"))
    return bool(d) and only_digits(chat_id).endswith(d[-10:])


async def tell_owner(text: str):
    chat = owner_chat()
    if chat:
        try:
            await wa_send(chat, text[:900])
        except Exception:
            pass


def blocked(chat_id: str) -> bool:
    items = [x.strip() for x in env("BLOCKED_CHATS").split(",") if x.strip()]
    return chat_id in items or any(only_digits(x) and only_digits(chat_id).endswith(only_digits(x)[-10:]) for x in items)


async def handle_owner_command(body: str, chat_id: str):
    parts = body.strip().split()
    cmd = parts[0].lower()
    if cmd == "/repos":
        repos = await gh("GET", "/user/repos?sort=pushed&per_page=10")
        text = "\n".join(f"• {r['full_name']}" for r in repos)
    elif cmd == "/deploy" and len(parts) > 1:
        text = json.dumps(await deploy(parts[1]), ensure_ascii=False)[:500]
    elif cmd == "/estado":
        tasks = [t for t in rows("tasks") if t.get("status") != "hecho"]
        pros = rows("prospects")
        text = (f"Pendientes abiertos: {len(tasks)}\n"
                f"Bandeja sin leer: {len([m for m in rows('inbox') if not m.get('read')])}\n"
                f"Prospectos: {len(pros)} ({len([p for p in pros if p.get('stage') == 'datos_completos'])} con datos completos)")
    elif cmd == "/prospectos":
        pros = rows("prospects")[:10]
        text = "\n".join(f"• {p.get('name') or p.get('phone')} · {p.get('business') or 'sin negocio'} · {p.get('stage')}"
                         for p in pros) or "Sin prospectos."
    elif cmd == "/pausa" and len(parts) > 1:
        p = next((x for x in rows("prospects") if only_digits(parts[1]) and x.get("phone", "").endswith(only_digits(parts[1])[-10:])), None)
        if p:
            p["paused"] = True
            put("prospects", p)
        text = "Pausado: ya no le contesto solo." if p else "No encontré ese prospecto."
    elif cmd == "/muestra" and len(parts) > 2:  # /muestra <número> <imágenes 0-3> [video]
        p = next((x for x in rows("prospects") if only_digits(parts[1]) and x.get("phone", "").endswith(only_digits(parts[1])[-10:])), None)
        if not p:
            text = "No encontré ese prospecto."
        else:
            p["sampleImages"] = max(0, min(3, int(only_digits(parts[2]) or 0)))
            p["sampleVideo"] = any(w.lower().startswith("vid") for w in parts[3:]) or p.get("sampleVideo", False)
            if p["sampleImages"] >= 3 and p["sampleVideo"]:
                p["sample"] = "entregada"
                p["paused"] = True  # muestra completa: termina la atención automática, sigue Carlos
                text = f"Muestra completa de {p.get('name') or p['phone']} ✅ Apagué su atención automática; el cierre es tuyo."
            else:
                p["sample"] = "en_proceso"
                text = f"Anotado: {p['sampleImages']}/3 imágenes, video {'listo' if p['sampleVideo'] else 'pendiente'}. Su atención sigue activa."
            put("prospects", p)
    else:
        text = "Comandos: /repos, /deploy <repo>, /estado, /prospectos, /pausa <número>, /muestra <número> <imágenes> [video]"
    await wa_send(chat_id, text)


# ---------------------------------------------------------------- agente de prospectos
def prospect_rules(result: dict, prospect: dict, first: bool) -> dict:
    """Reglas fijas del negocio: no dependen del modelo. Devuelve {send, text, escalate, why}."""
    reply = str(result.get("reply") or "").strip()
    if prospect.get("paused"):
        return {"send": False, "text": reply, "escalate": False, "why": "prospecto en pausa"}
    if not result.get("es_prospecto", True):
        return {"send": False, "text": reply, "escalate": False, "why": "no parece prospecto"}
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 3600))
    sent_today = prospect.get("sentByDay", {}).get(day, 0)
    if sent_today >= int(env("MAX_PROSPECT_REPLIES", "8")):
        return {"send": False, "text": reply, "escalate": True, "why": "tope de respuestas del día"}
    if result.get("escalate"):
        return {"send": True, "text": ACK_ESCALATE, "escalate": True, "why": result.get("motivo") or "pidió algo que decide Carlos"}
    if MONEY.search(PRECIO_OK.sub("", reply)):
        return {"send": True, "text": ACK_ESCALATE, "escalate": True, "why": "la respuesta traía precios o cifras"}
    if not reply:
        return {"send": first, "text": ACK_FIRST if first else "", "escalate": True, "why": "la IA no dio respuesta"}
    return {"send": True, "text": reply[:700], "escalate": False, "why": ""}


def find_prospect(chat_id: str):
    phone = only_digits(chat_id)
    return next((p for p in rows("prospects") if p.get("chatId") == chat_id or (phone and p.get("phone") == phone)), None)


def new_prospect(chat_id: str, body: str, name: str, fresh: bool = False) -> dict:
    return put("prospects", {"phone": only_digits(chat_id), "chatId": chat_id, "name": name, "business": "", "giro": "",
                             "city": "", "sells": "", "stage": "nuevo", "sample": "pendiente", "fresh": fresh,
                             "notes": body[:300], "history": [], "sentByDay": {}, "lastAck": 0})


async def quick_ack(m: dict) -> bool:
    """Acuse instantáneo desde el webhook, antes de la IA. Solo a prospectos y con los mismos candados."""
    chat = m["sender"]
    if (env("AUTO_REPLY") != "1" and not prospect_allowed(chat)) or is_owner(chat) or blocked(chat) or find_client(chat):
        return False
    prospect = find_prospect(chat)
    if prospect is None:
        if not prospect_allowed(chat) and await chat_has_my_messages(chat) is not False:
            db[f"known:{chat}"] = int(time.time())  # conocido o sin poder revisar: el proceso de fondo deja borrador
            return False
        prospect = new_prospect(chat, m["body"], m["name"], fresh=True)
    if prospect.get("paused") or prospect.get("stage") == "no_interesado":
        return False
    if time.time() - prospect.get("lastAck", 0) < int(env("ACK_EVERY_SEC", "300")):
        return False
    res = await wa_send(chat, ACK_FAST, kind="acuse")
    if res.get("status", 500) >= 300:
        return False
    prospect["lastAck"] = int(time.time())
    put("prospects", prospect)
    return True


async def attend_prospect(chat_id: str, body: str, name: str) -> dict:
    phone = only_digits(chat_id)
    prospect = find_prospect(chat_id)
    first = prospect is None
    if prospect and prospect.get("fresh"):  # lo acaba de crear el acuse instantáneo: sigue siendo su primer mensaje
        first = True
        prospect["fresh"] = False

    if prospect is None:
        known = False if prospect_allowed(chat_id) else (True if f"known:{chat_id}" in db else await chat_has_my_messages(chat_id))
        if known is not False:  # ya le has escrito antes, o no se pudo revisar: NO se contesta solo
            why = "ya hay mensajes tuyos en este chat" if known else "no pude revisar el historial del chat"
            put("inbox", {"phone": phone, "chatId": chat_id, "name": name, "clientId": "", "text": body,
                          "category": "otro", "urgency": "media", "summary": f"Sin respuesta automática: {why}.",
                          "missing": [], "draft": "", "by": "candado", "read": False, "sent": False})
            if known is None:
                await tell_owner(f"Visión OS: escribió {name or phone} y no pude revisar su historial, no le contesté. Mensaje: «{body[:200]}»")
            return {"ok": True, "category": "otro", "auto": False, "why": why}
        prospect = new_prospect(chat_id, body, name)

    history = prospect.get("history", [])[-12:]
    history.append({"role": "user", "content": body[:1200]})
    known_data = {k: prospect.get(v, "") for k, v in
                  (("nombre", "name"), ("negocio", "business"), ("giro", "giro"), ("ciudad", "city"), ("que_vende", "sells"))}
    system = PROSPECT_SYSTEM.format(pitch=env("PROSPECT_PITCH", DEFAULT_PITCH)) + \
        f"\n\nDatos que ya tienes de esta persona: {json.dumps(known_data, ensure_ascii=False)}" + \
        ("\nEs su PRIMER mensaje." if first else "\nYa se le saludó antes: no vuelvas a saludar.") + \
        f"\nSu muestra: {prospect.get('sampleImages', 0)} de 3 imágenes, video {'listo' if prospect.get('sampleVideo') else 'pendiente'}." + \
        ""
    msgs = [{"role": "system", "content": system}] + history

    try:
        result, used = await think(msgs, PROSPECT_SCHEMA)
    except Exception as e:
        result, used = {"es_prospecto": True, "reply": "", "escalate": False, "etapa": prospect.get("stage", "nuevo"),
                        "motivo": f"IA caída: {str(e)[:150]}"}, "plantilla"
    if prospect_allowed(chat_id):  # Carlos ordenó atenderlo: es prospecto; en su primer mensaje no puede salir «no interesado»
        result["es_prospecto"] = True
        if first and result.get("etapa") == "no_interesado":
            result["etapa"] = "nuevo"
    decision = prospect_rules(result, prospect, first)
    if first and result.get("es_prospecto", True) and not prospect.get("paused"):  # bienvenida fija de Carlos
        decision.update(send=True, text=FIRST_PITCH, escalate=bool(result.get("escalate")))

    # datos: solo se guardan los que vengan con contenido; nunca se borra lo que ya había
    for src, dst in (("nombre", "name"), ("negocio", "business"), ("giro", "giro"), ("ciudad", "city"), ("que_vende", "sells")):
        val = str(result.get(src) or "").strip()
        if val and val.lower() not in ("sin dato", "n/a", "desconocido"):
            prospect[dst] = val[:120]
    was_complete = prospect.get("stage") == "datos_completos"
    complete = all(prospect.get(k) for k in ("business", "giro", "city", "sells"))
    if result.get("etapa") == "no_interesado":
        prospect["stage"] = "no_interesado"
    elif complete:
        prospect["stage"] = "datos_completos"
    elif not first or decision["send"]:
        prospect["stage"] = "pidiendo_datos"

    second = not first and not prospect.get("pitch2") and not decision["escalate"] and prospect.get("stage") != "no_interesado"
    sent = False
    puede = env("AUTO_REPLY") == "1" or prospect_allowed(chat_id)
    if decision["send"] and decision["text"] and not decision["escalate"] and not first and not second:
        if complete and not was_complete and prospect.get("sample", "pendiente") != "entregada":
            decision["text"] = decision["text"].rstrip() + "\n\n" + PIDE_MATERIAL  # ya dio datos: pedir material
        elif prospect.get("replies", 0) % 3 == 1:  # poca dosis: 1 de cada 3 respuestas
            n = prospect.get("replies", 0)
            decision["text"] = decision["text"].rstrip() + "\n\n" + ARGUMENTOS[(n // 3) % len(ARGUMENTOS)]
    if second and puede and decision["send"] and decision["text"]:  # un solo mensaje: respuesta + lo aprendido
        decision["text"] = decision["text"].rstrip() + "\n\n" + SECOND_PITCH
        second = False
        prospect["pitch2"] = True
    if decision["send"] and decision["text"] and puede:
        res = await wa_send(chat_id, decision["text"])
        sent = res.get("status", 500) < 300
        if sent:
            day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 3600))
            by_day = prospect.get("sentByDay", {})
            prospect["sentByDay"] = {day: by_day.get(day, 0) + 1}
            prospect["replies"] = prospect.get("replies", 0) + 1
            history.append({"role": "assistant", "content": decision["text"]})
    if second and puede:  # lo aprendido + guía + muestra gratis + $500
        if (await wa_send(chat_id, SECOND_PITCH)).get("status", 500) < 300:
            prospect["pitch2"] = True
            history.append({"role": "assistant", "content": SECOND_PITCH})
    prospect["history"] = history[-14:]
    put("prospects", prospect)

    put("inbox", {"phone": phone, "chatId": chat_id, "name": prospect.get("name") or name, "clientId": "",
                  "text": body, "category": "prospecto", "urgency": "alta" if decision["escalate"] else "media",
                  "summary": decision["why"] or f"Prospecto · {prospect['stage']}", "missing": [],
                  "draft": decision["text"], "by": used, "read": False, "sent": sent})

    who = prospect.get("name") or name or phone
    if first and result.get("es_prospecto", True):
        put("tasks", {"title": f"Muestra gratis para {who}", "status": "pendiente",
                      "category": "prospecto", "prospectId": prospect["id"]})
        await tell_owner(f"Visión OS: prospecto nuevo, {who}. Dijo: «{body[:200]}»" + ("" if sent else " (no se le contestó solo)"))
    if decision["escalate"]:
        await tell_owner(f"Te necesito: prospecto {who} ({phone}). Motivo: {decision['why']}. Dijo: «{body[:300]}»")
    elif complete and not was_complete:
        await tell_owner(f"Visión OS: {who} ya dio sus datos. Negocio: {prospect['business']} · {prospect['giro']} · "
                         f"{prospect['city']}. Quiere vender: {prospect['sells']}. Falta mandarle su muestra.")
    return {"ok": True, "category": "prospecto", "auto": sent, "by": used, "stage": prospect["stage"]}


# ------------------------------------------------------------------ aprobación del plan por WhatsApp («aprobado»)
# APPROVAL_MAP (secreto vision-os) = {"<chatId>": "<token del enlace de su ficha en enlaces-clientes>"}.
# Si ese chat escribe «aprobado»: acuse al instante, constancia en vision-os-db, y en ~1 min el guardián le manda
# el estado real de su ficha, con qué se trabaja y los tiempos medidos. Lo que no esté en los datos NO se promete.
APROBADO = re.compile(r"^\W*(aprobad[oa]|apruebo)\b", re.I)
ACK_APPROVAL = "Recibido ✅ Gracias por aprobar tu plan. En un minuto te respondemos con el estado de tus anuncios."
TECH_STACK = ("WhatsApp conectado a nuestro sistema en la nube (Modal), un modelo de IA propio que lee tus mensajes "
              "y ordena los cambios, y vigilancia automática de tus anuncios cada 20 minutos de 7 a 23 h.")
APPROVAL_SCHEMA = {"type": "object", "required": ["reply"], "properties": {"reply": _S}}
APPROVAL_SYSTEM = """Escribes por WhatsApp a un cliente de Visión Agencia (Nogales, Sonora) que acaba de aprobar su plan.
Español mexicano, amable, directo, máximo 8 renglones, sin tecnicismos de marketing (nada de CTR, creativos, campaña de tráfico).
Háblale de TÚ. Usa SOLO los datos que te doy. Di: 1) que su aprobación quedó registrada, 2) en qué va (cuántas imágenes
ya están listas para publicar y cuántas seguimos mejorando), 3) con qué trabajamos (el sistema), 4) el siguiente paso.
NO menciones tiempos ni segundos: se agregan solos al final del mensaje.
Prohibido: precios, cifras de dinero, fechas o plazos que no vengan en los datos, garantías de resultados.
Si no viene plazo de publicación, di que Carlos le confirma la fecha. Responde SOLO el JSON {"reply": "..."}."""


def approval_map() -> dict:
    try:
        return json.loads(env("APPROVAL_MAP", "{}") or "{}")
    except Exception:
        return {}


COMO_VA = re.compile(r"(c[oó]mo\s+va|c[oó]mo\s+vamos|avance|estatus|status|en\s+qu[eé]\s+va|qu[eé]\s+onda\s+con|ya\s+est[aá]|para\s+cu[aá]ndo)", re.I)


def bitacora(token: str, evento: str):
    """Registro por cliente (lo que su contenedor va haciendo). Se escribe aparte; no frena la respuesta."""
    k = f"bitacora:{token}"
    items = (db.get(k, []) or [])[-40:]
    items.append({"cuando": sonora_now(), "evento": evento[:300]})
    db[k] = items


def resumen_rapido(token: str) -> str:
    f = ficha(token)
    piezas = f.get("extras", []) or []
    listas = sum(1 for p in piezas if float(p.get("nota") or 0) >= 8)
    log = (db.get(f"bitacora:{token}", []) or [])[-5:]
    lineas = "\n".join(f"• {e['cuando'][-5:]} · {e['evento']}" for e in log) or "• Sin movimientos registrados todavía."
    return (f"Así va tu proyecto ({sonora_now()[-5:]} h, hora de Sonora) 📋\n{lineas}\n\n"
            f"Imágenes listas para publicar: {listas} de {len(piezas)}.\n"
            f"Todo corre en tu propio contenedor en la nube; cualquier duda escríbela aquí.")


def prospect_allowed(chat_id: str) -> bool:
    """PROSPECT_ALLOW: chats que Carlos ordenó atender desde Modal aunque AUTO_REPLY=0 o ya haya historial."""
    return chat_id in [x.strip() for x in env("PROSPECT_ALLOW").split(",") if x.strip()]


def is_approval(m: dict) -> bool:
    return m["sender"] in approval_map() and bool(APROBADO.search(m["body"] or ""))


def sonora_now() -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.gmtime(time.time() - 7 * 3600))


def ficha(token: str) -> dict:
    try:
        return modal.Dict.from_name("enlaces-clientes")[token] or {}
    except Exception:
        return {}


async def approval_ack(m: dict) -> dict:
    """Corre en el webhook: acuse inmediato + constancia. Idempotente por chat y versión del plan."""
    token = approval_map()[m["sender"]]
    f = ficha(token)
    plan = f.get("mensaje", "")
    key = f"aprobado:{m['sender']}:{hashlib.sha1(plan.encode()).hexdigest()[:10]}"
    if key in db:
        return {"dup": True}
    t0 = time.time()
    res = await wa_send(m["sender"], ACK_APPROVAL, kind="acuse")
    rec = {"chatId": m["sender"], "cliente": f.get("cliente", ""), "cuando": sonora_now(), "plan": plan,
           "ackStatus": res.get("status"), "ackSeg": round(time.time() - t0, 1), "recibido": m.get("t0", t0)}
    db[key] = rec
    bitacora(token, "Aprobó su plan por WhatsApp; orden recibida")
    return rec


async def approval_reply(m: dict) -> dict:
    """Trabajo de fondo: arma el estado con datos reales y lo manda (guardián; si falla, plantilla fija)."""
    t_start = time.time()
    token = approval_map()[m["sender"]]
    f = ficha(token)
    plan = f.get("mensaje", "")
    rec = db.get(f"aprobado:{m['sender']}:{hashlib.sha1(plan.encode()).hexdigest()[:10]}", {}) or {}
    piezas = f.get("extras", []) or []
    listas = [p.get("titulo", "") for p in piezas if float(p.get("nota") or 0) >= 8]
    ajuste = [p.get("titulo", "") for p in piezas if float(p.get("nota") or 0) < 8]
    plazo = env("PLAZO_PUBLICACION", "")
    datos = {"cliente": f.get("cliente", ""), "aprobado_el": rec.get("cuando", sonora_now()),
             "piezas_listas_8_o_mas": listas, "piezas_en_ajuste": ajuste,
             "sistema": TECH_STACK, "acuse_enviado_en_seg": rec.get("ackSeg"),
             "plazo_publicacion": plazo or "SIN PLAZO CONFIRMADO: Carlos le confirma la fecha",
             "siguiente_paso": "Seguimos mejorando las imágenes que faltan hasta que pasen nuestra calificación, y preparamos la publicación; nada sale sin tu visto bueno."}
    msgs = [{"role": "system", "content": APPROVAL_SYSTEM},
            {"role": "user", "content": json.dumps(datos, ensure_ascii=False)}]
    t_ai = time.time()
    try:
        out = await guardian(msgs, APPROVAL_SCHEMA, max_tokens=500)
        text, by = str(out.get("reply") or "").strip(), "guardián"
    except Exception:
        text, by = "", "plantilla"
    ai_seg = round(time.time() - t_ai, 1)
    if not text or MONEY.search(text):
        text, by = "", "plantilla"
    if not text:
        text = (f"¡Listo! Tu aprobación quedó registrada ({datos['aprobado_el']}).\n"
                f"Piezas listas para publicar: {len(listas)} de {len(piezas)}. Las demás las seguimos ajustando.\n"
                f"Con qué trabajamos: {TECH_STACK}\n"
                + (f"Publicación: {plazo}.\n" if plazo else "Carlos te confirma la fecha de publicación.\n"))
    medido = f"\n\n⏱ Tiempos medidos: acuse en {rec.get('ackSeg', '?')} s · esta respuesta se armó en {ai_seg} s."
    res = await wa_send(m["sender"], (text + medido)[:1500])
    rec.update(respuesta=text, por=by, iaSeg=ai_seg, totalSeg=round(time.time() - t_start, 1), envioStatus=res.get("status"))
    db[f"aprobado:{m['sender']}:{hashlib.sha1(plan.encode()).hexdigest()[:10]}"] = rec
    put("inbox", {"phone": only_digits(m["sender"]), "chatId": m["sender"], "name": f.get("cliente", ""), "clientId": "",
                  "text": m["body"], "category": "seguimiento", "urgency": "alta", "summary": "Aprobó su plan por WhatsApp",
                  "missing": [], "draft": text, "by": by, "read": False, "sent": res.get("status", 500) < 300})
    await tell_owner(f"Visión OS: {f.get('cliente') or m['sender']} escribió «aprobado» ({rec.get('cuando')}). "
                     f"Se le respondió solo ({by}, {ai_seg} s). Revisa la bandeja.")
    return {"ok": True, "approval": True, "by": by}


async def process_message(m: dict) -> dict:
    sender, body, name = m["sender"], m["body"], m["name"]
    if is_approval(m):
        return await approval_reply(m)
    if is_owner(sender):
        if body.startswith("/"):
            await handle_owner_command(body, sender)
            return {"owner_command": True}
        return {"ignored": "dueño"}
    if blocked(sender):
        return {"ignored": "bloqueado"}
    if sender in approval_map() and COMO_VA.search(body or ""):  # «¿cómo va?»: respuesta rápida de la bitácora, sin Fable
        token = approval_map()[sender]
        res = await wa_send(sender, resumen_rapido(token))
        bitacora(token, "Preguntó cómo va; se le mandó el resumen de la bitácora")
        return {"ok": True, "como_va": True, "sent": res.get("status", 500) < 300}
    if sender in approval_map():  # cliente con ficha: lo atiende SU contenedor (Fable revisa y actualiza su estrategia)
        token = approval_map()[sender]
        await Cliente(token=token).revisar.spawn.aio(sender, body, "")
        return {"ok": True, "cliente_contenedor": token[:6]}

    client = find_client(sender)
    if not client:
        return await attend_prospect(sender, body, name)

    ctx = (f"Cliente: {client['name']} ({client.get('business', '')}). Fase: {client.get('phase', '')}. "
           f"Nota: {client.get('note', '')}")
    result = await triage(body, ctx)
    put("inbox", {"phone": only_digits(sender), "chatId": sender, "name": name, "clientId": client["id"],
                  "text": body, "category": result["category"], "urgency": result["urgency"],
                  "summary": result["summary"], "missing": result["missing"],
                  "draft": result["reply"], "by": result["by"], "read": False, "sent": False})
    if result["urgency"] == "alta" or result["category"] == "campaña":
        put("tasks", {"title": result["summary"] or body[:80], "status": "pendiente",
                      "category": result["category"], "clientId": client["id"]})
    return {"ok": True, "category": result["category"]}


# ---------------------------------------------------------------- un contenedor por cliente (revisor de estrategia con Fable)
# Cada cliente es una instancia Cliente(token=...) => su propio contenedor. Decide con lo que tiene en memoria
# (ficha + últimos mensajes) y la constancia (bitácora, versión anterior de la ficha) se escribe después.
fable_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl", "ca-certificates")
    .run_commands("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -", "apt-get install -y nodejs",
                  "npm install -g @anthropic-ai/claude-code")
    .pip_install("httpx")
)
FABLE_MODEL = "claude-fable-5-2"
ACK_REVIEW = "Recibido ✅ Lo estamos revisando con tu ficha; en un par de minutos te respondemos."
REVIEW_PROMPT = """Eres el estratega de Visión Agencia (Nogales, Sonora). Revisas la ficha de un cliente cada vez que llega un mensaje
en su chat (del cliente o una nota de Carlos, el dueño) y decides si la estrategia debe cambiar.

FICHA ACTUAL (JSON): {ficha}
ÚLTIMOS MENSAJES DEL CHAT (más viejo a más nuevo; CARLOS = el dueño de la agencia, CLIENTE = el cliente): {chat}
MENSAJE QUE DISPARA ESTA REVISIÓN (lo escribió {autor}): {trigger}\nNo le agradezcas un «aprobado» al cliente si no lo escribió él. Si lo escribió CARLOS, al cliente dile que revisamos su plan y lo mejoramos.

Reglas que no se rompen:
- Nada de precios, cifras de dinero, descuentos inventados, fechas ni plazos (Carlos los confirma).
- Si se pide una promoción (p. ej. Buen Fin) y no viene su detalle, escribe «promoción de Buen Fin (Carlos te confirma el detalle)».
- No prometas resultados. Nada se publica sin visto bueno del cliente.
- Al cliente háblale de TÚ, español mexicano, cálido y directo, sin tecnicismos (nada de CTR, creativos, campaña de tráfico).

Responde SOLO un JSON:
{{"cambia_estrategia": true|false,
 "plan_una_frase": "la conclusión a ejecutar en UNA frase para lo alto de la ficha, terminando con: 👉 Si estás de acuerdo, respóndenos «aprobado» por WhatsApp.",
 "estrategia": "estrategia completa para la ficha, en pasos simples (máx. 12 renglones)",
 "como_se_lograra": ["paso concreto 1", "paso 2", "..."],
 "respuesta_cliente": "mensaje de WhatsApp (máx. 8 renglones): di que entendimos, que su ficha se reorganiza con esta estrategia, cómo se va a lograr en 2-4 puntos, y que cada mensaje suyo lo revisa nuestro sistema y ajusta su estrategia si hace falta."}}"""


async def fetch_chat(chat_id: str, limit: int = 25) -> list:
    import httpx
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{WAAPI}/instances/{instance()}/client/action/fetch-messages",
                         headers={"Authorization": f"Bearer {env('WAAPI_TOKEN')}"}, json={"chatId": chat_id, "limit": limit})
    out = []
    for i in (_find_messages(r.json()) or []):
        m = i.get("message", i)
        if str(m.get("type", "chat")) in SYSTEM_TYPES or not m.get("body"):
            continue
        out.append(("CARLOS" if m.get("fromMe") else "CLIENTE") + ": " + str(m["body"])[:500])
    return out


cuentas_vol = modal.Volume.from_name("claude-cuentas")


@app.cls(image=fable_image, volumes={"/cuentas": cuentas_vol}, timeout=900, scaledown_window=300, max_containers=1)
class Cliente:
    token: str = modal.parameter()

    @modal.enter()
    def cargar(self):
        self.ficha = ficha(self.token)  # memoria del contenedor: decide con esto, sin consultar a nadie más
        self.ultimo_ack = 0

    def fable(self, prompt: str) -> dict:
        import subprocess
        e = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "CLAUDE"))}  # que mande la sesión de la cuenta
        e["CLAUDE_CONFIG_DIR"] = "/cuentas/" + env("FABLE_CUENTA", "claude3")
        cuentas_vol.reload()
        r = subprocess.run(["claude", "-p", prompt, "--model", FABLE_MODEL, "--output-format", "text"],
                           capture_output=True, text=True, timeout=600, cwd="/tmp", env=e)
        try:
            cuentas_vol.commit()  # guarda el token si Claude Code lo renovó
        except Exception:
            pass
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout)[:300])
        return loose_json(r.stdout)

    @modal.method()
    async def revisar(self, chat_id: str, trigger: str, nota: str = "", responder: bool = True) -> dict:
        t0 = time.time()
        if responder and time.time() - self.ultimo_ack > 300:
            await wa_send(chat_id, ACK_REVIEW, kind="acuse")
            self.ultimo_ack = time.time()
        dia = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 3600))
        cupo_key = f"fable:{self.token}:{dia}"
        usados = db.get(cupo_key, 0) or 0
        if usados >= int(env("FABLE_MAX_DIA", "2")):  # tope diario para no acabarnos Fable
            put("inbox", {"phone": only_digits(chat_id), "chatId": chat_id, "name": self.ficha.get("cliente", ""), "clientId": "",
                          "text": trigger, "category": "seguimiento", "urgency": "media",
                          "summary": "Tope de Fable del día alcanzado: revisar a mano", "missing": [], "draft": "",
                          "by": "tope", "read": False, "sent": False})
            await tell_owner(f"Visión OS: {self.ficha.get('cliente')} escribió y ya usó sus {usados} revisiones de Fable de hoy. "
                             f"Mensaje: «{trigger[:200]}»")
            if responder:
                await wa_send(chat_id, "Anotado ✅ Ya quedó en tu proyecto y Carlos lo revisa contigo en cuanto pueda. "
                                       "Escribe «¿cómo va?» cuando quieras para ver el avance.")
            bitacora(self.token, f"Pidió: «{trigger[:120]}» (anotado para Carlos)")
            return {"ok": True, "tope": True}
        db[cupo_key] = usados + 1
        chat = await fetch_chat(chat_id)
        vista = {k: self.ficha.get(k) for k in ("cliente", "mensaje", "estrategia")}
        vista["piezas"] = [{"titulo": p.get("titulo"), "nota": p.get("nota")} for p in self.ficha.get("extras", []) or []]
        prompt = REVIEW_PROMPT.format(ficha=json.dumps(vista, ensure_ascii=False)[:6000],
                                      chat=json.dumps(chat[-25:], ensure_ascii=False), trigger=(nota or trigger)[:800], autor="CARLOS" if nota else "CLIENTE")
        try:
            out, by = self.fable(prompt), "fable"
        except Exception as e:
            await tell_owner(f"Visión OS: Fable no pudo revisar la ficha de {self.ficha.get('cliente')}: {str(e)[:200]}")
            return {"ok": False, "error": str(e)[:200]}
        texto = str(out.get("respuesta_cliente") or "").strip()
        if MONEY.search(texto + str(out.get("plan_una_frase", ""))):
            await tell_owner(f"Visión OS: la propuesta de Fable para {self.ficha.get('cliente')} traía cifras; no se mandó. Revisa la bandeja.")
            responder = False
        # 1) decisión rápida: contestar ya
        sent = False
        if responder and texto:
            res = await wa_send(chat_id, texto[:1500])
            sent = res.get("status", 500) < 300
        # 2) constancia después: ficha reorganizada + versión anterior + bitácora
        if out.get("cambia_estrategia") and out.get("plan_una_frase"):
            d = modal.Dict.from_name("enlaces-clientes")
            f = d[self.token]
            f.setdefault("versiones", []).append({"cuando": sonora_now(), "mensaje": f.get("mensaje", ""), "estrategia": f.get("estrategia", "")})
            f["versiones"] = f["versiones"][-10:]
            f["mensaje"] = out["plan_una_frase"][:700]
            pasos = "\n".join(f"{i+1}. {p}" for i, p in enumerate(out.get("como_se_lograra") or []))
            f["estrategia"] = (str(out.get("estrategia") or "") + ("\n\nCÓMO SE LOGRARÁ\n" + pasos if pasos else ""))[:4000]
            f["revisadoEl"] = sonora_now()
            d[self.token] = f
            self.ficha = f
        bitacora(self.token, "Fable revisó su ficha" + (" y reorganizó la estrategia" if out.get("cambia_estrategia") else " (sin cambios)"))
        put("inbox", {"phone": only_digits(chat_id), "chatId": chat_id, "name": self.ficha.get("cliente", ""), "clientId": "",
                      "text": trigger, "category": "seguimiento", "urgency": "media",
                      "summary": "Fable revisó su ficha" + (" y la reorganizó" if out.get("cambia_estrategia") else ""),
                      "missing": [], "draft": texto, "by": by, "read": False, "sent": sent})
        await tell_owner(f"Visión OS: Fable revisó la ficha de {self.ficha.get('cliente')} "
                         f"({'la reorganizó' if out.get('cambia_estrategia') else 'sin cambios'}; {round(time.time()-t0)} s; "
                         f"{'respuesta enviada' if sent else 'respuesta NO enviada'}).")
        return {"ok": True, "cambia": bool(out.get("cambia_estrategia")), "sent": sent, "seg": round(time.time() - t0, 1),
                "plan": out.get("plan_una_frase"), "como": out.get("como_se_lograra"), "respuesta": texto}


ARRANQUE_PROMPT = """Eres el estratega de Visión Agencia. El contenedor propio del cliente acaba de ejecutar su orden.
CLIENTE: {cliente}
ESTRATEGIA VIGENTE: {estrategia}
REFERENCIAS ENCONTRADAS EN INSTAGRAM (ordenadas por vistas): {refs}
ESTADO DEL SISTEMA (medido ahora): {estado}
1) Escoge UNA referencia (la que mejor sirve para su objetivo) y di por qué en una línea.
2) Escribe el mensaje de WhatsApp para el cliente (TÚ, español mexicano, máx. 12 renglones, sin tecnicismos de marketing):
   - que recibimos su orden y ya se está ejecutando en SU PROPIO CONTENEDOR en la nube (un espacio de trabajo solo para su negocio,
     que no se comparte ni espera turno con otros clientes);
   - qué sistemas están activos (usa el estado medido, sin inventar);
   - la referencia escogida y por qué, en palabras simples;
   - tiempo de espera SOLO de lo medido: di cuánto tardó la búsqueda de referencias y que cada mensaje suyo se contesta en segundos;
     para las imágenes y el video nuevos di que Carlos le confirma la fecha (no inventes plazos);
   - que puede escribir «¿cómo va?» cuando quiera y recibe el avance al momento.
Nada de precios ni cifras de dinero. Responde SOLO JSON: {{"referencia_url": "...", "por_que": "...", "mensaje": "..."}}"""


async def apify_reels(hashtags: list, limit: int = 30) -> list:
    import httpx
    url = "https://api.apify.com/v2/acts/apify~instagram-hashtag-scraper/run-sync-get-dataset-items"
    async with httpx.AsyncClient(timeout=330) as c:
        r = await c.post(url, params={"token": env("APIFY_TOKEN"), "timeout": 300},
                         json={"hashtags": hashtags, "resultsType": "reels", "resultsLimit": limit})
    r.raise_for_status()
    items = []
    for it in r.json() if isinstance(r.json(), list) else []:
        views = it.get("videoPlayCount") or it.get("videoViewCount") or it.get("playsCount") or 0
        if it.get("url"):
            items.append({"url": it["url"], "vistas": int(views or 0), "likes": it.get("likesCount", 0),
                          "texto": (it.get("caption") or "")[:200], "cuenta": it.get("ownerUsername", "")})
    return sorted(items, key=lambda x: x["vistas"], reverse=True)


@app.function(image=fable_image, volumes={"/cuentas": cuentas_vol}, secrets=[modal.Secret.from_name("apify")], timeout=900)
async def arrancar_cliente(token: str, chat_id: str, hashtags: list, enviar: bool = True) -> dict:
    """Ejecuta la orden del cliente en su flujo: referencias (Apify) -> Fable escoge -> mensaje con estado y tiempos medidos."""
    import subprocess
    f = ficha(token)
    bitacora(token, "Orden recibida: buscar referencias en Instagram y rehacer imágenes y video con Buen Fin")
    t0 = time.time()
    try:
        refs = await apify_reels(hashtags)
        apify_ok = True
    except Exception as e:
        refs, apify_ok = [], False
        bitacora(token, f"Búsqueda de referencias falló: {str(e)[:120]}")
    apify_seg = round(time.time() - t0)
    bitacora(token, f"Búsqueda de referencias terminada: {len(refs)} reels revisados en {apify_seg} s")
    estado = {"contenedor_propio": "activo", "whatsapp_conectado": True, "busqueda_referencias": "ok" if apify_ok else "falló",
              "reels_revisados": len(refs), "segundos_busqueda": apify_seg, "fable": "activo", "respuesta_a_mensajes": "segundos",
              "vigilancia_automatica": "cada 20 min de 7 a 23 h"}
    prompt = ARRANQUE_PROMPT.format(cliente=f.get("cliente", ""), estrategia=(f.get("estrategia") or "")[:2500],
                                    refs=json.dumps(refs[:8], ensure_ascii=False), estado=json.dumps(estado, ensure_ascii=False))
    e = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "CLAUDE"))}
    e["CLAUDE_CONFIG_DIR"] = "/cuentas/" + env("FABLE_CUENTA", "claude3")
    cuentas_vol.reload()
    r = subprocess.run(["claude", "-p", prompt, "--model", FABLE_MODEL], capture_output=True, text=True, timeout=600, cwd="/tmp", env=e)
    try:
        cuentas_vol.commit()
    except Exception:
        pass
    out = loose_json(r.stdout) if r.returncode == 0 else {}
    msg = str(out.get("mensaje") or "").strip()
    if out.get("referencia_url"):
        d = modal.Dict.from_name("enlaces-clientes")
        fx = d[token]
        fx["referencias"] = refs[:5]
        fx["estrategia"] = (fx.get("estrategia") or "") + f"\n\nREFERENCIA ESCOGIDA: {out['referencia_url']} — {out.get('por_que', '')}"
        d[token] = fx
        bitacora(token, f"Referencia escogida: {out['referencia_url']}")
    sent = False
    if enviar and msg and not MONEY.search(msg):
        sent = (await wa_send(chat_id, msg[:1600])).get("status", 500) < 300
        if sent:
            bitacora(token, "Se le mandó el arranque con estado del sistema y tiempos")
    await tell_owner(f"Visión OS: arranque de {f.get('cliente')} — {len(refs)} reels en {apify_seg} s; referencia "
                     f"{out.get('referencia_url', 'sin escoger')}; mensaje {'enviado' if sent else 'NO enviado'}. "
                     "Falta: generar imágenes y video nuevos (dime con qué herramienta).")
    return {"refs": refs[:5], "elegida": out.get("referencia_url"), "por_que": out.get("por_que"), "mensaje": msg,
            "sent": sent, "apify_seg": apify_seg, "fable_err": (r.stderr or "")[:200] if r.returncode else ""}


DIRECTOR_PROMPT = """Somos los DIRECTORES CREATIVOS de Visión Agencia. El cliente mandó información nueva y le debemos la mejor
respuesta de cómo vamos a mejorar su estrategia para vender mejor.

FICHA Y ESTRATEGIA ACTUAL: {ficha}
CONVERSACIÓN RECIENTE (CLIENTE = el cliente; CARLOS = el dueño): {chat}
MATERIAL QUE YA NOS MANDÓ: {material}
REFERENCIAS ENCONTRADAS, UNA BÚSQUEDA POR CADA FUNCIÓN DE SU SERVICIO (ordenadas por vistas): {refs}
LO QUE REVISAMOS CONTRA FACEBOOK Y LAS REGLAS EN MÉXICO (úsalo para dar seguridad, sin tecnicismos): {facebook}

Haz esto:
1) Para cada función de su servicio escoge la mejor referencia y di qué ángulo tomamos de ella (una línea).
2) Mejora la estrategia: qué anuncio sale para qué función, en qué orden, y cómo entra su información nueva (número, promoción).
3) Si su promoción tiene un riesgo con Facebook o con las reglas en México, dilo con tacto y propón la versión segura que logra lo mismo.
4) Mensaje de WhatsApp al cliente (TÚ, español mexicano, cálido, de director creativo, máx. 16 renglones): qué haríamos para mejorar
   su estrategia, las referencias (con su enlace) por función, lo que revisamos con Facebook para vender con seguridad, y qué sigue.
Prohibido: precios, cifras de dinero, fechas o plazos, resultados garantizados. Nada se publica sin su visto bueno.
Responde SOLO JSON: {{"plan_una_frase": "conclusión a ejecutar en una frase para lo alto de la ficha, terminando con 👉 Si estás de acuerdo, respóndenos «aprobado» por WhatsApp.",
"estrategia": "estrategia mejorada en pasos simples (máx. 16 renglones)", "referencias": [{{"funcion": "...", "url": "...", "angulo": "..."}}],
"facebook": ["punto de seguridad 1", "..."], "mensaje": "..."}}"""

FACEBOOK_AMY = [
    "Sorteos: en México un sorteo con premio normalmente necesita permiso de la Secretaría de Gobernación; un premio seguro "
    "(por ejemplo, el 8.º viaje gratis para todos) logra lo mismo sin ese trámite.",
    "Si se anuncia un sorteo en Facebook, la página debe publicar sus bases y aclarar que Facebook no lo patrocina; no se puede "
    "pedir compartir en el muro como requisito.",
    "Anuncios para reclutar choferes: Facebook los trata como anuncios de empleo y limita segmentar por edad o género.",
    "No se puede insinuar datos personales del que ve el anuncio (por ejemplo «¿eres mujer y viajas sola?»): se dice «viaja segura».",
    "El número de WhatsApp del anuncio debe ser el oficial y verificado del negocio, para que el botón funcione.",
]
FUNCIONES_AMY = {
    "Pedir taxi desde el celular": ["pidetutaxi", "taxiapp"],
    "Viaje seguro y compartir viaje": ["viajeseguro", "taxiseguro"],
    "Botón de emergencia": ["botondepanico", "seguridadvial"],
    "Promoción 8.º viaje / Buen Fin": ["buenfin", "viajegratis"],
    "Reclutar choferes": ["choferes", "trabajodechofer"],
}


@app.function(image=fable_image, volumes={"/cuentas": cuentas_vol}, secrets=[modal.Secret.from_name("apify")], timeout=900)
async def director_creativo(token: str, chat_id: str, funciones: dict, facebook: list, material: list, enviar: bool = False) -> dict:
    import subprocess, asyncio
    f = ficha(token)
    dia = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 3600))
    cupo_key = f"fable:{token}:{dia}"
    usados = db.get(cupo_key, 0) or 0
    if usados >= int(env("FABLE_MAX_DIA", "2")):
        return {"tope": True}
    db[cupo_key] = usados + 1
    bitacora(token, "Dirección creativa: buscando referencias por cada función y revisando contra Facebook")
    t0 = time.time()
    res = await asyncio.gather(*[apify_reels(tags, 15) for tags in funciones.values()], return_exceptions=True)
    refs = {fn: ([] if isinstance(r, Exception) else r[:3]) for fn, r in zip(funciones, res)}
    total = sum(0 if isinstance(r, Exception) else len(r) for r in res)
    bitacora(token, f"Referencias por función: {total} reels revisados en {round(time.time() - t0)} s")
    chat = await fetch_chat(chat_id, 30)
    vista = {k: f.get(k) for k in ("cliente", "mensaje", "estrategia")}
    prompt = DIRECTOR_PROMPT.format(ficha=json.dumps(vista, ensure_ascii=False)[:5000], chat=json.dumps(chat[-20:], ensure_ascii=False),
                                    material=json.dumps(material, ensure_ascii=False), refs=json.dumps(refs, ensure_ascii=False)[:9000],
                                    facebook=json.dumps(facebook, ensure_ascii=False))
    e = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "CLAUDE"))}
    e["CLAUDE_CONFIG_DIR"] = "/cuentas/" + env("FABLE_CUENTA", "claude3")
    cuentas_vol.reload()
    r = subprocess.run(["claude", "-p", prompt, "--model", FABLE_MODEL], capture_output=True, text=True, timeout=700, cwd="/tmp", env=e)
    try:
        cuentas_vol.commit()
    except Exception:
        pass
    out = loose_json(r.stdout) if r.returncode == 0 else {}
    if out.get("plan_una_frase"):
        d = modal.Dict.from_name("enlaces-clientes")
        fx = d[token]
        fx.setdefault("versiones", []).append({"cuando": sonora_now(), "mensaje": fx.get("mensaje", ""), "estrategia": fx.get("estrategia", "")})
        fx["versiones"] = fx["versiones"][-10:]
        fx["mensaje"] = out["plan_una_frase"][:700]
        refs_txt = "\n".join(f"• {x.get('funcion')}: {x.get('url')} — {x.get('angulo')}" for x in out.get("referencias", []))
        fb_txt = "\n".join(f"• {x}" for x in out.get("facebook", []))
        fx["estrategia"] = (str(out.get("estrategia") or "") + "\n\nREFERENCIAS POR FUNCIÓN\n" + refs_txt +
                            "\n\nREVISADO CON FACEBOOK\n" + fb_txt)[:6000]
        fx["revisadoEl"] = sonora_now()
        d[token] = fx
        bitacora(token, "Dirección creativa: estrategia mejorada y ficha reorganizada")
    msg = str(out.get("mensaje") or "").strip()
    sent = False
    if enviar and msg and not MONEY.search(msg):
        sent = (await wa_send(chat_id, msg[:2000])).get("status", 500) < 300
        if sent:
            bitacora(token, "Se le mandó la propuesta de dirección creativa")
    return {"ok": bool(out), "seg": round(time.time() - t0), "out": out, "sent": sent, "err": (r.stderr or "")[:200] if r.returncode else ""}


# ---------------------------------------------------------------- vigía de la conexión de WhatsApp
async def alerta_fuera(texto: str) -> list:
    """Avisa por canales que NO dependen de WhatsApp (secreto «alertas»): ntfy (NTFY_TOPIC) y/o correo
    (ALERTA_EMAIL + GMAIL_USER + GMAIL_APP_PASSWORD). Devuelve los canales que sí salieron."""
    import httpx
    ok = []
    if env("NTFY_TOPIC"):
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(f"https://ntfy.sh/{env('NTFY_TOPIC')}", content=texto.encode(),
                                 headers={"Title": "Vision OS: WhatsApp", "Priority": "urgent", "Tags": "warning"})
            if r.status_code < 300:
                ok.append("ntfy")
        except Exception:
            pass
    if env("ALERTA_EMAIL") and env("GMAIL_USER") and env("GMAIL_APP_PASSWORD"):
        try:
            import smtplib
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = "Visión OS: WhatsApp desconectado", env("GMAIL_USER"), env("ALERTA_EMAIL")
            msg.set_content(texto)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as srv:
                srv.login(env("GMAIL_USER"), env("GMAIL_APP_PASSWORD"))
                srv.send_message(msg)
            ok.append("correo")
        except Exception:
            pass
    return ok


async def estado_waapi() -> str:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"https://waapi.app/api/v1/instances/{instance()}/client/status",
                            headers={"Authorization": f"Bearer {env('WAAPI_TOKEN')}"})
        return str(((r.json().get("clientStatus") or {}).get("instanceStatus")) or f"http {r.status_code}")
    except Exception as e:
        return f"error: {str(e)[:80]}"


async def chats_durante_caida(desde: float) -> list:
    """Chats (no grupos) que escribieron mientras WhatsApp estuvo caído: para que Carlos decida si se atienden."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{WAAPI}/instances/{instance()}/client/action/get-chats",
                             headers={"Authorization": f"Bearer {env('WAAPI_TOKEN')}"}, json={})
        chats = (r.json().get("data") or {}).get("data") or []
    except Exception:
        return []
    out = []
    for ch in chats:
        cid = (ch.get("id") or {}).get("_serialized", "")
        if cid.endswith("@g.us") or cid == "status@broadcast" or ch.get("timestamp", 0) < desde - 300:
            continue
        if ch.get("unreadCount"):
            out.append(f"• {ch.get('name') or only_digits(cid)} ({ch.get('unreadCount')} sin leer)")
    return out[:15]


async def vigia_whatsapp():
    """Cada 5 min: si la instancia de WaAPI deja de estar «ready», avisa fuera de WhatsApp (repite cada hora mientras
    siga caída). Cuando regresa, manda a Carlos por WhatsApp cuánto duró y quién escribió mientras tanto."""
    st = await estado_waapi()
    prev = db.get("wa_vigia") or {"ok": True, "desde": 0, "aviso": 0}
    now = time.time()
    if st == "ready":
        if not prev.get("ok"):
            mins = int((now - prev.get("desde", now)) / 60)
            quien = await chats_durante_caida(prev.get("desde", now))
            await tell_owner(f"Visión OS: WhatsApp reconectado ✅ Estuvo caído unos {mins} min. "
                             + ("Escribieron mientras tanto (esos mensajes NO los vio el sistema):\n" + "\n".join(quien)
                                if quien else "No veo chats con mensajes sin leer de ese rato."))
            await alerta_fuera(f"WhatsApp reconectado. Estuvo caído unos {mins} min.")
        db["wa_vigia"] = {"ok": True, "desde": 0, "aviso": 0, "visto": now}
        return {"estado": st}
    if prev.get("ok"):
        prev = {"ok": False, "desde": now, "aviso": 0}
    if now - prev.get("aviso", 0) > 3600:
        canales = await alerta_fuera(
            f"Tu WhatsApp se desconectó de WaAPI (estado: {st}). No entran ni salen mensajes del sistema. "
            f"Entra a waapi.app, instancia {instance()}, y escanea el QR desde WhatsApp > Dispositivos vinculados.")
        prev["aviso"] = now
        prev["canales"] = canales
    prev["visto"], prev["estado"] = now, st
    db["wa_vigia"] = prev
    return {"estado": st, "canales": prev.get("canales")}


@app.function(timeout=600, max_containers=5)
async def procesar(m: dict):
    """Trabajo de fondo: el webhook ya contestó 200 a WaAPI; aquí piensa la IA y se responde."""
    try:
        return await process_message(m)
    except Exception as e:
        await tell_owner(f"Visión OS: falló al procesar un mensaje de {m.get('name') or m.get('sender')}: {str(e)[:200]}")
        raise


# ---------------------------------------------------------------- GitHub
async def gh(method: str, path: str, body: dict | None = None):
    import httpx
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.request(
            method, GITHUB + path, json=body,
            headers={"Authorization": f"Bearer {env('GITHUB_TOKEN')}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else {}


async def deploy(repo: str) -> dict:
    """Despliega con un deploy hook de Render (RENDER_HOOKS) o dispara workflow deploy.yml."""
    hooks = json.loads(env("RENDER_HOOKS", "{}") or "{}")
    short = repo.split("/")[-1]
    if short in hooks:
        import httpx
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(hooks[short])
            return {"via": "render", "status": r.status_code}
    full = repo if "/" in repo else f"{env('GITHUB_OWNER')}/{repo}"
    info = await gh("GET", f"/repos/{full}")
    await gh("POST", f"/repos/{full}/actions/workflows/deploy.yml/dispatches", {"ref": info["default_branch"]})
    return {"via": "github-actions", "repo": full, "ref": info["default_branch"]}


# ---------------------------------------------------------------- API web
def build_web():
    from fastapi import Depends, FastAPI, Header, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    web = FastAPI(title="Visión OS")

    def auth(x_admin_key: str = Header(default="")):
        key = env("ADMIN_KEY")
        if not key or not hmac.compare_digest(x_admin_key.encode(), key.encode()):
            raise HTTPException(401, "Clave incorrecta")

    @web.get("/", response_class=HTMLResponse)
    def panel():
        html = open("/root/panel.html", encoding="utf-8").read()
        head = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body>')
        return head + html + "</body></html>"

    @web.get("/api/ping")
    def ping(_=Depends(auth)):
        seed_if_empty()
        return {"ok": True, "github": bool(env("GITHUB_TOKEN")), "waapi": bool(env("WAAPI_TOKEN")),
                "coo": True, "claude": bool(env("ANTHROPIC_API_KEY")),
                "meta": bool(env("META_TOKEN")), "auto_reply": env("AUTO_REPLY") == "1",
                "whatsapp": (db.get("wa_vigia") or {}).get("estado", "ready") if not (db.get("wa_vigia") or {"ok": True}).get("ok") else "ready"}

    @web.post("/api/vigia")  # lo llama GitHub Actions cada 5 min (Modal ya no deja más funciones programadas)
    async def vigia(_=Depends(auth)):
        return await vigia_whatsapp()

    # --- WhatsApp
    @web.post("/webhook/{secret}")
    async def webhook(secret: str, request: Request):
        expected = env("WEBHOOK_SECRET")
        if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
            raise HTTPException(404)
        payload = await request.json()

        if env("FORWARD_URL"):  # WaAPI solo manda a una URL: se reenvía tal cual al otro webhook, en segundo plano
            async def _reenviar(p):
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=10) as c:
                        await c.post(env("FORWARD_URL"), json=p)
                except Exception:
                    pass
            t = asyncio.create_task(_reenviar(payload))
            _tareas.add(t)
            t.add_done_callback(_tareas.discard)

        if payload.get("instanceId") is not None and str(payload.get("instanceId")) != instance():
            raise HTTPException(401, "instancia")
        if payload.get("event") not in (None, "message", "message_create"):
            return {"ignored": "evento"}
        m = extract_message(payload)
        if (not m["from_me"] and not m["status"] and m.get("media") and m["sender"] in approval_map()
                and not m["body"].strip()):  # audio/foto/video de un cliente con ficha: no se tira, se registra y se avisa
            if m["id"] and f"seen:{m['id']}" in db:
                return {"ignored": "repetido"}
            if m["id"]:
                db[f"seen:{m['id']}"] = int(time.time())
            token = approval_map()[m["sender"]]
            tipo = {"ptt": "audio", "audio": "audio", "image": "foto", "video": "video", "document": "archivo"}.get(m.get("type"), "archivo")
            await wa_send(m["sender"], f"Recibido ✅ tu {tipo}. Ya quedó en tu proyecto y lo usamos para crear tus piezas.", kind="acuse")
            bitacora(token, f"Mandó un {tipo} para su campaña")
            await tell_owner(f"Visión OS: {ficha(token).get('cliente', m['sender'])} mandó un {tipo} por WhatsApp. Ya se le confirmó.")
            return {"ok": True, "media": tipo}
        if m["from_me"] or m["status"] or not m["body"].strip() or not m["sender"] or m["sender"].endswith("@g.us"):
            return {"ignored": True}
        if m["id"]:
            key = f"seen:{m['id']}"
            if key in db:
                return {"ignored": "repetido"}
            db[key] = int(time.time())
        m["t0"] = time.time()
        if is_approval(m):  # «aprobado» del cliente: acuse ya, y la respuesta con estado sale del proceso de fondo
            rec = await approval_ack(m)
            if not rec.get("dup"):
                await procesar.spawn.aio(m)
            return {"ok": True, "approval": True, "dup": bool(rec.get("dup"))}
        acked = False
        try:
            acked = await quick_ack(m)  # «Recibido, procesando…» sale aquí, sin esperar a la IA
        except Exception:
            pass
        await procesar.spawn.aio(m)
        return {"ok": True, "ack": acked}

    @web.post("/api/send")
    async def send(request: Request, _=Depends(auth)):
        data = await request.json()
        res = await wa_send(data["chatId"], data["text"], kind="manual")
        if data.get("inboxId"):
            m = get("inbox", data["inboxId"])
            if m:
                m.update(sent=True, read=True)
                put("inbox", m)
        return res

    # --- Meta Ads
    @web.get("/api/meta/insights")
    async def meta(account: str, preset: str = "last_7_days", _=Depends(auth)):
        import httpx
        if not re.fullmatch(r"act_\d+", account):
            raise HTTPException(400, "Cuenta inválida")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"https://graph.facebook.com/v21.0/{account}/insights", params={
                "fields": "spend,impressions,clicks,ctr,cpc,actions", "date_preset": preset,
                "access_token": env("META_TOKEN")})
        if r.status_code >= 400:
            raise HTTPException(502, r.text[:200])
        return r.json()

    # --- GitHub
    @web.get("/api/github/repos")
    async def repos(_=Depends(auth)):
        try:
            data = await gh("GET", "/user/repos?sort=pushed&per_page=40")
        except Exception as e:
            raise HTTPException(502, str(e))
        return [{"full_name": r["full_name"], "private": r["private"], "pushed_at": r["pushed_at"],
                 "open_issues": r["open_issues_count"], "default_branch": r["default_branch"],
                 "url": r["html_url"]} for r in data]

    @web.get("/api/github/status")
    async def repo_status(repo: str, _=Depends(auth)):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise HTTPException(400, "Repo inválido")
        try:
            commits = await gh("GET", f"/repos/{repo}/commits?per_page=3")
            runs = await gh("GET", f"/repos/{repo}/actions/runs?per_page=3")
        except Exception as e:
            raise HTTPException(502, str(e))
        return {"commits": [{"sha": c["sha"][:7], "msg": c["commit"]["message"].split("\n")[0],
                             "date": c["commit"]["author"]["date"]} for c in commits],
                "runs": [{"name": r["name"], "status": r["status"], "conclusion": r["conclusion"],
                          "url": r["html_url"]} for r in runs.get("workflow_runs", [])]}

    @web.post("/api/github/deploy")
    async def gh_deploy(request: Request, _=Depends(auth)):
        data = await request.json()
        if not re.fullmatch(r"[\w.-]+(/[\w.-]+)?", data.get("repo", "")):
            raise HTTPException(400, "Repo inválido")
        try:
            return await deploy(data["repo"])
        except Exception as e:
            raise HTTPException(502, str(e))

    # --- CRUD genérico (al final para no tapar las rutas de arriba)
    @web.get("/api/{coll}")
    def list_docs(coll: str, _=Depends(auth)):
        if coll not in COLLECTIONS:
            raise HTTPException(404)
        seed_if_empty()
        return rows(coll)

    @web.post("/api/{coll}")
    async def save_doc(coll: str, request: Request, _=Depends(auth)):
        if coll not in COLLECTIONS:
            raise HTTPException(404)
        return put(coll, await request.json())

    @web.delete("/api/{coll}/{doc_id}")
    def delete_doc(coll: str, doc_id: str, _=Depends(auth)):
        if coll not in COLLECTIONS:
            raise HTTPException(404)
        remove(coll, doc_id)
        return {"ok": True}

    @web.exception_handler(Exception)
    async def err(_, e):
        return JSONResponse({"detail": str(e)[:200]}, status_code=500)

    return web


@app.function(min_containers=WEB_MIN_CONTAINERS, timeout=120)
@modal.asgi_app()
def web():
    return build_web()
