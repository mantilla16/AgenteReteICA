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


def _es_cuenta_reteica(cuenta: str) -> bool:
    return _digitos(cuenta).startswith(_PUC_RETEICA)


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

def _es_transaccion(fila, d: Deteccion) -> bool:
    """Fila de detalle real, respetando el filtro de jerarquia si lo hay."""
    col_cuenta = d.columnas.get("cuenta")
    if col_cuenta is None or col_cuenta >= len(fila):
        return False
    if d.filtro_transaccion is not None:
        col, marca = d.filtro_transaccion
        if col >= len(fila) or _texto(fila[col]) != marca:
            return False
    return _es_cuenta_reteica(fila[col_cuenta])


# --------------------------------------------------------------------------
# Lectura canonica
# --------------------------------------------------------------------------

def _retencion_de(fila, d: Deteccion):
    """El importe de la retencion practicada, normalizado a positivo."""
    if d.convencion_signo == "columnas_separadas":
        col = d.columnas.get("credito")
    else:
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
    for fila in filas[d.fila_encabezado + 1:]:
        if not _es_transaccion(fila, d):
            continue
        retencion = _retencion_de(fila, d)
        if retencion is None:
            continue
        lineas.append(LineaAuxiliar(
            cuenta=_digitos(celda(fila, "cuenta")),
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


def leer_saldos(filas, d: Deteccion, excluidas=()) -> dict:
    """Movimiento del periodo por cuenta 2368, desde cualquier balance.

    Usa la columna de retencion (credito/importe) como movimiento del periodo,
    igual criterio que el balance de SAP GRC ('Saldo Haber per.inf.'). Excluye
    las cuentas que el auditor haya marcado como contrapartida.
    """
    col_cuenta = d.columnas.get("cuenta")
    if col_cuenta is None:
        return {}
    excluidas = set(excluidas)
    saldos = {}
    for fila in filas[d.fila_encabezado + 1:]:
        if not _es_transaccion(fila, d):
            continue
        cuenta = _digitos(fila[col_cuenta])
        if cuenta in excluidas:
            continue
        valor = _retencion_de(fila, d)
        if valor is None:
            continue
        saldos[cuenta] = saldos.get(cuenta, Decimal("0")) + valor.copy_abs()
    return saldos
