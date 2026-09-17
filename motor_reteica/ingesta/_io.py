"""Lectura cruda de filas de un archivo tabular. Sin parametrizacion ni
tipos: eso lo resuelve parametros/columnas.py sobre el resultado de aqui.

Tres formatos coexisten en los exports que mandan los clientes, todos
llegan como ".xls" o ".xlsx" pero el contenedor es distinto:

  - XLSX (openpyxl):        el moderno, Office 2007+.
  - XLS OLE (xlrd):         el viejo Excel 97-2003 binario.
  - XLS TSV UTF-16:         SAP exporta asi con extension .xls -- es texto
                            tabulado con BOM UTF-16 LE. Ni openpyxl ni xlrd
                            lo entienden; fallaba en produccion con el
                            balance de un cliente y este modulo lo cazaba
                            mucho antes que la clasificacion.

La deteccion es por FIRMA de bytes (los primeros 4), no por extension: los
clientes renombran archivos y no podemos confiar en el sufijo.
"""

from pathlib import Path


# Firmas de los tres formatos:
#   D0CF11E0 -> OLE compound file (xls antiguo, doc, ppt viejos)
#   504B0304 -> ZIP (xlsx, docx, pptx modernos)
#   FFFE     -> BOM UTF-16 LE
_FIRMA_OLE = b"\xd0\xcf\x11\xe0"
_FIRMA_ZIP = b"PK\x03\x04"
_FIRMA_UTF16_LE = b"\xff\xfe"
_FIRMA_UTF16_BE = b"\xfe\xff"


def leer_filas(ruta, hoja: str = None) -> list:
    """Devuelve la primera hoja como lista de tuplas (fila -> celdas).

    Detecta el formato por los primeros bytes, no por la extension: SAP
    escribe TSV UTF-16 con nombre .xls y hay que aceptarlo o mitad de los
    clientes queda sin poder cargar sus insumos.
    """
    ruta = Path(ruta)
    with open(ruta, "rb") as fh:
        firma = fh.read(4)

    if firma.startswith(_FIRMA_ZIP):
        return _leer_xlsx(ruta, hoja)
    if firma.startswith(_FIRMA_OLE):
        return _leer_xls_binario(ruta, hoja)
    if firma.startswith(_FIRMA_UTF16_LE) or firma.startswith(_FIRMA_UTF16_BE):
        return _leer_tsv_unicode(ruta)

    # Ultimo recurso: intentar xlsx y luego xls, en ese orden. Que un
    # cliente renombre un archivo no debe romper el motor.
    try:
        return _leer_xlsx(ruta, hoja)
    except Exception:
        pass
    try:
        return _leer_xls_binario(ruta, hoja)
    except Exception:
        pass
    return _leer_tsv_unicode(ruta)


def _leer_xlsx(ruta: Path, hoja: str | None) -> list:
    import openpyxl
    libro = openpyxl.load_workbook(ruta, data_only=True)
    pagina = (libro[hoja] if hoja and hoja in libro.sheetnames
              else libro.worksheets[0])
    return list(pagina.iter_rows(values_only=True))


def _leer_xls_binario(ruta: Path, hoja: str | None) -> list:
    """Excel 97-2003 binario (.xls OLE). Usa xlrd."""
    import xlrd
    libro = xlrd.open_workbook(str(ruta))
    if hoja and hoja in libro.sheet_names():
        ws = libro.sheet_by_name(hoja)
    else:
        ws = libro.sheet_by_index(0)
    return [tuple(ws.cell_value(f, c) for c in range(ws.ncols))
            for f in range(ws.nrows)]


def _leer_tsv_unicode(ruta: Path) -> list:
    """SAP exporta con extension .xls y contenido TSV UTF-16 LE. Frecuente
    en 'Saldos de cuentas de mayor' y otros reportes. El separador es tab;
    los numeros vienen con formato colombiano ('29.982.086') y se convierten
    a numero cuando se puedan -- si no, se dejan como texto para que el
    detector de columnas los vea como etiquetas y decida."""
    texto = ruta.read_bytes().decode("utf-16")
    filas = []
    for linea in texto.splitlines():
        celdas = tuple(_normalizar(c) for c in linea.split("\t"))
        # Descarta la ultima celda vacia de las lineas que terminan en \t.
        while celdas and celdas[-1] in ("", None):
            celdas = celdas[:-1]
        filas.append(celdas)
    return filas


def _normalizar(celda: str):
    """Numeros con formato colombiano -> float. Todo lo demas queda texto."""
    valor = celda.strip()
    if not valor:
        return None
    # Un numero puede venir como '29.982.086' o '-1.234,56'. Cualquier
    # cadena que solo tenga digitos, puntos, comas y signo se intenta.
    limpio = valor.replace(".", "").replace(",", ".")
    if limpio.lstrip("-").replace(".", "").isdigit():
        try:
            n = float(limpio)
            # Si es entero exacto, devolvemos int para que openpyxl-style
            # comparisons con enteros funcionen.
            return int(n) if n.is_integer() else n
        except ValueError:
            pass
    return valor
