"""Insertar el borrador del cliente como imagen en la hoja DECLARACION.

La plantilla trae HORNEADA la cara del formulario de TERLICA como imagen
(xl/media/imageN.png, anclada en DECLARACION). Para cualquier otro cliente esa
imagen mentia: mostraba la declaracion de TERLICA sobre los datos de otra
empresa. El auditor pidio que se inserte el borrador que de verdad se subio.

Por que cirugia de zip y no openpyxl.add_image: el guardado final
(fidelidad.py) RECONSTRUYE el paquete desde la plantilla original y solo
reemplaza las hojas, los textos y los estilos. Media, dibujos y rels vienen
intactos del original SIEMPRE -- una imagen agregada con openpyxl se
descartaria. Asi que el reemplazo se hace DESPUES del guardado, sobre el
paquete ya producido: se sustituyen los BYTES de la imagen que el dibujo de
DECLARACION ya referencia, y se reescribe ese dibujo para que la caja tome el
ALTO proporcional al borrador (1..N paginas) sin deformarlo.

Si falta pymupdf/PIL o el PDF no se puede renderizar, no se toca nada: la hoja
queda con la imagen de la plantilla. El papel nunca se cae por esto -- las
columnas de datos (I:L) ya quedaron bien por otro camino.
"""

import io
import re
import zipfile
from pathlib import Path

# EMU por pulgada; el render se hace a DPI y se convierte a EMU para la caja.
_EMU_POR_PULGADA = 914400
_DPI = 200
_MAX_PAGINAS = 10


def insertar_borrador(xlsx_destino, ruta_pdf, hoja: str = "DECLARACION") -> bool:
    """Reemplaza la imagen de `hoja` por el borrador renderizado.

    Devuelve True si lo hizo, False si no pudo (y entonces deja el paquete
    intacto). No lanza: cualquier fallo se traga y conserva la plantilla.
    """
    xlsx_destino = Path(xlsx_destino)
    ruta_pdf = Path(ruta_pdf) if ruta_pdf else None
    if not ruta_pdf or not ruta_pdf.exists():
        return False

    try:
        draw, media, embed_id, cx = _ubicar_dibujo(xlsx_destino, hoja)
    except Exception:
        return False
    if not media:
        return False

    try:
        png, ancho_px, alto_px = _renderizar_pdf(ruta_pdf)
    except Exception:
        return False
    if not png or ancho_px <= 0 or alto_px <= 0:
        return False

    cy = int(round(cx * alto_px / ancho_px))
    nuevo_dibujo = _dibujo_una_celda(embed_id, cx, cy).encode("utf-8")

    try:
        _reescribir_zip(xlsx_destino, {media: png, draw: nuevo_dibujo})
    except Exception:
        return False
    return True


def _ubicar_dibujo(xlsx, nombre_hoja: str):
    """(ruta_dibujo, ruta_media, id_embed, cx) para la hoja dada.

    Se descubre siguiendo las relaciones del paquete en vez de cablear
    'image2.png': si la plantilla se vuelve a guardar y renumera dibujos, esto
    sigue encontrando la imagen correcta.
    """
    with zipfile.ZipFile(xlsx) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
        m = re.search(r'<sheet[^>]*name="%s"[^>]*r:id="([^"]+)"'
                      % re.escape(nombre_hoja), wb)
        if not m:
            return None, None, None, None
        rid = m.group(1)
        tgt = re.search(r'Id="%s"[^>]*Target="([^"]+)"' % re.escape(rid), rels)
        if not tgt:
            return None, None, None, None
        sheet = "xl/" + tgt.group(1).lstrip("/").replace("../", "")
        srels = "xl/worksheets/_rels/%s.rels" % sheet.split("/")[-1]
        if srels not in z.namelist():
            return None, None, None, None
        dtgt = re.search(r'Target="([^"]*drawings/[^"]+)"',
                         z.read(srels).decode("utf-8"))
        if not dtgt:
            return None, None, None, None
        draw = "xl/" + dtgt.group(1).replace("../", "")
        drels = "xl/drawings/_rels/%s.rels" % draw.split("/")[-1]
        rel_img = re.search(r'Id="([^"]+)"[^>]*Target="([^"]*media/[^"]+)"',
                            z.read(drels).decode("utf-8"))
        if not rel_img:
            return None, None, None, None
        embed_id = rel_img.group(1)
        media = "xl/" + rel_img.group(2).replace("../", "")
        ext = re.search(r'<a:ext cx="(\d+)" cy="(\d+)"',
                        z.read(draw).decode("utf-8"))
        cx = int(ext.group(1)) if ext else 5534797
    return draw, media, embed_id, cx


def _renderizar_pdf(ruta_pdf):
    """Renderiza el PDF a un PNG. Varias paginas se apilan en vertical.

    Devuelve (bytes_png, ancho_px, alto_px).
    """
    import pymupdf
    from PIL import Image

    doc = pymupdf.open(str(ruta_pdf))
    paginas = []
    zoom = _DPI / 72.0
    matriz = pymupdf.Matrix(zoom, zoom)
    for page in doc[:_MAX_PAGINAS]:
        pix = page.get_pixmap(matrix=matriz)
        paginas.append(Image.frombytes("RGB", [pix.width, pix.height],
                                       pix.samples))
    doc.close()
    if not paginas:
        return None, 0, 0

    if len(paginas) == 1:
        lienzo = paginas[0]
    else:
        ancho = max(p.width for p in paginas)
        # Todas a un ancho comun, apiladas con un filo blanco entre ellas.
        escaladas = [p if p.width == ancho
                     else p.resize((ancho, round(p.height * ancho / p.width)))
                     for p in paginas]
        separacion = max(1, round(ancho * 0.01))
        alto = sum(p.height for p in escaladas) + separacion * (len(escaladas) - 1)
        lienzo = Image.new("RGB", (ancho, alto), "white")
        y = 0
        for p in escaladas:
            lienzo.paste(p, (0, y))
            y += p.height + separacion

    buffer = io.BytesIO()
    lienzo.save(buffer, format="PNG")
    return buffer.getvalue(), lienzo.width, lienzo.height


def _dibujo_una_celda(embed_id: str, cx: int, cy: int) -> str:
    """Dibujo con anclaje de una celda (A2) y tamaño EXACTO cx x cy en EMU.

    oneCellAnchor fija la esquina superior en la celda y toma el tamaño del
    <xdr:ext>, sin depender de altos de fila: asi el alto se ajusta al
    borrador (proporcional a su numero de paginas) sin que Excel lo deforme.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/'
        'spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/'
        'drawingml/2006/main">'
        '<xdr:oneCellAnchor>'
        '<xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff>'
        '<xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
        '<xdr:ext cx="%d" cy="%d"/>'
        '<xdr:pic>'
        '<xdr:nvPicPr>'
        '<xdr:cNvPr id="2" name="Borrador declaracion"/>'
        '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>'
        '</xdr:nvPicPr>'
        '<xdr:blipFill>'
        '<a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships" r:embed="%s"/>'
        '<a:stretch><a:fillRect/></a:stretch>'
        '</xdr:blipFill>'
        '<xdr:spPr>'
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        '</xdr:spPr>'
        '</xdr:pic>'
        '<xdr:clientData/>'
        '</xdr:oneCellAnchor>'
        '</xdr:wsDr>' % (cx, cy, embed_id, cx, cy))


def _reescribir_zip(xlsx: Path, reemplazos: dict) -> None:
    """Reescribe el xlsx cambiando solo las partes de `reemplazos` {nombre: bytes}."""
    temporal = xlsx.with_suffix(".img.tmp")
    with zipfile.ZipFile(xlsx) as origen, \
            zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as salida:
        for nombre in origen.namelist():
            salida.writestr(origen.getinfo(nombre),
                            reemplazos.get(nombre, origen.read(nombre)))
    temporal.replace(xlsx)
