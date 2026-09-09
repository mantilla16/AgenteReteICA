"""Genera el icono del .exe: engranaje + check sobre fondo azul marino.

Reconstruido a partir de la referencia visual mostrada en el chat (no se
recibio el archivo original). Cuadrado azul marino solido (#001871, el
Space Blue de la paleta de marca de Russell Bedford), engranaje blanco en
forma de anillo con un check dentro.
"""

import math

from PIL import Image, ImageDraw

AZUL = (0, 24, 113, 255)      # #001871
BLANCO = (255, 255, 255, 255)
LADO = 512


def _gear_points(cx, cy, r_ext, r_int_teeth, r_valle, dientes):
    puntos = []
    paso = 2 * math.pi / (dientes * 2)
    ancho_diente = paso * 0.55
    for i in range(dientes * 2):
        angulo = i * paso
        radio_base = r_int_teeth if i % 2 == 0 else r_valle
        for delta, radio in ((-ancho_diente / 2, radio_base),
                             (ancho_diente / 2, radio_base)):
            a = angulo + delta
            puntos.append((cx + radio * math.cos(a), cy + radio * math.sin(a)))
    return puntos


def generar(ruta_png):
    img = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(img)

    radio_fondo = LADO * 0.46
    centro = LADO / 2
    dibujo.rounded_rectangle(
        [centro - radio_fondo, centro - radio_fondo,
         centro + radio_fondo, centro + radio_fondo],
        radius=LADO * 0.09, fill=AZUL)

    r_ext = LADO * 0.34
    r_valle = LADO * 0.285
    dibujo.polygon(_gear_points(centro, centro, r_ext, r_ext, r_valle, dientes=10),
                    fill=BLANCO)

    r_anillo_interior = LADO * 0.205
    dibujo.ellipse(
        [centro - r_anillo_interior, centro - r_anillo_interior,
         centro + r_anillo_interior, centro + r_anillo_interior],
        fill=AZUL)

    ancho_trazo = int(LADO * 0.045)
    check = [
        (centro - LADO * 0.11, centro + LADO * 0.005),
        (centro - LADO * 0.03, centro + LADO * 0.085),
        (centro + LADO * 0.135, centro - LADO * 0.09),
    ]
    dibujo.line(check, fill=BLANCO, width=ancho_trazo, joint="curve")
    for punto in (check[0], check[-1]):
        dibujo.ellipse(
            [punto[0] - ancho_trazo / 2, punto[1] - ancho_trazo / 2,
             punto[0] + ancho_trazo / 2, punto[1] + ancho_trazo / 2],
            fill=BLANCO)
    cx, cy = check[1]
    dibujo.ellipse([cx - ancho_trazo / 2, cy - ancho_trazo / 2,
                    cx + ancho_trazo / 2, cy + ancho_trazo / 2], fill=BLANCO)

    img.save(ruta_png)
    return img


if __name__ == "__main__":
    img = generar("icono_reteica.png")
    tamanos = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
              (128, 128), (256, 256)]
    img.save("icono_reteica.ico", sizes=tamanos)
    print("generado icono_reteica.png e icono_reteica.ico")
