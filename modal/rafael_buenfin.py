"""Rafael · BYD Azcapotzalco · piezas de Buen Fin (13 nov 2026, orden de Carlos: «la ficha de Rafael no se ha actualizado»).

La tanda del 12 nov no salió (Codex dio 403 al editar la foto real). En vez de generar caras nuevas, se toman las 6 piezas
que Rafael ya tiene en 8 o más y se les pone un sello «BUEN FIN» en la esquina libre (sin fechas, precios ni bono: no están
confirmados). Se califican con Glimmer y SOLO las de 8 o más pasan a su ficha (enlaces-clientes, campo extras).

    modal run modal/rafael_buenfin.py            # arma, califica y muestra notas (no toca la ficha)
    modal run modal/rafael_buenfin.py --subir    # además sube a la ficha las de 8 o más
"""
import re
from datetime import datetime, timedelta, timezone

import modal

app = modal.App("rafael-buenfin")
ws = modal.Volume.from_name("nexus-workspace")
med = modal.Volume.from_name("enlaces-medios", create_if_missing=True)
IMG = modal.Image.debian_slim(python_version="3.12").apt_install("fonts-dejavu-core").pip_install("pillow")
TAB = "/ws/workspaces/Nexusv2.0launch18octubre/entregables/tablero/p"
TOKEN = "a7C9YrXo6tCvJSnf5r4JacGR"
SONORA = timezone(timedelta(hours=-7))
BASES = [("rafael_gpt_prueba_08nov.jpg", "Buen Fin · Prueba tu BYD con cita"),
         ("rafael_gpt_listo_08nov.jpg", "Buen Fin · ¿Listo para tu BYD?"),
         ("rafael_gpt_preguntame_08nov.jpg", "Buen Fin · Pregúntale a Rafael"),
         ("rafael_a1_06nov.jpg", "Buen Fin · ¿Listo para comprar auto?"),
         ("rafael_a2_06nov.jpg", "Buen Fin · Cotiza Song Plus, King, Dolphin"),
         ("rafael_b2_06nov.jpg", "Buen Fin · ¿Eléctrico o híbrido?")]


def sello(base, salida):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(base).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f1, f2 = ImageFont.truetype(bold, 64), ImageFont.truetype(bold, 26)
    x, y, w, h = 34, 34, 330, 132
    d.rounded_rectangle((x + 6, y + 8, x + w + 6, y + h + 8), radius=22, fill=(0, 0, 0, 90))  # sombra
    d.rounded_rectangle((x, y, x + w, y + h), radius=22, fill=(214, 32, 48))
    d.rounded_rectangle((x, y + h - 44, x + w, y + h), radius=22, fill=(255, 205, 0))
    d.rectangle((x, y + h - 44, x + w, y + h - 22), fill=(255, 205, 0))
    t1 = "BUEN FIN"
    d.text((x + (w - d.textlength(t1, font=f1)) / 2, y + 10), t1, font=f1, fill="white")
    t2 = "BYD AZCAPOTZALCO"
    d.text((x + (w - d.textlength(t2, font=f2)) / 2, y + h - 38), t2, font=f2, fill=(20, 30, 60))
    im.save(salida, quality=93)


@app.function(image=IMG, volumes={"/ws": ws, "/med": med}, timeout=1200)
def armar(subir: bool = False):
    import os
    os.makedirs("/med/rafael", exist_ok=True)
    salidas = []
    for archivo, titulo in BASES:
        sal = f"/med/rafael/buenfin_{archivo}"
        sello(f"{TAB}/{archivo}", sal)
        salidas.append((titulo, sal))
    med.commit()
    fotos = [open(s, "rb").read() for _, s in salidas]
    P = ("Eres el evaluador de anuncios de Meta de Visión Agencia. Español mexicano, directo.\n"
         "NEGOCIO: Rafael, asesor de BYD Azcapotzalco (CDMX); campaña de Buen Fin para que le escriban por WhatsApp.\n"
         "DATOS CONFIRMADOS: modelos Song Plus, King y Dolphin; prueba de manejo con cita; WhatsApp publicado en sus anuncios. "
         "No hay precios, bonos ni fechas de Buen Fin confirmados (por eso no aparecen).\n"
         f"Califica las {len(fotos)} imágenes adjuntas como anuncios de Meta. Para CADA una usa exactamente este formato:\n"
         "IMAGEN N - CALIFICACIÓN: X/10\nQUÉ LO FRENA:\n- (máximo 2 líneas)\nARREGLOS:\n- (máximo 2 líneas)\nPROYECTADA: X/10")
    resp = str(modal.Cls.from_name("glimmer-rapido", "Rapido")().calificar.remote(P, fotos, 1800))
    notas = [float(x) for x in re.findall(r"CALIFICACI[ÓO]N:\s*([\d.]+)\s*/\s*10", resp)]
    frenos = []
    for b in re.split(r"(?=IMAGEN \d)", resp):
        m = re.search(r"QU[ÉE] LO FRENA:\s*\n?\s*[-•]?\s*(.+)", b)
        if m and "CALIFICACI" in b:
            frenos.append(m.group(1).strip()[:160])
    hoy = datetime.now(SONORA).strftime("%d/%m")
    piezas = [{"titulo": t, "fecha": hoy, "nota": notas[i] if i < len(notas) else None, "archivo": s.rsplit("/", 1)[-1],
               "ruta": s, "buenfin": True, "detalle": ""} for i, (t, s) in enumerate(salidas)]
    ok = [p for p in piezas if (p["nota"] or 0) >= 8]
    if subir and ok:
        enl = modal.Dict.from_name("enlaces-clientes")
        reg = enl[TOKEN]
        base = [x for x in (reg.get("extras") or []) if not x.get("buenfin")]
        enl[TOKEN] = {**reg, "extras": ok + base}
        db = modal.Dict.from_name("vision-os-db")
        bit = (db.get(f"bitacora:{TOKEN}") or [])[-40:]
        bit.append({"cuando": datetime.now(SONORA).strftime("%d/%m/%Y %H:%M"),
                    "evento": f"Listas tus imágenes de Buen Fin: {len(ok)} de {len(piezas)} pasaron la calificación de 8"})
        db[f"bitacora:{TOKEN}"] = bit
    return {"notas": notas, "frenos": frenos, "subidas": len(ok) if subir else 0, "resp": resp[:2500]}


@app.local_entrypoint()
def main(subir: bool = False):
    r = armar.remote(subir)
    print("notas:", r["notas"], "| subidas a la ficha:", r["subidas"])
    for i, f in enumerate(r["frenos"], 1):
        print(f"  {i}. frena: {f}")
