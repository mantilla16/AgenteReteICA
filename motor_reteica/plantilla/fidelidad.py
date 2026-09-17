"""Guardar la plantilla sin destruir lo que openpyxl no sabe conservar.

MEDIDO sobre la plantilla real: cargar y volver a guardar con openpyxl PIERDE

    xl/media/image1.emf          el LOGO DE LA FIRMA (EMF no soportado)
    xl/media/image2.png          la otra imagen
    xl/drawings/drawing2.xml     2 de los 3 dibujos, con sus rels
    xl/drawings/drawing3.xml
    xl/printerSettings/*.bin     LA CONFIGURACION DE IMPRESION
    xl/persons/person.xml        autores de comentarios
    xl/worksheets/_rels/sheet1|4|8.xml.rels

En un papel que se imprime y se firma, perder el logo y la configuracion de
impresion no es cosmetico.

ESTRATEGIA: no se parte del archivo que produce openpyxl para restaurarle
piezas -- son demasiadas y cada una es una oportunidad de equivocarse. Se
parte del PAQUETE ORIGINAL y se le reemplazan UNICAMENTE las partes que
llevan valores de celda:

    xl/worksheets/sheetN.xml     (las celdas)
    xl/sharedStrings.xml         (los textos)

Todo lo demas -- media, dibujos, rels, printerSettings, content types --
queda intacto POR CONSTRUCCION, porque nunca se toca.

Lo unico que hay que remendar: openpyxl no escribe los elementos de cola que
referencian dibujos e impresora (<drawing r:id>, <legacyDrawing>, el r:id de
<pageSetup>). Se copian del XML original de esa misma hoja.

xl/calcChain.xml se descarta a proposito: es una cache de orden de calculo y
Excel la reconstruye. Conservarla junto a celdas nuevas la vuelve incoherente.
"""

import re
import zipfile
from pathlib import Path

# Partes que SI vienen del archivo escrito por openpyxl.
#
# styles.xml va en este grupo aunque no lleve valores, y es OBLIGATORIO:
# cada celda del XML de una hoja referencia su formato por INDICE (s="12")
# contra la tabla de estilos con la que se escribio. Conservar el styles.xml
# del original junto a hojas escritas por openpyxl deja esos indices
# apuntando a otra tabla y Excel abre un archivo corrupto.
# Lo detecto test_el_resultado_lo_puede_volver_a_abrir_openpyxl.
_PARTES_CON_VALORES = re.compile(
    r"^xl/worksheets/sheet\d+\.xml$|^xl/sharedStrings\.xml$|^xl/styles\.xml$")

# Cache de orden de calculo: Excel la rehace. Mantenerla con celdas nuevas la
# deja apuntando a un grafo que ya no existe.
_DESCARTAR = "xl/calcChain.xml"


_RE_SHEET = re.compile(
    r'<sheet\b[^/>]*\bname="([^"]+)"[^/>]*\bsheetId="[^"]+"[^/>]*/?>')


def _visibilidades(xml: str) -> dict:
    """Devuelve {nombre_de_hoja: 'visible'|'hidden'|'veryHidden'}."""
    salida = {}
    for m in _RE_SHEET.finditer(xml):
        estado_m = re.search(r'state="([^"]+)"', m.group(0))
        salida[m.group(1)] = estado_m.group(1) if estado_m else "visible"
    return salida


def _propagar_visibilidad(xml_original: str, xml_escrito: str) -> str:
    """Aplica al workbook original el sheet state del openpyxl output.

    fidelidad.py conservaba el xml original tal cual. Eso mantiene formato y
    orden, pero tambien mantiene la visibilidad -- si el codigo del papel
    marca una hoja como oculta, ese cambio se perdia al escribir. Ahora,
    para cada hoja que el openpyxl output haya marcado con un estado
    distinto al del original, se remienda el atributo state en el xml.
    """
    de_openpyxl = _visibilidades(xml_escrito)
    del_original = _visibilidades(xml_original)

    resultado = xml_original
    for nombre, estado in de_openpyxl.items():
        if del_original.get(nombre) == estado:
            continue
        resultado = _remendar_state(resultado, nombre, estado)
    return resultado


def _remendar_state(xml: str, nombre: str, estado: str) -> str:
    """Injerta o reemplaza el atributo state en la etiqueta <sheet> del nombre."""
    patron = re.compile(
        r'(<sheet\b[^/>]*\bname="%s"[^/>]*?)(/?>)' % re.escape(nombre))
    def _reemplazar(m):
        etiqueta, cierre = m.group(1), m.group(2)
        etiqueta = re.sub(r'\s+state="[^"]+"', "", etiqueta)
        if estado != "visible":
            etiqueta += ' state="%s"' % estado
        return etiqueta + cierre
    return patron.sub(_reemplazar, xml, count=1)


def _forzar_recalculo(xml: str) -> str:
    """Marca el libro para que Excel recalcule TODO al abrirlo.

    Sin esto el papel se abre en blanco donde deberia haber cifras, y esa es
    la peor forma de fallar que tiene: no avisa, parece un papel vacio.

    openpyxl escribe las formulas pero no sus resultados, y aqui ademas se
    descarta calcChain.xml. Un Excel sin valores en cache y sin cadena de
    calculo no siempre reconstruye el grafo solo: muestra la celda vacia
    hasta que algo lo obligue. `fullCalcOnLoad` es ese algo.

    Afecta a REVISION ICA --que es casi toda formulas-- y a las columnas de
    BASE e IMPTO del borrador.
    """
    if "fullCalcOnLoad" in xml:
        return xml
    if "<calcPr" in xml:
        return re.sub(r"<calcPr([^>]*?)/>",
                      r'<calcPr\1 fullCalcOnLoad="1"/>', xml, count=1)
    return xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')

# Elementos de cola de una hoja que openpyxl no reescribe y que referencian
# partes del paquete (dibujos, impresora). Si no se remiendan, el logo y la
# configuracion de impresion quedan huerfanos aunque el archivo si los tenga.
_ETIQUETAS_DE_COLA = ("drawing", "legacyDrawing", "picture", "oleObjects",
                      "controls")


def _page_setup_de(xml: str) -> str:
    hallazgo = re.search(r"<pageSetup(?:\s[^>]*)?/>", xml)
    return hallazgo.group(0) if hallazgo else ""


_XMLNS_R = ('xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships"')


def _asegurar_namespace_r(xml: str) -> str:
    """Los enlaces a dibujos e impresora usan el prefijo r:.

    openpyxl escribe la raiz <worksheet> SIN declarar xmlns:r, asi que
    injertar un <drawing r:id="..."/> produce XML invalido ("unbound
    prefix") y Excel rechaza el archivo. Lo detecto
    test_el_resultado_lo_puede_volver_a_abrir_openpyxl.
    """
    if "xmlns:r=" in xml:
        return xml
    return re.sub(r"<worksheet\b", "<worksheet " + _XMLNS_R, xml, count=1)


def _remendar_hoja(xml_nuevo: str, xml_original: str) -> str:
    """Devuelve el XML de openpyxl con los enlaces del original restituidos."""
    # pageSetup: el original lleva r:id apuntando a printerSettings; el de
    # openpyxl no. Se prefiere el original solo si de verdad trae ese enlace.
    original_setup = _page_setup_de(xml_original)
    if "r:id" in original_setup:
        xml_nuevo = _asegurar_namespace_r(xml_nuevo)
        nuevo_setup = _page_setup_de(xml_nuevo)
        if nuevo_setup:
            xml_nuevo = xml_nuevo.replace(nuevo_setup, original_setup, 1)
        else:
            xml_nuevo = xml_nuevo.replace("</worksheet>",
                                          original_setup + "</worksheet>", 1)

    # Los elementos de cola del original que openpyxl no haya escrito.
    # Se comparan por etiqueta: si openpyxl ya puso un <drawing>, no se
    # duplica; si no lo puso, se restituye el del original.
    for etiqueta in _ETIQUETAS_DE_COLA:
        if re.search(r"<%s(?:\s|/|>)" % etiqueta, xml_nuevo):
            continue
        del_original = re.search(
            r"<%s(?:\s[^>]*)?/>|<%s(?:\s[^>]*)?>.*?</%s>"
            % (etiqueta, etiqueta, etiqueta), xml_original, re.DOTALL)
        if del_original:
            injerto = del_original.group(0)
            if "r:" in injerto:
                xml_nuevo = _asegurar_namespace_r(xml_nuevo)
            xml_nuevo = xml_nuevo.replace(
                "</worksheet>", injerto + "</worksheet>", 1)
    return xml_nuevo


def guardar_conservando_formato(libro, plantilla: Path, destino: Path) -> Path:
    """Guarda `libro` (openpyxl) en `destino` con el paquete de `plantilla`.

    El resultado conserva logo, dibujos, configuracion de impresion y todo lo
    que openpyxl no sabe manejar, porque esas partes nunca se reescriben.
    """
    plantilla, destino = Path(plantilla), Path(destino)
    temporal = destino.with_suffix(".openpyxl.tmp")
    libro.save(temporal)

    try:
        with zipfile.ZipFile(plantilla) as original, \
                zipfile.ZipFile(temporal) as escrito:
            nuevas = {n for n in escrito.namelist() if _PARTES_CON_VALORES.match(n)}
            originales = {n: original.read(n) for n in original.namelist()}

            with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as salida:
                for nombre in original.namelist():
                    if nombre == _DESCARTAR:
                        continue
                    if nombre in nuevas:
                        contenido = escrito.read(nombre).decode("utf-8")
                        if nombre.startswith("xl/worksheets/"):
                            contenido = _remendar_hoja(
                                contenido, originales[nombre].decode("utf-8"))
                        salida.writestr(nombre, contenido)
                    elif nombre == "xl/workbook.xml":
                        salida.writestr(nombre, _forzar_recalculo(
                            _propagar_visibilidad(
                                originales[nombre].decode("utf-8"),
                                escrito.read(nombre).decode("utf-8"))))
                    else:
                        salida.writestr(nombre, originales[nombre])

                # sharedStrings puede no existir en el original y si en el
                # escrito (si la plantilla no tenia textos compartidos).
                for nombre in sorted(nuevas - set(original.namelist())):
                    salida.writestr(nombre, escrito.read(nombre))
    finally:
        temporal.unlink(missing_ok=True)

    return destino
