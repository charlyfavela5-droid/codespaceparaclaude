"""ENLACES PARA CLIENTES (12 nov 2026, pedido de Carlos): una página por cliente con las imágenes y videos que se le
han hecho, para pasarle UN enlace por WhatsApp. Lee el tablero (datos.json) en vivo; no envía nada a nadie.

El enlace lleva una clave larga al azar: solo lo abre quien lo tenga. Se puede apagar cuando quieras.

  modal deploy enlaces.py
  modal run enlaces.py::crear --cliente rafael          # imprime el enlace (si ya existe, devuelve el mismo)
  modal run enlaces.py::crear --cliente rafael --nuevo  # apaga el anterior y crea otro
  modal run enlaces.py::apagar --cliente rafael
  modal run enlaces.py::lista
"""
import html
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import modal

app = modal.App("enlaces-clientes")
enlaces = modal.Dict.from_name("enlaces-clientes", create_if_missing=True)
ws = modal.Volume.from_name("nexus-workspace").read_only()
IMG = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi[standard]")
TAB = "/ws/workspaces/Nexusv2.0launch18octubre/entregables/tablero"
SONORA = timezone(timedelta(hours=-7))
LIMPIAR = [r"\s*\(elegido por Carlos\)", r"\bImagen ChatGPT\s*·\s*", r"\bChatGPT/Codex\b", r"\bChatGPT\b", r"\bCodex\b", r"\bGlimmer\b", r"\bH3\b"]


def _cliente(slug):
    ws.reload()
    with open(f"{TAB}/datos.json", encoding="utf-8") as f:
        for c in json.load(f):
            if isinstance(c, dict) and c.get("slug") == slug:
                return c
    return None


def _titulo(v):
    t = str(v.get("version") or "")
    for p in LIMPIAR:
        t = re.sub(p, "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ·")
    if not v.get("es_imagen"):  # videos: los nombres internos (p2, v4c, gancho_v2…) no le dicen nada al cliente
        m = re.search(r"«([^»]{3,40})»", t)
        return f"Video «{m.group(1)}»" if m else "Video"
    seg = t.split(" · ")[0].strip()
    return seg if seg and not re.fullmatch(r"[A-Za-z0-9_]{1,3}|[A-Z0-9_]{6,}", seg) else "Imagen"


def _piezas(c, extras=None):
    """Solo lo que el cliente puede ver: título, fecha, nota y el archivo. Nada de notas internas.
    extras = piezas que no están en el tablero (p. ej. las que ya se le mandaron por WhatsApp), guardadas en el volumen enlaces-medios."""
    out = []
    for v in c.get("versiones") or []:
        video = (v.get("vurl") or "").rsplit("/", 1)[-1]
        foto = (v.get("purl") or "").rsplit("/", 1)[-1]
        if video and not os.path.isfile(f"{TAB}/v/{video}"):
            video = ""
        if foto and not os.path.isfile(f"{TAB}/p/{foto}"):
            foto = ""
        if not video and not (v.get("es_imagen") and foto):
            continue
        try:
            nota = float(v.get("actual"))
        except (TypeError, ValueError):
            nota = None
        out.append({"titulo": _titulo(v), "fecha": str(v.get("fecha") or ""), "nota": nota, "video": video, "foto": foto,
                    "es_imagen": bool(v.get("es_imagen"))})
    # Tanda del 12 nov (A, B, C): todavía no está en el tablero; se muestra con su nota de ese día.
    for i, x in enumerate(extras or []):
        if os.path.isfile(x["ruta"]):
            out.insert(i, {"titulo": x["titulo"], "fecha": x.get("fecha", ""), "nota": x.get("nota"), "video": "", "foto": x["archivo"],
                           "es_imagen": True, "ruta": x["ruta"], "detalle": x.get("detalle", "")})
    carpeta = None if extras else CARPETAS.get(c.get("slug"))  # con piezas propias no se muestran las de la tanda
    if carpeta:
        try:
            resp = str((modal.Dict.from_name("glimmer-tanda-20261112").get(carpeta) or {}).get("respuesta", ""))
        except Exception:
            resp = ""
        notas = re.findall(r"CALIFICACI[ÓO]N:\s*([\d.]+)\s*/\s*10", resp)
        for i, letra in enumerate("ABC"):
            ruta = f"{CLI}/{carpeta}/tanda_20261112/{letra}.png"
            if os.path.isfile(ruta):
                out.insert(i, {"titulo": f"Propuesta {letra}", "fecha": "12/11", "nota": float(notas[i]) if i < len(notas) else None,
                               "video": "", "foto": f"tanda_{letra}.png", "es_imagen": True, "ruta": ruta})
    return out


CLI = "/ws/workspaces/Nexusv2.0launch18octubre/clientes"
CARPETAS = {"fernando": "Fernando", "giovanni": "Giovanni", "jose-grupo-jr": "Jose", "rafael": "Rafael_BYD", "manuel-xv": "Manuel_fotografia",
            "gerson-ginecologo": "Conde_ginecologo", "mariano-vizcaino": "Mariano", "victor-servilin": "Victor", "tatuador": "Tatuador9983316522",
            "guillermo-vicens": "Guillermo", "amy-vip": "Amy"}


CSS = """:root{color-scheme:light dark;--b:#fff;--t:#16202b;--m:#5f6b76;--l:#d9dee3;--ok:#0a7a4b;--am:#8a5a00;--c:#f4f6f8}
@media(prefers-color-scheme:dark){:root{--b:#12171c;--t:#e8ecef;--m:#9aa6b1;--l:#2b343c;--ok:#4cc38a;--am:#f2c14e;--c:#1a2128}}
*{box-sizing:border-box}body{margin:0;background:var(--b);color:var(--t);font:17px/1.5 system-ui,sans-serif}main{max-width:980px;margin:auto;padding:18px}
h1{font-size:1.45rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.4em 0 .5em}.mut{color:var(--m);font-size:.92rem}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}figure{margin:0;border:1px solid var(--l);border-radius:12px;padding:8px;background:var(--c)}
img,video{width:100%;border-radius:8px;display:block;background:#000}figcaption{font-size:.9rem;padding:6px 2px 0}
.n{display:inline-block;font-weight:700;border-radius:999px;padding:1px 9px;font-size:.85rem;border:1px solid currentColor}.ok{color:var(--ok)}.am{color:var(--am)}
.sis{border-collapse:collapse;width:100%}.sis th,.sis td{border-bottom:1px solid var(--l);padding:8px 6px;text-align:left;vertical-align:middle;font-size:.95rem}
.sis th{font-weight:600}.sis .m{white-space:nowrap}.bar{display:inline-block;width:110px;height:10px;border-radius:999px;background:var(--l);overflow:hidden;vertical-align:middle;margin-right:8px}
.bar i{display:block;height:100%;background:var(--ok)}@media(max-width:560px){.sis th,.sis td{display:block;border:0;padding:2px 0}.sis tr{display:block;border-bottom:1px solid var(--l);padding:8px 0}}
.caja{border-left:4px solid var(--ok);padding:8px 12px;background:var(--c);border-radius:0 8px 8px 0}"""


def _sistema(slug, ps):
    """Estado en vivo de los sistemas de Modal, solo lo que le sirve al cliente (nada de otros clientes ni alertas internas)."""
    ahora = datetime.now(SONORA)
    filas = []

    def barra(pct):
        pct = max(0, min(100, round(pct)))
        return f'<div class="bar"><i style="width:{pct}%"></i></div><b>{pct}%</b>'

    en8 = sum(1 for p in ps if (p["nota"] or 0) >= 8)
    if ps:
        filas.append(("Tus piezas en 8 o más", barra(100 * en8 / len(ps)), f"{en8} de {len(ps)} ya pasan la calificación para publicarse"))
    try:  # vigilancia: último pulso del sistema (corre cada 20 min de 7 a 23 h)
        u = modal.Dict.from_name("supervisor-bitacora").get("ultimo") or {}
        t = datetime.strptime(u["cuando"], "%Y-%m-%d %H:%M").replace(tzinfo=SONORA)
        mins = int((ahora - t).total_seconds() // 60)
        vivo = mins <= 45 or not (7 <= ahora.hour <= 23)
        hace = f"hace {mins} min" if mins < 120 else f"hace {mins // 60} h"
        filas.append(("Vigilancia automática", f'<span class="n {"ok" if vivo else "am"}">{"Activa" if vivo else "Revisando"}</span>',
                      f"Última revisión {hace} ({t.strftime('%d/%m %H:%M')}). Revisa cada 20 minutos, de 7 a 23 h"))
    except Exception:
        filas.append(("Vigilancia automática", '<span class="n am">Sin dato</span>', "No se pudo leer la última revisión"))
    try:  # modelo guardián gratuito: segundos de CPU usados hoy contra su tope diario
        uso = modal.Dict.from_name("atencion-clientes-estado").get("guardian_uso_rapido") or {}
        hoy = uso.get("fecha") == ahora.strftime("%Y-%m-%d")
        seg, llam = (uso.get("segundos", 0), uso.get("llamadas", 0)) if hoy else (0, 0)
        filas.append(("Modelo guardián (IA propia)", barra(100 * seg / 3600),
                      f"Uso de hoy: {llam} tareas atendidas. Lee los mensajes y ordena los cambios; le queda {max(0, 100 - round(100 * seg / 3600))}% de capacidad"))
    except Exception:
        filas.append(("Modelo guardián (IA propia)", '<span class="n am">Sin dato</span>', "No se pudo leer el uso de hoy"))
    try:  # cambios pedidos para ESTE cliente
        cs = [v for _, v in modal.Dict.from_name("cambios-rapidos").items() if isinstance(v, dict) and (v.get("orden") or {}).get("cliente") == slug
              and v.get("estado") not in ("prueba", "descartado")]
        hechos = sum(1 for v in cs if str(v.get("estado", "")).startswith(("hecho", "editado ·")))
        if cs:
            filas.append(("Cambios a tus piezas", barra(100 * hechos / len(cs)), f"{hechos} de {len(cs)} pedidos de cambio ya editados"))
    except Exception:
        pass
    return ("<h2>Sistema que cuida tu campaña</h2><table class='sis'>" + "".join(
        f"<tr><th>{a}</th><td class='m'>{b}</td><td class='mut'>{html.escape(c)}</td></tr>" for a, b, c in filas)
        + f"</table><p class='mut'>Datos en vivo de nuestros sistemas · {ahora.strftime('%d/%m %H:%M')} (hora de Sonora).</p>")


def _fig(tok, p):
    e = html.escape
    nota = "" if p["nota"] is None else f'<span class="n {"ok" if p["nota"] >= 8 else "am"}">{p["nota"]:g} de 10</span> '
    if p["es_imagen"]:
        medio = f'<a href="/{tok}/m/{e(p["foto"])}"><img src="/{tok}/m/{e(p["foto"])}" alt="{e(p["titulo"])}" loading="lazy"></a>'
    else:
        poster = f' poster="/{tok}/m/{e(p["foto"])}"' if p["foto"] else ""
        medio = f'<video controls playsinline preload="none"{poster} src="/{tok}/m/{e(p["video"])}"></video>'
    det = f'<br><span class="mut">{e(p["detalle"])}</span>' if p.get("detalle") else ""
    return f'<figure>{medio}<figcaption>{nota}{e(p["titulo"])}<br><span class="mut">{e(p["fecha"])}</span>{det}</figcaption></figure>'


def _estrategia(reg):
    t = (reg.get("estrategia") or "").strip()
    if not t:
        return ""
    titulo = reg.get("estrategia_titulo") or ("Estrategia para tu app: más pedidos y más choferes" if reg.get("slug") == "amy-vip"
                                              else "Tu estrategia")
    return (f"<h2>{html.escape(titulo)}</h2>"
            f"<div class='caja' style='white-space:pre-wrap'>{html.escape(t)}</div>"
            f"<p class='mut'>{html.escape(reg.get('estrategia_pie') or '')}</p>")


# ---------------------------------------------------------------------------------------------------------------
# AGENTES (13 nov 2026, orden de Carlos): el cliente ve en vivo qué agente trabaja en sus anuncios y qué hace,
# con sus propios datos (piezas, calificaciones, referencias, bitácora y sus mensajes). Solo si reg["agentes"].
# Nada de nombres internos (Glimmer, Codex…), notas para Carlos, precios ni bonos sin confirmar.
CSS_AG = """.ags{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.ag{border:1px solid var(--l);border-radius:12px;padding:12px 14px;background:var(--c)}
.ag h3{font-size:1rem;margin:0 0 4px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.ag p{margin:4px 0 0;font-size:.93rem}.est{font-size:.78rem;font-weight:700;border-radius:999px;padding:1px 9px;white-space:nowrap;border:1px solid currentColor}
.est.listo{color:var(--ok)}.est.trab{color:#1f6fd1}.est.esp,.est.falta{color:var(--am)}.est.fila{color:var(--m)}
@media(prefers-color-scheme:dark){.est.trab{color:#6fb0ff}}
.est.trab:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor;margin-right:5px;animation:lat 1.4s infinite}
@keyframes lat{50%{opacity:.25}}@media(prefers-reduced-motion:reduce){.est.trab:before{animation:none}}
.lin{list-style:none;padding:0;margin:0}.lin li{border-left:3px solid var(--l);padding:4px 0 8px 12px;font-size:.93rem}.lin b{font-weight:600}"""

INTERNO = [(r"\s*\(anotado para Carlos\)", " (lo recibió el equipo)"), (r"\bGlimmer\b", "la calificación"), (r"\bCarlos\b", "el equipo"),
           (r"\bCodex\b|\bChatGPT\b|\bQwen\b|\bFable[\w .]*", "nuestra IA"), (r"\(≈[^)]*\)", "")]


def _limpio(t):
    t = str(t or "")
    for a, b in INTERNO:
        t = re.sub(a, b, t)
    t = re.sub(r"^Pidió: ", "Nos escribiste: ", t)
    t = re.sub(r"^Se le mandaron", "Te mandamos", t)
    t = re.sub(r",?\s*siguiente paso.*$", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _agentes(tok, reg, ps):
    if not reg.get("agentes"):
        return ""
    e = html.escape
    camp = reg.get("campana") or "tu campaña"
    db = modal.Dict.from_name("vision-os-db")
    try:
        bit = db.get(f"bitacora:{tok}") or []
    except Exception:
        bit = []
    chat = reg.get("chatId") or ""
    ultimo_msj, aprobado = None, False
    try:
        for k in db.keys():
            if chat and k.startswith(f"aprobado:{chat}:"):
                aprobado = True
            elif chat and k.startswith("inbox:"):
                m = db.get(k) or {}
                if m.get("chatId") == chat and (ultimo_msj is None or m.get("updatedAt", 0) > ultimo_msj.get("updatedAt", 0)):
                    ultimo_msj = m
    except Exception:
        pass

    imgs = [p for p in ps if p["es_imagen"]]
    img8 = [p for p in imgs if (p["nota"] or 0) >= 8]
    vids = [p for p in ps if not p["es_imagen"]]
    vid8 = [p for p in vids if (p["nota"] or 0) >= 8]
    mejor_v = max([p["nota"] for p in vids if p["nota"] is not None] or [0])
    refs = reg.get("referencias") or []
    m_ref = re.search(r"REFERENCIA ESCOGIDA:\s*(\S+)", reg.get("estrategia") or "")
    revisados = next((re.search(r"(\d+) reels", x.get("evento", "")).group(1) for x in bit
                      if re.search(r"(\d+) reels", x.get("evento", ""))), None)

    ag = []  # (nombre, estado, texto)
    if refs or m_ref:
        txt = (f"Revisó {revisados} reels de autos en Instagram" if revisados else f"Juntó {len(refs)} reels muy vistos de autos") + \
              (" y escogió la referencia que vamos a replicar con tu producto." if m_ref else ".")
        ag.append(("Buscador de referencias", "listo", txt))
    ag.append(("Diseñador de imágenes", "listo" if len(img8) >= 3 else "trab",
               f"{len(img8)} imágenes tuyas ya pasan la calificación de 8 o más."
               + ("" if len(img8) >= 3 else " Sigue ajustando las que faltan.")))
    if vid8:
        ag.append(("Editor de video", "listo", f"Tu video ya tiene {max(p['nota'] for p in vid8):g} de 10: entra a {camp}."))
    else:
        ag.append(("Editor de video", "trab",
                   f"Tu mejor video va en {mejor_v:g} de 10. Lo está ajustando al estilo de tu referencia para llegar a 8; "
                   f"mientras, {camp} puede arrancar con las imágenes." if mejor_v else
                   f"Armando tu video al estilo de tu referencia."))
    n_cal = sum(1 for p in ps if p["nota"] is not None)
    ag.append(("Calificador de anuncios", "trab" if not vid8 else "listo",
               f"Calificó {n_cal} piezas de 0 a 10. Solo deja pasar a tu campaña lo que llega a 8, porque es lo que trae mensajes."))
    if ultimo_msj:
        cuando = datetime.fromtimestamp(ultimo_msj.get("updatedAt", 0), SONORA).strftime("%d/%m %H:%M")
        ag.append(("Atención por WhatsApp", "listo",
                   f"Recibió tu último mensaje «{_limpio(ultimo_msj.get('text'))[:60]}» ({cuando}) y lo pasó al equipo."))
    if aprobado:
        ag.append((f"Campaña {camp}", "trab", f"Ya aprobaste: estamos armando {camp} con las piezas de 8 o más. Se enciende cuando esté revisada."))
    else:
        ag.append((f"Campaña {camp}", "esp",
                   f"Lista para armarse con las piezas de 8 o más. Solo falta tu OK: respóndenos «aprobado» por WhatsApp."))

    # estado real que el equipo fija a mano (reg["agentes_notas"] = {nombre: [estado, texto]}): manda sobre lo calculado
    notas = reg.get("agentes_notas") or {}
    ag = [(n, *notas[n]) if n in notas else (n, s, t) for n, s, t in ag]
    ag += [(n, s, t) for n, (s, t) in notas.items() if n not in {a[0] for a in ag}]
    est = {"listo": "Listo", "trab": "Trabajando", "esp": "Espera tu OK", "fila": "En fila", "falta": "Falta algo de ti"}
    tarjetas = "".join(f"<div class='ag'><h3>{e(n)}<span class='est {s}'>{est[s]}</span></h3><p>{e(t)}</p></div>" for n, s, t in ag)
    lin = "".join(f"<li><b>{e(x.get('cuando', ''))}</b> · {e(_limpio(x.get('evento')))}</li>" for x in reversed(bit[-8:]))
    ahora = datetime.now(SONORA).strftime("%d/%m %H:%M")
    return (f"<section id='agentes'><h2>Tu equipo trabajando en {e(camp)}</h2>"
            f"<p class='mut'>Cada agente trabaja con tu información: tus piezas, tus calificaciones, tu referencia y tus mensajes. "
            f"Se actualiza solo · {ahora} (hora de Sonora).</p><div class='ags'>{tarjetas}</div>"
            + (f"<h2>Lo último que pasó</h2><ul class='lin'>{lin}</ul>" if lin else "") + "</section>")


# ---------------------------------------------------------------------------------------------------------------
# FICHA DE PROSPECTO (13 nov 2026, orden de Carlos: «siempre se atiende a los prospectos, convence con la ficha»).
# Visión OS la crea al primer mensaje (reg["prospecto"], reg["prospectId"]) y la manda por WhatsApp. Se llena sola con lo que
# el prospecto va diciendo (vision-os-db prospects:<id>). Solo cosas verdaderas: estados reales, el precio autorizado ($500)
# y los resultados que Carlos ya usa en la bienvenida.
RESULTADOS = [("Limpieza", "33 mensajes a $1.39 cada uno"), ("Impermeabilización", "18 mensajes a $2.87 cada uno")]
CSS_PR = """.est.fila{color:var(--m)}.datos{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:0;padding:0;list-style:none}
.datos li{border:1px solid var(--l);border-radius:10px;padding:8px 12px;background:var(--c);font-size:.93rem}.datos b{display:block;font-size:.8rem;color:var(--m);font-weight:600}
.falta{color:var(--am);font-weight:600}.ok8{font-size:1.05rem;line-height:1.55}"""


def _prospecto(reg):
    try:
        return modal.Dict.from_name("vision-os-db").get(f"prospects:{reg.get('prospectId')}") or {}
    except Exception:
        return {}


def _agentes_prospecto(tok, reg, p=None):
    e = html.escape
    p = p if p is not None else _prospecto(reg)
    try:
        bit = modal.Dict.from_name("vision-os-db").get(f"bitacora:{tok}") or []
    except Exception:
        bit = []
    datos = {"Negocio": p.get("business"), "Giro": p.get("giro"), "Ciudad": p.get("city"), "Qué quiere anunciar": p.get("sells")}
    faltan = [k for k, v in datos.items() if not v]
    completo = not faltan
    imgs, video = int(p.get("sampleImages") or 0), bool(p.get("sampleVideo"))
    giro = p.get("giro") or "su giro"
    ultimo = max((h for h in [p.get("updatedAt", 0)]), default=0)
    ag = [("Atención por WhatsApp", "listo",
           f"Recibió su mensaje{(' (' + datetime.fromtimestamp(ultimo, SONORA).strftime('%d/%m %H:%M') + ')') if ultimo else ''} "
           "y le contesta en segundos, a cualquier hora."),
          ("Ficha de su negocio", "listo" if completo else "esp",
           "Ya tenemos sus datos para armar la muestra." if completo else f"Nos falta: {', '.join(faltan).lower()}.")]
    if completo:
        ag += [("Buscador de referencias", "fila", f"Va a revisar los videos más virales de {giro} para encontrar el ángulo que más convence."),
               ("Diseñador de imágenes", "listo" if imgs >= 3 else ("trab" if imgs else "fila"),
                f"{imgs} de 3 imágenes de su muestra." + ("" if imgs >= 3 else " Con fotos reales de su negocio salen más fuertes.")),
               ("Editor de video", "listo" if video else "fila", "Su video está listo." if video else "Arma su video al estilo de la referencia."),
               ("Calificador de anuncios", "fila", "Califica cada pieza de 0 a 10 antes de enseñársela; solo pasa lo que llega a 8.")]
    else:
        ag += [("Buscador de referencias", "esp", "Arranca en cuanto sepamos su giro y su ciudad."),
               ("Diseñador de imágenes y video", "esp", "Arma sus 3 imágenes y 1 video en cuanto tengamos sus datos (y sus fotos, si las tiene)."),
               ("Calificador de anuncios", "esp", "Califica cada pieza de 0 a 10; solo le enseñamos lo que llega a 8.")]
    est = {"listo": "Listo", "trab": "Trabajando", "fila": "En fila", "esp": "Espera sus datos"}
    tarjetas = "".join(f"<div class='ag'><h3>{e(n)}<span class='est {s}'>{est[s]}</span></h3><p>{e(t)}</p></div>" for n, s, t in ag)
    lin = "".join(f"<li><b>{e(x.get('cuando', ''))}</b> · {e(_limpio(x.get('evento')))}</li>" for x in reversed(bit[-8:]))
    return (f"<section id='agentes'><h2>Su equipo de agentes</h2>"
            f"<p class='mut'>Trabajan con la información que usted nos da por WhatsApp. Se actualiza solo · "
            f"{datetime.now(SONORA).strftime('%d/%m %H:%M')} (hora de Sonora).</p><div class='ags'>{tarjetas}</div>"
            + (f"<h2>Lo último que pasó</h2><ul class='lin'>{lin}</ul>" if lin else "") + "</section>")


def _pagina_prospecto(tok, reg):
    e = html.escape
    p = _prospecto(reg)
    nombre = p.get("business") or p.get("name") or reg.get("cliente") or "Su negocio"
    datos = [("Negocio", p.get("business")), ("Giro", p.get("giro")), ("Ciudad", p.get("city")), ("Qué quiere anunciar", p.get("sells"))]
    lis = "".join(f"<li><b>{k}</b>{e(v) if v else '<span class=falta>Falta: mándenoslo por WhatsApp</span>'}</li>" for k, v in datos)
    res = "".join(f"<li><b>{e(a)}</b>{e(b)}</li>" for a, b in RESULTADOS)
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{e(nombre)} · Visión Agencia</title><style>{CSS}{CSS_AG}{CSS_PR}</style></head><body><main>
<h1>{e(nombre)} · su muestra gratis</h1>
<p class="mut">Visión Agencia · Sonora, 100% en línea con negocios de todo México.</p>
<div class="caja ok8">Le armamos <b>gratis</b> una muestra de <b>3 imágenes y 1 video</b> con su propio material. Antes de gastar un peso en
pauta, nuestro sistema califica cada anuncio de 0 a 10 y <b>solo se lanza lo que llega a 8</b>: abajo de 8 Facebook cobra por vistas y no
llegan mensajes. Si le convence la muestra, son <b>$500</b>.</div>
{_agentes_prospecto(tok, reg, p)}{JS_AG}
<h2>Lo que sabemos de su negocio</h2><ul class="datos">{lis}</ul>
<h2>Lo que nos ayuda de usted</h2>
<ul class="lin"><li>3 fotos o videos de su trabajo (del celular está bien). Si no tiene, generamos el material.</li>
<li>Qué precio o promoción quiere anunciar.</li><li>Un reel o anuncio que le guste, de referencia.</li>
<li>Un audio corto con su voz: el anuncio sale más fuerte que con voz genérica.</li></ul>
<h2>Resultados reales de clientes nuestros</h2><ul class="datos">{res}</ul>
<p class="mut">Mándenos todo por WhatsApp; esta página se actualiza sola con lo que nos vaya enviando.</p></main></body></html>"""


JS_AG = """<script>
setInterval(async()=>{try{const r=await fetch(location.pathname.replace(/\\/$/,'')+'/agentes',{cache:'no-store'});
 if(r.ok){const t=await r.text();const s=document.getElementById('agentes');if(s&&t)s.outerHTML=t}}catch(e){}},60000);
</script>"""


JS_GEN = """<script>
const base=location.pathname.replace(/\\/$/,''),b=document.getElementById('gen'),s=document.getElementById('genmsg');
async function est(){const r=await fetch(base+'/estado');return r.json()}
async function poll(){for(;;){const d=await est();
 if(d.estado==='listo'){location.reload();return}
 if(d.estado==='error'){s.textContent=d.msg||'Falló';b.disabled=false;return}
 s.textContent=d.msg||'Armando los anuncios (2 a 5 minutos)…';await new Promise(r=>setTimeout(r,6000))}}
b.onclick=async()=>{b.disabled=true;s.textContent='Enviando…';
 const r=await fetch(base+'/generar',{method:'POST'});const d=await r.json();
 if(!r.ok){s.textContent=d.detail||'No se pudo';b.disabled=false;return}poll()};
est().then(d=>{if(d.estado==='corriendo'){b.disabled=true;poll()}else if(d.msg){s.textContent=d.msg}});
</script>"""


def _generador(reg):
    """Botón solo en el enlace interno (reg['generador']); el cliente no lo ve."""
    if not reg.get("generador") or reg.get("slug") not in ANUNCIOS:
        return ""
    n = len(ANUNCIOS[reg["slug"]])
    return (f"<h2>Generar los {n} anuncios que faltan</h2><div class='caja'>"
            f"<button id='gen' style='font:inherit;font-weight:700;padding:10px 18px;border-radius:10px;border:0;background:#23A960;color:#fff;cursor:pointer'>"
            f"Generar {n} anuncios</button> <span id='genmsg' class='mut'></span>"
            f"<p class='mut'>Los arma sobre la foto de la flotilla, los califica con Glimmer y los pone aquí. "
            f"Solo los de 8 o más pasan a la ficha de la clienta; los demás quedan en esta página en revisión. Máximo 2 corridas al día.</p></div>{JS_GEN}")


def _pagina(tok, reg, c):
    e = html.escape
    ps = _piezas(c, reg.get("extras"))
    listas = [p for p in ps if p["nota"] is not None and p["nota"] >= 8]
    resto = [p for p in ps if p not in listas]
    bloques = []
    for titulo, grupo in (("Imágenes listas para tu campaña (8 o más)", [p for p in listas if p["es_imagen"]]),
                          ("Videos listos para tu campaña (8 o más)", [p for p in listas if not p["es_imagen"]]),
                          ("Videos en ajuste para llegar a 8", [p for p in resto if not p["es_imagen"]]),
                          ("Imágenes en ajuste", [p for p in resto if p["es_imagen"]])):
        if grupo:
            bloques.append(f"<h2>{titulo}</h2><div class='g'>" + "".join(_fig(tok, p) for p in grupo) + "</div>")
    nota = f"<p class='caja'>{e(reg.get('mensaje'))}</p>" if reg.get("mensaje") else ""
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{e(c.get('cliente'))} · Visión Agencia</title><style>{CSS}{CSS_AG}</style></head><body><main>
<h1>{e(c.get('cliente'))} · tus anuncios</h1>
<p class="mut">Visión Agencia · {len(ps)} piezas. La calificación es de 0 a 10; solo publicamos lo que llega a 8 o más, porque es lo que trae mensajes y no solo vistas.</p>
{nota}{_agentes(tok, reg, ps)}{JS_AG if reg.get("agentes") else ""}{_sistema(reg["slug"], ps)}{''.join(bloques) or "<p>Todavía no hay piezas para mostrar.</p>"}{_estrategia(reg)}{_generador(reg)}
<p class="mut">Dinos por WhatsApp cuáles apruebas o qué cambio quieres.</p></main></body></html>"""


med = modal.Volume.from_name("enlaces-medios", create_if_missing=True)


@app.function(image=IMG, volumes={"/ws": ws, "/med": med}, timeout=300, max_containers=2, scaledown_window=120)
@modal.asgi_app()
def web():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse

    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def _reg(tok):
        reg = enlaces.get(tok) if re.fullmatch(r"[A-Za-z0-9_-]{16,40}", tok or "") else None
        if not isinstance(reg, dict) or not reg.get("activo"):
            raise HTTPException(404, "Este enlace no existe o ya se apagó.")
        return reg

    @api.get("/{tok}/estado")
    def estado(tok: str):
        g = _reg(tok).get("gen") or {}
        return {"estado": g.get("estado", "reposo"), "msg": g.get("msg", "")}

    @api.post("/{tok}/generar")
    def generar(tok: str):
        reg = _reg(tok)
        if not reg.get("generador") or reg.get("slug") not in ANUNCIOS:
            raise HTTPException(404, "No disponible.")
        g = reg.get("gen") or {}
        hoy = datetime.now(SONORA).strftime("%Y-%m-%d")
        n = g.get("n_hoy", 0) if g.get("fecha") == hoy else 0
        if g.get("estado") == "corriendo" and time.time() - g.get("t", 0) < 1500:
            return {"estado": "corriendo"}
        if n >= 2:
            raise HTTPException(429, "Ya se usaron las 2 corridas de hoy.")
        enlaces[tok] = {**reg, "gen": {"estado": "corriendo", "t": time.time(), "fecha": hoy, "n_hoy": n + 1, "msg": "Armando los anuncios…"}}
        producir.spawn(tok)
        return {"estado": "corriendo"}

    @api.get("/{tok}/agentes", response_class=HTMLResponse)
    def agentes(tok: str):
        reg = _reg(tok)
        if reg.get("prospecto"):
            return HTMLResponse(_agentes_prospecto(tok, reg), headers={"Cache-Control": "no-store"})
        c = _cliente(reg["slug"]) or {}
        return HTMLResponse(_agentes(tok, reg, _piezas(c, reg.get("extras"))), headers={"Cache-Control": "no-store"})

    @api.get("/{tok}", response_class=HTMLResponse)
    def pagina(tok: str):
        try:
            med.reload()
        except Exception:
            pass
        reg = _reg(tok)
        if reg.get("prospecto"):
            return HTMLResponse(_pagina_prospecto(tok, reg), headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})
        c = _cliente(reg["slug"])
        if not c:
            raise HTTPException(404, "Sin datos.")
        return HTMLResponse(_pagina(tok, reg, c), headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})

    @api.get("/{tok}/m/{nombre}")
    def medio(tok: str, nombre: str):
        try:
            med.reload()
        except Exception:
            pass
        reg = _reg(tok)
        c = _cliente(reg["slug"]) or {}
        for p in _piezas(c, reg.get("extras")):  # solo archivos de ESE cliente
            if nombre == p["video"]:
                return FileResponse(f"{TAB}/v/{nombre}", media_type="video/mp4", headers={"X-Robots-Tag": "noindex"})
            if nombre == p["foto"]:
                return FileResponse(p.get("ruta") or f"{TAB}/p/{nombre}", headers={"X-Robots-Tag": "noindex"})
        raise HTTPException(404, "No encontrado.")

    return api


# ---------------------------------------------------------------------------------------------------------------
# GENERADOR DE ANUNCIOS (12 nov 2026). Botón → /generar → producir (CPU, sobre la foto real de la flotilla) → Glimmer
# (A100, una sola llamada) → piezas en el volumen enlaces-medios y en el registro del enlace.
# Regla del 8: solo lo que califica 8 o más pasa a los enlaces de la clienta; el resto queda en el enlace interno.
# Hoy compone con PIL; con Codex dando 403 no hay fotos nuevas generadas.
APP_URL = "amy-vip-taxi-9ts5.onrender.com"  # el de los anuncios que Amy ya aprobó (el encargo del 11 nov decía amy-vip-taxi-1: confirmar)
ANUNCIOS = {"amy-vip": {
    "negocio": "Amy VIP Taxis · Nogales, Sonora (taxis con app propia para pedir)",
    "base": "/med/amy/flotilla.jpg",
    "datos": ("16 choferes hoy; promoción aprobada «Tu 8.º servicio es gratis»; la app tiene botón de emergencia, compartir viaje y estados "
              "activo/ocupado/descanso. No hay precios, tiempos de llegada, horario, número de WhatsApp ni foto de la dueña confirmados."),
    "piezas": [
        {"titulo": "Anuncio nuevo · pasajeros: viaja seguro", "lineas": ["Viaja seguro", "en Nogales"],
         "checks": ["Botón de emergencia en la app", "Comparte tu viaje en vivo", "Tu 8.º servicio es GRATIS"],
         "cta": "Pide tu taxi desde el celular", "cta2": APP_URL},
        {"titulo": "Anuncio nuevo · choferes: únete", "lineas": ["¿Eres chofer", "en Nogales?"],
         "checks": ["Recibe pedidos en tu celular", "Tú eliges: activo, ocupado o descanso", "Únete a una flotilla de 16 choferes"],
         "cta": "Escríbenos y únete a Amy VIP Taxis", "cta2": "Te contamos los requisitos por mensaje"},
    ]}}
IMG_PROD = modal.Image.debian_slim(python_version="3.12").apt_install("fonts-dejavu-core").pip_install("pillow")


def _componer(spec, base, salida):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    W, H = 1080, 1350
    NAVY, AM, VERDE = (20, 40, 140), (245, 197, 24), (35, 160, 90)
    ruta = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    im = Image.new("RGB", (W, H), (255, 255, 255)); d = ImageDraw.Draw(im)

    def ajusta(txt, tam, ancho):
        f = ImageFont.truetype(ruta, tam)
        while d.textlength(txt, font=f) > ancho and tam > 20:
            tam -= 2; f = ImageFont.truetype(ruta, tam)
        return f, tam

    foto = ImageOps.fit(Image.open(base).convert("RGB"), (W, 520), Image.LANCZOS, centering=(0.5, 0.72)); im.paste(foto, (0, 660))
    d.rectangle((0, 0, W, 18), fill=AM)
    f, _ = ajusta("AMY VIP TAXIS · NOGALES", 34, 700); t = "AMY VIP TAXIS · NOGALES"; w = d.textlength(t, font=f)
    d.rounded_rectangle(((W - w) / 2 - 28, 46, (W + w) / 2 + 28, 106), radius=30, fill=AM); d.text(((W - w) / 2, 54), t, font=f, fill=NAVY)
    y = 135
    for l in spec["lineas"]:
        f, tam = ajusta(l, 108, W - 120); d.text(((W - d.textlength(l, font=f)) / 2, y), l, font=f, fill=NAVY); y += int(tam * 1.14)
    y = max(y + 14, 400)
    for c in spec["checks"]:
        d.ellipse((70, y + 4, 122, y + 56), fill=VERDE); d.text((82, y + 8), "✓", font=ImageFont.truetype(ruta, 40), fill=(255, 255, 255))
        f, _ = ajusta(c, 44, W - 190); d.text((146, y + 6), c, font=f, fill=NAVY); y += 80
    d.rectangle((0, 1180, W, H), fill=AM)
    f, _ = ajusta(spec["cta"], 52, W - 100); d.text(((W - d.textlength(spec["cta"], font=f)) / 2, 1205), spec["cta"], font=f, fill=NAVY)
    f, _ = ajusta(spec["cta2"], 38, W - 100); d.text(((W - d.textlength(spec["cta2"], font=f)) / 2, 1280), spec["cta2"], font=f, fill=NAVY)
    im.save(salida, quality=92)


@app.function(image=IMG_PROD, volumes={"/med": med}, timeout=1200, max_containers=1)
def producir(tok: str):
    reg = enlaces.get(tok) or {}
    cfg = ANUNCIOS.get(reg.get("slug"))
    try:
        if not cfg:
            raise RuntimeError("este cliente no tiene generador")
        med.reload()
        sello = datetime.now(SONORA).strftime("%m%d%H%M")
        salidas = []
        for i, spec in enumerate(cfg["piezas"], 1):
            sal = f"/med/amy/gen_{sello}_{i}.jpg"; _componer(spec, cfg["base"], sal); salidas.append((spec, sal))
        med.commit()
        enlaces[tok] = {**enlaces[tok], "gen": {**(enlaces[tok].get("gen") or {}), "estado": "corriendo", "msg": "Calificando con Glimmer (2 a 4 minutos)…"}}
        notas, frenos, resp = [], [], ""
        try:
            fotos = [open(s, "rb").read() for _, s in salidas]
            P = (f"Eres el evaluador de anuncios de Meta de Visión Agencia. Español mexicano, directo.\nNEGOCIO: {cfg['negocio']}\nDATOS CONFIRMADOS: {cfg['datos']}\n"
                 f"Califica las {len(fotos)} imágenes adjuntas como anuncios de Meta. Para CADA una usa exactamente este formato:\n"
                 "IMAGEN N - CALIFICACIÓN: X/10\nQUÉ LO FRENA:\n- (máximo 2 líneas)\nARREGLOS:\n- (máximo 2 líneas)\nPROYECTADA: X/10")
            resp = str(modal.Cls.from_name("glimmer-rapido", "Rapido")().calificar.remote(P, fotos, 1800))
            notas = [float(x) for x in re.findall(r"CALIFICACI[ÓO]N:\s*([\d.]+)\s*/\s*10", resp)]
            for b in re.split(r"(?=IMAGEN \d)", resp):
                m = re.search(r"QU[ÉE] LO FRENA:\s*\n?\s*[-•]?\s*(.+)", b)
                if m and "CALIFICACI" in b:
                    frenos.append(m.group(1).strip()[:160])
        except Exception as e:
            resp = f"sin calificar: {type(e).__name__}: {str(e)[:120]}"
        nuevas = []
        for i, (spec, sal) in enumerate(salidas):
            nota = notas[i] if i < len(notas) else None
            nuevas.append({"titulo": spec["titulo"], "fecha": datetime.now(SONORA).strftime("%d/%m"), "nota": nota, "archivo": f"amy_{os.path.basename(sal)}",
                           "ruta": sal, "gen": True, "detalle": ("Lo que la frena: " + frenos[i]) if i < len(frenos) and (nota or 0) < 8 else ""})
        for t, r in list(enlaces.items()):
            if not isinstance(r, dict) or r.get("slug") != reg.get("slug") or not r.get("activo"):
                continue
            base = [x for x in (r.get("extras") or []) if not x.get("gen")]
            mias = nuevas if t == tok else [x for x in nuevas if (x["nota"] or 0) >= 8]  # a la clienta solo lo que llega a 8
            enlaces[t] = {**r, "extras": mias + base}
        ok8 = sum(1 for x in nuevas if (x["nota"] or 0) >= 8)
        enlaces[tok] = {**enlaces[tok], "gen": {**(enlaces[tok].get("gen") or {}), "estado": "listo", "t": time.time(),
                                                 "msg": f"Listo: {len(nuevas)} anuncios, {ok8} en 8 o más.", "glimmer": resp[:3000]}}
        return {"ok": True, "notas": notas, "en_8": ok8}
    except Exception as e:
        enlaces[tok] = {**(enlaces.get(tok) or reg), "gen": {**((enlaces.get(tok) or reg).get("gen") or {}), "estado": "error",
                                                              "msg": f"Falló: {type(e).__name__}: {str(e)[:140]}"}}
        return {"ok": False, "error": str(e)[:200]}


@app.function(image=IMG, volumes={"/ws": ws}, timeout=120)
def gestionar(slug: str, accion: str = "crear", nuevo: bool = False, mensaje: str = "", extra: dict = None):
    """crear (devuelve el vigente o hace uno), apagar, o lista (slug vacío). extra = campos a guardar en el registro (extras, estrategia…)."""
    if accion == "lista":
        return [{"slug": v["slug"], "token": k, "activo": v.get("activo"), "creado": v.get("creado")} for k, v in enlaces.items() if isinstance(v, dict)]
    vigentes = [k for k, v in enlaces.items() if isinstance(v, dict) and v.get("slug") == slug and v.get("activo")]
    if accion == "apagar" or nuevo:
        for k in vigentes:
            enlaces[k] = {**enlaces[k], "activo": False}
        if accion == "apagar":
            return {"apagados": len(vigentes)}
        vigentes = []
    c = _cliente(slug)
    if not c:
        return {"error": f"no hay cliente «{slug}» en el tablero"}
    if vigentes:
        tok = vigentes[0]
        if mensaje:
            enlaces[tok] = {**enlaces[tok], "mensaje": mensaje[:600]}
    else:
        tok = secrets.token_urlsafe(18)
        enlaces[tok] = {"slug": slug, "cliente": c.get("cliente"), "activo": True, "mensaje": mensaje[:600],
                        "creado": datetime.now(SONORA).strftime("%Y-%m-%d %H:%M")}
    if extra:
        enlaces[tok] = {**enlaces[tok], **extra}
    ps = _piezas(c, enlaces[tok].get("extras"))
    return {"token": tok, "cliente": c.get("cliente"), "piezas": len(ps), "en_8": sum(1 for p in ps if (p["nota"] or 0) >= 8)}


def _url(tok):
    return modal.Function.from_name("enlaces-clientes", "web").get_web_url().rstrip("/") + "/" + tok


@app.local_entrypoint()
def crear(cliente: str, nuevo: bool = False, mensaje: str = ""):
    r = modal.Function.from_name("enlaces-clientes", "gestionar").remote(cliente, "crear", nuevo, mensaje)
    if r.get("error"):
        print(r["error"]); return
    url = _url(r["token"])
    aqui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "enlaces.json")
    reg = json.load(open(aqui, encoding="utf-8")) if os.path.exists(aqui) else {}
    reg[cliente] = {"url": url, "piezas": r["piezas"], "en_8": r["en_8"]}
    json.dump(reg, open(aqui, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{r['cliente']}: {r['piezas']} piezas ({r['en_8']} en 8 o más)\n{url}")


@app.local_entrypoint()
def apagar(cliente: str):
    print(modal.Function.from_name("enlaces-clientes", "gestionar").remote(cliente, "apagar"))


@app.local_entrypoint()
def lista():
    for x in modal.Function.from_name("enlaces-clientes", "gestionar").remote("", "lista"):
        print(x["slug"], "activo" if x["activo"] else "apagado", x["creado"], _url(x["token"]))
