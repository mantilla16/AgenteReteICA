"""Adaptador: de cualquier formato detectado al modelo canonico del motor.

Es el puente entre la deteccion dinamica (deteccion.py + cuadres.py) y los
tipos que el motor ya consume (LineaAuxiliar, dict de saldos). Aplica lo que
cada formato exige sin que el motor downstream se entere:

  - filtro de jerarquia (SAP B1: solo filas con Serie='AstCont'),
  - convencion de signo (columna unica con signo vs debito/credito separados),
  - derivacion de la TARIFA desde el nombre de la cuenta, porque la sub-cuenta
    la codifica distinto cada ERP y el dict estatico del municipio no puede
    tenerlas todas.

REGLA: aqui NO se valida el mapeo -- eso es de cuadres.py, y el llamador debe
correrlo antes de confiar en lo que sale de aca. Este modulo solo TRADUCE.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from motor_reteica.ingesta.deteccion import Deteccion, _a_decimal, _PUC_RETEICA
from motor_reteica.tipos import LineaAuxiliar

_SIN_FECHA = date(1900, 1, 1)
_FORMATOS_FECHA = ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y",
                   "%d-%m-%Y")


def _a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor in (None, ""):
        return _SIN_FECHA
    s = str(valor).strip().split(" ")[0]
    for f in _FORMATOS_FECHA:
        try:
            return datetime.strptime(s, f.split(" ")[0]).date()
        except ValueError:
            pass
    return _SIN_FECHA


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor)) if valor is not None else ""


def _es_codigo_cuenta(cuenta) -> bool:
    """La celda es un CODIGO de cuenta ICA real, no un subtotal de texto.

    '2368010005' o 2368010005 -> True. 'Cuenta 2368010005 - Retencion...' (fila
    de subtotal) -> False, porque trae letras: no es un codigo, es un rotulo.
    Asi se descartan los subtotales que algunos exports intercalan.
    """
    if cuenta is None or cuenta == "":
        return False
    if isinstance(cuenta, (int, float)):
        return str(int(cuenta)).startswith(_PUC_RETEICA)
    nucleo = re.sub(r"[.\-\s]", "", str(cuenta).strip())
    return nucleo.isdigit() and nucleo.startswith(_PUC_RETEICA)


def _es_cuenta_reteica(cuenta: str) -> bool:
    return _es_codigo_cuenta(cuenta)


# --------------------------------------------------------------------------
# Derivacion de tarifa desde el nombre de la cuenta
# --------------------------------------------------------------------------

_RE_POR_MIL = re.compile(r"(\d+(?:[.,]\d+)?)\s*x\s*1000", re.IGNORECASE)
_RE_PORCENTAJE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def derivar_tarifa(nombre_cuenta: str):
    """La tarifa que codifica el nombre de la cuenta, o None si no se ve.

    Formatos vistos:
      - SAP B1 (Equinorte): "...RETENIDO SANTA M. 5x1000"  -> 0.005
      - SAP GRC (TERLICA/ZFT): "Impuest ICA Reten 7%"      -> 0.007
    Nunca adivina: si el nombre no trae ni 'Nx1000' ni 'N%', devuelve None y el
    llamador cae al mapa del municipio (o deja la tarifa sin resolver, que un
    control reportara).
    """
    if not nombre_cuenta:
        return None
    m = _RE_POR_MIL.search(nombre_cuenta)
    if m:
        return (Decimal(m.group(1).replace(",", ".")) / Decimal("1000"))
    m = _RE_PORCENTAJE.search(nombre_cuenta)
    if m:
        return (Decimal(m.group(1).replace(",", ".")) / Decimal("100"))
    return None


def tarifas_de_ruta(ruta, tipo: str) -> dict:
    """Tarifas por cuenta derivadas del archivo en `ruta`. {} si no se pueden.

    Lectura barata (una pasada) que el pipeline usa para completar el mapa de
    tarifas del municipio con las sub-cuentas del cliente que el dict estatico
    no tiene (p.ej. las de SAP B1). Nunca lanza: un archivo ilegible devuelve {}.
    """
    from motor_reteica.ingesta._io import leer_filas
    from motor_reteica.ingesta.deteccion import detectar
    try:
        hoja = "BALANCE" if tipo == "balance" else None
        filas = leer_filas(ruta, hoja=hoja)
        d = detectar(filas, tipo_esperado=tipo)
        return tarifas_por_cuenta(filas, d)
    except Exception:
        return {}


def tarifas_por_cuenta(filas, d: Deteccion) -> dict:
    """{cuenta: tarifa} derivada de los nombres de cuenta del archivo.

    Recorre el archivo una vez; para cada sub-cuenta ICA con nombre legible,
    deriva la tarifa. Es lo que hace que el motor no dependa de un dict
    estatico por cliente: la tarifa viene del propio dato.
    """
    col_cuenta = d.columnas.get("cuenta")
    col_nombre = d.columnas.get("nombre_cuenta")
    if col_cuenta is None or col_nombre is None:
        return {}
    tarifas = {}
    for fila in filas[d.fila_encabezado + 1:]:
        if col_cuenta >= len(fila) or col_nombre >= len(fila):
            continue
        cuenta = _digitos(fila[col_cuenta])
        if not cuenta.startswith(_PUC_RETEICA) or cuenta in tarifas:
            continue
        tarifa = derivar_tarifa(_texto(fila[col_nombre]))
        if tarifa is not None:
            tarifas[cuenta] = tarifa
    return tarifas


# --------------------------------------------------------------------------
# Filtro de filas
# --------------------------------------------------------------------------

def _transacciones(filas, d: Deteccion):
    """Genera (fila, cuenta_efectiva) por cada transaccion real de retencion.

    Resuelve dos rarezas comunes de los exports contables:
      - FILAS DE SUBTOTAL intercaladas ('Cuenta 2368010005 - ...'): se saltan,
        para no doblar los importes que ya estan en el detalle.
      - CUENTA QUE NO SE REPITE: muchos exports ponen la cuenta solo en la
        primera fila de cada bloque y dejan las siguientes en blanco (mismo
        tercero, otra factura). Se ARRASTRA la ultima cuenta valida hacia esas
        filas de continuacion. La bateria de cuadres valida que el arrastre no
        haya inventado nada: si el total no cuadra con el del propio archivo,
        el mapeo se rechaza.

    Respeta el filtro de jerarquia (SAP B1: Serie='AstCont') cuando existe.
    """
    col_cuenta = d.columnas.get("cuenta")
    if col_cuenta is None:
        return
    filtro = d.filtro_transaccion
    ultima_cuenta = None
    for fila in filas[d.fila_encabezado + 1:]:
        celda = fila[col_cuenta] if col_cuenta < len(fila) else None

        # Fila con codigo de cuenta ICA: fija la cuenta del bloque.
        if _es_codigo_cuenta(celda):
            ultima_cuenta = _digitos(celda)
        elif celda not in (None, ""):
            # Celda con texto que NO es codigo (subtotal, rotulo): corta el
            # arrastre y se salta. Evita atribuir el subtotal a la cuenta previa.
            ultima_cuenta = None
            continue
        # celda vacia -> se conserva ultima_cuenta (fila de continuacion)

        if ultima_cuenta is None:
            continue
        if filtro is not None:
            col, marca = filtro
            if col >= len(fila) or _texto(fila[col]) != marca:
                continue
        if _retencion_de(fila, d) is None:
            continue
        yield fila, ultima_cuenta


# --------------------------------------------------------------------------
# Lectura canonica
# --------------------------------------------------------------------------

def _retencion_de(fila, d: Deteccion):
    """El importe de la retencion practicada, normalizado a positivo.

    La retencion es el HABER: credito si el formato lo trae (SAP B1, o un papel
    con 'Retencion'), si no la columna unica con signo ('Importe en ML').
    """
    col = d.columnas.get("credito")
    if col is None:
        col = d.columnas.get("importe")
    if col is None or col >= len(fila):
        return None
    return _a_decimal(fila[col])


def leer_lineas(filas, d: Deteccion) -> list:
    """Lineas del auxiliar en modelo canonico, desde cualquier formato."""
    def celda(fila, rol):
        i = d.columnas.get(rol)
        return fila[i] if i is not None and i < len(fila) else None

    lineas = []
    for fila, cuenta_efectiva in _transacciones(filas, d):
        retencion = _retencion_de(fila, d)
        lineas.append(LineaAuxiliar(
            cuenta=cuenta_efectiva,
            nit=_texto(celda(fila, "nit")),
            tercero=_texto(celda(fila, "nombre")),
            fecha_documento=_a_fecha(celda(fila, "fecha_documento")),
            fecha_contabilizacion=_a_fecha(
                celda(fila, "fecha_contabilizacion")
                or celda(fila, "fecha_documento")),
            referencia=_texto(celda(fila, "referencia")),
            documento=_texto(celda(fila, "documento")),
            concepto=_texto(celda(fila, "concepto")),
            retencion=retencion.copy_abs(),
        ))
    return lineas


def _normalizar(texto: str) -> str:
    s = str(texto or "").upper()
    for a, b in (("Á", "A"), ("É", "E"), ("Í", "I"), ("Ó", "O"), ("Ú", "U"),
                 ("Ñ", "N")):
        s = s.replace(a, b)
    return s


def _menciona_municipio(nombre_cuenta: str, municipio: str) -> bool:
    """El nombre de la cuenta nombra al municipio (aunque venga abreviado).

    En un balance con varios municipios, las cuentas ICA traen el municipio en
    el nombre ('...RETENIDO SANTA M. 5x1000'). Se busca la primera palabra
    significativa del municipio (>=4 letras: 'SANTA', 'GALAPA', 'CARTAGENA').
    """
    nombre = _normalizar(nombre_cuenta)
    palabras = [p for p in _normalizar(municipio).split() if len(p) >= 4]
    return any(p in nombre for p in palabras) if palabras else False


def leer_saldos(filas, d: Deteccion, excluidas=(), municipio: str = None) -> dict:
    """Movimiento del periodo por cuenta 2368, desde cualquier balance.

    Maneja el balance COMPLETO de la empresa (miles de cuentas, con jerarquia y
    varios municipios), no solo un extracto de 2368:

      - JERARQUIA: la cuenta 2368 tiene padres que son SUBTOTALES (2368, 236805,
        23680503) y hojas de detalle (2368050301...). Se toman solo las HOJAS
        (una cuenta que no es prefijo de otra), para no doblar el movimiento.
      - FILA RESUMEN: cada cuenta trae una fila de total (sin tercero, NIT vacio)
        y filas por tercero. El movimiento de la cuenta es el de la fila resumen;
        sumar las de tercero volveria a doblar.
      - MUNICIPIO: si el balance trae cuentas de varios municipios, se queda con
        las del municipio en revision (por el nombre de la cuenta). Si ninguna
        nombra municipio (formato SAP GRC, 'Impuest ICA Reten 7%'), no filtra.
    """
    col_cuenta = d.columnas.get("cuenta")
    if col_cuenta is None:
        return {}
    col_nombre = d.columnas.get("nombre_cuenta")
    col_nit = d.columnas.get("nit")
    excluidas = set(excluidas)

    # 1. Fila RESUMEN de cada cuenta 2368 (sin tercero): {cuenta: (nombre, valor)}
    resumen = {}
    for fila in filas[d.fila_encabezado + 1:]:
        if col_cuenta >= len(fila) or not _es_codigo_cuenta(fila[col_cuenta]):
            continue
        # Fila de tercero (trae NIT/codigo SN): es el desglose, no el total.
        if col_nit is not None and col_nit < len(fila) and \
                _texto(fila[col_nit]):
            continue
        cuenta = _digitos(fila[col_cuenta])
        if cuenta in resumen:
            continue
        valor = _retencion_de(fila, d)
        nombre = (_texto(fila[col_nombre])
                  if col_nombre is not None and col_nombre < len(fila) else "")
        resumen[cuenta] = (nombre, valor.copy_abs() if valor is not None
                           else Decimal("0"))

    if not resumen:
        return {}

    # 2. Solo HOJAS: una cuenta que no es prefijo de ninguna otra recogida.
    codigos = set(resumen)
    hojas = {c for c in codigos
             if not any(o != c and o.startswith(c) for o in codigos)}

    # 3. Filtro por municipio, solo si el balance mezcla municipios.
    if municipio:
        del_municipio = {c for c in hojas
                         if _menciona_municipio(resumen[c][0], municipio)}
        if del_municipio and len(del_municipio) < len(hojas):
            hojas = del_municipio

    return {c: resumen[c][1] for c in hojas if c not in excluidas}
