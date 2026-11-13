"""Amy VIP Taxis · frames para replicar su referencia MÁS VIRAL (13 nov 2026, orden de Carlos).

Referencia: instagram.com/p/CqB49s7Ja0Y (11.5 M de vistas, 9.7 s). Fórmula: UNA toma continua de humor donde «el otro
transporte» sale mal, con un texto fijo abajo («Por eso preferí ser Taxi Ejecutivo 🤣»). No se copia el chiste original
(se burla de personas por su peso) ni su material: solo la fórmula, resuelta con Amy.

Frames 3-5 usan material REAL de Amy (fotos que mandó por WhatsApp, guardadas en enlaces-medios amy/recibido).
Frames 1-2 no tienen material: salen como tarjeta de «toma por grabar» (Amy con su celular, o Codex). Nada de Qwen.

    python modal/amy_frames_viral.py <carpeta_con_fotos> <carpeta_salida>
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1080, 1920
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
NAVY, AMARILLO, BLANCO, NEGRO = (20, 40, 140), (245, 197, 24), (255, 255, 255), (15, 15, 15)
FRASE = "Por eso mejor pido Amy VIP Taxis 😂"

TOMAS = [  # (id, segundos, fondo real o None, textos, descripción de la toma)
    ("01_gancho", "0-2 s", None, [],
     "TOMA POR GRABAR · Alguien esperando en la banqueta a pleno sol en Nogales, sudando y viendo el celular: "
     "«el taxi pirata no llega». Cámara en mano, una sola toma, como el viral."),
    ("02_climax", "2-5 s", None, [],
     "TOMA POR GRABAR · Llega un carro viejo sin clima; la persona se sube y le cae el calor, la ventana no baja. "
     "Exagerado y chistoso, sin burlarse de nadie."),
    ("03_giro", "5-7 s", "image_1794120218.jpg", ["Y llega tu", "Amy VIP Taxi"], ""),
    ("04_remate", "7-9 s", "image_1794119291.jpg", ["Seguro y con clima", "Botón de emergencia", "Comparte tu viaje"], "", 860),
    ("05_cierre", "9-11 s", "image_1794119967.jpg", ["Tu 8.º viaje GRATIS", "WhatsApp 631 302 0074"], ""),
]


def fuente(t):
    return ImageFont.truetype(BOLD, t)


def ajusta(d, txt, tam, ancho):
    f = fuente(tam)
    while d.textlength(txt, font=f) > ancho and tam > 24:
        tam -= 2
        f = fuente(tam)
    return f


def frase_fija(im):
    """Caja blanca con texto negro en el tercio bajo, igual que el viral."""
    d = ImageDraw.Draw(im)
    txt = FRASE.replace(" 😂", "")
    f = ajusta(d, txt, 62, W - 160)
    tw = d.textlength(txt, font=f)
    x, y = (W - tw) / 2, 1330
    d.rounded_rectangle((x - 26, y - 18, x + tw + 26, y + 84), radius=18, fill=BLANCO)
    d.text((x, y), txt, font=f, fill=NEGRO)


def frame_real(fondo, textos, y=120):
    cara = y > 400  # foto con cara: se encuadra desde arriba y los textos van abajo de la cara
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(fondo)).convert("RGB"), (W, H), Image.LANCZOS,
                      centering=(0.5, 0.15 if cara else 0.4))
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle((0, y - 100, W, y + 400), fill=(0, 0, 0, 90 if cara else 110))
    for i, t in enumerate(textos):
        f = ajusta(d, t, 92 if i == 0 else 72, W - 120)
        tw = d.textlength(t, font=f)
        d.rounded_rectangle(((W - tw) / 2 - 24, y - 10, (W + tw) / 2 + 24, y + f.size + 16), radius=16,
                            fill=AMARILLO if i == 0 else (255, 255, 255, 235))
        d.text(((W - tw) / 2, y), t, font=f, fill=NAVY)
        y += f.size + 46
    frase_fija(im)
    return im


def frame_por_grabar(desc):
    im = Image.new("RGB", (W, H), (38, 42, 48))
    d = ImageDraw.Draw(im)
    d.rectangle((40, 40, W - 40, H - 40), outline=(120, 128, 138), width=6)
    d.text((80, 90), "TOMA POR GRABAR", font=fuente(64), fill=AMARILLO)
    palabras, lineas, l = desc.split(" · ", 1)[-1].split(), [], ""
    for p in palabras:
        if d.textlength(l + " " + p, font=fuente(46)) > W - 180:
            lineas.append(l)
            l = p
        else:
            l = (l + " " + p).strip()
    lineas.append(l)
    for i, t in enumerate(lineas):
        d.text((80, 220 + i * 66), t, font=fuente(46), fill=BLANCO)
    frase_fija(im)
    return im


def hoja(frames, salida):
    th = []
    for n, seg, im in frames:
        t = im.resize((270, 480))
        c = Image.new("RGB", (270, 520), "white")
        c.paste(t, (0, 40))
        ImageDraw.Draw(c).text((6, 8), f"{n} · {seg}", font=fuente(20), fill=NEGRO)
        th.append(c)
    h = Image.new("RGB", (len(th) * 280, 520), "white")
    for i, c in enumerate(th):
        h.paste(c, (i * 280, 0))
    h.save(salida, quality=90)


def main(fotos, salida):
    fotos, salida = Path(fotos), Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    frames = []
    for n, seg, fondo, textos, desc, *ys in TOMAS:
        im = frame_real(fotos / fondo, textos, *ys) if fondo else frame_por_grabar(desc)
        im.save(salida / f"amy_viral_{n}.jpg", quality=92)
        frames.append((n, seg, im))
    hoja(frames, salida / "amy_viral_storyboard.jpg")
    (salida / "amy_viral_guion.md").write_text(
        "# Amy VIP Taxis · réplica del viral (11.5 M vistas)\n\nFrase fija abajo todo el video: «" + FRASE + "»\n\n"
        + "\n".join(f"- **{n}** ({seg}): " + (desc or "material real de Amy · " + " / ".join(textos)) for n, seg, fondo, textos, desc, *_ in TOMAS)
        + "\n\nFrames 01 y 02: Amy los graba con su celular (lo más rápido y lo que mejor califica) o se piden a Codex. "
          "Confirmar con Amy si la promo vigente es el 8.º viaje (su volante del 10 nov decía 5.º servicio).\n", encoding="utf-8")
    print("listo:", salida)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
